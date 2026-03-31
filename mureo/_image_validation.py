"""メディアファイルアップロード共通バリデーション

Meta Ads / Google Ads 両方で使用するファイル検証ロジック（画像・動画対応）。
"""

from __future__ import annotations

from pathlib import Path


def _validate_media_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
    media_type_label: str,
) -> Path:
    """メディアファイルの入力バリデーションを実行する（画像・動画共通）。

    Args:
        file_path: ローカルファイルのパス
        max_size_bytes: ファイルサイズ上限（バイト）
        max_size_label: エラーメッセージ用のサイズ表示（例: "30MB"）
        allowed_extensions: 許可する拡張子の集合（小文字、ドットなし）
        media_type_label: エラーメッセージ用のメディア種別（例: "画像", "動画"）

    Returns:
        検証済みのPathオブジェクト

    Raises:
        ValueError: パストラバーサル、未対応形式、サイズ超過
        FileNotFoundError: ファイルが存在しない
    """
    # パストラバーサル防止（..チェック + resolve()で正規化）
    if ".." in file_path:
        raise ValueError(f"不正なファイルパス: パスに '..' を含めることはできません: {file_path}")

    path = Path(file_path)

    # ファイル存在チェック
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {file_path}")

    # シンボリックリンク解決後に通常ファイルであることを確認
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"不正なファイルパス: 通常のファイルではありません: {file_path}")

    # 拡張子チェック
    ext = path.suffix.lower().lstrip(".")
    if ext not in allowed_extensions:
        allowed_str = ", ".join(sorted(allowed_extensions))
        raise ValueError(
            f"対応していない{media_type_label}形式です: .{ext} "
            f"(対応形式: {allowed_str})"
        )

    # ファイルサイズチェック
    size = path.stat().st_size
    if size > max_size_bytes:
        raise ValueError(
            f"ファイルサイズが上限を超えています: "
            f"{size:,} bytes (上限: {max_size_label})"
        )

    return path


def validate_image_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
) -> Path:
    """画像ファイルの入力バリデーションを実行する。

    Args:
        file_path: ローカル画像ファイルのパス
        max_size_bytes: ファイルサイズ上限（バイト）
        max_size_label: エラーメッセージ用のサイズ表示（例: "30MB"）
        allowed_extensions: 許可する拡張子の集合（小文字、ドットなし）

    Returns:
        検証済みのPathオブジェクト

    Raises:
        ValueError: パストラバーサル、未対応形式、サイズ超過
        FileNotFoundError: ファイルが存在しない
    """
    return _validate_media_file(
        file_path,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
        allowed_extensions=allowed_extensions,
        media_type_label="画像",
    )


def validate_video_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
) -> Path:
    """動画ファイルの入力バリデーションを実行する。

    Args:
        file_path: ローカル動画ファイルのパス
        max_size_bytes: ファイルサイズ上限（バイト）
        max_size_label: エラーメッセージ用のサイズ表示（例: "100MB"）
        allowed_extensions: 許可する拡張子の集合（小文字、ドットなし）

    Returns:
        検証済みのPathオブジェクト

    Raises:
        ValueError: パストラバーサル、未対応形式、サイズ超過
        FileNotFoundError: ファイルが存在しない
    """
    return _validate_media_file(
        file_path,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
        allowed_extensions=allowed_extensions,
        media_type_label="動画",
    )
