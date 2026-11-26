"""Routing between a built-in platform's tools and a plugin serving it.

A plugin provider that declares ``serves_platform`` re-publishes a built-in
platform's tool surface under its own prefix (``meta_ads_acme_campaigns_list``
next to ``meta_ads_campaigns_list``). When a workspace's account is configured
only under that provider, the agent needs to know which family reaches it, and
the built-in tools must not proceed on another account. These tests cover the
static table built at server load, the configured check and the always-on
notice; the refusals and pointers are in ``test_serving_providers_dispatch.py``.
"""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mureo.core.providers import (
    SERVED_PLATFORMS,
    required_fields_stored,
)
from mureo.core.runtime_context import (
    DEFAULT_WORKSPACE_ID,
    RuntimeContextFactoryError,
    default_runtime_context,
    reset_runtime_context,
)
from mureo.mcp import _plugin_tables
from mureo.mcp import server as mcp_server
from mureo.mcp import serving_providers as sp
from mureo.policy.platform_model import reset_platform_models
from tests._runtime_context_fakes import install_runtime_factory
from tests._server_reload import reloaded_server
from tests._serving_providers_support import (
    ACME,
    ALL_CONFIGURED,
    CONFIGURED,
    GATES,
    GOOGLE_ACME,
    HEADING,
    LINE_BOTH,
    LINE_NONE,
    LINE_UNKNOWN,
    PROVIDER,
    SC_ACME,
    SECRET,
    AcmeProvider,
    Store,
    discover_for,
    install_backend,
    owned,
    plugin_class,
    scoped_backend,
    serve,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_LOGGER = "mureo.mcp.serving_providers"


@pytest.fixture
def no_platform_models() -> Iterator[None]:
    # The bundled ChatGPT Ads provider registers a delivery model at server
    # load; cleared so the server's instructions hold only what is asserted.
    reset_platform_models()
    yield
    reset_platform_models()


# ---------------------------------------------------------------------------
# 1. Default install
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("no_platform_models")
def test_default_install_is_unchanged_and_reads_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    monkeypatch.setattr(
        "mureo.core.runtime_context.get_runtime_context",
        lambda: SimpleNamespace(workspace_id=DEFAULT_WORKSPACE_ID, secret_store=store),
    )
    assert _plugin_tables._SERVING_PROVIDERS == {}
    assert mcp_server._server_instructions() is None
    assert sp.served_platforms_instructions() == ""
    assert sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads") is None
    assert sp.served_pointer("meta_ads") == ""
    store.load.assert_not_called()


def test_allow_list_table_covers_every_servable_platform() -> None:
    assert frozenset(sp._ALLOW_LISTS) == SERVED_PLATFORMS


# ---------------------------------------------------------------------------
# 2. Prefix derivation
# ---------------------------------------------------------------------------


def _builtins(*platforms: str) -> dict[str, frozenset[str]]:
    """The built-in tool names the server serves for ``platforms``."""
    view = mcp_server._tool_families_view()
    return {family: names for names, family in view if family in platforms}


def test_prefix_is_derived_from_a_partial_operation_set() -> None:
    owners, dispatch = owned(
        AcmeProvider(), "meta_ads_acme_campaigns_list", "meta_ads_acme_campaigns_get"
    )
    table = sp.serving_providers(owners, dispatch, _builtins("meta_ads"))
    assert table == {"meta_ads": (ACME,)}


def test_tools_that_mirror_no_builtin_do_not_disturb_the_prefix() -> None:
    owners, dispatch = owned(
        AcmeProvider(), "meta_ads_acme_campaigns_list", "acme_status_report"
    )
    table = sp.serving_providers(owners, dispatch, _builtins("meta_ads"))
    assert table == {"meta_ads": (ACME,)}


@pytest.mark.parametrize(
    "names",
    [
        ("meta_ads_acme_campaigns_list", "meta_ads_other_campaigns_get"),
        ("meta_ads_ac\nme_campaigns_list",),
        ("meta_ads_" + "a" * 130 + "_campaigns_list",),
    ],
    ids=["two-prefixes", "line-break", "too-long"],
)
def test_no_single_renderable_prefix_yields_no_entry_and_a_warning(
    names: tuple[str, ...], caplog: pytest.LogCaptureFixture
) -> None:
    owners, dispatch = owned(AcmeProvider(), *names)
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert sp.serving_providers(owners, dispatch, _builtins("meta_ads")) == {}
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_no_tool_mirroring_a_builtin_is_logged_at_debug_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owners, dispatch = owned(
        AcmeProvider(), "acme_status_report", "google_ads_acme_campaigns_list"
    )
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert sp.serving_providers(owners, dispatch, _builtins("meta_ads")) == {}
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_a_prefix_a_builtin_name_starts_with_is_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # meta_ads_ads_* would also match the built-in meta_ads_ads_list.
    owners, dispatch = owned(AcmeProvider(), "meta_ads_ads_campaigns_list")
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert sp.serving_providers(owners, dispatch, _builtins("meta_ads")) == {}
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "meta_ads_ads_" in caplog.text


class _BuiltinNamedProvider(AcmeProvider):
    name = "meta_ads"
    _mureo_provider_name = "meta_ads"


def test_a_provider_named_like_a_builtin_section_is_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owners, dispatch = owned(_BuiltinNamedProvider(), "meta_ads_acme_campaigns_list")
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert sp.serving_providers(owners, dispatch, _builtins("meta_ads")) == {}
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_a_suffix_with_an_underscore_is_one_prefix() -> None:
    owners, dispatch = owned(
        AcmeProvider(),
        "meta_ads_acme_corp_campaigns_list",
        "meta_ads_acme_corp_campaigns_get",
    )
    table = sp.serving_providers(owners, dispatch, _builtins("meta_ads"))
    assert table == {
        "meta_ads": (
            sp.ServingProvider(PROVIDER, "meta_ads_acme_corp_", ACME.required_keys),
        )
    }


# ---------------------------------------------------------------------------
# 3. Malformed declarations, gated-off families
# ---------------------------------------------------------------------------


class _MalformedProvider(AcmeProvider):
    serves_platform = "tiktok_ads"


class _BadFieldsProvider(AcmeProvider):
    account_credential_fields = ["not", "a", "tuple"]  # type: ignore[assignment]


@pytest.mark.parametrize("provider_class", [_MalformedProvider, _BadFieldsProvider])
def test_malformed_declaration_drops_the_provider_with_a_warning(
    provider_class: type, caplog: pytest.LogCaptureFixture
) -> None:
    owners, dispatch = owned(provider_class(), "meta_ads_acme_campaigns_list")
    with caplog.at_level(logging.WARNING, logger="mureo.mcp.serving_providers"):
        table = sp.serving_providers(owners, dispatch, _builtins("meta_ads"))
    assert table == {}
    assert any("plugin declaration rejected" in r.getMessage() for r in caplog.records)


def test_family_not_served_this_run_gets_no_entry() -> None:
    owners, dispatch = owned(AcmeProvider(), "meta_ads_acme_campaigns_list")
    assert sp.serving_providers(owners, dispatch, _builtins("google_ads")) == {}


def test_server_load_fills_the_table_for_a_serving_plugin() -> None:
    with reloaded_server(discover_for(plugin_class("meta_ads")), env=GATES):
        assert _plugin_tables._SERVING_PROVIDERS == {"meta_ads": (ACME,)}
    assert _plugin_tables._SERVING_PROVIDERS == {}


def test_server_load_skips_a_family_switched_off() -> None:
    env = {**GATES, "MUREO_DISABLE_META_ADS": "1"}
    with reloaded_server(discover_for(plugin_class("meta_ads")), env=env):
        assert _plugin_tables._SERVING_PROVIDERS == {}


def test_server_still_builds_with_a_malformed_declaration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        caplog.at_level(logging.WARNING, logger="mureo.mcp.serving_providers"),
        reloaded_server(
            discover_for(plugin_class("tiktok_ads")), env=GATES
        ) as server_mod,
    ):
        assert _plugin_tables._SERVING_PROVIDERS == {}
        assert server_mod._create_server() is not None
    assert any("plugin declaration rejected" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. Configured: required fields, secrecy, a failing store
# ---------------------------------------------------------------------------


def test_one_required_field_missing_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_backend(monkeypatch, Store({PROVIDER: {"access_token": SECRET}}))
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.configured_serving_providers("meta_ads") == ()
    assert sp.served_platforms_instructions() == ""


def test_all_required_fields_stored_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_backend(monkeypatch, Store({PROVIDER: CONFIGURED}))
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.configured_serving_providers("meta_ads") == (ACME,)


def test_secret_values_reach_neither_the_notice_nor_the_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    with caplog.at_level(logging.DEBUG):
        notice = sp.served_platforms_instructions()
        refusal = sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads")
    assert notice
    assert refusal is not None
    assert SECRET not in notice
    assert SECRET not in refusal[0].text
    assert SECRET not in caplog.text


def test_a_store_that_raises_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = Store()
    store.load = MagicMock(side_effect=OSError(f"cannot read {SECRET}"))  # type: ignore[method-assign]
    install_backend(monkeypatch, store)
    serve(monkeypatch, "meta_ads", ACME)
    with caplog.at_level(logging.WARNING, logger="mureo.mcp.serving_providers"):
        assert sp.configured_serving_providers("meta_ads") == ()
    assert PROVIDER in caplog.text
    assert "OSError" in caplog.text
    assert SECRET not in caplog.text


# ---------------------------------------------------------------------------
# 5. A broken runtime-context factory
# ---------------------------------------------------------------------------


def test_factory_error_omits_the_notice_and_the_server_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RuntimeContextFactoryError("two factories registered")

    monkeypatch.setattr("mureo.core.runtime_context.get_runtime_context", _boom)
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.configured_serving_providers("meta_ads") == ()
    assert sp.served_platforms_instructions() == ""
    assert sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads") is None
    assert mcp_server._create_server() is not None


# ---------------------------------------------------------------------------
# 6. The notice lines, the cap and the order
# ---------------------------------------------------------------------------


def test_none_line_when_the_builtin_allow_list_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.served_platforms_instructions() == f"{HEADING}\n{LINE_NONE}"


def test_both_line_when_the_builtin_allow_list_has_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped_backend(monkeypatch, {"meta_account_ids": frozenset({"act_111"})})
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.served_platforms_instructions() == f"{HEADING}\n{LINE_BOTH}"


def test_unknown_line_when_the_workspace_is_not_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_backend(monkeypatch, Store({PROVIDER: CONFIGURED}))
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.served_platforms_instructions() == f"{HEADING}\n{LINE_UNKNOWN}"


def test_several_families_are_joined_and_platforms_are_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beta = sp.ServingProvider("meta_ads_beta", "meta_ads_beta_", ("token",))
    sections = {**ALL_CONFIGURED, "meta_ads_beta": {"token": "x"}}
    install_backend(monkeypatch, Store(sections, multi_account=True))
    serve(monkeypatch, "search_console", SC_ACME)
    serve(monkeypatch, "meta_ads", ACME, beta)
    serve(monkeypatch, "google_ads", GOOGLE_ACME)
    lines = sp.served_platforms_instructions().split("\n")
    assert lines[0] == HEADING
    assert [line.split(":")[0] for line in lines[1:]] == [
        "- Google Ads",
        "- Meta Ads",
        "- Search Console",
    ]
    assert lines[2].startswith(
        "- Meta Ads: use the meta_ads_acme_* or meta_ads_beta_* tools. "
    )


def test_block_is_capped_with_an_omission_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sections: dict[str, dict[str, Any]] = {}
    for platform in sorted(SERVED_PLATFORMS):
        rows = []
        for index in range(2):
            name = f"{platform}_{chr(97 + index) * 110}"
            rows.append(sp.ServingProvider(name, f"{name}_", ("token",)))
            sections[name] = {"token": "x"}
        serve(monkeypatch, platform, *rows)
    install_backend(monkeypatch, Store(sections, multi_account=True))
    block = sp.served_platforms_instructions()
    assert len(block) <= sp.MAX_TOTAL_CHARS
    assert block.startswith(HEADING)
    assert block.endswith(
        "NOTE: this list is INCOMPLETE — 1 further platform line(s) did not fit "
        "in this block's length budget."
    )
    assert "- Google Ads: " in block


class _RaisingAllowListStore(Store):
    """A store whose Meta allow-list property fails when read."""

    @property
    def meta_account_ids(self) -> frozenset[str]:
        raise RuntimeError(f"allow-list backend down {SECRET}")


def test_a_line_that_raises_is_omitted_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _RaisingAllowListStore(ALL_CONFIGURED, multi_account=True)
    install_backend(monkeypatch, store)
    serve(monkeypatch, "meta_ads", ACME)
    serve(monkeypatch, "google_ads", GOOGLE_ACME)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        block = sp.served_platforms_instructions()
    assert block.split("\n")[1].startswith("- Google Ads: ")
    assert "Meta Ads" not in block
    assert "meta_ads" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "backend down" not in caplog.text
    with pytest.raises(RuntimeError):
        sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads")


@pytest.mark.usefixtures("no_platform_models")
def test_notice_sits_between_workspace_and_platform_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(ALL_CONFIGURED, multi_account=True)
    ctx = dataclasses.replace(
        default_runtime_context(), secret_store=store, workspace_id="client:acme"
    )
    install_runtime_factory(monkeypatch, lambda: ctx)
    reset_runtime_context()
    serve(monkeypatch, "meta_ads", ACME)
    text = mcp_server._server_instructions()
    assert text is not None
    sections = text.split("\n\n")
    assert "client:acme" in sections[0]
    assert sections[1] == f"{HEADING}\n{LINE_NONE}"


# ---------------------------------------------------------------------------
# 7. One configured rule
# ---------------------------------------------------------------------------


def test_no_fields_is_not_configured() -> None:
    assert required_fields_stored(()) is False


def test_no_required_field_is_not_configured() -> None:
    assert required_fields_stored(((False, True), (False, False))) is False


def test_one_required_field_missing_is_not_stored() -> None:
    assert required_fields_stored(((True, True), (True, False))) is False


def test_every_required_field_stored_is_configured() -> None:
    assert required_fields_stored(((True, True), (True, True), (False, False)))
