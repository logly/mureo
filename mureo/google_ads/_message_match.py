"""マルチモーダル メッセージマッチ評価

Playwrightでスクリーンショットを取得する機能を提供する。
mureo-coreではLLM依存を除去しているため、Vision LLMによる評価は行わない。
LLMによるメッセージマッチ評価はManaged側で実施すること。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SCREENSHOT_TIMEOUT_MS = 30_000
_VIEWPORT_WIDTH = 1280
_VIEWPORT_HEIGHT = 800


@dataclass(frozen=True)
class MessageMatchResult:
    """メッセージマッチ評価結果"""

    url: str
    overall_score: int  # 1-10
    headline_match: int  # 1-10
    description_match: int  # 1-10
    cta_match: int  # 1-10
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    suggestions: tuple[str, ...]
    error: str | None = None


class LPScreenshotter:
    """PlaywrightでLPのスクリーンショットを取得する"""

    async def capture(self, url: str) -> bytes:
        """URLのスクリーンショットをPNGバイナリで返す

        Raises:
            RuntimeError: スクリーンショット取得に失敗した場合
        """
        from mureo.analysis.lp_analyzer import LPAnalyzer

        # SSRF対策: LPAnalyzerと同じURL検証を使用
        LPAnalyzer._validate_url(url)

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwrightが利用できません。pip install playwright && playwright install を実行してください"
            ) from exc

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": _VIEWPORT_WIDTH, "height": _VIEWPORT_HEIGHT},
                )
                await page.goto(url, timeout=_SCREENSHOT_TIMEOUT_MS, wait_until="networkidle")
                screenshot = await page.screenshot(full_page=False, type="png")
                return screenshot
            finally:
                await browser.close()


class MessageMatchEvaluator:
    """広告文とLPのメッセージマッチ評価。

    mureo-coreではLLM依存を除去しているため、Vision LLMによる評価は行わない。
    プロンプト生成とレスポンスパースのみを担当する。
    LLMによる評価はManaged側で実施すること。
    """

    _EVAL_PROMPT = """\
あなたは広告文とランディングページの「メッセージマッチ」を評価する専門家です。

以下の広告文がLPのスクリーンショット画像と一致しているかを評価してください。
{strategic_context_section}
## 広告文
### 見出し
{headlines}

### 説明文
{descriptions}

## 評価基準
1. **headline_match** (1-10): 広告見出しとLP上のメインメッセージの一致度
2. **description_match** (1-10): 広告説明文とLPコンテンツの一致度
3. **cta_match** (1-10): 広告のCTA（行動喚起）とLP上のCTAの一致度
4. **overall_score** (1-10): 総合的なメッセージマッチ度

## 出力フォーマット（JSON）
```json
{{
    "overall_score": 7,
    "headline_match": 8,
    "description_match": 6,
    "cta_match": 7,
    "strengths": ["LP上の主要見出しと広告見出しが一致している"],
    "weaknesses": ["広告で訴求している価格情報がLP上で目立たない"],
    "suggestions": ["LPのファーストビューに広告と同じ価格訴求を追加する"]
}}
```

JSON のみを出力してください。"""

    def build_prompt(
        self,
        headlines: list[str],
        descriptions: list[str],
        strategic_context: str | None = None,
    ) -> str:
        """LLM評価用のプロンプトを生成する。

        LLM呼び出し自体はManaged側で実施する。
        """
        ctx_section = ""
        if strategic_context:
            ctx_section = (
                "\n## 戦略コンテキスト\n"
                "以下のペルソナ・USP・ターゲット情報を踏まえて、"
                "広告文がターゲットに適切なメッセージを伝えているかも評価してください。\n\n"
                f"{strategic_context}\n"
            )

        return self._EVAL_PROMPT.format(
            headlines="\n".join(f"- {h}" for h in headlines),
            descriptions="\n".join(f"- {d}" for d in descriptions),
            strategic_context_section=ctx_section,
        )

    @staticmethod
    def parse_response(content: str) -> MessageMatchResult:
        """LLMレスポンスをパースする"""
        # JSONブロックを抽出
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("メッセージマッチ評価のJSONパースに失敗: %s", exc)
            return MessageMatchResult(
                url="",
                overall_score=0,
                headline_match=0,
                description_match=0,
                cta_match=0,
                strengths=(),
                weaknesses=(),
                suggestions=(),
                error=f"評価結果のパースに失敗しました: {exc}",
            )

        return MessageMatchResult(
            url="",
            overall_score=int(data.get("overall_score", 0)),
            headline_match=int(data.get("headline_match", 0)),
            description_match=int(data.get("description_match", 0)),
            cta_match=int(data.get("cta_match", 0)),
            strengths=tuple(data.get("strengths", [])),
            weaknesses=tuple(data.get("weaknesses", [])),
            suggestions=tuple(data.get("suggestions", [])),
        )
