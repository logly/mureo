"""MCP tool family for Creative Studio visual generation (PR-A).

Two tools, self-contained in one module (mirroring
``tools_analytics_registry``):

- ``creative_studio_providers_list`` — enumerate configured image providers
  and their capabilities.
- ``creative_studio_generate_visual`` — generate text-free key visuals with
  one or all configured providers, write them to a run directory with a
  provenance manifest, and return the paths.

The composer / templates / brand-kit tools arrive in PR-B.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool

from mureo._image_validation import validate_image_file
from mureo.creative_studio.formats import generation_size_for_aspect
from mureo.creative_studio.providers import ImageProvider, available_providers
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

# The hard constraint appended to every provider prompt: image models render
# text (especially Japanese) poorly, so they generate the VISUAL only — the
# typography layer (PR-B) overlays copy afterward.
_NO_TEXT_CONSTRAINT = (
    "Absolutely no text, no letters, no words, no typography, no watermarks, "
    "no logos in the image. Leave clean negative space suitable for overlaying "
    "headline text later."
)

_ASPECTS = ("square", "portrait", "landscape", "vertical")


def build_visual_prompt(user_prompt: str) -> str:
    """Wrap ``user_prompt`` with the hard no-text constraint."""
    return f"{user_prompt.strip()} {_NO_TEXT_CONSTRAINT}"


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
            },
            "required": ["prompt"],
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

    providers = _resolve_providers(provider_arg)
    if not providers:
        return _error(
            "No image provider is configured. Add an API key in the dashboard "
            "'creative_studio' credentials section, or export one of the "
            "environment variables OPENAI_API_KEY, GEMINI_API_KEY, FAL_KEY, "
            "then retry."
        )

    width, height = generation_size_for_aspect(aspect)
    wrapped_prompt = build_visual_prompt(prompt)
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


_HANDLERS = {
    "creative_studio_providers_list": _handle_providers_list,
    "creative_studio_generate_visual": _handle_generate_visual,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a Creative Studio tool call."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


__all__ = ["TOOLS", "build_visual_prompt", "handle_tool"]
