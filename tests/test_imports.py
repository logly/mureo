"""import検証テスト

全モジュールがimportできること、DB/LLM系のimportが含まれていないことを確認する。
"""

from __future__ import annotations

import ast
import importlib
import pathlib
from typing import Any

import pytest

# mureo-core パッケージルート
_MUREO_ROOT = pathlib.Path(__file__).resolve().parent.parent / "mureo"

# DB/LLM系の禁止importパターン
_FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "sqlalchemy",
        "alembic",
        "asyncpg",
        "aiosqlite",
        "supabase",
        "openai",
        "anthropic",
        "google.generativeai",
        "langchain",
        "slack_bolt",
        "slack_sdk",
        "apscheduler",
        "fastapi",
        "uvicorn",
        "redis",
    }
)

# テスト対象モジュール一覧
_ALL_MODULES: list[str] = [
    "mureo",
    "mureo.google_ads",
    "mureo.google_ads.client",
    "mureo.google_ads.mappers",
    "mureo.google_ads._ads",
    "mureo.google_ads._keywords",
    "mureo.google_ads._analysis",
    "mureo.google_ads._analysis_constants",
    "mureo.google_ads._analysis_performance",
    "mureo.google_ads._analysis_search_terms",
    "mureo.google_ads._analysis_keywords",
    "mureo.google_ads._analysis_budget",
    "mureo.google_ads._analysis_rsa",
    "mureo.google_ads._analysis_auction",
    "mureo.google_ads._analysis_btob",
    "mureo.google_ads._extensions",
    "mureo.google_ads._diagnostics",
    "mureo.google_ads._monitoring",
    "mureo.google_ads._creative",
    "mureo.google_ads._rsa_validator",
    "mureo.google_ads._rsa_insights",
    "mureo.google_ads._intent_classifier",
    "mureo.google_ads._message_match",
    "mureo.meta_ads",
    "mureo.meta_ads.client",
    "mureo.meta_ads.mappers",
    "mureo.meta_ads._campaigns",
    "mureo.meta_ads._ad_sets",
    "mureo.meta_ads._ads",
    "mureo.meta_ads._creatives",
    "mureo.meta_ads._audiences",
    "mureo.meta_ads._pixels",
    "mureo.meta_ads._insights",
    "mureo.meta_ads._analysis",
    "mureo.analysis",
    "mureo.analysis.lp_analyzer",
    "mureo.context",
    "mureo.context.errors",
    "mureo.context.models",
    "mureo.context.state",
    "mureo.context.strategy",
]


def _collect_imports_from_file(filepath: pathlib.Path) -> list[str]:
    """ASTを使ってPythonファイルからimport文のモジュール名を収集する"""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


@pytest.mark.unit
class TestModuleImports:
    """全モジュールがimportできることを確認"""

    @pytest.mark.parametrize("module_name", _ALL_MODULES)
    def test_import_succeeds(self, module_name: str) -> None:
        """各モジュールが正常にimportできる"""
        mod = importlib.import_module(module_name)
        assert mod is not None


@pytest.mark.unit
class TestNoForbiddenImports:
    """DB/LLM系のimportが含まれていないことをAST解析で確認"""

    def _collect_all_py_files(self) -> list[pathlib.Path]:
        """mureo/ 配下の全.pyファイルを収集"""
        return sorted(_MUREO_ROOT.rglob("*.py"))

    def test_no_forbidden_imports_in_package(self) -> None:
        """mureo/配下の全ファイルに禁止importが含まれていない"""
        violations: list[str] = []

        for py_file in self._collect_all_py_files():
            imports = _collect_imports_from_file(py_file)
            for imp in imports:
                # トップレベルモジュール名で比較
                top_module = imp.split(".")[0]
                for forbidden in _FORBIDDEN_MODULES:
                    if top_module == forbidden.split(".")[0] and imp.startswith(
                        forbidden
                    ):
                        violations.append(
                            f"{py_file.relative_to(_MUREO_ROOT.parent)}: "
                            f"import {imp}"
                        )

        assert violations == [], (
            "禁止されたDB/LLM系のimportが検出されました:\n"
            + "\n".join(violations)
        )
