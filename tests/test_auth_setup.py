"""Tests for the Google Ads OAuth flow and setup wizard (TDD: RED -> GREEN -> IMPROVE)."""

from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth import GoogleAdsCredentials

# Windows test shim: `simple_term_menu` imports Unix-only `termios` and
# raises NotImplementedError at import on Windows, so even
# `patch("simple_term_menu.TerminalMenu", ...)` cannot resolve its
# target there. These tests exercise the arrow-menu and the
# numeric-input *fallback*; on a real Windows runtime the fallback is
# what executes (production's widened `except (ImportError,
# NotImplementedError)`), so installing a minimal stub here only lets
# the existing patch-based tests run on Windows — it does NOT fake
# product behaviour (production never sees this stub on real Windows;
# it genuinely has no simple_term_menu and falls back).
if sys.platform == "win32":  # pragma: no cover - Windows CI only
    import types as _types

    try:  # real package present? (won't be on Windows, but be safe)
        import simple_term_menu as _stm_real  # noqa: F401
    except Exception:
        _stm_stub = _types.ModuleType("simple_term_menu")

        class _StubTerminalMenu:  # patched per-test; never truly used
            def __init__(self, *a: object, **k: object) -> None: ...

            def show(self) -> None:
                return None

        _stm_stub.TerminalMenu = _StubTerminalMenu  # type: ignore[attr-defined]
        sys.modules["simple_term_menu"] = _stm_stub


# ---------------------------------------------------------------------------
# 1. The local server receives the callback (kept for Meta Ads)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_oauth_callback_server() -> None:
    """The local HTTP server receives the OAuth callback."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0)  # auto-select a free port
    actual_port = server.server.server_address[1]

    # Start the server in the background.
    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    # Send the callback request.
    time.sleep(0.1)  # wait for the server to start
    conn = http.client.HTTPConnection("localhost", actual_port)
    conn.request("GET", "/callback?code=test-auth-code-123")
    response = conn.getresponse()
    conn.close()

    assert response.status == 200
    assert server.authorization_code == "test-auth-code-123"


@pytest.mark.unit
def test_oauth_callback_server_error() -> None:
    """When the OAuth callback returns an error parameter."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0)
    actual_port = server.server.server_address[1]

    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    time.sleep(0.1)
    conn = http.client.HTTPConnection("localhost", actual_port)
    conn.request("GET", "/callback?error=access_denied")
    response = conn.getresponse()
    conn.close()

    assert response.status == 200
    assert server.authorization_code is None
    assert server.error == "access_denied"


# ---------------------------------------------------------------------------
# 4. credentials.json — new save
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_credentials_new(tmp_path: Path) -> None:
    """A new credentials.json is saved correctly."""
    from mureo.auth_setup import save_credentials

    cred_path = tmp_path / "credentials.json"

    google_creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
        login_customer_id="1234567890",
    )

    save_credentials(
        path=cred_path,
        google=google_creds,
        customer_id="1234567890",
    )

    assert cred_path.exists()
    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["developer_token"] == "dev-tok"
    assert data["google_ads"]["client_id"] == "cid"
    assert data["google_ads"]["client_secret"] == "csec"
    assert data["google_ads"]["refresh_token"] == "rtok"
    assert data["google_ads"]["login_customer_id"] == "1234567890"


# ---------------------------------------------------------------------------
# 5. credentials.json — merge save with existing data
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_credentials_merge(tmp_path: Path) -> None:
    """Existing credentials.json is merged and saved."""
    from mureo.auth_setup import save_credentials

    cred_path = tmp_path / "credentials.json"

    # Pre-save existing Meta Ads credentials.
    existing = {
        "meta_ads": {
            "access_token": "existing-meta-token",
            "app_id": "existing-app-id",
        }
    }
    cred_path.write_text(json.dumps(existing), encoding="utf-8")

    # Add Google Ads credentials.
    google_creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    save_credentials(path=cred_path, google=google_creds)

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    # Google Ads is added.
    assert data["google_ads"]["developer_token"] == "dev-tok"
    # Meta Ads is preserved.
    assert data["meta_ads"]["access_token"] == "existing-meta-token"


# ---------------------------------------------------------------------------
# 6. Create the directory if it does not exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_credentials_creates_directory(tmp_path: Path) -> None:
    """The ~/.mureo/ directory is auto-created when it does not exist."""
    from mureo.auth_setup import save_credentials

    nested_path = tmp_path / "nonexistent" / "dir" / "credentials.json"

    google_creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    save_credentials(path=nested_path, google=google_creds)

    assert nested_path.exists()
    data = json.loads(nested_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["developer_token"] == "dev-tok"


# ---------------------------------------------------------------------------
# 7. List accounts (API mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_accessible_accounts() -> None:
    """Can list accessible accounts via the Google Ads API."""
    from mureo.auth_setup import list_accessible_accounts

    creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    # Mock direct calls into the Google Ads SDK.
    mock_ga_client = MagicMock()

    # CustomerService (used for listing accounts).
    mock_customer_service = MagicMock()
    mock_response = MagicMock()
    mock_response.resource_names = [
        "customers/1234567890",
        "customers/9876543210",
    ]
    mock_customer_service.list_accessible_customers.return_value = mock_response

    # GoogleAdsService (used for fetching account names).
    # Both are non-manager accounts.
    mock_ga_service = MagicMock()
    mock_row_1 = MagicMock()
    mock_row_1.customer.descriptive_name = "テストアカウント1"
    mock_row_1.customer.manager = False
    mock_row_2 = MagicMock()
    mock_row_2.customer.descriptive_name = "テストアカウント2"
    mock_row_2.customer.manager = False
    mock_ga_service.search.side_effect = [[mock_row_1], [mock_row_2]]

    def _get_service(name: str) -> MagicMock:
        if name == "CustomerService":
            return mock_customer_service
        return mock_ga_service

    mock_ga_client.get_service.side_effect = _get_service

    with patch(
        "google.ads.googleads.client.GoogleAdsClient", return_value=mock_ga_client
    ):
        accounts = await list_accessible_accounts(creds)

    assert len(accounts) == 2
    assert accounts[0]["id"] == "1234567890"
    assert accounts[0]["name"] == "テストアカウント1"
    assert accounts[0]["is_manager"] is False
    assert accounts[0]["parent_id"] is None
    assert accounts[1]["id"] == "9876543210"
    assert accounts[1]["name"] == "テストアカウント2"
    assert accounts[1]["is_manager"] is False
    assert accounts[1]["parent_id"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_accessible_accounts_traverses_mcc_children() -> None:
    """Can also enumerate child accounts under an MCC."""
    from mureo.auth_setup import list_accessible_accounts

    creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    mock_ga_client = MagicMock()

    # listAccessibleCustomers returns only the MCC.
    mock_customer_service = MagicMock()
    mock_response = MagicMock()
    mock_response.resource_names = ["customers/1111111111"]
    mock_customer_service.list_accessible_customers.return_value = mock_response

    # 1st search: MCC info.
    mcc_row = MagicMock()
    mcc_row.customer.descriptive_name = "親MCC"
    mcc_row.customer.manager = True

    # 2nd search: the two child accounts under the MCC.
    child_row_1 = MagicMock()
    child_row_1.customer_client.id = 2222222222
    child_row_1.customer_client.descriptive_name = "子アカウントA"
    child_row_1.customer_client.manager = False
    child_row_2 = MagicMock()
    child_row_2.customer_client.id = 3333333333
    child_row_2.customer_client.descriptive_name = "子アカウントB"
    child_row_2.customer_client.manager = False

    mock_ga_service = MagicMock()
    mock_ga_service.search.side_effect = [
        [mcc_row],
        [child_row_1, child_row_2],
    ]

    def _get_service(name: str) -> MagicMock:
        if name == "CustomerService":
            return mock_customer_service
        return mock_ga_service

    mock_ga_client.get_service.side_effect = _get_service

    with patch(
        "google.ads.googleads.client.GoogleAdsClient", return_value=mock_ga_client
    ):
        accounts = await list_accessible_accounts(creds)

    assert len(accounts) == 3
    # Parent MCC
    assert accounts[0]["id"] == "1111111111"
    assert accounts[0]["name"] == "親MCC"
    assert accounts[0]["is_manager"] is True
    assert accounts[0]["parent_id"] is None
    # Child account A (parent_id = MCC).
    assert accounts[1]["id"] == "2222222222"
    assert accounts[1]["name"] == "子アカウントA"
    assert accounts[1]["is_manager"] is False
    assert accounts[1]["parent_id"] == "1111111111"
    # Child account B.
    assert accounts[2]["id"] == "3333333333"
    assert accounts[2]["name"] == "子アカウントB"
    assert accounts[2]["is_manager"] is False
    assert accounts[2]["parent_id"] == "1111111111"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_accessible_accounts_empty() -> None:
    """Returns an empty list when no accounts are accessible."""
    from mureo.auth_setup import list_accessible_accounts

    creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    mock_ga_client = MagicMock()
    mock_customer_service = MagicMock()
    mock_response = MagicMock()
    mock_response.resource_names = []
    mock_customer_service.list_accessible_customers.return_value = mock_response
    mock_ga_client.get_service.return_value = mock_customer_service

    with patch(
        "google.ads.googleads.client.GoogleAdsClient", return_value=mock_ga_client
    ):
        accounts = await list_accessible_accounts(creds)

    assert accounts == []


# ---------------------------------------------------------------------------
# 8. Full setup flow (input / OAuth / API all mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_google_ads_flow(tmp_path: Path) -> None:
    """The complete Google Ads setup flow works correctly."""
    from mureo.auth_setup import OAuthResult, setup_google_ads

    cred_path = tmp_path / "credentials.json"

    # Mock user input.
    user_inputs = iter(
        [
            "test-developer-token",  # Developer Token
            "test-client-id.apps.googleusercontent.com",  # Client ID
            "test-client-secret",  # Client Secret
        ]
    )

    mock_accounts = [
        {
            "id": "1234567890",
            "name": "Account 1234567890",
            "is_manager": False,
            "parent_id": None,
        },
        {
            "id": "9876543210",
            "name": "Account 9876543210",
            "is_manager": False,
            "parent_id": None,
        },
    ]

    mock_oauth_result = OAuthResult(
        refresh_token="1//test-refresh-token",
        access_token="ya29.test-access-token",
    )

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        patch("mureo.auth_setup._select_account", return_value="1234567890"),
        patch(
            "mureo.auth_setup.run_google_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_accessible_accounts",
            new_callable=AsyncMock,
            return_value=mock_accounts,
        ),
    ):
        result = await setup_google_ads(credentials_path=cred_path)

    assert result.developer_token == "test-developer-token"
    assert result.client_id == "test-client-id.apps.googleusercontent.com"
    assert result.client_secret == "test-client-secret"
    assert result.refresh_token == "1//test-refresh-token"
    assert result.login_customer_id == "1234567890"

    # The result should be saved into credentials.json.
    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["developer_token"] == "test-developer-token"
    assert data["google_ads"]["login_customer_id"] == "1234567890"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_google_ads_flow_no_accounts(tmp_path: Path) -> None:
    """credentials.json is still saved when no account is found."""
    from mureo.auth_setup import OAuthResult, setup_google_ads

    cred_path = tmp_path / "credentials.json"

    user_inputs = iter(
        [
            "test-developer-token",
            "test-client-id",
            "test-client-secret",
        ]
    )

    mock_oauth_result = OAuthResult(
        refresh_token="1//test-refresh-token",
        access_token="ya29.test-access-token",
    )

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        patch(
            "mureo.auth_setup.run_google_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_accessible_accounts",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await setup_google_ads(credentials_path=cred_path)

    assert result.developer_token == "test-developer-token"
    assert result.refresh_token == "1//test-refresh-token"
    assert result.login_customer_id is None

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["developer_token"] == "test-developer-token"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_google_ads_flow_selects_mcc_child(tmp_path: Path) -> None:
    """When a child account under an MCC is selected, login_customer_id is the parent MCC."""
    from mureo.auth_setup import OAuthResult, setup_google_ads

    cred_path = tmp_path / "credentials.json"

    user_inputs = iter(
        [
            "test-developer-token",
            "test-client-id",
            "test-client-secret",
        ]
    )

    # MCC + 2 child accounts (children carry parent_id).
    mock_accounts = [
        {
            "id": "1111111111",
            "name": "親MCC",
            "is_manager": True,
            "parent_id": None,
        },
        {
            "id": "2222222222",
            "name": "子アカウントA",
            "is_manager": False,
            "parent_id": "1111111111",
        },
    ]

    mock_oauth_result = OAuthResult(
        refresh_token="1//test-refresh-token",
        access_token="ya29.test-access-token",
    )

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        # Select child account A.
        patch("mureo.auth_setup._select_account", return_value="2222222222"),
        patch(
            "mureo.auth_setup.run_google_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_accessible_accounts",
            new_callable=AsyncMock,
            return_value=mock_accounts,
        ),
    ):
        result = await setup_google_ads(credentials_path=cred_path)

    # login_customer_id should be set to the parent MCC.
    assert result.login_customer_id == "1111111111"
    # customer_id should be set to the selected child account.
    assert result.customer_id == "2222222222"

    # Both should also be saved into credentials.json.
    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["login_customer_id"] == "1111111111"
    assert data["google_ads"]["customer_id"] == "2222222222"


# ---------------------------------------------------------------------------
# 9. Full OAuth flow (InstalledAppFlow)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_google_oauth() -> None:
    """run_google_oauth runs OAuth via InstalledAppFlow."""
    from mureo.auth_setup import OAuthResult, run_google_oauth

    mock_credentials = MagicMock()
    mock_credentials.refresh_token = "1//mock-refresh"
    mock_credentials.token = "ya29.mock-access"

    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = mock_credentials

    with patch(
        "mureo.auth_setup.InstalledAppFlow.from_client_config",
        return_value=mock_flow,
    ) as mock_from_config:
        result = await run_google_oauth(
            client_id="test-cid",
            client_secret="test-csec",
        )

    assert isinstance(result, OAuthResult)
    assert result.refresh_token == "1//mock-refresh"
    assert result.access_token == "ya29.mock-access"

    # InstalledAppFlow should be initialised with the correct client_config.
    mock_from_config.assert_called_once()
    call_args = mock_from_config.call_args
    client_config = call_args[0][0]
    assert client_config["installed"]["client_id"] == "test-cid"
    assert client_config["installed"]["client_secret"] == "test-csec"
    assert call_args[1]["scopes"] == [
        "https://www.googleapis.com/auth/adwords",
        "https://www.googleapis.com/auth/webmasters",
    ]

    # run_local_server should be called with port=0 (auto-select) and prompt="consent".
    mock_flow.run_local_server.assert_called_once_with(port=0, prompt="consent")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_google_oauth_no_refresh_token() -> None:
    """Raises an error when refresh_token cannot be obtained."""
    from mureo.auth_setup import run_google_oauth

    mock_credentials = MagicMock()
    mock_credentials.refresh_token = None
    mock_credentials.token = "ya29.mock-access"

    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = mock_credentials

    with patch(
        "mureo.auth_setup.InstalledAppFlow.from_client_config",
        return_value=mock_flow,
    ):
        with pytest.raises(RuntimeError, match="Failed to obtain refresh_token"):
            await run_google_oauth(
                client_id="test-cid",
                client_secret="test-csec",
            )


# ---------------------------------------------------------------------------
# 10. save_credentials without login_customer_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_credentials_without_customer_id(tmp_path: Path) -> None:
    """credentials.json is saved correctly even without customer_id."""
    from mureo.auth_setup import save_credentials

    cred_path = tmp_path / "credentials.json"

    google_creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    save_credentials(path=cred_path, google=google_creds)

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["developer_token"] == "dev-tok"
    assert data["google_ads"].get("login_customer_id") is None


# ---------------------------------------------------------------------------
# 11. File permissions (credentials.json is 0600)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX 0o600; Windows perms are documented best-effort (NTFS ACL)",
)
def test_save_credentials_file_permissions(tmp_path: Path) -> None:
    """credentials.json is saved with 0600 permissions."""
    import stat

    from mureo.auth_setup import save_credentials

    cred_path = tmp_path / "credentials.json"

    google_creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    save_credentials(path=cred_path, google=google_creds)

    file_mode = cred_path.stat().st_mode
    # owner read/write only
    assert stat.S_IMODE(file_mode) == 0o600


# ---------------------------------------------------------------------------
# 12. OAuth state parameter (CSRF protection) — Meta Ads callback server
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_oauth_callback_server_validates_state() -> None:
    """The callback server validates the state parameter correctly."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0, expected_state="correct-state")
    actual_port = server.server.server_address[1]

    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    time.sleep(0.1)
    conn = http.client.HTTPConnection("localhost", actual_port)
    conn.request("GET", "/callback?code=test-code&state=correct-state")
    response = conn.getresponse()
    conn.close()

    assert response.status == 200
    assert server.authorization_code == "test-code"


@pytest.mark.unit
def test_oauth_state_mismatch() -> None:
    """An error is raised when the state parameter mismatches."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0, expected_state="correct-state")
    actual_port = server.server.server_address[1]

    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    time.sleep(0.1)
    conn = http.client.HTTPConnection("localhost", actual_port)
    conn.request("GET", "/callback?code=test-code&state=wrong-state")
    response = conn.getresponse()
    conn.close()

    assert response.status == 403
    assert server.authorization_code is None
    assert server.error is not None
    assert "state" in server.error.lower()


@pytest.mark.unit
def test_oauth_state_missing_in_callback() -> None:
    """An error is raised when the callback has no state parameter."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0, expected_state="expected-state")
    actual_port = server.server.server_address[1]

    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    time.sleep(0.1)
    conn = http.client.HTTPConnection("localhost", actual_port)
    conn.request("GET", "/callback?code=test-code")
    response = conn.getresponse()
    conn.close()

    assert response.status == 403
    assert server.authorization_code is None


# ---------------------------------------------------------------------------
# 13. XSS prevention (HTML escaping)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_xss_prevention() -> None:
    """The callback server's HTML output is properly escaped."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0)
    actual_port = server.server.server_address[1]

    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    time.sleep(0.1)
    conn = http.client.HTTPConnection("localhost", actual_port)
    # An error parameter simulating an XSS attack.
    conn.request(
        "GET",
        "/callback?error=%3Cscript%3Ealert(1)%3C/script%3E",
    )
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()

    # The <script> tag should be escaped.
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


# ---------------------------------------------------------------------------
# 14. InstalledAppFlow.run_local_server raises an exception
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_google_oauth_flow_exception() -> None:
    """When InstalledAppFlow.run_local_server() raises, the exception propagates."""
    from mureo.auth_setup import run_google_oauth

    mock_flow = MagicMock()
    mock_flow.run_local_server.side_effect = Exception("Cannot open browser")

    with patch(
        "mureo.auth_setup.InstalledAppFlow.from_client_config",
        return_value=mock_flow,
    ):
        with pytest.raises(Exception, match="Cannot open browser"):
            await run_google_oauth(
                client_id="test-cid",
                client_secret="test-csec",
            )


# ---------------------------------------------------------------------------
# Tests for MCP-config placement
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_install_mcp_config_global_via_claude_cli(tmp_path: Path) -> None:
    """Global scope delegates to ``claude mcp add-json --scope user``.

    Claude Code reads user-scope MCP servers from ``~/.claude.json``
    (managed by the ``claude`` CLI), NOT from ``~/.claude/settings.json``
    — so the installer must shell out to the CLI, not edit settings.json.
    """
    from types import SimpleNamespace

    from mureo.auth_setup import install_mcp_config

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with (
        patch("mureo.auth_setup.shutil.which", return_value="/usr/bin/claude"),
        patch("mureo.auth_setup.subprocess.run", side_effect=fake_run),
        patch("mureo.auth_setup.Path.home", return_value=tmp_path),
    ):
        result = install_mcp_config(scope="global")

    assert result == tmp_path / ".claude.json"
    # Self-heal: a stale/wrong entry is removed before re-adding.
    assert calls[0][1:3] == ["mcp", "remove"]
    add = calls[1]
    assert add[1:4] == ["mcp", "add-json", "mureo"]
    assert add[add.index("--scope") + 1] == "user"
    payload = json.loads(add[4])
    assert payload["type"] == "stdio"
    # Absolute interpreter (sys.executable), not bare "python" — Claude
    # Code spawns MCP servers with a minimal PATH that lacks pyenv/venv
    # shims, so bare "python" would not have mureo installed.
    assert payload["command"] == sys.executable
    assert payload["args"] == ["-m", "mureo.mcp"]


@pytest.mark.unit
def test_install_mcp_config_global_cli_failure_raises(tmp_path: Path) -> None:
    """A present-but-failing ``claude`` CLI surfaces loudly (no silent
    misconfiguration)."""
    from types import SimpleNamespace

    from mureo.auth_setup import install_mcp_config

    def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
        rc = 0 if "remove" in argv else 2
        return SimpleNamespace(returncode=rc, stdout="", stderr="boom")

    with (
        patch("mureo.auth_setup.shutil.which", return_value="/usr/bin/claude"),
        patch("mureo.auth_setup.subprocess.run", side_effect=fake_run),
        patch("mureo.auth_setup.Path.home", return_value=tmp_path),
        pytest.raises(RuntimeError, match="add-json failed"),
    ):
        install_mcp_config(scope="global")


@pytest.mark.unit
def test_install_mcp_config_global_fallback_no_cli(tmp_path: Path) -> None:
    """No ``claude`` binary → atomic merge into ``~/.claude.json`` root
    ``mcpServers``, preserving unrelated keys."""
    from mureo.auth_setup import install_mcp_config

    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {"numStartups": 3, "mcpServers": {"figma": {"type": "http"}}}
        ),
        encoding="utf-8",
    )

    with (
        patch("mureo.auth_setup.shutil.which", return_value=None),
        patch("mureo.auth_setup.Path.home", return_value=tmp_path),
    ):
        result = install_mcp_config(scope="global")

    assert result == claude_json
    payload = json.loads(claude_json.read_text(encoding="utf-8"))
    assert payload["numStartups"] == 3  # unrelated key preserved
    assert "figma" in payload["mcpServers"]  # other server preserved
    assert payload["mcpServers"]["mureo"]["type"] == "stdio"
    assert payload["mcpServers"]["mureo"]["command"] == sys.executable
    assert payload["mcpServers"]["mureo"]["args"] == ["-m", "mureo.mcp"]


@pytest.mark.unit
def test_install_mcp_config_project(tmp_path: Path) -> None:
    """Project-level MCP config is created correctly."""
    from mureo.auth_setup import install_mcp_config

    with patch("mureo.auth_setup.Path.cwd", return_value=tmp_path):
        result = install_mcp_config(scope="project")

    assert result is not None
    assert result.name == ".mcp.json"
    settings = json.loads(result.read_text(encoding="utf-8"))
    assert "mureo" in settings["mcpServers"]


@pytest.mark.unit
def test_install_mcp_config_project_already_exists(tmp_path: Path) -> None:
    """Project scope skips when mureo is already in ``.mcp.json``."""
    from mureo.auth_setup import install_mcp_config

    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text(
        json.dumps(
            {"mcpServers": {"mureo": {"command": "python", "args": ["-m"]}}}
        ),
        encoding="utf-8",
    )

    with patch("mureo.auth_setup.Path.cwd", return_value=tmp_path):
        result = install_mcp_config(scope="project")

    assert result is None  # skip


@pytest.mark.unit
def test_install_mcp_config_project_merges_existing(tmp_path: Path) -> None:
    """Project scope merges into an existing ``.mcp.json``."""
    from mureo.auth_setup import install_mcp_config

    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text(
        json.dumps(
            {"mcpServers": {"other-tool": {"command": "node", "args": ["s.js"]}}}
        ),
        encoding="utf-8",
    )

    with patch("mureo.auth_setup.Path.cwd", return_value=tmp_path):
        result = install_mcp_config(scope="project")

    assert result is not None
    settings = json.loads(result.read_text(encoding="utf-8"))
    assert "other-tool" in settings["mcpServers"]  # preserved
    assert "mureo" in settings["mcpServers"]  # added
    assert settings["mcpServers"]["mureo"]["type"] == "stdio"


# ---------------------------------------------------------------------------
# install_credential_guard tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_install_credential_guard_new(tmp_path: Path) -> None:
    """Credential guard hooks are added to empty settings."""
    from mureo.auth_setup import install_credential_guard

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"
    settings_path.write_text("{}")

    with patch("mureo.auth_setup.Path.home", return_value=tmp_path):
        result = install_credential_guard()

    assert result is not None
    settings = json.loads(result.read_text(encoding="utf-8"))
    pre_tool_use = settings["hooks"]["PreToolUse"]
    assert len(pre_tool_use) == 2
    assert pre_tool_use[0]["matcher"] == "Read"
    assert pre_tool_use[1]["matcher"] == "Bash"
    assert "[mureo-credential-guard]" in pre_tool_use[0]["hooks"][0]["command"]


@pytest.mark.unit
def test_install_credential_guard_preserves_existing_hooks(tmp_path: Path) -> None:
    """Existing hooks are preserved when adding credential guard."""
    from mureo.auth_setup import install_credential_guard

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"
    existing = {
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo done"}]}
            ],
            "PreToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [{"type": "command", "command": "echo check"}],
                }
            ],
        },
        "someOtherSetting": True,
    }
    settings_path.write_text(json.dumps(existing))

    with patch("mureo.auth_setup.Path.home", return_value=tmp_path):
        result = install_credential_guard()

    assert result is not None
    settings = json.loads(result.read_text(encoding="utf-8"))
    # Existing hooks preserved
    assert "Stop" in settings["hooks"]
    assert settings["someOtherSetting"] is True
    # Existing PreToolUse hook preserved + 2 mureo hooks appended
    pre_tool_use = settings["hooks"]["PreToolUse"]
    assert len(pre_tool_use) == 3
    assert pre_tool_use[0]["matcher"] == "Write"  # original
    assert pre_tool_use[1]["matcher"] == "Read"  # mureo
    assert pre_tool_use[2]["matcher"] == "Bash"  # mureo


@pytest.mark.unit
def test_install_credential_guard_skip_if_already_installed(tmp_path: Path) -> None:
    """Skip if mureo credential guard is already installed."""
    from mureo.auth_setup import install_credential_guard

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"

    # Install once
    settings_path.write_text("{}")
    with patch("mureo.auth_setup.Path.home", return_value=tmp_path):
        install_credential_guard()

    # Install again — should skip
    with patch("mureo.auth_setup.Path.home", return_value=tmp_path):
        result = install_credential_guard()

    assert result is None
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    # Still only 2 mureo hooks (no duplicates)
    assert len(settings["hooks"]["PreToolUse"]) == 2


@pytest.mark.unit
def test_install_credential_guard_skip_on_corrupt_json(tmp_path: Path) -> None:
    """Skip gracefully if settings.json is corrupt."""
    from mureo.auth_setup import install_credential_guard

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.json"
    settings_path.write_text("{invalid json")

    with patch("mureo.auth_setup.Path.home", return_value=tmp_path):
        result = install_credential_guard()

    assert result is None  # skipped, not crashed
    # File is untouched
    assert settings_path.read_text() == "{invalid json"


# ---------------------------------------------------------------------------
# _select_account tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_select_account_fallback_valid_choice() -> None:
    """Selection by number input without simple-term-menu (lines 62-76)."""
    from mureo.auth_setup import _select_account

    accounts = [
        {"id": "111", "name": "Account A"},
        {"id": "222", "name": "Account B"},
    ]

    with patch("simple_term_menu.TerminalMenu", side_effect=ImportError):
        with patch("builtins.input", return_value="2"):
            result = _select_account(accounts)

    assert result == "222"


@pytest.mark.unit
def test_select_account_fallback_invalid_choice() -> None:
    """Invalid number input without simple-term-menu (lines 75-76)."""
    from mureo.auth_setup import _select_account

    accounts = [
        {"id": "111", "name": "Account A"},
    ]

    with patch("simple_term_menu.TerminalMenu", side_effect=ImportError):
        with patch("builtins.input", return_value="999"):
            result = _select_account(accounts)

    assert result is None


@pytest.mark.unit
def test_select_account_fallback_non_numeric() -> None:
    """Non-numeric input without simple-term-menu (line 73)."""
    from mureo.auth_setup import _select_account

    accounts = [
        {"id": "111", "name": "Account A"},
    ]

    with patch("simple_term_menu.TerminalMenu", side_effect=ImportError):
        with patch("builtins.input", return_value="abc"):
            result = _select_account(accounts)

    assert result is None


@pytest.mark.unit
def test_select_account_terminal_menu_cancel() -> None:
    """Cancel from TerminalMenu (returns None) (lines 56-58)."""
    from mureo.auth_setup import _select_account

    accounts = [
        {"id": "111", "name": "Account A"},
    ]

    mock_menu = MagicMock()
    mock_menu.show.return_value = None  # cancel

    with patch("simple_term_menu.TerminalMenu", return_value=mock_menu):
        result = _select_account(accounts)

    assert result is None


@pytest.mark.unit
def test_select_account_with_custom_label_fn() -> None:
    """A custom label is used when label_fn is provided (lines 46-47)."""
    from mureo.auth_setup import _select_account

    accounts = [
        {"id": "111", "name": "Account A"},
    ]

    mock_menu = MagicMock()
    mock_menu.show.return_value = 0

    with patch("simple_term_menu.TerminalMenu", return_value=mock_menu) as MockTM:
        result = _select_account(accounts, label_fn=lambda a: f"Custom: {a['name']}")

    assert result == "111"
    # Verify the labels passed to TerminalMenu.
    call_args = MockTM.call_args
    assert call_args[0][0] == ["Custom: Account A"]


# ---------------------------------------------------------------------------
# setup_mcp_config tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_setup_mcp_config_fallback_global() -> None:
    """Choose Global via number input without simple-term-menu (lines 388-398)."""
    from mureo.auth_setup import setup_mcp_config

    with (
        patch("simple_term_menu.TerminalMenu", side_effect=ImportError),
        patch("mureo.auth_setup.input_func", return_value="1"),
        patch(
            "mureo.auth_setup.install_mcp_config", return_value=Path("/tmp/test")
        ) as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_called_once_with(scope="global")


@pytest.mark.unit
def test_setup_mcp_config_fallback_project() -> None:
    """Choose Project via number input without simple-term-menu."""
    from mureo.auth_setup import setup_mcp_config

    with (
        patch("simple_term_menu.TerminalMenu", side_effect=ImportError),
        patch("mureo.auth_setup.input_func", return_value="2"),
        patch(
            "mureo.auth_setup.install_mcp_config", return_value=Path("/tmp/test")
        ) as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_called_once_with(scope="project")


@pytest.mark.unit
def test_setup_mcp_config_fallback_skip() -> None:
    """Skip via number input without simple-term-menu (lines 395-396)."""
    from mureo.auth_setup import setup_mcp_config

    with (
        patch("simple_term_menu.TerminalMenu", side_effect=ImportError),
        patch("mureo.auth_setup.input_func", return_value="3"),
        patch("mureo.auth_setup.install_mcp_config") as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_not_called()


@pytest.mark.unit
def test_setup_mcp_config_fallback_default() -> None:
    """Empty input defaults to Global without simple-term-menu (line 394)."""
    from mureo.auth_setup import setup_mcp_config

    with (
        patch("simple_term_menu.TerminalMenu", side_effect=ImportError),
        patch("mureo.auth_setup.input_func", return_value=""),
        patch(
            "mureo.auth_setup.install_mcp_config", return_value=Path("/tmp/test")
        ) as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_called_once_with(scope="global")


@pytest.mark.unit
def test_setup_mcp_config_terminal_menu_skip() -> None:
    """Choose Skip from TerminalMenu (index=2) (line 383)."""
    from mureo.auth_setup import setup_mcp_config

    mock_menu = MagicMock()
    mock_menu.show.return_value = 2  # skip

    with (
        patch("simple_term_menu.TerminalMenu", return_value=mock_menu),
        patch("mureo.auth_setup.install_mcp_config") as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_not_called()


@pytest.mark.unit
def test_setup_mcp_config_terminal_menu_cancel() -> None:
    """Cancel from TerminalMenu (None)."""
    from mureo.auth_setup import setup_mcp_config

    mock_menu = MagicMock()
    mock_menu.show.return_value = None

    with (
        patch("simple_term_menu.TerminalMenu", return_value=mock_menu),
        patch("mureo.auth_setup.install_mcp_config") as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_not_called()


@pytest.mark.unit
def test_setup_mcp_config_already_exists() -> None:
    """When MCP config already exists (lines 403-404)."""
    from mureo.auth_setup import setup_mcp_config

    mock_menu = MagicMock()
    mock_menu.show.return_value = 0  # global

    with (
        patch("simple_term_menu.TerminalMenu", return_value=mock_menu),
        patch("mureo.auth_setup.install_mcp_config", return_value=None) as mock_install,
    ):
        setup_mcp_config()

    mock_install.assert_called_once()


# ---------------------------------------------------------------------------
# Additional OAuthCallbackServer tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_oauth_callback_server_invalid_request() -> None:
    """A malformed request (no code, no error)."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0)
    actual_port = server.server.server_address[1]

    server_thread = threading.Thread(target=server.wait_for_callback, daemon=True)
    server_thread.start()

    time.sleep(0.1)
    conn = http.client.HTTPConnection("localhost", actual_port)
    conn.request("GET", "/callback?unexpected=value")
    response = conn.getresponse()
    conn.close()

    assert response.status == 400
    assert server.authorization_code is None
    assert server.error is None


@pytest.mark.unit
def test_oauth_callback_server_shutdown() -> None:
    """The shutdown method works correctly."""
    from mureo.auth_setup import OAuthCallbackServer

    server = OAuthCallbackServer(port=0)
    server.shutdown()  # should complete without raising


# ---------------------------------------------------------------------------
# save_credentials Meta Ads tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_credentials_meta_ads(tmp_path: Path) -> None:
    """Meta Ads credentials are saved correctly."""
    from mureo.auth import MetaAdsCredentials
    from mureo.auth_setup import save_credentials

    cred_path = tmp_path / "credentials.json"

    meta_creds = MetaAdsCredentials(
        access_token="meta-access-tok",
        app_id="app-123",
        app_secret="app-secret-456",
    )

    save_credentials(
        path=cred_path,
        meta=meta_creds,
        account_id="act_789",
    )

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["meta_ads"]["access_token"] == "meta-access-tok"
    assert data["meta_ads"]["app_id"] == "app-123"
    assert data["meta_ads"]["app_secret"] == "app-secret-456"
    assert data["meta_ads"]["account_id"] == "act_789"


@pytest.mark.unit
def test_save_credentials_corrupted_existing(tmp_path: Path) -> None:
    """A new file is created even when the existing credentials.json is corrupt."""
    from mureo.auth_setup import save_credentials

    cred_path = tmp_path / "credentials.json"
    cred_path.write_text("not valid json", encoding="utf-8")

    google_creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    save_credentials(path=cred_path, google=google_creds)

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["google_ads"]["developer_token"] == "dev-tok"


# ---------------------------------------------------------------------------
# Meta Ads OAuth tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generate_meta_auth_url() -> None:
    """The Meta OAuth authorization URL is generated correctly."""
    from mureo.auth_setup import _generate_meta_auth_url

    url = _generate_meta_auth_url(app_id="test-app-id", port=8888, state="abc123")

    assert "test-app-id" in url
    assert "localhost%3A8888" in url or "localhost:8888" in url
    assert "state=abc123" in url
    assert "ads_management" in url


@pytest.mark.unit
def test_generate_meta_auth_url_no_state() -> None:
    """When state=None, the state parameter is omitted."""
    from mureo.auth_setup import _generate_meta_auth_url

    url = _generate_meta_auth_url(app_id="test-app-id", port=8888, state=None)

    assert "state=" not in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exchange_code_for_short_token() -> None:
    """Fetching a short-lived token."""
    from mureo.auth_setup import _exchange_code_for_short_token

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "short-lived-tok"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await _exchange_code_for_short_token(
            code="test-code",
            app_id="test-app",
            app_secret="test-secret",
            redirect_uri="http://localhost:8888/callback",
        )

    assert result == "short-lived-tok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exchange_code_for_short_token_error() -> None:
    """RuntimeError when short-lived token fetch fails."""
    from mureo.auth_setup import _exchange_code_for_short_token

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(side_effect=RuntimeError("connection error"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        with pytest.raises(RuntimeError, match="Short-Lived Token"):
            await _exchange_code_for_short_token(
                code="test-code",
                app_id="test-app",
                app_secret="test-secret",
                redirect_uri="http://localhost:8888/callback",
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exchange_short_for_long_token() -> None:
    """Converting to a long-lived token."""
    from mureo.auth_setup import MetaOAuthResult, _exchange_short_for_long_token

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "long-lived-tok",
        "expires_in": 5184000,
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await _exchange_short_for_long_token(
            short_token="short-tok",
            app_id="test-app",
            app_secret="test-secret",
        )

    assert isinstance(result, MetaOAuthResult)
    assert result.access_token == "long-lived-tok"
    assert result.expires_in == 5184000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exchange_short_for_long_token_error() -> None:
    """RuntimeError when long-lived token conversion fails."""
    from mureo.auth_setup import _exchange_short_for_long_token

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(side_effect=RuntimeError("api error"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        with pytest.raises(RuntimeError, match="Long-Lived Token"):
            await _exchange_short_for_long_token(
                short_token="short-tok",
                app_id="test-app",
                app_secret="test-secret",
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_meta_ad_accounts() -> None:
    """Fetching the Meta ad-account list."""
    from mureo.auth_setup import list_meta_ad_accounts

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "act_111", "name": "Test Account", "account_status": 1},
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        accounts = await list_meta_ad_accounts("test-token")

    assert len(accounts) == 1
    assert accounts[0]["id"] == "act_111"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_meta_ad_accounts_error() -> None:
    """RuntimeError when fetching the Meta ad-account list fails."""
    from mureo.auth_setup import list_meta_ad_accounts

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get = AsyncMock(side_effect=RuntimeError("api error"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        with pytest.raises(RuntimeError, match="Failed to retrieve ad account list"):
            await list_meta_ad_accounts("test-token")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth() -> None:
    """Full Meta OAuth flow."""
    from mureo.auth_setup import MetaOAuthResult, run_meta_oauth

    with (
        patch("mureo.auth_setup.OAuthCallbackServer") as MockServer,
        patch("mureo.auth_setup.webbrowser.open"),
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-token",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=MetaOAuthResult(
                access_token="long-lived-tok", expires_in=5184000
            ),
        ),
    ):
        server_instance = MockServer.return_value
        server_instance.server.server_address = ("localhost", 9999)
        server_instance.error = None
        server_instance.authorization_code = "test-auth-code"
        # wait_for_callback returns immediately.
        server_instance.wait_for_callback = MagicMock()

        result = await run_meta_oauth(
            app_id="test-app-id",
            app_secret="test-app-secret",
        )

    assert isinstance(result, MetaOAuthResult)
    assert result.access_token == "long-lived-tok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth_error() -> None:
    """When the Meta OAuth flow returns an error."""
    from mureo.auth_setup import run_meta_oauth

    with (
        patch("mureo.auth_setup.OAuthCallbackServer") as MockServer,
        patch("mureo.auth_setup.webbrowser.open"),
    ):
        server_instance = MockServer.return_value
        server_instance.server.server_address = ("localhost", 9999)
        server_instance.error = "access_denied"
        server_instance.authorization_code = None
        server_instance.wait_for_callback = MagicMock()

        with pytest.raises(RuntimeError, match="access_denied"):
            await run_meta_oauth(
                app_id="test-app-id",
                app_secret="test-app-secret",
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth_timeout() -> None:
    """When the Meta OAuth flow times out."""
    from mureo.auth_setup import run_meta_oauth

    with (
        patch("mureo.auth_setup.OAuthCallbackServer") as MockServer,
        patch("mureo.auth_setup.webbrowser.open"),
    ):
        server_instance = MockServer.return_value
        server_instance.server.server_address = ("localhost", 9999)
        server_instance.error = None
        server_instance.authorization_code = None  # timeout
        server_instance.wait_for_callback = MagicMock()

        with pytest.raises(RuntimeError, match="Authentication timed out"):
            await run_meta_oauth(
                app_id="test-app-id",
                app_secret="test-app-secret",
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_flow(tmp_path: Path) -> None:
    """The complete Meta Ads setup flow."""
    from mureo.auth_setup import MetaOAuthResult, setup_meta_ads

    cred_path = tmp_path / "credentials.json"

    user_inputs = iter(["test-app-id", "test-app-secret"])

    mock_oauth_result = MetaOAuthResult(
        access_token="long-lived-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Account 1", "account_status": 1},
        {"id": "act_222", "name": "Account 2", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        patch(
            "mureo.auth_setup.run_meta_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_meta_ad_accounts",
            new_callable=AsyncMock,
            return_value=mock_accounts,
        ),
        patch("mureo.auth_setup._select_account", return_value="act_222"),
    ):
        result = await setup_meta_ads(credentials_path=cred_path)

    assert result.access_token == "long-lived-token"
    assert result.app_id == "test-app-id"

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["meta_ads"]["access_token"] == "long-lived-token"
    assert data["meta_ads"]["account_id"] == "act_222"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_single_account(tmp_path: Path) -> None:
    """A single account is auto-selected."""
    from mureo.auth_setup import MetaOAuthResult, setup_meta_ads

    cred_path = tmp_path / "credentials.json"

    user_inputs = iter(["test-app-id", "test-app-secret"])

    mock_oauth_result = MetaOAuthResult(
        access_token="long-lived-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Single Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        patch(
            "mureo.auth_setup.run_meta_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_meta_ad_accounts",
            new_callable=AsyncMock,
            return_value=mock_accounts,
        ),
    ):
        result = await setup_meta_ads(credentials_path=cred_path)

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    assert data["meta_ads"]["account_id"] == "act_111"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_no_accounts(tmp_path: Path) -> None:
    """RuntimeError when no accounts are found."""
    from mureo.auth_setup import MetaOAuthResult, setup_meta_ads

    cred_path = tmp_path / "credentials.json"

    user_inputs = iter(["test-app-id", "test-app-secret"])

    mock_oauth_result = MetaOAuthResult(
        access_token="long-lived-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        patch(
            "mureo.auth_setup.run_meta_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_meta_ad_accounts",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        with pytest.raises(RuntimeError, match="No ad accounts found"):
            await setup_meta_ads(credentials_path=cred_path)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_cancel_selection(tmp_path: Path) -> None:
    """When account selection is cancelled, the default account is used."""
    from mureo.auth_setup import MetaOAuthResult, setup_meta_ads

    cred_path = tmp_path / "credentials.json"

    user_inputs = iter(["test-app-id", "test-app-secret"])

    mock_oauth_result = MetaOAuthResult(
        access_token="long-lived-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Account 1", "account_status": 1},
        {"id": "act_222", "name": "Account 2", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=user_inputs),
        patch(
            "mureo.auth_setup.run_meta_oauth",
            new_callable=AsyncMock,
            return_value=mock_oauth_result,
        ),
        patch(
            "mureo.auth_setup.list_meta_ad_accounts",
            new_callable=AsyncMock,
            return_value=mock_accounts,
        ),
        patch("mureo.auth_setup._select_account", return_value=None),
    ):
        result = await setup_meta_ads(credentials_path=cred_path)

    data = json.loads(cred_path.read_text(encoding="utf-8"))
    # On cancel, the first account is the default.
    assert data["meta_ads"]["account_id"] == "act_111"


@pytest.mark.unit
def test_resolve_default_path() -> None:
    """Resolve the default path."""
    from mureo.auth_setup import _resolve_default_path

    path = _resolve_default_path()
    assert path.name == "credentials.json"
    assert ".mureo" in str(path)
