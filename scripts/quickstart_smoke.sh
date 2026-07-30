#!/usr/bin/env bash
#
# Quickstart smoke test (#488) — run the README's no-credentials quickstart
# end to end in a throwaway HOME and a throwaway virtualenv.
#
#   pip install mureo
#   mureo setup claude-code --skip-auth
#   mureo demo init --scenario seasonality-trap
#
# That path is the funnel entry for every first-time user, and nothing else
# guards it: a broken console entry point, a setup step that writes nowhere,
# or a demo bundle that stops importing would be reported by strangers rather
# than by CI. Every step is also asserted to be free of FutureWarning /
# DeprecationWarning / Traceback, which is what #486 (the google-api-core
# FutureWarnings printed on every command under Python 3.10) looked like.
#
# The script owns the whole rehearsal so a developer runs LOCALLY exactly what
# .github/workflows/quickstart-smoke.yml runs in CI — the workflow only picks
# the interpreter and the install spec.
#
# Environment:
#   MUREO_SMOKE_PYTHON        Interpreter to build the venv from (default: python3)
#   MUREO_SMOKE_INSTALL_SPEC  What to `pip install` (default: this checkout).
#                             Set to `mureo` for the weekly PyPI-wheel variant.
#   MUREO_SMOKE_WORKDIR       Scratch dir to use (default: a fresh mktemp -d).
#   MUREO_SMOKE_KEEP          Set to 1 to keep an auto-created workdir even on
#                             success (it is always kept on failure).
#
# Usage:
#   scripts/quickstart_smoke.sh
#   MUREO_SMOKE_INSTALL_SPEC=mureo scripts/quickstart_smoke.sh
#
# pipefail matters here: the assertion helpers pipe command output, and
# without it a failure on the left of a pipe would be masked by a successful
# grep/sed on the right.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${MUREO_SMOKE_PYTHON:-python3}"
INSTALL_SPEC="${MUREO_SMOKE_INSTALL_SPEC:-$REPO_ROOT}"
if [ -n "${MUREO_SMOKE_WORKDIR:-}" ]; then
    WORK_DIR="$MUREO_SMOKE_WORKDIR"
    OWNS_WORKDIR=0 # caller-supplied (CI): never remove it, the caller owns it
else
    WORK_DIR="$(mktemp -d)"
    OWNS_WORKDIR=1
fi

SANDBOX_HOME="$WORK_DIR/home"
VENV_DIR="$WORK_DIR/venv"
WORKSPACE="$WORK_DIR/workspace"
LOG_DIR="$WORK_DIR/logs"

mkdir -p "$SANDBOX_HOME" "$WORKSPACE" "$LOG_DIR"

# Clean up an auto-created workdir on SUCCESS only — a venv plus 25 installed
# skills is not something to leave behind on every local run. On failure it is
# kept deliberately: the captured step logs under $LOG_DIR and the sandbox
# HOME are the evidence needed to debug. MUREO_SMOKE_KEEP=1 keeps it always.
cleanup() {
    cleanup_rc=$?
    if [ "$cleanup_rc" -eq 0 ] &&
        [ "$OWNS_WORKDIR" -eq 1 ] &&
        [ "${MUREO_SMOKE_KEEP:-0}" != "1" ]; then
        rm -rf "$WORK_DIR"
    elif [ "$cleanup_rc" -ne 0 ]; then
        echo "(workdir kept for debugging: $WORK_DIR)"
    fi
}
trap cleanup EXIT

# A fresh HOME is the whole point: `mureo setup` writes to ~/.claude.json,
# ~/.claude/settings.json and ~/.claude/skills/, and `mureo demo init` writes
# to ~/.mureo/byod/. Redirecting HOME keeps the developer's real Claude Code
# config untouched and makes the assertions below meaningful.
export HOME="$SANDBOX_HOME"
# Do not let a developer's ~/.mureo overrides leak in through the env.
unset MUREO_BYOD_DIR 2>/dev/null || true
# Deterministic, parseable CLI output.
export NO_COLOR=1
# PYTHONWARNINGS is deliberately NOT forced to "default": this smoke asserts
# what a real first-time user actually SEES, under Python's stock filters.
# The stricter all-warnings-visible check (``python -W default``) lives in
# tests/test_cli_import_hygiene.py, where it can be scoped to mureo's own
# import path instead of every dependency's.

MUREO_BIN="$VENV_DIR/bin/mureo"
VENV_PYTHON="$VENV_DIR/bin/python"

STEP_NO=0

echo "=== mureo quickstart smoke ==="
echo "  python      : $PYTHON_BIN"
echo "  install spec: $INSTALL_SPEC"
echo "  sandbox HOME: $HOME"
echo "  workdir     : $WORK_DIR"
echo ""

fail() {
    echo ""
    echo "SMOKE FAILED: $1"
    exit 1
}

# Markers that must never appear in a mureo command's own output. #486 is
# exactly the FutureWarning case: two google-api-core blocks printed before
# any mureo output, on every command, under Python 3.10.
NOISE_MARKERS="FutureWarning DeprecationWarning Traceback"

# Run a command, capture stdout+stderr, and fail loudly on a non-zero exit or
# (unless $1 is "--exit-only") on any noise marker in the output. Echoes the
# captured output on failure so CI logs show the offending text, not just the
# assertion.
run_step() {
    check_noise=1
    if [ "$1" = "--exit-only" ]; then
        check_noise=0
        shift
    fi
    step_label="$1"
    shift
    STEP_NO=$((STEP_NO + 1))
    step_log="$LOG_DIR/$(printf '%02d' "$STEP_NO").log"

    echo "--- step $STEP_NO: $step_label"
    set +e
    "$@" >"$step_log" 2>&1
    step_rc=$?
    set -e

    if [ "$step_rc" -ne 0 ]; then
        echo "    exit code: $step_rc (expected 0)"
        echo "    --- captured output ---"
        sed 's/^/    /' "$step_log"
        fail "$step_label exited $step_rc"
    fi

    if [ "$check_noise" -eq 1 ]; then
        for marker in $NOISE_MARKERS; do
            if grep -q "$marker" "$step_log"; then
                echo "    --- captured output ---"
                sed 's/^/    /' "$step_log"
                fail "$step_label emitted '$marker' (see output above)"
            fi
        done
        echo "    ok (exit 0, output free of: $NOISE_MARKERS)"
    else
        echo "    ok (exit 0)"
    fi

    LAST_LOG="$step_log"
}

assert_file() {
    if [ ! -f "$1" ]; then
        echo "    contents of $(dirname "$1"):"
        ls -la "$(dirname "$1")" 2>&1 | sed 's/^/      /' || true
        fail "expected file is missing: $1"
    fi
    echo "    ok: $1"
}

assert_dir() {
    if [ ! -d "$1" ]; then
        fail "expected directory is missing: $1"
    fi
    echo "    ok: $1/"
}

# ---------------------------------------------------------------------------
# 1. Fresh venv + install
# ---------------------------------------------------------------------------
"$PYTHON_BIN" -m venv "$VENV_DIR"
# --exit-only: the noise gate is about MUREO's output. pip emits its own
# internal DeprecationWarnings on some interpreter/pip combinations, and a
# genuine install failure shows up as a non-zero exit anyway.
run_step --exit-only "pip install $INSTALL_SPEC" \
    "$VENV_PYTHON" -m pip install --disable-pip-version-check --quiet "$INSTALL_SPEC"

if [ ! -x "$MUREO_BIN" ]; then
    fail "console entry point was not installed at $MUREO_BIN"
fi

# ---------------------------------------------------------------------------
# 2. mureo --version (#487) — exit 0 and a single `mureo <version>` line
# ---------------------------------------------------------------------------
run_step "mureo --version" "$MUREO_BIN" --version
version_out="$(tr -d '\r' <"$LAST_LOG" | sed '/^$/d')"
if ! printf '%s' "$version_out" | grep -Eq '^mureo [0-9]+\.[0-9]+\.[0-9]+'; then
    echo "    got: [$version_out]"
    fail "mureo --version did not print a 'mureo <version>' line"
fi
echo "    ok: $version_out"

# ---------------------------------------------------------------------------
# 3. mureo setup claude-code --skip-auth — writes land under the sandbox HOME
# ---------------------------------------------------------------------------
run_step "mureo setup claude-code --skip-auth" \
    "$MUREO_BIN" setup claude-code --skip-auth

# ~/.claude.json root `mcpServers` is where Claude Code reads user-scope MCP
# servers from (auth_setup._claude_user_config_path); ~/.claude/settings.json
# carries the credential-guard hook; skills land in ~/.claude/skills/.
assert_file "$HOME/.claude.json"
assert_file "$HOME/.claude/settings.json"
assert_dir "$HOME/.claude/skills"
assert_file "$HOME/.claude/skills/daily-check/SKILL.md"
assert_file "$HOME/.claude/skills/_mureo-shared/SKILL.md"

"$VENV_PYTHON" -c '
import json, os, sys

home = os.environ["HOME"]
with open(os.path.join(home, ".claude.json"), encoding="utf-8") as fh:
    data = json.load(fh)
servers = data.get("mcpServers", {})
if "mureo" not in servers:
    print("FAIL: ~/.claude.json has no mcpServers.mureo entry")
    print(json.dumps(data, indent=2)[:2000])
    sys.exit(1)
print("    ok: ~/.claude.json registers mcpServers.mureo")

with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
    settings = json.load(fh)
hooks = settings.get("hooks", {}).get("PreToolUse", [])
if not hooks:
    print("FAIL: ~/.claude/settings.json has no PreToolUse credential guard")
    print(json.dumps(settings, indent=2)[:2000])
    sys.exit(1)
print("    ok: ~/.claude/settings.json installs the credential guard hook")
' || fail "mureo setup claude-code --skip-auth did not write the expected config"

# ---------------------------------------------------------------------------
# 4. mureo demo init --scenario seasonality-trap
# ---------------------------------------------------------------------------
cd "$WORKSPACE"
run_step "mureo demo init --scenario seasonality-trap" \
    "$MUREO_BIN" demo init --scenario seasonality-trap

DEMO_DIR="$WORKSPACE/mureo-demo"
assert_dir "$DEMO_DIR"
assert_file "$DEMO_DIR/STRATEGY.md"
assert_file "$DEMO_DIR/STATE.json"
assert_file "$DEMO_DIR/.mcp.json"
assert_file "$DEMO_DIR/bundle.xlsx"
assert_file "$DEMO_DIR/README.md"

# The demo bundle round-trips through `mureo byod import`, so both demo
# platforms must be registered in ~/.mureo/byod/manifest.json with their
# CSV directories on disk — that is what puts the MCP tools in BYOD mode.
assert_file "$HOME/.mureo/byod/manifest.json"
"$VENV_PYTHON" -c '
import json, os, sys

home = os.environ["HOME"]
byod = os.path.join(home, ".mureo", "byod")
with open(os.path.join(byod, "manifest.json"), encoding="utf-8") as fh:
    manifest = json.load(fh)
platforms = manifest.get("platforms", {})
missing = [p for p in ("google_ads", "meta_ads") if p not in platforms]
if missing:
    print("FAIL: manifest.json does not register %s" % ", ".join(missing))
    print(json.dumps(manifest, indent=2)[:2000])
    sys.exit(1)
for p in ("google_ads", "meta_ads"):
    if not os.path.isdir(os.path.join(byod, p)):
        print("FAIL: manifest registers %s but %s/ is missing on disk" % (p, p))
        sys.exit(1)
print("    ok: byod/manifest.json registers google_ads + meta_ads")
' || fail "mureo demo init did not register both BYOD platforms"

# ---------------------------------------------------------------------------
# 5. mureo byod status inside the demo workspace
# ---------------------------------------------------------------------------
cd "$DEMO_DIR"
run_step "mureo byod status" "$MUREO_BIN" byod status

echo ""
echo "=== quickstart smoke PASSED ($STEP_NO steps) ==="
