"""MCP tool family for Creative Studio (PR-A visual generation + PR-B compose).

Self-contained in one module (mirroring ``tools_analytics_registry``):

- ``creative_studio_providers_list`` — enumerate configured image providers
  and their capabilities.
- ``creative_studio_generate_visual`` — generate text-free key visuals with
  one or all configured providers, write them to a run directory with a
  provenance manifest, and return the paths.
- ``creative_studio_brand_kit_get`` — return the loaded brand kit (colours /
  fonts / logo) so the agent can judge brand fit.
- ``creative_studio_edit_visual`` — refine a visual through a provider's edit
  path (for the art-direction loop).
- ``creative_studio_compose`` — composite copy + brand over a visual into
  per-format banner PNGs via the HTML/CSS composition engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from mureo._image_validation import validate_image_file
from mureo.creative_studio import composer
from mureo.creative_studio.brand_kit import DEFAULT_BRAND_KIT, BrandKit, load_brand_kit
from mureo.creative_studio.formats import FORMATS_BY_ID, generation_size_for_aspect
from mureo.creative_studio.providers import (
    ImageProvider,
    NotSupportedError,
    available_providers,
)
from mureo.creative_studio.workspace import (
    create_run_dir,
    sha256_of,
    write_bytes,
    write_manifest,
)
from mureo.mcp._helpers import _json_result, _opt, _require
from mureo.throttle import CREATIVE_STUDIO_THROTTLE, Throttler

logger = logging.getLogger(__name__)

# One shared throttle bucket in front of EVERY provider call. Kept module-level
# so tests can patch ``_THROTTLER.acquire`` and assert it is awaited.
_THROTTLER = Throttler(CREATIVE_STUDIO_THROTTLE)

# Generated PNGs are validated before being returned downstream.
_MAX_IMAGE_BYTES = 30 * 1024 * 1024
_MAX_IMAGE_LABEL = "30MB"
_ALLOWED_IMAGE_EXTENSIONS = frozenset({"png"})

# Compose accepts any raster the browser can decode as a background visual.
_COMPOSE_INPUT_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})

# The hard constraint appended to every provider prompt: image models render
# text (especially Japanese) poorly, so they generate the VISUAL only — the
# typography layer (PR-B) overlays copy afterward.
_NO_TEXT_CONSTRAINT = (
    "Absolutely no text, no letters, no words, no typography, no watermarks, "
    "no logos in the image. Leave clean negative space suitable for overlaying "
    "headline text later."
)

_ASPECTS = ("square", "portrait", "landscape", "vertical")

# Template-aware negative-space guidance. Keyed by composer template id, each
# value is one precise English composition sentence appended to the provider
# prompt so the generated visual leaves the calm zone the overlay template
# needs. Enforcing negative space mechanically (rather than trusting the
# agent to remember it) is what keeps the composed copy legible. The keys must
# stay in lock-step with :data:`mureo.creative_studio.composer.TEMPLATES`.
TEMPLATE_NEGATIVE_SPACE: dict[str, str] = {
    "hero_overlay": (
        "Compose the subject in the upper two thirds; keep the lower third "
        "visually calm and uncluttered for a text overlay."
    ),
    "split": (
        "Compose the subject so it reads well when cropped to one half of the "
        "frame; keep the composition centered-weighted with clean edges."
    ),
    "minimal_badge": (
        "Center-weighted subject with even, low-contrast texture around it, "
        "suitable for a centered card overlay."
    ),
}


def build_visual_prompt(user_prompt: str, template: str | None = None) -> str:
    """Wrap ``user_prompt`` with template negative space + the no-text constraint.

    The optional ``template`` (a composer template id) appends one precise
    composition sentence *between* the user prompt and the hard no-text
    constraint, so the generated visual reserves the calm zone the overlay
    template will place copy into. An unknown or ``None`` template adds nothing,
    so the wrapper stays backward compatible.
    """
    parts = [user_prompt.strip()]
    guidance = TEMPLATE_NEGATIVE_SPACE.get(template) if template else None
    if guidance:
        parts.append(guidance)
    parts.append(_NO_TEXT_CONSTRAINT)
    return " ".join(parts)


TOOLS: list[Tool] = [
    Tool(
        name="creative_studio_providers_list",
        description=(
            "List the image-generation providers available to Creative "
            "Studio. Each entry reports its name, whether an API key is "
            "configured (credential store or env var), its capabilities "
            "(edit support + max size), and its model ids. Call this before "
            "creative_studio_generate_visual to see which providers can be "
            "selected."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="creative_studio_generate_visual",
        description=(
            "Generate text-free key-visual PNGs for an ad creative. The "
            "prompt describes the imagery ONLY — headline/body/CTA text is "
            "added later by the typography layer, so a hard no-text "
            "constraint is appended automatically. Images are written to a "
            "new run directory with a provenance manifest.json; the tool "
            "returns the run id, directory, file paths (with SHA-256), and "
            "manifest path. Use 'provider' to pick one configured provider, "
            "or 'all' to fan out one image per configured provider."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Description of the VISUAL only (scene, subject, "
                        "style, mood). Do not include any copy/text to render."
                    ),
                },
                "aspect": {
                    "type": "string",
                    "enum": list(_ASPECTS),
                    "default": "square",
                    "description": (
                        "Master aspect class; picks the recommended " "generation size."
                    ),
                },
                "n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "default": 2,
                    "description": "Number of candidate images to generate.",
                },
                "provider": {
                    "type": "string",
                    "description": (
                        "Provider name to use (defaults to the first "
                        "configured provider). Pass 'all' to generate one "
                        "image per configured provider."
                    ),
                },
                "template": {
                    "type": "string",
                    "enum": list(composer.TEMPLATES),
                    "description": (
                        "Layout template you intend to compose with. When set, "
                        "a precise negative-space sentence is appended to the "
                        "prompt so the subject leaves the calm zone that "
                        "template overlays copy into (hero_overlay -> lower "
                        "third clear; split -> one half clear; minimal_badge -> "
                        "even center-weighted texture). Omit to add nothing."
                    ),
                },
            },
            "required": ["prompt"],
        },
    ),
    Tool(
        name="creative_studio_brand_kit_get",
        description=(
            "Return the loaded brand kit (colours, fonts, logo path, and logo "
            "clear-space) read from ./BRAND_KIT/kit.yml. When no kit exists, "
            "tasteful neutral defaults are returned and 'defaults_used' is "
            "true. Use this to judge brand fit before composing banners."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="creative_studio_edit_visual",
        description=(
            "Refine an existing key visual through an image provider's edit "
            "path (the art-direction loop: fix a weak visual, then re-score). "
            "The instruction describes the imagery change ONLY — no text is "
            "rendered by the model. The edited PNG is written next to the "
            "input as '<stem>_edit_<k>.png' and validated; the tool returns "
            "its path, SHA-256, and the provider used."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PNG visual to edit.",
                },
                "instruction": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "What to change about the imagery (e.g. 'brighten the "
                        "sky, remove the clutter on the left')."
                    ),
                },
                "provider": {
                    "type": "string",
                    "description": (
                        "Provider name to use. Defaults to the first "
                        "configured provider whose capabilities report edit "
                        "support."
                    ),
                },
            },
            "required": ["path", "instruction"],
        },
    ),
    Tool(
        name="creative_studio_compose",
        description=(
            "Composite ad copy + brand kit over a key visual into per-format "
            "banner PNGs. The typography layer: headline/body/CTA/badge/logo "
            "are laid out in HTML/CSS and rendered by headless Chromium so "
            "Japanese text is pixel-perfect. Pick a layout 'template', the "
            "target 'formats', and pass the copy; the composed PNGs land in a "
            "new run directory with a provenance manifest. Requires the "
            "'creative' extra (pip install 'mureo[creative]')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "visual_path": {
                    "type": "string",
                    "description": (
                        "Path to the text-free background key visual "
                        "(png/jpg/jpeg/webp)."
                    ),
                },
                "headline": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The primary headline copy.",
                },
                "cta": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The call-to-action button label.",
                },
                "body": {
                    "type": "string",
                    "description": "Optional supporting body line.",
                },
                "badge": {
                    "type": "string",
                    "description": (
                        "Optional short badge chip (e.g. a limited-offer flag; "
                        "used by the minimal_badge template)."
                    ),
                },
                "template": {
                    "type": "string",
                    "enum": list(composer.TEMPLATES),
                    "default": "hero_overlay",
                    "description": "Layout template to render.",
                },
                "formats": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": sorted(FORMATS_BY_ID),
                    },
                    "uniqueItems": True,
                    "default": ["meta_feed_1x1"],
                    "description": "Target format ids to render.",
                },
            },
            "required": ["visual_path", "headline", "cta"],
        },
    ),
]


def _error(message: str) -> list[TextContent]:
    """Return a JSON error envelope ``{"error": message}``."""
    return _json_result({"error": message})


def _safe_is_configured(provider: ImageProvider) -> bool:
    try:
        return bool(provider.is_configured())
    except Exception:  # noqa: BLE001 — a broken provider is simply unavailable
        logger.debug("is_configured failed for provider %r", provider, exc_info=True)
        return False


def _resolve_providers(provider_arg: str | None) -> list[ImageProvider]:
    """Resolve the provider(s) to use from the ``provider`` argument.

    - ``"all"`` → every configured provider (fan-out).
    - a name → that provider, only if configured.
    - omitted → the first configured provider.
    """
    providers = available_providers()
    configured = [p for p in providers if _safe_is_configured(p)]
    if provider_arg == "all":
        return configured
    if provider_arg:
        return [
            p for p in providers if p.name == provider_arg and _safe_is_configured(p)
        ]
    return configured[:1]


async def _handle_providers_list(_arguments: dict[str, Any]) -> list[TextContent]:
    payload: list[dict[str, Any]] = []
    for provider in available_providers():
        payload.append(
            {
                "name": provider.name,
                "configured": _safe_is_configured(provider),
                "capabilities": provider.capabilities(),
                "models": list(provider.models),
            }
        )
    return _json_result({"providers": payload})


async def _handle_generate_visual(arguments: dict[str, Any]) -> list[TextContent]:
    prompt = _require(arguments, "prompt")
    aspect = _opt(arguments, "aspect", "square")
    n = int(_opt(arguments, "n", 2))
    provider_arg = _opt(arguments, "provider")
    template = _opt(arguments, "template")

    # Validate the template at the boundary (the schema enum is advisory only):
    # an unknown value would inject no guidance yet still be recorded in the
    # manifest, making the provenance lie — and a non-string value would crash
    # ``build_visual_prompt`` before the error envelope. Reject it, mirroring the
    # server-side check in ``creative_studio_compose``.
    if template is not None and template not in composer.TEMPLATES:
        valid = ", ".join(composer.TEMPLATES)
        return _error(f"unknown template {template!r}. Valid templates: {valid}")

    providers = _resolve_providers(provider_arg)
    if not providers:
        return _error(
            "No image provider is configured. Add an API key in the dashboard "
            "'creative_studio' credentials section, or export one of the "
            "environment variables OPENAI_API_KEY, GEMINI_API_KEY, FAL_KEY, "
            "then retry."
        )

    width, height = generation_size_for_aspect(aspect)
    wrapped_prompt = build_visual_prompt(prompt, template)
    fan_out = provider_arg == "all"

    run_dir = create_run_dir()
    run_id = run_dir.name

    try:
        files_meta = await _generate_into(
            providers,
            run_dir=run_dir,
            prompt=wrapped_prompt,
            width=width,
            height=height,
            n=1 if fan_out else n,
        )
    except Exception as exc:  # noqa: BLE001 — surface as an error envelope
        logger.warning("creative_studio_generate_visual failed", exc_info=True)
        return _error(f"visual generation failed: {exc}")

    model = (
        providers[0].models[0] if len(providers) == 1 and providers[0].models else None
    )
    manifest_data: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider_arg or providers[0].name,
        "model": model,
        "prompt": prompt,
        "aspect": aspect,
        "n": n,
        "template": template,
        "files": files_meta,
    }
    manifest_path = write_manifest(run_dir, manifest_data)
    _record_audit(run_id, manifest_path)

    return _json_result(
        {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "files": files_meta,
            "manifest": str(manifest_path),
        }
    )


async def _generate_into(
    providers: list[ImageProvider],
    *,
    run_dir: Path,
    prompt: str,
    width: int,
    height: int,
    n: int,
) -> list[dict[str, Any]]:
    """Generate with each provider, write + validate PNGs, return file metadata."""
    files_meta: list[dict[str, Any]] = []
    for provider in providers:
        # Throttle EACH provider call.
        await _THROTTLER.acquire()
        images = await provider.generate(prompt, width=width, height=height, n=n)
        for index, data in enumerate(images):
            filename = f"{provider.name}_{index:02d}.png"
            path = write_bytes(run_dir / filename, data)
            # Validate before including the file in the result (fail closed).
            validate_image_file(
                str(path),
                max_size_bytes=_MAX_IMAGE_BYTES,
                max_size_label=_MAX_IMAGE_LABEL,
                allowed_extensions=_ALLOWED_IMAGE_EXTENSIONS,
            )
            files_meta.append(
                {
                    "path": str(path),
                    "sha256": sha256_of(path),
                    "provider": provider.name,
                }
            )
    return files_meta


def _record_audit(run_id: str, manifest_path: Path) -> None:
    """Best-effort audit-only action_log entry. No-op without STATE.json.

    Mirrors :mod:`mureo.mcp.native_reversal`: wrapped in try/except so it
    never breaks the tool call, and records nothing when there is no
    STATE.json in the current working directory. ``reversible_params`` is
    ``None`` — visual generation writes local files only and is not a
    platform mutation to reverse.
    """
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log

        now = datetime.now(timezone.utc)
        entry = ActionLogEntry(
            timestamp=now.isoformat(timespec="seconds"),
            action="creative_studio_generate_visual",
            platform="creative_studio",
            summary=f"Generated key visuals (run {run_id})",
            command="creative_studio_generate_visual",
            metrics_at_action={
                "run_id": run_id,
                "manifest_path": str(manifest_path),
            },
            reversible_params=None,
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — auditing must never break the tool call
        logger.warning(
            "creative_studio audit action_log promotion failed", exc_info=True
        )


def _brand_summary(brand: BrandKit) -> dict[str, Any]:
    """Serialisable summary of a brand kit for a manifest / tool result."""
    return {
        "colors": dict(brand.colors),
        "fonts": dict(brand.fonts),
        "logo": str(brand.logo_path) if brand.logo_path is not None else None,
        "logo_min_clear_px": brand.logo_min_clear_px,
        "defaults_used": brand == DEFAULT_BRAND_KIT,
    }


async def _handle_brand_kit_get(_arguments: dict[str, Any]) -> list[TextContent]:
    brand = load_brand_kit()
    return _json_result(_brand_summary(brand))


def _resolve_edit_provider(provider_arg: str | None) -> ImageProvider | None:
    """Resolve the provider for an edit call.

    A named provider must merely be configured (a non-edit provider then
    surfaces a clear NotSupportedError envelope at call time). With no name,
    the first configured provider advertising edit support is chosen.
    """
    configured = [p for p in available_providers() if _safe_is_configured(p)]
    if provider_arg:
        for provider in configured:
            if provider.name == provider_arg:
                return provider
        return None
    for provider in configured:
        try:
            if provider.capabilities().get("edit"):
                return provider
        except Exception:  # noqa: BLE001 — a broken provider is simply skipped
            logger.debug("capabilities() failed for %r", provider, exc_info=True)
    return None


def _next_free_edit_path(input_path: Path) -> Path:
    """Return ``<stem>_edit_<k>.png`` next to ``input_path`` for the next free k."""
    parent = input_path.parent
    stem = input_path.stem
    k = 1
    while True:
        candidate = parent / f"{stem}_edit_{k}.png"
        if not candidate.exists():
            return candidate
        k += 1


async def _handle_edit_visual(arguments: dict[str, Any]) -> list[TextContent]:
    path_arg = _require(arguments, "path")
    instruction = _require(arguments, "instruction")
    provider_arg = _opt(arguments, "provider")

    try:
        in_path = validate_image_file(
            str(path_arg),
            max_size_bytes=_MAX_IMAGE_BYTES,
            max_size_label=_MAX_IMAGE_LABEL,
            allowed_extensions=_ALLOWED_IMAGE_EXTENSIONS,
        )
    except (ValueError, FileNotFoundError) as exc:
        return _error(f"invalid image path: {exc}")

    provider = _resolve_edit_provider(provider_arg)
    if provider is None:
        if provider_arg:
            return _error(
                f"provider {provider_arg!r} is not configured. Configure it in "
                "the dashboard 'creative_studio' credentials section first."
            )
        return _error(
            "No image provider with edit capability is configured. Add an "
            "edit-capable provider's API key (e.g. OPENAI_API_KEY) in the "
            "'creative_studio' credentials section, then retry."
        )

    try:
        await _THROTTLER.acquire()
        edited = await provider.edit(in_path.read_bytes(), instruction)
    except NotSupportedError as exc:
        return _error(
            f"provider {provider.name!r} does not support image editing: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 — surface as an error envelope
        logger.warning("creative_studio_edit_visual failed", exc_info=True)
        return _error(f"image edit failed: {exc}")

    out_path = write_bytes(_next_free_edit_path(in_path), edited)
    try:
        validate_image_file(
            str(out_path),
            max_size_bytes=_MAX_IMAGE_BYTES,
            max_size_label=_MAX_IMAGE_LABEL,
            allowed_extensions=_ALLOWED_IMAGE_EXTENSIONS,
        )
    except (ValueError, FileNotFoundError) as exc:
        return _error(f"edited image failed validation: {exc}")

    sha = sha256_of(out_path)
    _studio_audit(
        "creative_studio_edit_visual",
        f"Edited visual {in_path.name} -> {out_path.name} via {provider.name}",
        {"input": str(in_path), "output": str(out_path), "provider": provider.name},
    )
    return _json_result(
        {"path": str(out_path), "sha256": sha, "provider": provider.name}
    )


async def _handle_compose(arguments: dict[str, Any]) -> list[TextContent]:
    visual_path = _require(arguments, "visual_path")
    headline = _require(arguments, "headline")
    cta = _require(arguments, "cta")
    body = _opt(arguments, "body")
    badge = _opt(arguments, "badge")
    template = _opt(arguments, "template", "hero_overlay")
    formats = _opt(arguments, "formats") or ["meta_feed_1x1"]

    try:
        vpath = validate_image_file(
            str(visual_path),
            max_size_bytes=_MAX_IMAGE_BYTES,
            max_size_label=_MAX_IMAGE_LABEL,
            allowed_extensions=_COMPOSE_INPUT_EXTENSIONS,
        )
    except (ValueError, FileNotFoundError) as exc:
        return _error(f"invalid visual path: {exc}")

    if template not in composer.TEMPLATES:
        valid = ", ".join(composer.TEMPLATES)
        return _error(f"unknown template {template!r}. Valid templates: {valid}")

    if not isinstance(formats, list) or not formats:
        return _error("formats must be a non-empty array of format ids")
    # Defensively dedupe (preserving order): the schema declares uniqueItems,
    # but the handler can be called directly, so never render a format twice.
    formats = list(dict.fromkeys(formats))
    unknown = [f for f in formats if f not in FORMATS_BY_ID]
    if unknown:
        valid = ", ".join(sorted(FORMATS_BY_ID))
        return _error(f"unknown format id(s): {unknown}. Valid format ids: {valid}")

    brand = load_brand_kit()
    copy = composer.CopySpec(headline=headline, body=body, cta=cta, badge=badge)

    run_dir = create_run_dir()
    run_id = run_dir.name

    try:
        files_meta = await composer.compose(
            vpath, copy, template, formats, brand, run_dir
        )
    except RuntimeError as exc:
        # Missing 'creative' extra — surface the pip hint verbatim.
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 — surface as an error envelope
        logger.warning("creative_studio_compose failed", exc_info=True)
        return _error(f"composition failed: {exc}")

    manifest_data: dict[str, Any] = {
        "kind": "compose",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "template": template,
        "inputs": {
            "visual_path": str(vpath),
            "visual_sha256": sha256_of(vpath),
        },
        "copy": {"headline": headline, "body": body, "cta": cta, "badge": badge},
        "brand": _brand_summary(brand),
        "files": files_meta,
    }
    manifest_path = write_manifest(run_dir, manifest_data)
    _studio_audit(
        "creative_studio_compose",
        f"Composed {len(files_meta)} banner(s) with '{template}' (run {run_id})",
        {"run_id": run_id, "manifest_path": str(manifest_path)},
    )

    return _json_result(
        {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "files": files_meta,
            "manifest": str(manifest_path),
        }
    )


def _studio_audit(action: str, summary: str, metrics: dict[str, Any]) -> None:
    """Best-effort audit-only action_log entry. No-op without STATE.json.

    Mirrors :func:`_record_audit`: wrapped in try/except so it never breaks
    the tool call, and records nothing when there is no STATE.json in the
    current working directory. ``reversible_params`` is ``None`` — composition
    and edits write local files only and are not platform mutations to
    reverse.
    """
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log

        now = datetime.now(timezone.utc)
        entry = ActionLogEntry(
            timestamp=now.isoformat(timespec="seconds"),
            action=action,
            platform="creative_studio",
            summary=summary,
            command=action,
            metrics_at_action=metrics,
            reversible_params=None,
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — auditing must never break the tool call
        logger.warning(
            "creative_studio audit action_log promotion failed", exc_info=True
        )


_HANDLERS = {
    "creative_studio_providers_list": _handle_providers_list,
    "creative_studio_generate_visual": _handle_generate_visual,
    "creative_studio_brand_kit_get": _handle_brand_kit_get,
    "creative_studio_edit_visual": _handle_edit_visual,
    "creative_studio_compose": _handle_compose,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a Creative Studio tool call."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


__all__ = ["TEMPLATE_NEGATIVE_SPACE", "TOOLS", "build_visual_prompt", "handle_tool"]
