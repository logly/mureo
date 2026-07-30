"""CLI startup import hygiene — no eager Google SDK import (#486).

On Python 3.10 (the minimum supported version) ``google.api_core`` emits a
``FutureWarning`` at import time about the 2026-10-04 end of 3.10 support,
and ``google.ads.googleads`` emits a second one for its versioned package.
Before this guard, *every* ``mureo`` invocation printed both — including
``--help``, ``demo init`` and ``byod status``, none of which touch Google —
because ``mureo.cli.main`` → ``mureo.cli.auth_cmd`` → ``mureo.auth`` pulled
the Google Ads SDK in at module scope.

Four lines of vendor warning noise before any mureo output is the first
thing a new user sees after ``pip install mureo``, so the fix is a root
one: the SDK is imported lazily, inside the factories that actually build
a Google client. These tests pin both halves of that contract —

  - importing the CLI entry point leaves ``google.*`` out of ``sys.modules``
    and writes nothing to stderr, and
  - the Google path still works, importing the SDK on demand.

Everything runs in a subprocess because ``sys.modules`` state is global and
the rest of the suite imports the SDK freely.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Warning/exception markers that must never appear on a CLI startup path.
#: Mirrors the CI quickstart smoke gate (#488).
_NOISE_MARKERS = ("FutureWarning", "DeprecationWarning", "Traceback")

#: Snippet that prints every ``google`` module left in ``sys.modules``.
_GOOGLE_MODULES_SNIPPET = (
    "print(sorted(m for m in sys.modules "
    "if m == 'google' or m.startswith('google.') or m.startswith('google_')))"
)


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter with all warnings enabled.

    ``-W default`` re-enables the warnings Python hides by default, so a
    regression surfaces here even when the ambient filter is quiet. ``cwd``
    is the repo root so the checkout under test wins over any ``mureo``
    installed in site-packages.
    """
    return subprocess.run(
        [sys.executable, "-W", "default", "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
        check=False,
    )


def _assert_no_noise(result: subprocess.CompletedProcess[str], label: str) -> None:
    combined = result.stdout + result.stderr
    for marker in _NOISE_MARKERS:
        assert marker not in combined, (
            f"{label} emitted {marker}:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


#: Modules on the startup path of commands that never talk to Google.
#:
#: - ``mureo.cli.main`` — the console entry point itself (every command).
#: - ``mureo.auth`` — reached via ``mureo.cli.auth_cmd``; loads credentials,
#:   which needs no SDK (only *building* a client does).
#: - ``mureo.auth_setup`` — imported by ``mureo setup <agent> --skip-auth``
#:   for ``install_mcp_config`` / ``install_credential_guard``, neither of
#:   which touches Google. It also re-exports the account-listing helpers for
#:   backward compatibility, which is what used to drag the SDK in.
#: - ``mureo.cli.web_auth`` — the ``mureo configure`` OAuth wizard. Deferring
#:   the re-exports behind ``__getattr__`` is not enough on its own here: a
#:   top-level ``from mureo.auth_setup import list_accessible_accounts``
#:   *triggers* ``__getattr__`` at import time and loads the SDK anyway.
_SDK_FREE_MODULES = (
    "mureo.cli.main",
    "mureo.auth",
    "mureo.auth_setup",
    "mureo.cli.web_auth",
)


class TestCliStartupDoesNotImportGoogleSdk:
    """CLI startup must not drag the Google SDK in."""

    @pytest.mark.parametrize("module_name", _SDK_FREE_MODULES)
    def test_import_leaves_google_out_of_sys_modules(self, module_name: str) -> None:
        result = _run_python(
            f"import sys\nimport {module_name}\n{_GOOGLE_MODULES_SNIPPET}\n"
        )

        assert result.returncode == 0, result.stderr
        assert (
            result.stdout.strip() == "[]"
        ), f"{module_name} imported Google modules at import time: {result.stdout.strip()}"

    @pytest.mark.parametrize("module_name", _SDK_FREE_MODULES)
    def test_import_writes_nothing_to_stderr(self, module_name: str) -> None:
        result = _run_python(f"import {module_name}")

        assert result.returncode == 0, result.stderr
        _assert_no_noise(result, f"import {module_name}")
        assert result.stderr == "", f"unexpected stderr:\n{result.stderr}"


class TestCliCommandsAreNoiseFree:
    """The commands a first-time user runs print only their own output."""

    @pytest.mark.parametrize("argv", [["--help"], ["--version"], ["byod", "--help"]])
    def test_command_output_is_free_of_warnings(self, argv: list[str]) -> None:
        result = subprocess.run(
            [sys.executable, "-W", "default", "-m", "mureo", *argv],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
            check=False,
        )

        assert result.returncode == 0, result.stderr
        _assert_no_noise(result, f"mureo {' '.join(argv)}")


class TestGoogleAdsPathStillWorks:
    """Laziness must not break the commands that DO need the SDK."""

    def test_creating_a_google_ads_client_imports_the_sdk_on_demand(self) -> None:
        result = _run_python(
            "import sys\n"
            "from mureo.auth import GoogleAdsCredentials, create_google_ads_client\n"
            "assert 'google.ads.googleads.client' not in sys.modules, "
            "'SDK imported eagerly by mureo.auth'\n"
            "creds = GoogleAdsCredentials(\n"
            "    developer_token='dev-tok',\n"
            "    client_id='cid',\n"
            "    client_secret='csec',\n"
            "    refresh_token='rtok',\n"
            "    login_customer_id='1234567890',\n"
            ")\n"
            "client = create_google_ads_client(creds, customer_id='5555555555')\n"
            "assert type(client).__name__ == 'GoogleAdsApiClient', type(client)\n"
            "assert 'google.ads.googleads.client' in sys.modules, "
            "'SDK never loaded on demand'\n"
            "print('OK')\n"
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "OK"

    def test_account_listing_reexports_still_resolve(self) -> None:
        """The backward-compat aliases on ``mureo.auth_setup`` still work.

        ``mureo.auth_setup.list_accessible_accounts`` /
        ``list_meta_ad_accounts`` are documented legacy import paths, so
        deferring them must not turn either into an ``AttributeError``.

        This covers *import* identity only. That the wizards still route
        their calls through these module attributes — so patching the legacy
        name actually intercepts the network call — is the separate,
        behavioural guarantee proven in
        ``tests/test_public_account_listing.py``.
        """
        result = _run_python(
            "import mureo.auth_setup as m\n"
            "from mureo.google_ads.accounts import list_accessible_accounts\n"
            "from mureo.meta_ads.accounts import list_meta_ad_accounts\n"
            "assert m.list_accessible_accounts is list_accessible_accounts\n"
            "assert m.list_meta_ad_accounts is list_meta_ad_accounts\n"
            "from mureo.auth_setup import list_accessible_accounts as viafrom\n"
            "assert viafrom is list_accessible_accounts\n"
            "print('OK')\n"
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "OK"

    def test_google_oauth_flow_builder_still_works(self) -> None:
        """``build_google_flow`` imports google-auth-oauthlib on demand."""
        result = _run_python(
            "import sys\n"
            "import mureo.auth_setup as m\n"
            "assert 'google_auth_oauthlib.flow' not in sys.modules, "
            "'OAuth lib imported eagerly'\n"
            "installed = m.build_google_flow(client_id='cid', client_secret='csec')\n"
            "assert type(installed).__name__ == 'InstalledAppFlow', type(installed)\n"
            "web = m.build_google_flow(client_id='cid', client_secret='csec', "
            "redirect_uri='http://localhost:1/cb')\n"
            "assert type(web).__name__ == 'Flow', type(web)\n"
            "assert 'google_auth_oauthlib.flow' in sys.modules\n"
            "print('OK')\n"
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "OK"

    def test_creating_a_meta_ads_client_still_works(self) -> None:
        result = _run_python(
            "from mureo.auth import MetaAdsCredentials, create_meta_ads_client\n"
            "creds = MetaAdsCredentials(access_token='tok', account_id='act_1')\n"
            "client = create_meta_ads_client(creds, account_id='act_1')\n"
            "assert type(client).__name__ == 'MetaAdsApiClient', type(client)\n"
            "print('OK')\n"
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "OK"
