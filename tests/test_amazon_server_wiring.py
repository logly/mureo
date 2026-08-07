"""Amazon bridge ↔ server #114 safety-layer wiring (TDD, #113 task #25).

The internal Amazon bridge must ride the SAME collect/dispatch path as
entry-point plugins: tools exposed, audited, throttled, and mutating
calls promoted to STATE.json action_log — with NO change to dispatch.
Manifest absent ⇒ no Amazon tools (regression-safe).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

_MANIFEST = {
    "generated_at": "2026-05-18T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [
        {
            "name": "account_management-query_advertiser_account",
            "description": "List advertiser accounts.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "campaign_management-create_campaign",
            "description": "Create an SP campaign.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ],
}


class _FakeSession:
    async def initialize(self) -> None: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        from mcp.types import TextContent

        return type(
            "R", (), {"content": [TextContent(type="text", text=f"ok:{name}")]}
        )()


def _fake_connect(url, headers):
    class _CM:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *e):
            return False

    return _CM()


def _no_thirdparty(**_kw):
    return ()


def _reload_server(
    monkeypatch,
    tmp_path: Path,
    *,
    with_manifest: bool,
    manifest: dict[str, Any] | None = None,
    connect=_fake_connect,
):
    from mureo.amazon_ads import bridge as bmod
    from mureo.auth import AmazonAdsCredentials
    from mureo.mcp import plugin_audit

    mp = tmp_path / "amazon_tools.json"
    if with_manifest:
        mp.write_text(json.dumps(manifest or _MANIFEST))
    monkeypatch.setattr(
        "mureo.core.providers.registry.discover_providers", _no_thirdparty
    )
    monkeypatch.setattr(bmod, "manifest_path", lambda: mp)
    monkeypatch.setattr(
        bmod,
        "load_amazon_ads_credentials",
        lambda *a, **k: AmazonAdsCredentials(
            client_id="cid", access_token="Atza|SECRET"
        ),
    )
    monkeypatch.setattr(bmod, "_default_connect", connect)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    from mureo.mcp import server as mod

    return importlib.reload(mod)


def _seed_state(d: Path) -> None:
    from mureo.context.models import StateDocument
    from mureo.context.state import write_state_file

    write_state_file(d / "STATE.json", StateDocument())


@pytest.mark.unit
class TestAmazonServerWiring:
    def test_amazon_tools_collected_and_dispatched_to_bridge(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.amazon_ads.bridge import AmazonAdsBridge

        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            assert "campaign_management-create_campaign" in mod._PLUGIN_NAMES
            assert "account_management-query_advertiser_account" in mod._PLUGIN_NAMES
            disp = mod._PLUGIN_DISPATCH["campaign_management-create_campaign"]
            assert isinstance(disp, AmazonAdsBridge)
        finally:
            importlib.reload(mod)

    async def test_mutating_amazon_call_audited_and_promoted(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            out = await mod.handle_call_tool(
                "campaign_management-create_campaign", {"name": "X"}
            )
            assert out  # forwarded content returned
            audit = [
                json.loads(x)
                for x in (tmp_path / "audit.jsonl").read_text().splitlines()
            ]
            assert audit and audit[-1]["source"] == "mureo-amazon-ads-bridge"
            doc = read_state_file(tmp_path / "STATE.json")
            assert len(doc.action_log) == 1
            e = doc.action_log[0]
            assert e.action == "campaign_management-create_campaign"
            # #537: distribution AND provider. The bridge ships one platform,
            # but the key shape does not depend on that — see
            # ``mureo.core.platform_keys``.
            assert e.platform == "plugin:mureo-amazon-ads-bridge:amazon_ads"
            assert e.observation_due is not None  # Phase 4 window
        finally:
            importlib.reload(mod)

    async def test_readonly_amazon_call_not_promoted(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            await mod.handle_call_tool(
                "account_management-query_advertiser_account", {}
            )
            doc = read_state_file(tmp_path / "STATE.json")
            assert doc.action_log == ()  # read-only ⇒ jsonl audit only
            assert (tmp_path / "audit.jsonl").exists()
        finally:
            importlib.reload(mod)

    def test_no_manifest_means_no_amazon_tools_regression_safe(
        self, monkeypatch, tmp_path
    ) -> None:
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=False)
        try:
            amazon = [
                n
                for n in mod._PLUGIN_NAMES
                if "campaign_management" in n or "account_management" in n
            ]
            assert amazon == []
        finally:
            importlib.reload(mod)


_REVERSIBLE_MANIFEST = {
    "generated_at": "2026-05-18T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [
        {
            "name": "campaign_management-update_campaign_state",
            "description": "Update campaign state.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ],
}

_AMAZON_ERROR_JSON = (
    '{"code":"FIELD_VALUE_IS_INVALID","message":"Multi marketplace query '
    'requests only support query by primary resource id"}'
)
_AMAZON_VALIDATION_TEXT = (
    "Validation failed: provided input does not match tool input schema. "
    "Validation errors: [/body: required property 'adProductFilter' not found]"
)
_AMAZON_SUCCESS_JSON = '{"campaigns":[{"campaignId":"C1","state":"ENABLED"}]}'
#: Mutation acks. No mutation success shape is live-verified anywhere in this
#: repo, so a write may answer with nothing but scalars. None of these carries
#: ``isError``, so none of them may EVER be read as a failure — doing so would
#: drop the ``action_log`` entry for a change that really happened.
_AMAZON_ACKS = (
    '{"code":"CREATED","message":"Campaign 123 created successfully"}',
    '{"code":"ACCEPTED","message":"request accepted"}',
    '{"code":"UPDATED","message":"campaign updated"}',
    '{"code":"DELETED","message":"campaign deleted"}',
    '{"code":"ENABLED","message":"campaign enabled"}',
    '{"code":"IN_PROGRESS","message":"update in progress"}',
    '{"code": 200, "message": "Campaign updated successfully"}',
    '{"code":"SUCCESS","message":"OK","campaignId":"C1"}',
)


def _connect_returning(text: str, *, is_error: bool = False):
    """Connect factory: every tool answers ``text`` with ``isError``.

    ``isError`` is the field the real ``CallToolResult`` carries and is the
    bridge's sole structural failure signal (live-verified 2026-08-05).
    """

    class _Sess:
        async def initialize(self) -> None: ...

        async def call_tool(self, name: str, arguments: dict[str, Any]):
            from mcp.types import TextContent

            return type(
                "R",
                (),
                {
                    "content": [TextContent(type="text", text=text)],
                    "isError": is_error,
                },
            )()

    class _CM:
        async def __aenter__(self):
            return _Sess()

        async def __aexit__(self, *e):
            return False

    return lambda url, headers: _CM()


@pytest.mark.unit
class TestBridgedFailureIsNotRecordedAsAMutation:
    """#528 — a platform-side failure must not land in ``action_log``.

    Amazon returns its failures as ordinary successful content, so the whole
    chain has to be checked, not just the detector: promotion is skipped, the
    jsonl audit still records the attempt exactly as it does today, no
    reversal is attached, and the (normalised) response still reaches the
    agent.
    """

    def _audit(self, tmp_path: Path) -> list[dict[str, Any]]:
        return [
            json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()
        ]

    async def _dispatch(
        self, monkeypatch, tmp_path, tool, text, *, manifest=None, is_error=False
    ):
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        mod = _reload_server(
            monkeypatch,
            tmp_path,
            with_manifest=True,
            manifest=manifest,
            connect=_connect_returning(text, is_error=is_error),
        )
        try:
            return await mod.handle_call_tool(tool, {"campaignId": "C1"})
        finally:
            importlib.reload(mod)

    async def test_json_error_envelope_skips_the_action_log(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            _AMAZON_ERROR_JSON,
            is_error=True,
        )

        doc = read_state_file(tmp_path / "STATE.json")
        assert doc.action_log == ()  # the mutation never happened
        # ...but the response still reaches the agent, normalised. The message
        # survives; the quoted code value is masked by the shared redactor.
        assert out and out[0].text.startswith("API error:")
        assert "Multi marketplace query requests" in out[0].text
        # ...and the attempt is still audited — as a PLATFORM failure. ``ok``
        # keeps its meaning ("the call did not raise"), so the operator-facing
        # trail carries the outcome separately instead of reading as success.
        audit = self._audit(tmp_path)
        assert audit[-1]["tool"] == "campaign_management-create_campaign"
        assert audit[-1]["ok"] is True
        assert audit[-1]["platform_ok"] is False
        assert "Multi marketplace query requests" in audit[-1]["error"]

    async def test_a_token_shaped_code_reaches_neither_agent_nor_audit(
        self, monkeypatch, tmp_path
    ) -> None:
        """The operator-facing trail must never carry a credential in clear.

        ``plugin_audit.jsonl`` is written to disk and kept; a leak there
        outlives the session. The scrub has to happen before the failure text
        is reshaped for display, or the redactor's ``"code":`` anchor is gone
        by the time it runs.
        """
        secret = "AQABAAgAAAAmoFfGtYxfTKd1RVy5Z1oL8vXeqR7uKQzTOKENVALUE1234"
        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            f'{{"code": "{secret}", "message": "authorization code rejected"}}',
            is_error=True,
        )

        assert secret not in out[0].text
        assert secret not in (tmp_path / "audit.jsonl").read_text()
        assert "authorization code rejected" in self._audit(tmp_path)[-1]["error"]

    async def test_a_code_suffixed_key_reaches_neither_agent_nor_audit(
        self, monkeypatch, tmp_path
    ) -> None:
        """Same guarantee for a key the redactor's ``code`` rule used to miss."""
        secret = "AQABAAABBBCCCDDDauthcode123456"
        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            f'{{"code":"BAD","message":"rejected","authorizationCode":"{secret}"}}',
            is_error=True,
        )

        assert secret not in out[0].text
        assert secret not in (tmp_path / "audit.jsonl").read_text()

    @pytest.mark.parametrize(
        "key",
        ["clientSecret", "refreshToken", "accessToken", "apiKey", "client-secret"],
    )
    @pytest.mark.parametrize("with_message", [True, False], ids=["message", "none"])
    async def test_a_camel_case_credential_key_reaches_nothing(
        self, monkeypatch, tmp_path, key, with_message
    ) -> None:
        """Every credential family, in the spelling Amazon's surface uses.

        Both paths this change added put a raw body in front of the agent and
        into ``plugin_audit.jsonl``: the extras append (message present) and
        the no-message fallback (message absent). A snake_case-only redactor
        leaks through both.
        """
        secret = "amzn1.oa2-cs.v1.SUPERSECRETVALUE"
        message = '"message":"rejected",' if with_message else ""
        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            f'{{"code":"BAD",{message}"{key}":"{secret}"}}',
            is_error=True,
        )

        assert secret not in out[0].text
        assert secret not in (tmp_path / "audit.jsonl").read_text()

    async def test_validation_failure_text_skips_the_action_log(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            _AMAZON_VALIDATION_TEXT,
            is_error=True,
        )

        assert read_state_file(tmp_path / "STATE.json").action_log == ()
        assert out[0].text.startswith("API error:")
        assert "adProductFilter" in out[0].text
        assert self._audit(tmp_path)[-1]["platform_ok"] is False

    async def test_failed_reversible_mutation_attaches_no_reversal(
        self, monkeypatch, tmp_path
    ) -> None:
        """A reversal for a change that never happened is a phantom rollback."""
        from mureo.context.state import read_state_file

        await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-update_campaign_state",
            _AMAZON_ERROR_JSON,
            manifest=_REVERSIBLE_MANIFEST,
            is_error=True,
        )

        doc = read_state_file(tmp_path / "STATE.json")
        assert doc.action_log == ()  # no entry ⇒ no reversible_params either

    async def test_successful_envelope_is_unchanged_and_still_promoted(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            _AMAZON_SUCCESS_JSON,
        )

        assert out[0].text == _AMAZON_SUCCESS_JSON  # forwarded verbatim
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        assert doc.action_log[0].action == "campaign_management-create_campaign"
        assert "platform_ok" not in self._audit(tmp_path)[-1]  # plain success

    @pytest.mark.parametrize("ack", _AMAZON_ACKS)
    async def test_a_scalar_mutation_ack_is_still_promoted(
        self, monkeypatch, tmp_path, ack
    ) -> None:
        """The inverse failure mode: a real change must NOT be lost.

        Every one of these acks was misclassified as a failure by an earlier
        payload heuristic. None carries ``isError``, so each must reach
        ``action_log`` — misreading one would drop the audit entry, the
        observation window and the rollback candidate for a change that
        actually happened.
        """
        from mureo.context.state import read_state_file

        out = await self._dispatch(
            monkeypatch, tmp_path, "campaign_management-create_campaign", ack
        )

        assert out[0].text == ack  # untouched
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        assert doc.action_log[0].action == "campaign_management-create_campaign"

    async def test_readonly_tool_error_keeps_its_existing_behaviour(
        self, monkeypatch, tmp_path
    ) -> None:
        """Read-only tools were never promoted; normalising changes nothing."""
        from mureo.context.state import read_state_file

        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "account_management-query_advertiser_account",
            _AMAZON_ERROR_JSON,
            is_error=True,
        )

        assert read_state_file(tmp_path / "STATE.json").action_log == ()
        assert out[0].text.startswith("API error:")
        # A read-only tool is audit-only either way, but the trail must still
        # say the platform refused the call.
        assert self._audit(tmp_path)[-1]["platform_ok"] is False

    async def test_is_error_on_a_success_looking_body_skips_promotion(
        self, monkeypatch, tmp_path
    ) -> None:
        """Only ``isError`` can catch this — the body reads as a success."""
        from mureo.context.state import read_state_file

        out = await self._dispatch(
            monkeypatch,
            tmp_path,
            "campaign_management-create_campaign",
            _AMAZON_SUCCESS_JSON,
            is_error=True,
        )

        assert read_state_file(tmp_path / "STATE.json").action_log == ()
        assert out[0].text.startswith("API error:")
        assert self._audit(tmp_path)[-1]["platform_ok"] is False


@pytest.mark.unit
class TestAmazonRegistryRegistration:
    """#121 — the bridge is registered ONCE, and only once.

    The synthetic ``ProviderEntry`` is now single-sourced in
    ``mureo.amazon_ads.provider`` and registered into
    ``default_registry`` (so the configure UI can see it) *and* fed to
    ``collect_plugin_tools`` (so the MCP server exposes its tools).
    Both paths must not double-count.
    """

    def test_startup_registers_amazon_in_the_default_registry(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.amazon_ads.bridge import AmazonAdsBridge
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            assert "amazon_ads" in default_registry
            assert default_registry.get("amazon_ads").provider_class is AmazonAdsBridge
        finally:
            importlib.reload(mod)

    def test_discover_yields_the_amazon_entry_exactly_once(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            names = [e.name for e in mod._discover_with_amazon()]
            assert names.count("amazon_ads") == 1
            # Idempotent: calling again (as a re-discovery would) does not
            # duplicate the entry either.
            names = [e.name for e in mod._discover_with_amazon()]
            assert names.count("amazon_ads") == 1
        finally:
            importlib.reload(mod)

    def test_each_amazon_tool_is_collected_exactly_once(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            names = [t.name for t in mod._PLUGIN_TOOLS]
            assert names.count("campaign_management-create_campaign") == 1
            assert names.count("account_management-query_advertiser_account") == 1
            assert len(mod._ALL_TOOLS) == len({t.name for t in mod._ALL_TOOLS})
        finally:
            importlib.reload(mod)

    def test_registration_contributes_zero_tools_without_a_manifest(
        self, monkeypatch, tmp_path
    ) -> None:
        """Registry presence must not create tools out of thin air."""
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=False)
        try:
            assert "amazon_ads" in default_registry  # UI can still configure it
            assert mod._PLUGIN_TOOLS == []
        finally:
            importlib.reload(mod)


@pytest.mark.unit
class TestBuiltInShadowingPolicy:
    """#121 review follow-up — the built-in wins a name clash, everywhere.

    ``Registry`` is first-wins, so *when* the in-tree bridge registers
    decides whether a third-party distribution publishing a
    ``mureo.providers`` entry point named ``amazon_ads`` can take the
    slot. Both in-tree startup paths must therefore register the
    built-in BEFORE running entry-point discovery. These tests pin that
    property from the observable side (which entry comes back), not by
    asserting call order.
    """

    def _foreign_entry(self):
        from mureo.core.providers.registry import ProviderEntry

        class _Squatter:
            name = "amazon_ads"
            display_name = "Amazon Ads (third party)"
            capabilities = frozenset()

        return ProviderEntry(
            name="amazon_ads",
            display_name="Amazon Ads (third party)",
            capabilities=frozenset(),
            provider_class=_Squatter,
            source_distribution="squatter-plugin",
        )

    def _discover_publishing_foreign_amazon(self, foreign):
        """Fake entry-point discovery that ships an ``amazon_ads`` provider.

        Mirrors ``Registry._load_entry_point``: it attempts registration
        and returns ONLY the entries actually inserted, so an entry
        dropped by first-wins is absent from the result — exactly what
        the real discovery pass does.
        """
        import warnings

        from mureo.core.providers import default_registry
        from mureo.core.providers.registry import RegistryWarning

        def _discover(*_a, **_kw):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RegistryWarning)
                default_registry.register(foreign)
            stored = default_registry.get("amazon_ads")
            return (foreign,) if stored is foreign else ()

        return _discover

    def test_builtin_beats_a_same_named_entry_point_plugin(
        self, monkeypatch, tmp_path
    ) -> None:
        """Registering first means the entry-point squatter is dropped."""
        from mureo.amazon_ads.bridge import AmazonAdsBridge
        from mureo.amazon_ads.provider import AMAZON_SOURCE_DISTRIBUTION
        from mureo.core.providers import default_registry
        from mureo.mcp import server as mod

        monkeypatch.setattr(default_registry, "_entries", {})
        foreign = self._foreign_entry()
        monkeypatch.setattr(
            "mureo.core.providers.registry.discover_providers",
            self._discover_publishing_foreign_amazon(foreign),
        )

        entries = mod._discover_with_amazon()

        amazon = [e for e in entries if e.name == "amazon_ads"]
        assert len(amazon) == 1  # still exactly once
        assert amazon[0].source_distribution == AMAZON_SOURCE_DISTRIBUTION
        assert amazon[0].provider_class is AmazonAdsBridge
        # ...and the registry agrees, so the configure UI renders the
        # built-in's credential fields rather than the squatter's.
        assert default_registry.get("amazon_ads").provider_class is AmazonAdsBridge

    def test_a_genuinely_pre_registered_foreign_entry_still_wins(
        self, monkeypatch, tmp_path
    ) -> None:
        """First-wins is not overridden — it is only made deterministic.

        A foreign ``amazon_ads`` already in the registry BEFORE the
        startup path runs keeps the slot, matching the registry's
        documented shadowing contract.
        """
        from mureo.core.providers import default_registry
        from mureo.mcp import server as mod

        foreign = self._foreign_entry()
        monkeypatch.setattr(default_registry, "_entries", {"amazon_ads": foreign})
        monkeypatch.setattr(
            "mureo.core.providers.registry.discover_providers", _no_thirdparty
        )

        entries = mod._discover_with_amazon()

        amazon = [e for e in entries if e.name == "amazon_ads"]
        assert len(amazon) == 1
        assert amazon[0] is foreign
        assert default_registry.get("amazon_ads") is foreign

    def test_configure_path_also_registers_before_discovery(self, monkeypatch) -> None:
        """The configure process resolves the name identically (#121).

        Same scenario as the MCP test above, through
        ``ConfigureWizard._discover_providers_safely`` — the two
        processes must not disagree about who owns ``amazon_ads``.
        """
        from mureo.amazon_ads.bridge import AmazonAdsBridge
        from mureo.core.providers import default_registry
        from mureo.web.server import ConfigureWizard

        monkeypatch.setattr(default_registry, "_entries", {})
        foreign = self._foreign_entry()
        monkeypatch.setattr(
            "mureo.web.server.discover_providers",
            self._discover_publishing_foreign_amazon(foreign),
        )

        ConfigureWizard._discover_providers_safely()

        assert default_registry.get("amazon_ads").provider_class is AmazonAdsBridge


@pytest.mark.unit
class TestAmazonDisableEnvVar:
    """``MUREO_DISABLE_AMAZON_ADS=1`` steps the bridge aside (audit #53).

    Google / Meta / GA4 all have a ``MUREO_DISABLE_*`` coexistence control;
    Amazon had none, so an operator who wired Amazon's MCP up directly in
    their host had no way to stop mureo from ALSO exposing the same tools.
    The two processes that register the provider — the MCP server and the
    configure UI — must agree, or the dashboard would advertise a card for a
    bridge the server does not serve.
    """

    def test_mcp_discovery_omits_amazon_when_disabled(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.core.providers import default_registry
        from mureo.mcp import server as mod

        monkeypatch.setattr(default_registry, "_entries", {})
        monkeypatch.setattr(
            "mureo.core.providers.registry.discover_providers", _no_thirdparty
        )
        monkeypatch.setenv("MUREO_DISABLE_AMAZON_ADS", "1")

        entries = mod._discover_with_amazon()

        assert [e for e in entries if e.name == "amazon_ads"] == []
        # Not registered either: a disabled bridge must not linger in the
        # registry for the configure UI to render a card from.
        assert "amazon_ads" not in default_registry

    def test_mcp_server_exposes_no_amazon_tools_when_disabled(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        monkeypatch.setenv("MUREO_DISABLE_AMAZON_ADS", "1")
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            assert "campaign_management-create_campaign" not in mod._PLUGIN_NAMES
        finally:
            monkeypatch.delenv("MUREO_DISABLE_AMAZON_ADS", raising=False)
            importlib.reload(mod)

    def test_configure_process_omits_amazon_when_disabled(self, monkeypatch) -> None:
        from mureo.core.providers import default_registry
        from mureo.web.server import ConfigureWizard

        monkeypatch.setattr(default_registry, "_entries", {})
        monkeypatch.setattr("mureo.web.server.discover_providers", _no_thirdparty)
        monkeypatch.setenv("MUREO_DISABLE_AMAZON_ADS", "1")

        ConfigureWizard._discover_providers_safely()

        assert "amazon_ads" not in default_registry

    @pytest.mark.parametrize("value", ["0", "", "true", "  1  ", "yes"])
    def test_truthy_coercion_does_not_disable(self, monkeypatch, value) -> None:
        """Exact-string ``"1"``, matching every other MUREO_DISABLE_* gate."""
        from mureo.core.providers import default_registry
        from mureo.mcp import server as mod

        monkeypatch.setattr(default_registry, "_entries", {})
        monkeypatch.setattr(
            "mureo.core.providers.registry.discover_providers", _no_thirdparty
        )
        monkeypatch.setenv("MUREO_DISABLE_AMAZON_ADS", value)

        entries = mod._discover_with_amazon()

        assert [e.name for e in entries if e.name == "amazon_ads"] == ["amazon_ads"]
