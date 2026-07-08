"""Version/extension-package discovery for ``mureo.web.about``.

``collect_about_info`` resolves the installed mureo version plus every
installed mureo plugin, discovered along two axes (#365): the plugin
entry-point groups AND the ``mureo`` / ``mureo-*`` name prefix (the same
set the updater sees). These tests mock both surfaces entirely — the
machine running them may carry real mureo plugins (dev boxes do), so
nothing here depends on what is actually installed.
"""

from __future__ import annotations

import json
import re
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mureo.web.about import (
    ABOUT_ENTRY_POINT_GROUPS,
    UNKNOWN_VERSION,
    collect_about_info,
)

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


class _FakeDist:
    """Stand-in for ``importlib.metadata.Distribution`` (name + version)."""

    def __init__(self, name: Any, version: Any) -> None:
        self.name = name
        self.version = version


class _FakeEntryPoint:
    """Minimal ``EntryPoint`` stand-in.

    ``mureo.web.about`` reads ``dist`` / ``module`` via ``getattr``, so a
    plain object with the same attribute names is sufficient.
    ``dist_raises=True`` simulates a distribution whose metadata lookup
    blows up — the fault-isolation case.
    """

    def __init__(
        self,
        *,
        dist: _FakeDist | None = None,
        module: str = "",
        dist_raises: bool = False,
    ) -> None:
        self._dist = dist
        self.module = module
        self._dist_raises = dist_raises

    @property
    def dist(self) -> _FakeDist | None:
        if self._dist_raises:
            raise RuntimeError("broken plugin metadata")
        return self._dist


def _entry_points_for(
    by_group: dict[str, tuple[_FakeEntryPoint, ...]],
) -> Any:
    """Build an ``entry_points(group=...)`` replacement from a mapping."""

    def fake_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        return by_group.get(group, ())

    return fake_entry_points


def _version_for(versions: dict[str, str]) -> Any:
    """Build a ``version(name)`` replacement from a mapping."""

    def fake_version(name: str) -> str:
        if name in versions:
            return versions[name]
        raise PackageNotFoundError(name)

    return fake_version


@pytest.mark.unit
class TestCollectAboutInfo:
    @pytest.fixture(autouse=True)
    def _no_name_prefixed_dists(self) -> Any:
        """Neutralise the real name-prefix distribution walk (#365).

        ``collect_about_info`` now also lists every installed ``mureo`` /
        ``mureo-*`` distribution (the same set the updater discovers). That
        walk hits real installed metadata, so on a dev box carrying real
        ``mureo-*`` plugins it would break these hermetic entry-point cases.
        Default it to "no name-prefixed dists"; the cases that exercise the
        name-prefix axis re-patch it inside their own ``with`` block.
        """
        with patch("mureo.web.about._discover_all_mureo_packages", return_value=[]):
            yield

    def test_groups_constant_covers_all_mureo_plugin_surfaces(self) -> None:
        assert ABOUT_ENTRY_POINT_GROUPS == (
            "mureo.providers",
            "mureo.skills",
            "mureo.runtime_context_factory",
            "mureo.web_extensions",
            "mureo.policy_gates",
            "mureo.analytics",
        )

    def test_mureo_always_present_with_no_entry_points(self) -> None:
        with (
            patch("mureo.web.about.entry_points", _entry_points_for({})),
            patch("mureo.web.about.version", _version_for({"mureo": "9.9.9"})),
        ):
            info = collect_about_info()
        assert info["mureo"] == {"name": "mureo", "version": "9.9.9"}
        assert info["packages"] == [{"name": "mureo", "version": "9.9.9"}]

    def test_mureo_version_falls_back_when_package_not_found(self) -> None:
        """A dev tree without an installed dist must not 500 — placeholder."""
        with (
            patch("mureo.web.about.entry_points", _entry_points_for({})),
            patch("mureo.web.about.version", _version_for({})),
        ):
            info = collect_about_info()
        assert info["mureo"]["version"] == UNKNOWN_VERSION

    def test_deduplicates_distributions_across_groups(self) -> None:
        """One distribution contributing to several groups appears once."""
        dist = _FakeDist("mureo-agency", "0.1.12")
        by_group = {
            "mureo.providers": (_FakeEntryPoint(dist=dist),),
            "mureo.runtime_context_factory": (_FakeEntryPoint(dist=dist),),
            "mureo.web_extensions": (_FakeEntryPoint(dist=dist),),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["mureo", "mureo-agency"]

    def test_packages_sorted_by_distribution_name(self) -> None:
        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist=_FakeDist("zeta-plugin", "2.0.0")),
                _FakeEntryPoint(dist=_FakeDist("alpha-plugin", "0.3.0")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["alpha-plugin", "mureo", "zeta-plugin"]

    def test_mureo_seed_wins_over_entry_point_contribution(self) -> None:
        """mureo's own entry points never override the seeded version."""
        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist=_FakeDist("mureo", "0.0.0-stale")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "9.9.9"})),
        ):
            info = collect_about_info()
        assert info["packages"] == [{"name": "mureo", "version": "9.9.9"}]

    def test_broken_entry_point_is_skipped(self) -> None:
        """Per-entry-point fault isolation — one broken plugin never
        breaks the endpoint (mirrors ``mureo.web.extensions``)."""
        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist_raises=True),
                _FakeEntryPoint(dist=_FakeDist("good-plugin", "1.2.3")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["good-plugin", "mureo"]

    def test_group_listing_failure_is_isolated(self) -> None:
        """A whole group blowing up must not take down the others."""

        def exploding_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
            if group == "mureo.providers":
                raise RuntimeError("metadata index corrupted")
            return (_FakeEntryPoint(dist=_FakeDist("web-plugin", "3.0.0")),)

        with (
            patch("mureo.web.about.entry_points", exploding_entry_points),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["mureo", "web-plugin"]

    def test_dist_none_falls_back_to_packages_distributions(self) -> None:
        """Python 3.10 may give ``EntryPoint.dist is None`` — the owning
        distribution is then resolved via ``packages_distributions()``."""
        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist=None, module="acme_plugin.providers"),
            ),
        }
        versions = {"mureo": "1.0.0", "acme-plugin": "2.0.0"}
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for(versions)),
            patch(
                "mureo.web.about.packages_distributions",
                return_value={"acme_plugin": ["acme-plugin"]},
            ),
        ):
            info = collect_about_info()
        assert {"name": "acme-plugin", "version": "2.0.0"} in info["packages"]

    def test_dist_none_fallback_version_none_uses_placeholder(self) -> None:
        """The ``dist is None`` fallback path also normalizes a ``None``
        version (malformed dist-info) to the placeholder — matching the
        dist-present branch and never emitting a non-string version."""

        def version_returns_none(name: str) -> str | None:
            return "1.0.0" if name == "mureo" else None

        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist=None, module="acme_plugin.providers"),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", version_returns_none),
            patch(
                "mureo.web.about.packages_distributions",
                return_value={"acme_plugin": ["acme-plugin"]},
            ),
        ):
            info = collect_about_info()
        assert {"name": "acme-plugin", "version": UNKNOWN_VERSION} in info["packages"]

    def test_dist_none_without_mapping_is_skipped(self) -> None:
        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist=None, module="orphan_plugin.providers"),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
            patch("mureo.web.about.packages_distributions", return_value={}),
        ):
            info = collect_about_info()
        assert info["packages"] == [{"name": "mureo", "version": "1.0.0"}]

    def test_missing_dist_version_uses_placeholder(self) -> None:
        by_group = {
            "mureo.providers": (
                _FakeEntryPoint(dist=_FakeDist("no-version-plugin", None)),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        assert {
            "name": "no-version-plugin",
            "version": UNKNOWN_VERSION,
        } in info["packages"]

    def test_payload_carries_only_names_and_versions(self) -> None:
        """No secrets, no file paths — each package row is name+version."""
        by_group = {
            "mureo.web_extensions": (
                _FakeEntryPoint(dist=_FakeDist("some-plugin", "1.0.0")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        assert set(info.keys()) == {"mureo", "packages"}
        assert set(info["mureo"].keys()) == {"name", "version"}
        for pkg in info["packages"]:
            assert set(pkg.keys()) == {"name", "version"}

    # -- #365: consistency with the update checker ------------------------
    #
    # The "Installed packages" list and the "Update available" banner must
    # agree on what counts as an installed mureo package. The updater keys
    # off the ``mureo`` / ``mureo-*`` name prefix; About must list that same
    # set so a package can never be flagged "update available" while absent
    # from "Installed packages".

    def test_name_prefixed_package_without_entry_points_is_listed(self) -> None:
        """A ``mureo-*`` plugin registering NONE of the scanned entry-point
        groups (e.g. ``mureo-logly-tools`` — ``mureo.skills`` only, but here
        with no entry point at all) is still listed, matching the updater."""
        with (
            patch("mureo.web.about.entry_points", _entry_points_for({})),
            patch(
                "mureo.web.about.version",
                _version_for({"mureo": "1.0.0", "mureo-logly-tools": "0.3.0"}),
            ),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                return_value=["mureo", "mureo-logly-tools"],
            ),
        ):
            info = collect_about_info()
        assert {"name": "mureo-logly-tools", "version": "0.3.0"} in info["packages"]
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["mureo", "mureo-logly-tools"]

    def test_name_prefixed_package_missing_version_uses_placeholder(self) -> None:
        """A name-prefix-discovered dist whose version cannot be resolved
        degrades to the placeholder rather than dropping the row."""
        with (
            patch("mureo.web.about.entry_points", _entry_points_for({})),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                return_value=["mureo", "mureo-ghost"],
            ),
        ):
            info = collect_about_info()
        assert {"name": "mureo-ghost", "version": UNKNOWN_VERSION} in info["packages"]

    def test_name_prefix_and_entry_point_dedupe_by_canonical(self) -> None:
        """A package surfaced by BOTH axes (a skills entry point AND the
        name prefix) appears exactly once."""
        by_group = {
            "mureo.skills": (
                _FakeEntryPoint(dist=_FakeDist("mureo-logly-tools", "0.3.0")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch(
                "mureo.web.about.version",
                _version_for({"mureo": "1.0.0", "mureo-logly-tools": "0.3.0"}),
            ),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                return_value=["mureo", "mureo-logly-tools"],
            ),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["mureo", "mureo-logly-tools"]

    def test_skills_only_entry_point_plugin_is_listed(self) -> None:
        """A skills plugin NOT named ``mureo-*`` (so invisible to the
        name-prefix axis) is surfaced via the now-scanned skills group."""
        by_group = {
            "mureo.skills": (_FakeEntryPoint(dist=_FakeDist("acme-skills", "1.1.0")),),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["acme-skills", "mureo"]

    def test_policy_gate_and_analytics_groups_are_scanned(self) -> None:
        """The policy-gate and analytics extension surfaces are scanned too,
        so a plugin contributing only those still appears."""
        by_group = {
            "mureo.policy_gates": (
                _FakeEntryPoint(dist=_FakeDist("gate-plugin", "2.0.0")),
            ),
            "mureo.analytics": (
                _FakeEntryPoint(dist=_FakeDist("analytics-plugin", "3.0.0")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["analytics-plugin", "gate-plugin", "mureo"]

    def test_name_prefix_discovery_failure_is_isolated(self) -> None:
        """If the name-prefix walk blows up, the endpoint still returns the
        entry-point-derived rows rather than 500-ing."""
        by_group = {
            "mureo.providers": (_FakeEntryPoint(dist=_FakeDist("ep-plugin", "1.0.0")),),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for({"mureo": "1.0.0"})),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                side_effect=RuntimeError("metadata index corrupted"),
            ),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["ep-plugin", "mureo"]

    def test_name_prefixed_version_none_uses_placeholder(self) -> None:
        """``importlib.metadata.version`` returns ``None`` (not raises) for a
        dist whose ``METADATA`` has a Name but no Version header. The row must
        still carry a string version (payload shape ``{"name","version"}``)."""

        def version_returns_none(name: str) -> str | None:
            if name == "mureo":
                return "1.0.0"
            return None  # malformed dist-info: Version header absent

        with (
            patch("mureo.web.about.entry_points", _entry_points_for({})),
            patch("mureo.web.about.version", version_returns_none),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                return_value=["mureo", "mureo-malformed"],
            ),
        ):
            info = collect_about_info()
        row = next(p for p in info["packages"] if p["name"] == "mureo-malformed")
        assert row == {"name": "mureo-malformed", "version": UNKNOWN_VERSION}
        assert isinstance(row["version"], str)

    def test_mixed_case_name_dedupes_and_displays_canonical(self) -> None:
        """A distribution whose raw entry-point name is mixed-case / underscored
        is deduped against its name-prefix canonical form AND displayed in the
        canonical form — so About labels it identically to the update banner."""
        by_group = {
            "mureo.skills": (
                _FakeEntryPoint(dist=_FakeDist("Mureo_Logly_Tools", "0.3.0")),
            ),
        }
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch(
                "mureo.web.about.version",
                _version_for({"mureo": "1.0.0", "mureo-logly-tools": "0.3.0"}),
            ),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                return_value=["mureo", "mureo-logly-tools"],
            ),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        assert names == ["mureo", "mureo-logly-tools"]
        assert "Mureo_Logly_Tools" not in names

    def test_every_updater_package_appears_exactly_once(self) -> None:
        """Property of #365: every name the updater discovers is listed here
        exactly once (⊆ guarantee), regardless of entry-point registration."""
        updater_set = ["mureo", "mureo-agency", "mureo-logly-tools", "mureo-x"]
        by_group = {
            # Only one of them also registers an entry point — the rest are
            # name-prefix-only, exactly the #365 gap.
            "mureo.providers": (
                _FakeEntryPoint(dist=_FakeDist("mureo-agency", "0.1.0")),
            ),
        }
        versions = {name: "1.0.0" for name in updater_set}
        with (
            patch("mureo.web.about.entry_points", _entry_points_for(by_group)),
            patch("mureo.web.about.version", _version_for(versions)),
            patch(
                "mureo.web.about._discover_all_mureo_packages",
                return_value=updater_set,
            ),
        ):
            info = collect_about_info()
        names = [pkg["name"] for pkg in info["packages"]]
        for canonical in updater_set:
            assert names.count(canonical) == 1, f"{canonical} not listed exactly once"


@pytest.mark.unit
class TestAboutAssets:
    """Static-content guards for the About tab wiring (same discipline
    as ``test_web_assets_extension_overrides.py``)."""

    def test_app_html_has_about_tab_and_group(self) -> None:
        html = (_WEB / "app.html").read_text(encoding="utf-8")
        assert 'data-dashboard-nav="about"' in html
        assert 'data-dashboard-group="about"' in html
        # Logo reuses the bundled wordmark assets with both scheme variants.
        assert html.count('src="/static/logo.png"') >= 2
        assert html.count('src="/static/logo-dark.png"') >= 2

    def test_dashboard_js_fetches_about_endpoint(self) -> None:
        js = (_WEB / "dashboard.js").read_text(encoding="utf-8")
        assert "/api/about" in js

    def test_about_is_the_last_static_nav_item(self) -> None:
        """The About tab must sit at the very bottom of the dashboard
        nav — below Danger Zone in the static markup."""
        html = (_WEB / "app.html").read_text(encoding="utf-8")
        nav_keys = re.findall(r'data-dashboard-nav="([^"]+)"', html)
        assert nav_keys, "no dashboard nav items found"
        assert nav_keys[-1] == "about"

    def test_extension_tabs_are_inserted_before_about(self) -> None:
        """Extension nav items must be inserted BEFORE the About item
        (not appended at the end of the list), so About stays the last
        tab even when plugins such as the agency extension add tabs."""
        js = (_WEB / "extensions.js").read_text(encoding="utf-8")
        assert 'data-dashboard-nav="about"' in js
        assert "insertBefore" in js

    def test_i18n_has_about_keys_in_both_locales(self) -> None:
        catalog = json.loads((_WEB / "i18n.json").read_text(encoding="utf-8"))
        for locale in ("en", "ja"):
            for key in (
                "dashboard.nav_about",
                "dashboard.about_title",
                "dashboard.about_version",
                "dashboard.about_col_package",
                "dashboard.about_col_version",
            ):
                assert key in catalog[locale], f"{locale} missing {key}"
        assert catalog["en"]["dashboard.about_title"] == "About mureo"
        assert catalog["ja"]["dashboard.about_title"] == "mureoについて"


@pytest.mark.unit
class TestUpdateAssets:
    """#239 — static-content guards for the About-tab update + one-click
    upgrade wiring (same discipline as ``TestAboutAssets``)."""

    def test_app_html_has_update_section_and_button(self) -> None:
        """The About group hosts the update area + the Update button."""
        html = (_WEB / "app.html").read_text(encoding="utf-8")
        assert "data-about-updates" in html
        assert "data-about-update-button" in html

    def test_app_html_has_update_nav_badge_anchor(self) -> None:
        """The About nav item is the anchor the red indicator attaches to."""
        html = (_WEB / "app.html").read_text(encoding="utf-8")
        assert 'data-dashboard-nav="about"' in html

    def test_dashboard_js_fetches_updates_endpoint(self) -> None:
        js = (_WEB / "dashboard.js").read_text(encoding="utf-8")
        assert "/api/updates" in js

    def test_dashboard_js_posts_upgrade_endpoint(self) -> None:
        js = (_WEB / "dashboard.js").read_text(encoding="utf-8")
        assert "/api/upgrade" in js

    def test_dashboard_js_adds_update_nav_badge(self) -> None:
        """The red indicator is wired to the About nav item."""
        js = (_WEB / "dashboard.js").read_text(encoding="utf-8")
        assert "nav-badge-update" in js
        assert '[data-dashboard-nav="about"]' in js

    def test_dashboard_js_upgrade_is_one_click_no_confirm_panel(self) -> None:
        """ "Update all" upgrades DIRECTLY on click — the previous two-step
        in-page confirm panel was removed for a one-click flow, and the
        upgrade never triggers a native ``window.confirm`` dialog."""
        js = (_WEB / "dashboard.js").read_text(encoding="utf-8")
        html = (_WEB / "app.html").read_text(encoding="utf-8")
        assert "data-about-update-confirm" not in js
        assert "data-about-update-confirm" not in html
        assert "window.confirm" not in js
        # The Update-all button wires straight to the upgrade.
        start = js.index("function wireUpgradeButton")
        assert "runUpgrade" in js[start : start + 300]

    def test_i18n_has_update_keys_in_both_locales(self) -> None:
        catalog = json.loads((_WEB / "i18n.json").read_text(encoding="utf-8"))
        for locale in ("en", "ja"):
            for key in (
                "dashboard.about_update_available",
                "dashboard.about_update_button",
                "dashboard.about_update_running",
                "dashboard.about_update_restarting",
                "dashboard.about_update_done_restart",
                "dashboard.about_update_failed",
                "dashboard.about_up_to_date",
                "dashboard.about_update_badge",
                "dashboard.about_update_row",
            ):
                assert key in catalog[locale], f"{locale} missing {key}"
        # ja must be natural Japanese (not the en string echoed back).
        assert (
            catalog["ja"]["dashboard.about_update_button"]
            != catalog["en"]["dashboard.about_update_button"]
        )
