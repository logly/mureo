"""Unit tests for the Codex CLI image provider.

Hermetic: no real ``codex`` process is ever spawned. A tiny fake ``codex``
executable is placed on ``PATH`` (an absolute-shebang Python script) that
writes a valid PNG to the ``-C`` working directory. Its behaviour is driven by
a ``control.json`` written *next to the fake binary* (NOT via environment
variables) — deliberately, because the provider now spawns codex with a minimal
allow-listed environment, so any test-control env var would be stripped before
the fake could read it. Reading control from a sidecar file keeps the tests
working end-to-end against the real argv / subprocess / env-filtering path
without any network, API key, or ChatGPT login.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import mureo.creative_studio.providers.codex_cli as codex_mod
from mureo.creative_studio.providers import NotSupportedError, available_providers

# The 8-byte PNG signature the provider validates its output against.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _write_fake_codex(bin_dir: Path) -> Path:
    """Write a fake ``codex`` executable into ``bin_dir`` and return its path.

    Behaviour is read at call time from ``<bin_dir>/control.json`` (resolved
    relative to the fake's own path, so it survives a stripped environment):

    - ``mode`` — ok (default) / sleep / none / auth / empty / leak / symlink
    - ``argv_log`` / ``env_log`` / ``calls_log`` — optional file paths the fake
      dumps its argv / environ / per-invocation ``-C`` dir into
    - ``leak_value`` — the token the ``leak`` mode prints to stderr
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "codex"
    body = f"""#!{sys.executable}
import sys, os, time, json

here = os.path.dirname(os.path.realpath(sys.argv[0]))
control = {{}}
cpath = os.path.join(here, "control.json")
if os.path.exists(cpath):
    with open(cpath, encoding="utf-8") as fh:
        control = json.load(fh)

argv = sys.argv
if control.get("argv_log"):
    with open(control["argv_log"], "w", encoding="utf-8") as fh:
        json.dump(argv, fh)
if control.get("env_log"):
    with open(control["env_log"], "w", encoding="utf-8") as fh:
        json.dump(dict(os.environ), fh)

outdir = os.getcwd()
if "-C" in argv:
    outdir = argv[argv.index("-C") + 1]

if control.get("calls_log"):
    with open(control["calls_log"], "a", encoding="utf-8") as fh:
        fh.write(outdir + "\\n")

mode = control.get("mode", "ok")
png = b"\\x89PNG\\r\\n\\x1a\\n fake codex image bytes"
out = os.path.join(outdir, "output.png")

if mode == "sleep":
    time.sleep(30)
    mode = "ok"
if mode == "auth":
    sys.stderr.write("stream error: You must be logged in. Run `codex login`.\\n")
    sys.exit(1)
if mode == "none":
    sys.stderr.write("some transient failure while generating the image\\n")
    sys.exit(1)
if mode == "leak":
    token = control.get("leak_value", "LEAK")
    sys.stderr.write("boom: request failed with token=" + token + " (bad)\\n")
    sys.exit(1)
if mode == "empty":
    open(out, "wb").close()
    sys.exit(0)
if mode == "symlink":
    target = os.path.join(outdir, "secret_target.bin")
    with open(target, "wb") as fh:
        fh.write(b"\\x89PNG\\r\\n\\x1a\\n SECRET CONTENT")
    os.symlink(target, out)
    sys.exit(0)

with open(out, "wb") as fh:
    fh.write(png)
sys.exit(0)
"""
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return script


@pytest.fixture
def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Put a fake ``codex`` on an isolated ``PATH`` with a ``configure`` helper."""
    bin_dir = tmp_path / "bin"
    _write_fake_codex(bin_dir)
    control_path = bin_dir / "control.json"
    # Isolate PATH to the fake bin dir so ``shutil.which`` never finds a real
    # codex; the fake uses an absolute shebang so it needs nothing else on PATH.
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("MUREO_CODEX_TIMEOUT", raising=False)

    def configure(**kwargs: object) -> None:
        data: dict[str, object] = {"mode": "ok"}
        data.update(kwargs)
        control_path.write_text(json.dumps(data), encoding="utf-8")

    configure()  # default: happy path
    return SimpleNamespace(bin_dir=bin_dir, configure=configure)


# ---------------------------------------------------------------------------
# is_configured / discovery
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_configured_true_when_on_path(fake_codex: SimpleNamespace) -> None:
    assert codex_mod.CodexCliImageProvider().is_configured() is True


@pytest.mark.unit
def test_is_configured_false_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_mod.shutil, "which", lambda _name: None)
    assert codex_mod.CodexCliImageProvider().is_configured() is False


@pytest.mark.unit
def test_codex_registered_in_available_providers(fake_codex: SimpleNamespace) -> None:
    names = {p.name for p in available_providers()}
    assert "codex" in names


@pytest.mark.unit
def test_capabilities_advertise_no_api_key() -> None:
    caps = codex_mod.CodexCliImageProvider().capabilities()
    assert "edit" in caps
    assert isinstance(caps["max_size"], list) and len(caps["max_size"]) == 2
    # Codex needs no API key — only the local `codex login`.
    assert caps["requires_api_key"] is False
    assert caps["auth"] == "codex_cli_login"


@pytest.mark.unit
def test_capabilities_edit_is_false() -> None:
    # The CLI edit path is agent-mediated and not reliable enough to ship
    # (see the live-validation note in the module docstring).
    assert codex_mod.CodexCliImageProvider().capabilities()["edit"] is False


@pytest.mark.unit
async def test_edit_raises_not_supported() -> None:
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(NotSupportedError):
        await provider.edit(b"data", "make it warmer")


# ---------------------------------------------------------------------------
# generate — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_returns_png_bytes(fake_codex: SimpleNamespace) -> None:
    provider = codex_mod.CodexCliImageProvider()
    images = await provider.generate("a calm lake", width=1024, height=1024, n=1)
    assert len(images) == 1
    assert images[0].startswith(_PNG_MAGIC)


@pytest.mark.unit
async def test_generate_n2_runs_sequentially_in_distinct_dirs(
    fake_codex: SimpleNamespace, tmp_path: Path
) -> None:
    calls_log = tmp_path / "calls.txt"
    fake_codex.configure(calls_log=str(calls_log))
    provider = codex_mod.CodexCliImageProvider()
    images = await provider.generate("a fox", width=1024, height=1024, n=2)
    assert len(images) == 2
    assert all(img.startswith(_PNG_MAGIC) for img in images)
    dirs = calls_log.read_text(encoding="utf-8").split()
    assert len(dirs) == 2  # two sequential invocations
    assert len(set(dirs)) == 2  # each in its own private temp dir


@pytest.mark.unit
@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1024, 1024, "1024x1024"),
        (1920, 1080, "1536x1024"),
        (1080, 1920, "1024x1536"),
        (2000, 500, "1536x1024"),
    ],
)
async def test_generate_clamps_size_into_instruction(
    fake_codex: SimpleNamespace,
    tmp_path: Path,
    width: int,
    height: int,
    expected: str,
) -> None:
    argv_log = tmp_path / "argv.json"
    fake_codex.configure(argv_log=str(argv_log))
    provider = codex_mod.CodexCliImageProvider()
    await provider.generate("a bird", width=width, height=height, n=1)
    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    instruction = argv[-1]  # prompt is the final argv element
    assert expected in instruction


# ---------------------------------------------------------------------------
# generate — argv is exec-form (no shell) + end-of-options hardening
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_uses_exec_form_argv(
    fake_codex: SimpleNamespace, tmp_path: Path
) -> None:
    argv_log = tmp_path / "argv.json"
    fake_codex.configure(argv_log=str(argv_log))
    # A prompt full of shell metacharacters — with exec form these are inert.
    nasty = "a cat; rm -rf / && echo $(whoami) | cat > /tmp/pwn `id`"
    provider = codex_mod.CodexCliImageProvider()
    images = await provider.generate(nasty, width=1024, height=1024, n=1)
    assert images[0].startswith(_PNG_MAGIC)

    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    assert Path(argv[0]).name == "codex"
    assert argv[1] == "exec"
    assert "--sandbox" in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "--skip-git-repo-check" in argv
    assert "-C" in argv
    # The whole prompt rides inside a single argv element (the instruction),
    # passed verbatim — never split across argv by a shell and never
    # interpreted, proving the exec (non-shell) invocation.
    assert argv[-1].count(nasty) == 1
    assert sum(1 for a in argv if nasty in a) == 1


@pytest.mark.unit
async def test_generate_inserts_end_of_options_separator(
    fake_codex: SimpleNamespace, tmp_path: Path
) -> None:
    argv_log = tmp_path / "argv.json"
    fake_codex.configure(argv_log=str(argv_log))
    # A prompt that begins with '--' would look like an option without a guard.
    nasty = "--dangerously-bypass-approvals-and-sandbox then draw a fox"
    provider = codex_mod.CodexCliImageProvider()
    await provider.generate(nasty, width=1024, height=1024, n=1)

    argv = json.loads(argv_log.read_text(encoding="utf-8"))
    # Exactly one bare end-of-options marker (distinct from --sandbox etc.),
    # immediately before the instruction — so nothing after it is parsed as a
    # codex flag.
    assert argv.count("--") == 1
    assert argv[-2] == "--"
    assert nasty in argv[-1]


# ---------------------------------------------------------------------------
# generate — environment hardening + start_new_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_spawns_with_filtered_env_and_new_session(
    fake_codex: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    real = codex_mod.asyncio.create_subprocess_exec

    async def _wrapper(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs
        return await real(*args, **kwargs)

    monkeypatch.setattr(codex_mod.asyncio, "create_subprocess_exec", _wrapper)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-secret-gemini")
    monkeypatch.setenv("FAL_KEY", "fal-secret-key")

    provider = codex_mod.CodexCliImageProvider()
    await provider.generate("a bird", width=1024, height=1024, n=1)

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    # New session/process group for group-kill on timeout.
    assert kwargs.get("start_new_session") is True
    env = kwargs.get("env")
    assert isinstance(env, dict)
    # Provider secrets are stripped; PATH/HOME survive.
    assert "OPENAI_API_KEY" not in env
    assert "GEMINI_API_KEY" not in env
    assert "FAL_KEY" not in env
    assert "PATH" in env
    assert "HOME" in env


@pytest.mark.unit
async def test_child_process_environ_excludes_provider_keys(
    fake_codex: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_log = tmp_path / "env.json"
    fake_codex.configure(env_log=str(env_log))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-secret-gemini")
    monkeypatch.setenv("FAL_KEY", "fal-secret-key")

    provider = codex_mod.CodexCliImageProvider()
    await provider.generate("a bird", width=1024, height=1024, n=1)

    child_env = json.loads(env_log.read_text(encoding="utf-8"))
    # The child (fake codex) actually received a filtered environment.
    assert "OPENAI_API_KEY" not in child_env
    assert "GEMINI_API_KEY" not in child_env
    assert "FAL_KEY" not in child_env
    assert "PATH" in child_env
    assert "HOME" in child_env


# ---------------------------------------------------------------------------
# generate — failure paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_missing_binary_raises_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(codex_mod.shutil, "which", lambda _name: None)
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    msg = str(excinfo.value)
    assert "codex" in msg.lower()
    assert "PATH" in msg


@pytest.mark.unit
async def test_generate_timeout_kills_and_raises(
    fake_codex: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_codex.configure(mode="sleep")
    monkeypatch.setenv("MUREO_CODEX_TIMEOUT", "0.5")
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    assert "timed out" in str(excinfo.value).lower()
    assert "MUREO_CODEX_TIMEOUT" in str(excinfo.value)


@pytest.mark.unit
async def test_generate_output_missing_surfaces_stderr(
    fake_codex: SimpleNamespace,
) -> None:
    fake_codex.configure(mode="none")
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    assert "transient failure while generating" in str(excinfo.value)


@pytest.mark.unit
async def test_generate_empty_output_raises(fake_codex: SimpleNamespace) -> None:
    fake_codex.configure(mode="empty")
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError):
        await provider.generate("x", width=1024, height=1024, n=1)


@pytest.mark.unit
async def test_generate_auth_error_adds_login_hint(
    fake_codex: SimpleNamespace,
) -> None:
    fake_codex.configure(mode="auth")
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    assert "codex login" in str(excinfo.value).lower()


@pytest.mark.unit
async def test_generate_rejects_symlink_output(fake_codex: SimpleNamespace) -> None:
    fake_codex.configure(mode="symlink")
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    msg = str(excinfo.value)
    assert "symlink" in msg.lower()
    # The symlink target's content must never be read into / disclosed.
    assert "SECRET CONTENT" not in msg


@pytest.mark.unit
async def test_generate_redacts_configured_secret_in_stderr(
    fake_codex: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-PLANTED-SECRET-abc123"
    fake_codex.configure(mode="leak", leak_value=secret)
    monkeypatch.setattr(
        codex_mod,
        "_creative_studio_secret",
        lambda field: secret if field == "openai_api_key" else None,
    )
    provider = codex_mod.CodexCliImageProvider()
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    msg = str(excinfo.value)
    assert secret not in msg
    assert "***" in msg


# ---------------------------------------------------------------------------
# providers_list handler row for codex
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_providers_list_row_for_codex(fake_codex: SimpleNamespace) -> None:
    import mureo.mcp.tools_creative_studio as mod

    result = await mod.handle_tool("creative_studio_providers_list", {})
    payload = json.loads(result[0].text)
    rows = {row["name"]: row for row in payload["providers"]}
    assert "codex" in rows
    codex_row = rows["codex"]
    assert codex_row["configured"] is True  # fake codex is on PATH
    assert codex_row["capabilities"]["requires_api_key"] is False
    assert codex_row["models"] == ["gpt-image"]
