"""RSA (Responsive Search Ad) text validation module.

Validates and auto-corrects ad text before API calls based on Google Ads regulations.
Auto-correctable violations are fixed; only unfixable critical violations raise ValueError.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from dataclasses import dataclass

# === Google Ads character width limits ===
# Full-width=2, half-width=1. Headline max 30, description max 90.
HEADLINE_MAX_WIDTH = 30
DESCRIPTION_MAX_WIDTH = 90

# === Auto-correction patterns (regex) ===

# Consecutive punctuation/exclamation (2 or more)
_CONSECUTIVE_PUNCTUATION = re.compile(r"([！？!?。、，．]{2,})")

# Consecutive decorative symbols (3 or more)
_SYMBOL_REPEAT = re.compile(r"([◆◇★☆●○▲△■□♪♫◎※→←↑↓]{3,})")

# Consecutive full-width spaces
_ZENKAKU_SPACES = re.compile(r"\u3000{2,}")

# Leading/trailing unnecessary symbols
_EDGE_SYMBOLS = re.compile(r"^[！？!?。、]+|[。、]+$")

# Half-width katakana (Google disapproval target) -> auto-convert to full-width
_HALFWIDTH_KATAKANA = re.compile(r"[\uFF65-\uFF9F]+")

# Emoji (disapproval target in Google ad text) -> auto-remove
# Note: \u2600-\u26FF, \u2700-\u27BF contain decorative symbols and are excluded.
# Actual emoji are in Unicode supplementary planes (U+1Fxxx), so only those are targeted.
_EMOJI = re.compile(
    r"[\U0001F600-\U0001F64F"  # emoticons
    r"\U0001F300-\U0001F5FF"  # symbols & pictographs
    r"\U0001F680-\U0001F6FF"  # transport & map
    r"\U0001F900-\U0001F9FF"  # supplemental symbols
    r"\U0001FA00-\U0001FA6F"  # chess etc.
    r"\U0001FA70-\U0001FAFF"  # extended symbols
    r"\uFE0F]+",  # variation selector
)

# === URL validation ===


def display_width(text: str) -> int:
    """Calculate display width using Google Ads rules.

    East Asian Width categories:
      W (Wide), F (Fullwidth) -> 2
      A (Ambiguous) -> 2 (Google Ads treats these as full-width in Japanese context.
        e.g., quotation marks, ellipsis, em dash, etc.)
      Na (Narrow), N (Neutral), H (Halfwidth) -> 1
    """
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ("W", "F", "A") else 1
    return width


def _is_valid_url(url: str) -> bool:
    """Basic URL structure check (scheme + hostname presence)."""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# === Warnings (prohibited expressions) ===

# Superlative/No.1 claims (Act against Unjustifiable Premiums: misleading superiority claims)
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

# Price/free claims (Act against Unjustifiable Premiums: misleading advantage claims)
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

# Guarantee/absolute claims (misleading superiority, Google editorial policy violation)
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

# Medical/health claims (Pharmaceutical Affairs Act, Google healthcare policy)
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

# Clickbait expressions (Google editorial policy: unclear relevance)
_CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"こちらをクリック"),
    re.compile(r"ここをクリック"),
    re.compile(r"今すぐクリック"),
    re.compile(r"click\s*here", re.IGNORECASE),
)

# All categories combined (for string matching)
_PROHIBITED_EXPRESSIONS: frozenset[str] = (
    _SUPERLATIVE_CLAIMS | _PRICE_CLAIMS | _GUARANTEE_CLAIMS | _MEDICAL_CLAIMS
)


@dataclass(frozen=True)
class RSAValidationResult:
    """RSA validation result."""

    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    warnings: tuple[str, ...]


# Max length for sanitization target text. Generous margin for RSA headline (30) / description (90).
# Inputs exceeding this are truncated first before regex (ReDoS defense).
_MAX_SANITIZE_LENGTH = 200


def _sanitize_text(text: str) -> tuple[str, list[str]]:
    """Normalize a single text and return a list of applied fixes.

    Order: length limit -> half-width kana conversion -> emoji removal -> punctuation reduction -> symbol repeat reduction
          -> full-width space normalization -> leading/trailing symbol removal
    """
    fixes: list[str] = []
    if len(text) > _MAX_SANITIZE_LENGTH:
        text = text[:_MAX_SANITIZE_LENGTH]
        fixes.append(f"Text exceeded {_MAX_SANITIZE_LENGTH} characters; truncated")
    original = text

    # Half-width katakana -> full-width katakana (NFKC normalization)
    if _HALFWIDTH_KATAKANA.search(text):
        text = unicodedata.normalize("NFKC", text)
        fixes.append(
            f"Converted half-width katakana to full-width: '{original}' -> '{text}'"
        )

    # Remove emoji
    if _EMOJI.search(text):
        text = _EMOJI.sub("", text)
        fixes.append("Removed emoji")

    # Reduce consecutive punctuation/exclamation to single
    if _CONSECUTIVE_PUNCTUATION.search(text):
        text = _CONSECUTIVE_PUNCTUATION.sub(lambda m: m.group(1)[0], text)
        fixes.append("Reduced consecutive punctuation to single")

    # Reduce decorative symbol repetition to single
    if _SYMBOL_REPEAT.search(text):
        text = _SYMBOL_REPEAT.sub(lambda m: m.group(1)[0], text)
        fixes.append("Reduced decorative symbol repetition to single")

    # Consecutive full-width spacesを半角スペース1個に変換
    if _ZENKAKU_SPACES.search(text):
        text = _ZENKAKU_SPACES.sub(" ", text)
        fixes.append("Converted consecutive full-width spaces to half-width space")

    # Leading/trailing unnecessary symbolsを除去
    if _EDGE_SYMBOLS.search(text):
        text = _EDGE_SYMBOLS.sub("", text)
        fixes.append("Removed leading/trailing unnecessary symbols")

    return text.strip(), fixes


def _check_prohibited(text: str) -> list[str]:
    """Check prohibited expressions via both string matching and regex patterns."""
    warnings: list[str] = []

    # String matching
    for expr in _PROHIBITED_EXPRESSIONS:
        if expr in text:
            warnings.append(f"Prohibited expression '{expr}' detected: '{text}'")

    # Regex patterns (clickbait)
    for pattern in _CLICKBAIT_PATTERNS:
        if pattern.search(text):
            warnings.append(
                f"Clickbait expression detected (pattern: {pattern.pattern}): '{text}'"
            )

    return warnings


def validate_rsa_texts(
    headlines: list[str],
    descriptions: list[str],
    final_url: str,
) -> RSAValidationResult:
    """Validate RSA ad text and return corrected text.

    処理順序:
    1. URL format check for final_url (ValueError if invalid)
    2. Auto-correct each text via _sanitize_text
    3. Check each text for prohibited expressions (_check_prohibited)
    4. Deduplicate headlines
    5. Return RSAValidationResult
    """
    all_warnings: list[str] = []

    # 1. URL format check
    if not final_url:
        raise ValueError("final_url (destination URL) is required")
    if not _is_valid_url(final_url):
        raise ValueError(
            f"Invalid URL format: '{final_url}' "
            "(please specify a URL starting with http:// or https://)"
        )

    # 2. Sanitize each text (exclude texts that become empty)
    sanitized_headlines: list[str] = []
    for h in headlines:
        cleaned, fixes = _sanitize_text(h)
        if fixes:
            all_warnings.extend(f"Headline auto-fix: {fix}" for fix in fixes)
        if cleaned:
            sanitized_headlines.append(cleaned)
        else:
            all_warnings.append(
                f"Excluded headline that became empty after sanitization: '{h}'"
            )

    sanitized_descriptions: list[str] = []
    for d in descriptions:
        cleaned, fixes = _sanitize_text(d)
        if fixes:
            all_warnings.extend(f"Description auto-fix: {fix}" for fix in fixes)
        if cleaned:
            sanitized_descriptions.append(cleaned)
        else:
            all_warnings.append(
                f"Excluded description that became empty after sanitization: '{d}'"
            )

    # 3. Prohibited expression check
    for h in sanitized_headlines:
        all_warnings.extend(_check_prohibited(h))
    for d in sanitized_descriptions:
        all_warnings.extend(_check_prohibited(d))

    # 4. Character width check (full-width=2, half-width=1)
    too_long_errors: list[str] = []
    for i, h in enumerate(sanitized_headlines):
        w = display_width(h)
        if w > HEADLINE_MAX_WIDTH:
            too_long_errors.append(
                f"Headline {i + 1} is too long ({w}/{HEADLINE_MAX_WIDTH}): '{h}'"
            )
    for i, d in enumerate(sanitized_descriptions):
        w = display_width(d)
        if w > DESCRIPTION_MAX_WIDTH:
            too_long_errors.append(
                f"Description {i + 1} is too long ({w}/{DESCRIPTION_MAX_WIDTH}): '{d}'"
            )
    if too_long_errors:
        raise ValueError(
            "Google Ads character limit exceeded (full-width=2, half-width=1):\n"
            + "\n".join(too_long_errors)
        )

    # 5. Deduplicate headlines
    seen: set[str] = set()
    unique_headlines: list[str] = []
    for h in sanitized_headlines:
        if h in seen:
            all_warnings.append(f"Removed duplicate headline: '{h}'")
        else:
            seen.add(h)
            unique_headlines.append(h)

    return RSAValidationResult(
        headlines=tuple(unique_headlines),
        descriptions=tuple(sanitized_descriptions),
        warnings=tuple(all_warnings),
    )


# === Ad Strength Prediction ===

# Ad Strength score weights (total 1.0)
_WEIGHT_HEADLINE_COUNT = 0.25
_WEIGHT_DESCRIPTION_COUNT = 0.15
_WEIGHT_HEADLINE_DIVERSITY = 0.25
_WEIGHT_KEYWORD_RELEVANCE = 0.20
_WEIGHT_PIN_PENALTY = 0.10
_WEIGHT_SITELINK_BONUS = 0.05

# Level determination thresholds
_THRESHOLD_EXCELLENT = 0.85
_THRESHOLD_GOOD = 0.65
_THRESHOLD_AVERAGE = 0.40

# Headline similarity threshold (bigram Jaccard coefficient)
_SIMILARITY_THRESHOLD = 0.6

# Synonym pair dictionary (for headline diversity check) - pre-converted to tuples
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

    name: str  # Factor name
    score: float  # 0.0 ~ 1.0
    weight: float  # Weight
    message: str  # Improvement message


@dataclass(frozen=True)
class AdStrengthResult:
    """Ad Strength 予測結果。"""

    level: str  # "POOR" | "AVERAGE" | "GOOD" | "EXCELLENT"
    score: float  # 0.0 ~ 1.0
    factors: tuple[AdStrengthFactor, ...]
    suggestions: tuple[str, ...]  # For LLM feedback


def _bigram_similarity(a: str, b: str) -> float:
    """Measure string similarity using 2-character bigram Jaccard coefficient."""
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
    """Check if two texts have a synonym relationship based on synonym pair dictionary."""
    for w0, w1 in _SYNONYM_PAIRS_TUPLES:
        if (w0 in a and w1 in b) or (w1 in a and w0 in b):
            return True
    return False


def _check_headline_diversity(
    headlines: list[str],
) -> tuple[float, list[str]]:
    """Evaluate headline diversity.

    Returns:
        (diversity_score 0.0~1.0, improvement_message_list)
    """
    if len(headlines) <= 1:
        return 1.0, []

    similar_pairs: list[tuple[str, str]] = []
    total_pairs = 0

    for i in range(len(headlines)):
        for j in range(i + 1, len(headlines)):
            total_pairs += 1
            sim = _bigram_similarity(headlines[i], headlines[j])
            if sim >= _SIMILARITY_THRESHOLD or _has_synonym_overlap(
                headlines[i], headlines[j]
            ):
                similar_pairs.append((headlines[i], headlines[j]))

    if total_pairs == 0:
        return 1.0, []

    diversity_score = 1.0 - (len(similar_pairs) / total_pairs)
    messages: list[str] = []
    for a, b in similar_pairs[:3]:  # 最大3件まで報告
        messages.append(f'Similar headlines: "{a}" and "{b}"')

    return max(0.0, diversity_score), messages


def _strip_match_type(keyword: str) -> str:
    """Remove match type prefix/suffix."""
    kw = keyword.strip()
    # Phrase match: "keyword" / Exact match: [keyword]
    if (kw.startswith('"') and kw.endswith('"')) or (
        kw.startswith("[") and kw.endswith("]")
    ):
        kw = kw[1:-1]
    # Modified broad match: +keyword
    if kw.startswith("+"):
        kw = kw[1:]
    return kw.strip()


def _check_keyword_relevance(
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str],
) -> tuple[float, list[str]]:
    """Evaluate keyword inclusion rate in ad text.

    Returns:
        (relevance_score 0.0~1.0, missing_keyword_list)
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
    """Calculate score from headline count via linear interpolation."""
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
    """Evaluate headline count."""
    score = _interpolate_headline_score(len(headlines))
    msg = f"Headline count: {len(headlines)}"
    suggestions: list[str] = []
    if len(headlines) < 8:
        suggestions.append(
            f"Please add {8 - len(headlines)} more headlines"
            f" (currently {len(headlines)}, recommended 8+)"
        )
        msg += " (recommended 8+)"
    return (
        AdStrengthFactor(
            name="headline_count",
            score=score,
            weight=_WEIGHT_HEADLINE_COUNT,
            message=msg,
        ),
        suggestions,
    )


def _eval_description_count(
    descriptions: list[str],
) -> tuple[AdStrengthFactor, list[str]]:
    """Evaluate description count."""
    count = len(descriptions)
    score = 1.0 if count >= 4 else (0.75 if count == 3 else 0.5)
    msg = f"Description count: {count}"
    suggestions: list[str] = []
    if count < 4:
        suggestions.append(
            f"Please add {4 - count} more descriptions (currently {count}, recommended 4)"
        )
        msg += " (recommended 4)"
    return (
        AdStrengthFactor(
            name="description_count",
            score=score,
            weight=_WEIGHT_DESCRIPTION_COUNT,
            message=msg,
        ),
        suggestions,
    )


def _eval_diversity(
    headlines: list[str],
) -> tuple[AdStrengthFactor, list[str]]:
    """Evaluate headline diversity."""
    score, msgs = _check_headline_diversity(headlines)
    msg = f"Headline diversity: {score:.0%}"
    if msgs:
        msg += " (similar expressions found)"
    return (
        AdStrengthFactor(
            name="headline_diversity",
            score=score,
            weight=_WEIGHT_HEADLINE_DIVERSITY,
            message=msg,
        ),
        msgs,
    )


def _eval_keyword_relevance(
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str] | None,
) -> tuple[AdStrengthFactor, list[str]]:
    """Evaluate keyword relevance."""
    score, missing = _check_keyword_relevance(
        headlines,
        descriptions,
        keywords or [],
    )
    msg = f"Keyword relevance: {score:.0%}"
    suggestions: list[str] = []
    if keywords is None:
        msg += " (no keywords specified)"
    elif missing:
        suggestions.append(f"Missing keywords: {', '.join(missing[:5])}")
        msg += f" ({len(missing)} missing)"
    return (
        AdStrengthFactor(
            name="keyword_relevance",
            score=score,
            weight=_WEIGHT_KEYWORD_RELEVANCE,
            message=msg,
        ),
        suggestions,
    )


def _eval_pin_penalty(
    pinned_count: int,
) -> tuple[AdStrengthFactor, list[str]]:
    """Evaluate pin penalty."""
    score = 0.3 if pinned_count > 0 else 1.0
    msg = f"Pinned: {pinned_count}"
    suggestions: list[str] = []
    if pinned_count > 0:
        suggestions.append("Removing pins (position locking) will improve Ad Strength")
        msg += " (pinning reduces Ad Strength)"
    return (
        AdStrengthFactor(
            name="pin_penalty",
            score=score,
            weight=_WEIGHT_PIN_PENALTY,
            message=msg,
        ),
        suggestions,
    )


def _eval_sitelink_bonus(
    has_sitelinks: bool,
) -> tuple[AdStrengthFactor, list[str]]:
    """Evaluate sitelink bonus."""
    score = 1.0 if has_sitelinks else 0.5
    msg = "Sitelinks: " + ("present" if has_sitelinks else "none")
    suggestions: list[str] = []
    if not has_sitelinks:
        suggestions.append("Setting 6+ sitelinks will improve Ad Strength")
        msg += " (recommended)"
    return (
        AdStrengthFactor(
            name="sitelink_bonus",
            score=score,
            weight=_WEIGHT_SITELINK_BONUS,
            message=msg,
        ),
        suggestions,
    )


def _score_to_level(score: float) -> str:
    """Determine Ad Strength level from overall score."""
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
    """Predict ad Ad Strength (effectiveness).

    Comprehensively evaluates headline count, description count,
    diversity, keyword relevance, pinning, and sitelinks
    based on Google Ads Ad Strength criteria.
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
