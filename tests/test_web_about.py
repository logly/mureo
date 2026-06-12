"""Version/extension-package discovery for ``mureo.web.about``.

``collect_about_info`` resolves the installed mureo version plus every
distribution contributing to mureo's plugin entry-point groups via
:mod:`importlib.metadata`. These tests mock that surface entirely —
the machine running them may carry real mureo plugins (dev boxes do),
so nothing here depends on what is actually installed.
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
    def test_groups_constant_covers_all_three_plugin_surfaces(self) -> None:
        assert ABOUT_ENTRY_POINT_GROUPS == (
            "mureo.providers",
            "mureo.runtime_context_factory",
            "mureo.web_extensions",
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
