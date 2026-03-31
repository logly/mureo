"""RSA（レスポンシブ検索広告）テキストのバリデーションモジュール。

Google広告のレギュレーションに基づき、広告テキストをAPIコール前に検証・自動修正する。
自動修正可能な違反は修正し、修正不可能な重大違反のみValueErrorで拒否する。
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from dataclasses import dataclass

# === Google Ads 文字幅制限 ===
# 全角文字=2、半角文字=1 で計測。見出し上限30、説明文上限90。
HEADLINE_MAX_WIDTH = 30
DESCRIPTION_MAX_WIDTH = 90

# === 自動修正系（正規表現） ===

# 句読点・感嘆符の連続（2個以上）
_CONSECUTIVE_PUNCTUATION = re.compile(r"([！？!?。、，．]{2,})")

# 装飾記号の連続（3個以上）
_SYMBOL_REPEAT = re.compile(r"([◆◇★☆●○▲△■□♪♫◎※→←↑↓]{3,})")

# 全角スペースの連続
_ZENKAKU_SPACES = re.compile(r"\u3000{2,}")

# 先頭・末尾の不要記号
_EDGE_SYMBOLS = re.compile(r"^[！？!?。、]+|[。、]+$")

# 半角カタカナ（Google不承認対象）→ 全角カタカナに自動変換
_HALFWIDTH_KATAKANA = re.compile(r"[\uFF65-\uFF9F]+")

# 絵文字（Google広告テキストで不承認対象）→ 自動除去
# 注意: \u2600-\u26FF, \u2700-\u27BF は装飾記号（★☆♪等）を含むため除外。
# 実際の絵文字はUnicode補助面（U+1Fxxx）にあるため、そちらのみ対象とする。
_EMOJI = re.compile(
    r"[\U0001F600-\U0001F64F"  # 顔文字
    r"\U0001F300-\U0001F5FF"  # 記号・絵文字
    r"\U0001F680-\U0001F6FF"  # 交通・地図
    r"\U0001F900-\U0001F9FF"  # 補足絵文字
    r"\U0001FA00-\U0001FA6F"  # チェス等
    r"\U0001FA70-\U0001FAFF"  # 拡張絵文字
    r"\uFE0F]+",  # 異体字セレクタ
)

# === URL検証 ===


def display_width(text: str) -> int:
    """Google Ads方式の表示幅を計算する。

    East Asian Width カテゴリ:
      W (Wide), F (Fullwidth) → 2
      A (Ambiguous) → 2（日本語コンテキストではGoogle Adsが全角扱いする。
        例: ""…—※①℃ 等）
      Na (Narrow), N (Neutral), H (Halfwidth) → 1
    """
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ("W", "F", "A") else 1
    return width


def _is_valid_url(url: str) -> bool:
    """URLの基本的な構造チェック（スキーム + ホスト名の存在）。"""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False

# === 警告系（禁止表現） ===

# 最上級・No.1表現（景表法 優良誤認、根拠なき最上級表示）
_SUPERLATIVE_CLAIMS: frozenset[str] = frozenset(
    {
        "世界一",
        "日本一",
        "業界No.1",
        "No.1",
        "ナンバーワン",
        "世界初",
        "日本初",
        "業界初",
        "世界最大",
        "日本最大",
        "世界最高",
        "日本最高",
        "世界最速",
        "最高峰",
        "唯一",
        "唯一無二",
    }
)

# 価格・無料系（景表法 有利誤認）
_PRICE_CLAIMS: frozenset[str] = frozenset(
    {
        "最安値",
        "最安",
        "激安",
        "格安",
        "底値",
        "完全無料",
        "全額無料",
        "0円",
    }
)

# 効果保証・断定表現（景表法 優良誤認、Google編集ポリシー違反）
_GUARANTEE_CLAIMS: frozenset[str] = frozenset(
    {
        "絶対",
        "100%",
        "必ず",
        "確実",
        "間違いなく",
        "効果保証",
        "成果保証",
        "返金保証",
        "全額返金",
        "guaranteed",
        "guarantee",
    }
)

# 医療・健康・ダイエット系（薬機法・Google ヘルスケアポリシー）
_MEDICAL_CLAIMS: frozenset[str] = frozenset(
    {
        "治る",
        "完治",
        "治療効果",
        "奇跡",
        "奇跡的",
        "万能薬",
        "特効薬",
        "副作用なし",
    }
)

# クリックベイト表現（Google編集ポリシー「不明瞭な関連性」）
_CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"こちらをクリック"),
    re.compile(r"ここをクリック"),
    re.compile(r"今すぐクリック"),
    re.compile(r"click\s*here", re.IGNORECASE),
)

# 全カテゴリ統合（文字列マッチ用）
_PROHIBITED_EXPRESSIONS: frozenset[str] = (
    _SUPERLATIVE_CLAIMS | _PRICE_CLAIMS | _GUARANTEE_CLAIMS | _MEDICAL_CLAIMS
)


@dataclass(frozen=True)
class RSAValidationResult:
    """RSAバリデーション結果。"""

    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    warnings: tuple[str, ...]


# サニタイズ対象テキストの最大長。RSA見出し30文字・説明文90文字に対して余裕を持たせた値。
# これを超える入力は先に切り詰めてから正規表現を適用する（ReDoS防御）。
_MAX_SANITIZE_LENGTH = 200


def _sanitize_text(text: str) -> tuple[str, list[str]]:
    """1つのテキストを正規化し、適用した修正のリストを返す。

    順序: 長さ制限 → 半角カナ変換 → 絵文字除去 → 句読点縮約 → 記号反復縮約
          → 全角スペース正規化 → 先頭末尾記号除去
    """
    fixes: list[str] = []
    if len(text) > _MAX_SANITIZE_LENGTH:
        text = text[:_MAX_SANITIZE_LENGTH]
        fixes.append(f"テキストが{_MAX_SANITIZE_LENGTH}文字を超過したため切り詰め")
    original = text

    # 半角カタカナ → 全角カタカナ（NFKC正規化）
    if _HALFWIDTH_KATAKANA.search(text):
        text = unicodedata.normalize("NFKC", text)
        fixes.append(f"半角カタカナを全角に変換: '{original}' → '{text}'")

    # 絵文字除去
    if _EMOJI.search(text):
        text = _EMOJI.sub("", text)
        fixes.append("絵文字を除去")

    # 句読点・感嘆符の連続を1個に縮約
    if _CONSECUTIVE_PUNCTUATION.search(text):
        text = _CONSECUTIVE_PUNCTUATION.sub(lambda m: m.group(1)[0], text)
        fixes.append("句読点の連続を1個に縮約")

    # 装飾記号の反復を1個に縮約
    if _SYMBOL_REPEAT.search(text):
        text = _SYMBOL_REPEAT.sub(lambda m: m.group(1)[0], text)
        fixes.append("装飾記号の反復を1個に縮約")

    # 全角スペースの連続を半角スペース1個に変換
    if _ZENKAKU_SPACES.search(text):
        text = _ZENKAKU_SPACES.sub(" ", text)
        fixes.append("全角スペースの連続を半角スペースに変換")

    # 先頭・末尾の不要記号を除去
    if _EDGE_SYMBOLS.search(text):
        text = _EDGE_SYMBOLS.sub("", text)
        fixes.append("先頭・末尾の不要記号を除去")

    return text.strip(), fixes


def _check_prohibited(text: str) -> list[str]:
    """禁止表現チェック。文字列マッチ + 正規表現パターンの両方を検査。"""
    warnings: list[str] = []

    # 文字列マッチ
    for expr in _PROHIBITED_EXPRESSIONS:
        if expr in text:
            warnings.append(f"禁止表現 '{expr}' を検出: '{text}'")

    # 正規表現パターン（クリックベイト）
    for pattern in _CLICKBAIT_PATTERNS:
        if pattern.search(text):
            warnings.append(
                f"クリックベイト表現を検出 (パターン: {pattern.pattern}): '{text}'"
            )

    return warnings


def validate_rsa_texts(
    headlines: list[str],
    descriptions: list[str],
    final_url: str,
) -> RSAValidationResult:
    """RSA広告テキストをバリデーションし、修正済みテキストを返す。

    処理順序:
    1. final_url のURL形式チェック（不正ならValueError）
    2. 各テキストを _sanitize_text で自動修正
    3. 各テキストの禁止表現チェック（_check_prohibited）
    4. 見出しの重複除去
    5. RSAValidationResult を返却
    """
    all_warnings: list[str] = []

    # 1. URL形式チェック
    if not final_url:
        raise ValueError("final_url（リンク先URL）は必須です")
    if not _is_valid_url(final_url):
        raise ValueError(
            f"不正なURL形式です: '{final_url}' "
            "(http:// または https:// で始まるURLを指定してください)"
        )

    # 2. 各テキストをサニタイズ（空文字列になったテキストは除外）
    sanitized_headlines: list[str] = []
    for h in headlines:
        cleaned, fixes = _sanitize_text(h)
        if fixes:
            all_warnings.extend(
                f"見出し自動修正: {fix}" for fix in fixes
            )
        if cleaned:
            sanitized_headlines.append(cleaned)
        else:
            all_warnings.append(f"サニタイズ後に空になった見出しを除外: '{h}'")

    sanitized_descriptions: list[str] = []
    for d in descriptions:
        cleaned, fixes = _sanitize_text(d)
        if fixes:
            all_warnings.extend(
                f"説明文自動修正: {fix}" for fix in fixes
            )
        if cleaned:
            sanitized_descriptions.append(cleaned)
        else:
            all_warnings.append(f"サニタイズ後に空になった説明文を除外: '{d}'")

    # 3. 禁止表現チェック
    for h in sanitized_headlines:
        all_warnings.extend(_check_prohibited(h))
    for d in sanitized_descriptions:
        all_warnings.extend(_check_prohibited(d))

    # 4. 文字幅チェック（全角=2, 半角=1）
    too_long_errors: list[str] = []
    for i, h in enumerate(sanitized_headlines):
        w = display_width(h)
        if w > HEADLINE_MAX_WIDTH:
            too_long_errors.append(
                f"見出し{i + 1}が長すぎます（{w}/{HEADLINE_MAX_WIDTH}）: '{h}'"
            )
    for i, d in enumerate(sanitized_descriptions):
        w = display_width(d)
        if w > DESCRIPTION_MAX_WIDTH:
            too_long_errors.append(
                f"説明文{i + 1}が長すぎます（{w}/{DESCRIPTION_MAX_WIDTH}）: '{d}'"
            )
    if too_long_errors:
        raise ValueError(
            "Google Ads文字数制限超過（全角=2文字, 半角=1文字でカウント）:\n"
            + "\n".join(too_long_errors)
        )

    # 5. 見出しの重複除去
    seen: set[str] = set()
    unique_headlines: list[str] = []
    for h in sanitized_headlines:
        if h in seen:
            all_warnings.append(f"重複する見出しを除去: '{h}'")
        else:
            seen.add(h)
            unique_headlines.append(h)

    return RSAValidationResult(
        headlines=tuple(unique_headlines),
        descriptions=tuple(sanitized_descriptions),
        warnings=tuple(all_warnings),
    )


# === Ad Strength 予測 ===

# Ad Strength スコア配分（合計 1.0）
_WEIGHT_HEADLINE_COUNT = 0.25
_WEIGHT_DESCRIPTION_COUNT = 0.15
_WEIGHT_HEADLINE_DIVERSITY = 0.25
_WEIGHT_KEYWORD_RELEVANCE = 0.20
_WEIGHT_PIN_PENALTY = 0.10
_WEIGHT_SITELINK_BONUS = 0.05

# レベル判定閾値
_THRESHOLD_EXCELLENT = 0.85
_THRESHOLD_GOOD = 0.65
_THRESHOLD_AVERAGE = 0.40

# 見出し類似度の閾値（bigram Jaccard係数）
_SIMILARITY_THRESHOLD = 0.6

# 同義語ペア辞書（見出し多様性チェックで使用）— タプルに事前変換済み
_SYNONYM_PAIRS_TUPLES: tuple[tuple[str, str], ...] = (
    ("安い", "格安"),
    ("無料", "0円"),
    ("おすすめ", "人気"),
    ("簡単", "手軽"),
    ("最新", "新しい"),
    ("安心", "信頼"),
    ("即日", "当日"),
    ("割引", "値引き"),
    ("申込", "申し込み"),
    ("見積", "見積もり"),
)


@dataclass(frozen=True)
class AdStrengthFactor:
    """Ad Strength 評価因子。"""

    name: str  # 因子名
    score: float  # 0.0 ~ 1.0
    weight: float  # 重み
    message: str  # 改善メッセージ（日本語）


@dataclass(frozen=True)
class AdStrengthResult:
    """Ad Strength 予測結果。"""

    level: str  # "POOR" | "AVERAGE" | "GOOD" | "EXCELLENT"
    score: float  # 0.0 ~ 1.0
    factors: tuple[AdStrengthFactor, ...]
    suggestions: tuple[str, ...]  # LLMフィードバック用


def _bigram_similarity(a: str, b: str) -> float:
    """2文字bigramのJaccard係数で文字列の類似度を測定する。"""
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    bigrams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    bigrams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _has_synonym_overlap(a: str, b: str) -> bool:
    """同義語ペア辞書に基づき、2つのテキストに同義語関係があるか判定する。"""
    for w0, w1 in _SYNONYM_PAIRS_TUPLES:
        if (w0 in a and w1 in b) or (w1 in a and w0 in b):
            return True
    return False


def _check_headline_diversity(
    headlines: list[str],
) -> tuple[float, list[str]]:
    """見出しの多様性を評価する。

    Returns:
        (多様性スコア 0.0~1.0, 改善メッセージリスト)
    """
    if len(headlines) <= 1:
        return 1.0, []

    similar_pairs: list[tuple[str, str]] = []
    total_pairs = 0

    for i in range(len(headlines)):
        for j in range(i + 1, len(headlines)):
            total_pairs += 1
            sim = _bigram_similarity(headlines[i], headlines[j])
            if sim >= _SIMILARITY_THRESHOLD or _has_synonym_overlap(headlines[i], headlines[j]):
                similar_pairs.append((headlines[i], headlines[j]))

    if total_pairs == 0:
        return 1.0, []

    diversity_score = 1.0 - (len(similar_pairs) / total_pairs)
    messages: list[str] = []
    for a, b in similar_pairs[:3]:  # 最大3件まで報告
        messages.append(f"類似する見出し: 「{a}」と「{b}」")

    return max(0.0, diversity_score), messages


def _strip_match_type(keyword: str) -> str:
    """マッチタイプのプレフィックス・サフィックスを除去する。"""
    kw = keyword.strip()
    # フレーズマッチ: "keyword" / 完全一致: [keyword]
    if (kw.startswith('"') and kw.endswith('"')) or (
        kw.startswith("[") and kw.endswith("]")
    ):
        kw = kw[1:-1]
    # 絞り込み部分一致: +keyword
    if kw.startswith("+"):
        kw = kw[1:]
    return kw.strip()


def _check_keyword_relevance(
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str],
) -> tuple[float, list[str]]:
    """キーワードの広告テキストへの含有率を評価する。

    Returns:
        (関連性スコア 0.0~1.0, 未含有キーワードリスト)
    """
    if not keywords:
        return 0.5, []

    all_text = " ".join(headlines) + " " + " ".join(descriptions)
    all_text_lower = all_text.lower()

    missing: list[str] = []
    for kw in keywords:
        stripped = _strip_match_type(kw)
        if not stripped:
            continue
        if stripped.lower() not in all_text_lower:
            missing.append(kw)

    total = len([kw for kw in keywords if _strip_match_type(kw)])
    if total == 0:
        return 0.5, []

    matched = total - len(missing)
    return matched / total, missing


def _interpolate_headline_score(count: int) -> float:
    """見出し数からスコアを線形補間で算出する。"""
    breakpoints = [(3, 0.2), (5, 0.4), (8, 0.6), (10, 0.75), (13, 0.85), (15, 1.0)]

    if count <= breakpoints[0][0]:
        return breakpoints[0][1]
    if count >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    for i in range(len(breakpoints) - 1):
        c0, s0 = breakpoints[i]
        c1, s1 = breakpoints[i + 1]
        if c0 <= count <= c1:
            ratio = (count - c0) / (c1 - c0)
            return s0 + ratio * (s1 - s0)

    return breakpoints[-1][1]


def _eval_headline_count(
    headlines: list[str],
) -> tuple[AdStrengthFactor, list[str]]:
    """見出し数を評価する。"""
    score = _interpolate_headline_score(len(headlines))
    msg = f"見出し数: {len(headlines)}個"
    suggestions: list[str] = []
    if len(headlines) < 8:
        suggestions.append(
            f"見出しを{8 - len(headlines)}個追加してください"
            f"（現在{len(headlines)}個、推奨8個以上）"
        )
        msg += "（推奨8個以上）"
    return AdStrengthFactor(
        name="headline_count", score=score,
        weight=_WEIGHT_HEADLINE_COUNT, message=msg,
    ), suggestions


def _eval_description_count(
    descriptions: list[str],
) -> tuple[AdStrengthFactor, list[str]]:
    """説明文数を評価する。"""
    count = len(descriptions)
    score = 1.0 if count >= 4 else (0.75 if count == 3 else 0.5)
    msg = f"説明文数: {count}個"
    suggestions: list[str] = []
    if count < 4:
        suggestions.append(
            f"説明文を{4 - count}個追加してください（現在{count}個、推奨4個）"
        )
        msg += "（推奨4個）"
    return AdStrengthFactor(
        name="description_count", score=score,
        weight=_WEIGHT_DESCRIPTION_COUNT, message=msg,
    ), suggestions


def _eval_diversity(
    headlines: list[str],
) -> tuple[AdStrengthFactor, list[str]]:
    """見出し多様性を評価する。"""
    score, msgs = _check_headline_diversity(headlines)
    msg = f"見出し多様性: {score:.0%}"
    if msgs:
        msg += "（類似表現あり）"
    return AdStrengthFactor(
        name="headline_diversity", score=score,
        weight=_WEIGHT_HEADLINE_DIVERSITY, message=msg,
    ), msgs


def _eval_keyword_relevance(
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str] | None,
) -> tuple[AdStrengthFactor, list[str]]:
    """キーワード関連性を評価する。"""
    score, missing = _check_keyword_relevance(
        headlines, descriptions, keywords or [],
    )
    msg = f"キーワード関連性: {score:.0%}"
    suggestions: list[str] = []
    if keywords is None:
        msg += "（キーワード未指定）"
    elif missing:
        suggestions.append(f"未含有キーワード: {', '.join(missing[:5])}")
        msg += f"（{len(missing)}個未含有）"
    return AdStrengthFactor(
        name="keyword_relevance", score=score,
        weight=_WEIGHT_KEYWORD_RELEVANCE, message=msg,
    ), suggestions


def _eval_pin_penalty(
    pinned_count: int,
) -> tuple[AdStrengthFactor, list[str]]:
    """ピン留めペナルティを評価する。"""
    score = 0.3 if pinned_count > 0 else 1.0
    msg = f"ピン留め: {pinned_count}個"
    suggestions: list[str] = []
    if pinned_count > 0:
        suggestions.append("ピン留め（位置固定）を外すとAd Strengthが向上します")
        msg += "（ピン留めはAd Strength低下要因）"
    return AdStrengthFactor(
        name="pin_penalty", score=score,
        weight=_WEIGHT_PIN_PENALTY, message=msg,
    ), suggestions


def _eval_sitelink_bonus(
    has_sitelinks: bool,
) -> tuple[AdStrengthFactor, list[str]]:
    """サイトリンクボーナスを評価する。"""
    score = 1.0 if has_sitelinks else 0.5
    msg = "サイトリンク: " + ("あり" if has_sitelinks else "なし")
    suggestions: list[str] = []
    if not has_sitelinks:
        suggestions.append("サイトリンクを6個以上設定するとAd Strengthが向上します")
        msg += "（設定推奨）"
    return AdStrengthFactor(
        name="sitelink_bonus", score=score,
        weight=_WEIGHT_SITELINK_BONUS, message=msg,
    ), suggestions


def _score_to_level(score: float) -> str:
    """総合スコアからAd Strengthレベルを判定する。"""
    if score >= _THRESHOLD_EXCELLENT:
        return "EXCELLENT"
    if score >= _THRESHOLD_GOOD:
        return "GOOD"
    if score >= _THRESHOLD_AVERAGE:
        return "AVERAGE"
    return "POOR"


def predict_ad_strength(
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str] | None = None,
    has_sitelinks: bool = False,
    pinned_count: int = 0,
) -> AdStrengthResult:
    """広告のAd Strength（有効性）を予測する。

    Google Adsの Ad Strength 評価基準に基づき、見出し数・説明文数・
    多様性・キーワード関連性・ピン留め・サイトリンクを総合評価する。
    """
    evaluators = [
        _eval_headline_count(headlines),
        _eval_description_count(descriptions),
        _eval_diversity(headlines),
        _eval_keyword_relevance(headlines, descriptions, keywords),
        _eval_pin_penalty(pinned_count),
        _eval_sitelink_bonus(has_sitelinks),
    ]
    factors = [factor for factor, _ in evaluators]
    suggestions = [s for _, sug_list in evaluators for s in sug_list]
    total_score = sum(f.score * f.weight for f in factors)

    return AdStrengthResult(
        level=_score_to_level(total_score),
        score=total_score,
        factors=tuple(factors),
        suggestions=tuple(suggestions),
    )
