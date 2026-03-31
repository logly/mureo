"""Meta Ads Conversions API ハッシュ化ユーティリティ

Meta CAPI では em(email), ph(phone), fn(名), ln(姓) 等の
個人情報フィールドを SHA-256 でハッシュ化して送信する必要がある。
"""
from __future__ import annotations

import hashlib
import re

# ハッシュ化対象の PII フィールド
# em, ph は個別ロジック（メール正規化・電話番号数字抽出）を適用
# その他は lowercase + strip で正規化
_PII_FIELDS_LOWERCASE: frozenset[str] = frozenset(
    {"em", "ph", "fn", "ln", "ct", "st", "zp", "country", "db", "ge"}
)

# 非 PII フィールド（ハッシュ化しない）
_NON_PII_FIELDS: frozenset[str] = frozenset(
    {
        "client_ip_address",
        "client_user_agent",
        "fbc",
        "fbp",
        "external_id",
        "subscription_id",
        "lead_id",
    }
)

# SHA-256 ハッシュ値の正規表現（64 文字の 16 進数）
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _is_already_hashed(value: str) -> bool:
    """値が既に SHA-256 ハッシュ済みかどうかを判定する"""
    return bool(_SHA256_PATTERN.match(value))


def _sha256(value: str) -> str:
    """文字列を SHA-256 でハッシュ化する"""
    return hashlib.sha256(value.encode()).hexdigest()


def hash_email(email: str) -> str:
    """メールアドレスを SHA-256 ハッシュ化する

    Meta API 要件:
    - 前後の空白を除去
    - 小文字に変換
    - SHA-256 でハッシュ化

    Args:
        email: メールアドレス（平文）

    Returns:
        SHA-256 ハッシュ値（64 文字の 16 進数）
    """
    normalized = email.strip().lower()
    return _sha256(normalized)


def hash_phone(phone: str) -> str:
    """電話番号を SHA-256 ハッシュ化する

    Meta API 要件:
    - 数字以外の文字（ハイフン、スペース、括弧、+）を除去
    - SHA-256 でハッシュ化

    Args:
        phone: 電話番号（平文、国コード付き可）

    Returns:
        SHA-256 ハッシュ値（64 文字の 16 進数）
    """
    digits_only = re.sub(r"[^\d]", "", phone)
    return _sha256(digits_only)


def _hash_pii_value(key: str, value: str) -> str:
    """PII フィールドの値をハッシュ化する

    em は hash_email、ph は hash_phone、その他は lowercase + SHA-256。
    既にハッシュ済みの場合はそのまま返す。
    """
    if _is_already_hashed(value):
        return value

    if key == "em":
        return hash_email(value)
    if key == "ph":
        return hash_phone(value)

    # fn, ln, ct, st, zp, country, db, ge: lowercase + strip + hash
    return _sha256(value.strip().lower())


def normalize_user_data(user_data: dict[str, object]) -> dict[str, object]:
    """user_data の個人情報フィールドを自動ハッシュ化する

    Meta Conversions API に送信する user_data 辞書内の PII フィールドを
    SHA-256 でハッシュ化する。既にハッシュ済みの値はスキップする。

    Args:
        user_data: user_data 辞書

    Returns:
        PII フィールドがハッシュ化された新しい辞書（元の辞書は変更しない）
    """
    result: dict[str, object] = {}

    for key, value in user_data.items():
        if key in _NON_PII_FIELDS or key not in _PII_FIELDS_LOWERCASE:
            result[key] = value
            continue

        if isinstance(value, list):
            result[key] = [
                _hash_pii_value(key, v) if isinstance(v, str) else v
                for v in value
            ]
        elif isinstance(value, str):
            result[key] = _hash_pii_value(key, value)
        else:
            result[key] = value

    return result
