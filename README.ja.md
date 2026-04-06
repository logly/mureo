<p align="center">
  <img src="docs/img/logo.png" alt="mureo" width="300">
</p>

<p align="center">
  AIエージェントのためのマーケティングオーケストレーションフレームワーク
</p>

<p align="center">
  <a href="README.md">English</a>
</p>

## mureoとは

**mureo** は、AIエージェントが単なるAPI呼び出しではなく、実際のビジネス目標 — 認知獲得、リード獲得、売上、継続率 — を達成することを支援するマーケティングオーケストレーションフレームワークです。戦略コンテキスト、ワークフローコマンド、ビルトインのドメイン知識を組み合わせ、エージェントが複数のプラットフォームをまたいだマーケティング運用を実行できるようガイドします。

広告プラットフォームのAPIは今後、Google・Metaなど各社の公式MCPから提供されるようになります。mureoの価値はそれらAPIのラッパーにあるのではなく、**その上のオーケストレーション層** — ビジネス戦略に基づいて *何を、いつ、なぜ* すべきかを知ること — にあります。

- **戦略駆動** — `STRATEGY.md` にペルソナ、USP、ブランドボイス、目標、運用モードを定義します。エージェントの全ての判断は、単なる数値ではなくあなたの戦略に基づきます。
- **ワークフローコマンド** — 10個のスラッシュコマンド（`/daily-check`、`/rescue`、`/creative-refresh` など）がエージェントをマーケティング運用全体へガイドします。戦略コンテキストと適切なツールを、適切な順序で連携させます。
- **クロスプラットフォーム** — Google広告、Meta広告、Search Console、GA4（今後さらに追加予定）を横断してオーケストレートし、単一プラットフォームのツールでは不可能な協調的な意思決定を実現します。
- **ビルトインのドメイン知識** — 生のAPIデータを実行可能なインサイトに変換する分析・診断・最適化ロジック。30種類以上の理由コードによるキャンペーン診断、検索語インテント分析、予算効率スコアリング、RSAバリデーションなど。
- **MCP + CLI インターフェース** — AIエージェント（Claude Code、Cursor など）向けに169個のMCPツール、加えてスクリプトや簡易チェック向けのCLIを提供します。
- **DB不要・LLM非依存** — mureoはエージェントの「手」であり「脳」ではありません。状態は全てローカルファイル（`STRATEGY.md`、`STATE.json`）または広告プラットフォーム自体にあり、判断は全てエージェント側に残ります。

### 分析・診断

| 機能 | 説明 |
|------|------|
| **キャンペーン診断** | 30以上の理由コードによる配信状態分析、学習期間検出、スマート入札戦略の分類 |
| **パフォーマンス分析** | 期間比較、コスト増加調査、クロスキャンペーンのヘルスチェック |
| **検索語分析** | N-gram分布、インテントパターン検出、追加/除外候補の自動スコアリング |
| **予算効率** | クロスキャンペーンの予算配分分析と再配分提案 |
| **RSA広告バリデーション** | 禁止表現検出、文字幅計算、自動修正、広告の有効性予測 |
| **RSAアセット監査** | アセット単位のパフォーマンス分析、差し替え/追加提案 |
| **デバイス分析** | CPAギャップ検出、ゼロコンバージョンデバイスの特定 |
| **オークションインサイト** | 競合状況分析、インプレッションシェアのトレンド |
| **B2B最適化** | 業種別のキャンペーンチェックと提案 |

### クリエイティブ・ランディングページ

| 機能 | 説明 |
|------|------|
| **ランディングページ分析** | SSRF対策付きHTML解析、構造化データ抽出、業種推定、CTA/特徴/価格の検出 |
| **クリエイティブリサーチ** | LP分析・既存広告・検索語・キーワード提案を統合したリサーチパッケージ |
| **メッセージマッチ評価** | 広告コピーとランディングページの整合性スコアリング（Playwrightによるスクリーンショット取得） |

### モニタリング・ゴール評価

| 機能 | 説明 |
|------|------|
| **配信ゴール評価** | キャンペーン状態・診断・パフォーマンスを統合し、critical/warning/healthyに分類 |
| **CPAゴール追跡** | 実績CPAと目標の比較、トレンド分析 |
| **CVゴール追跡** | 日次コンバージョン量の目標比較 |
| **ゼロコンバージョン診断** | コンバージョンゼロのキャンペーンの原因分析 |

### Meta広告分析

| 機能 | 説明 |
|------|------|
| **配置分析** | パブリッシャープラットフォーム別（Facebook、Instagram、Audience Network）のパフォーマンス |
| **コスト調査** | CPA悪化の原因分析 |
| **広告比較** | 広告セット内のA/B性能比較 |
| **クリエイティブ提案** | データに基づくクリエイティブ改善の提案 |
| **PIIハッシュ化** | Conversions API準拠のフィールド別正規化付きSHA-256ハッシュ |

### インフラ

| 機能 | 説明 |
|------|------|
| **レート制限** | トークンバケット+時間あたり上限で、高速エージェントリクエストによるAPI BANを防止 |
| **トークン自動更新** | Meta広告のLong-Lived Tokenを60日期限前に自動更新 |
| **戦略コンテキスト** | Markdown形式の戦略永続化（STRATEGY.md）+ JSON形式のキャンペーン状態（STATE.json） |
| **画像・動画バリデーション** | パストラバーサル防止、拡張子ホワイトリスト、アップロードサイズ制限 |

## ワークフローコマンド

個々のMCPツールに加えて、mureoはClaude Code向けに **10個のスラッシュコマンド** を提供します。これらはあなたの戦略（`STRATEGY.md`）と169個のMCPツールを繋ぎ、戦略駆動のマーケティング運用を可能にします。

### 仕組み

コマンドは **プラットフォーム非依存のオーケストレーション指示書** です。どのツールを呼ぶかをハードコードしません。各コマンドはAIエージェントに対して以下を指示します：

1. **プラットフォーム検出** — STATE.jsonを読み、どのプラットフォームが設定されているか確認
2. **ツール選択** — 検出した各プラットフォームに対し、適切なMCPツールを選ぶ
3. **データソース相関** — 広告プラットフォームのデータに、Search Console（有機検索）やGA4（サイト内行動）が利用可能なら組み合わせる
4. **インサイト統合** — 統一されたクロスプラットフォームの推奨を生成
5. **実行前に確認** — 書き込み操作は必ずユーザーの承認を得る

この設計により、新プラットフォーム（例：TikTok広告）を追加してもコマンドの書き換えは不要です。エージェントが設定内容に応じて自動的に適応します。

3つのレイヤーが協調して動きます：

| レイヤー | 役割 | 例（`/creative-refresh`） |
|---------|------|--------------------------|
| **mureo（MCPツール）** | データ取得、分析、バリデーション | 全プラットフォームのクリエイティブ監査、LP分析、テキストバリデーション |
| **AIエージェント（LLM）** | プラットフォーム検出、ツール選択、クリエイティブ生成 | 設定プラットフォームの検出、ペルソナ+USPに沿ったクリエイティブの作成 |
| **あなた（人間）** | 最終承認 | 変更前のレビューと承認 |

### コマンド一覧

| コマンド | 用途 | データソース |
|---------|------|------------|
| `/onboard` | プラットフォーム検出、STRATEGY.md生成、STATE.json初期化 | 全ての設定済み |
| `/daily-check` | クロスプラットフォームのヘルスチェック + 有機検索パルス + サイト行動相関 | 広告プラットフォーム + Search Console + GA4 |
| `/rescue` | 緊急パフォーマンス修復、サイト側 vs 広告側の切り分け診断 | 広告プラットフォーム + GA4 |
| `/search-term-cleanup` | 有料/有機キーワード重複分析を含むキーワードクリーンアップ | 広告プラットフォーム + Search Console + GA4 |
| `/creative-refresh` | マルチプラットフォームのクリエイティブ更新、有機キーワードからの着想 | 広告プラットフォーム + Search Console + GA4 |
| `/budget-rebalance` | 有機カバレッジを考慮したクロスプラットフォーム予算最適化 | 広告プラットフォーム + Search Console + GA4 |
| `/competitive-scan` | 有料 + 有機の統合競合分析 | 広告プラットフォーム + Search Console + GA4 |
| `/goal-review` | マルチソースによる目標進捗評価 | 全プラットフォーム + 全データソース |
| `/weekly-report` | クロスプラットフォームの週次運用レポート | 全プラットフォーム + 全データソース |
| `/sync-state` | マルチプラットフォームSTATE.json同期 | 全ての設定済み |

### はじめ方

最初に `/onboard` を実行してアカウント設定とSTRATEGY.md生成を行います。その後は `/daily-check` で日次モニタリングを行います。

```
# Claude Code上で
/onboard          # 初回：戦略と状態をセットアップ
/daily-check      # 日常：全キャンペーンをチェック
/rescue           # パフォーマンス悪化時
```

### 例：`/creative-refresh` のフロー

```
あなた: /creative-refresh

エージェントがSTRATEGY.mdを読む:
  ペルソナ: "予算制約のあるSaaSマーケター"
  USP: "AIで広告運用工数を週10時間削減"
  ブランドボイス: "データ駆動、誇張なし"
  データソース: Google広告、Meta広告、Search Console、GA4

エージェントがSTATE.jsonから設定済みプラットフォームを検出:
  → Google広告 + Meta広告

エージェントが各プラットフォーム・データソースのツールを呼び出す:
  → 各広告プラットフォームのクリエイティブ監査 → 低パフォーマンス資産3件
  → ランディングページ分析 → LPの訴求点：無料トライアル、ROI改善
  → Search Console上位クエリ → "広告運用自動化"がオーガニックで高クリック
  → GA4 LPエンゲージメント → 料金ページのバウンス率が高い

エージェント（LLM）がプラットフォーム別にコピーを生成:
  Google広告（検索）: "AIで広告運用時間60%削減"      ← ペルソナの痛み
  Google広告（検索）: "無料トライアル | 広告自動化"   ← LP + 有機キーワード
  Meta広告（ソーシャル）: "広告レポート地獄からの脱出..."  ← ブランドボイス + ソーシャル向け

エージェントが各プラットフォームのバリデーションツールを実行。

エージェントがプラットフォーム別に承認を求める:
  "Google広告3件とMeta広告2件の差し替えを提案します。理由は..."

あなたが承認 → エージェントが各プラットフォームの更新ツールを呼び出す。
```

コマンドは戦略コンテキスト（運用モード、ペルソナ、USP、ブランドボイス、市場コンテキスト）を使って挙動を調整します。運用モードの詳細は [skills/mureo-workflows/SKILL.md](skills/mureo-workflows/SKILL.md) を参照してください。

## クイックスタート

### Claude Code（推奨）

```bash
pip install "mureo[cli,mcp]"
mureo setup claude-code
```

このコマンド1つで全てが完了します：
1. Google広告 / Meta広告の認証（OAuth）
2. Claude Code用MCP設定
3. 認証情報ガード（AIエージェントによるシークレット読み取りをブロック）
4. 10個のワークフローコマンド（`/daily-check`、`/rescue` など）
5. 6個のスキル（ツールリファレンス、戦略ガイド、エビデンスベース判断）

セットアップ後、Claude Codeで `/onboard` を実行して開始します。

### Cursor

```bash
pip install "mureo[cli,mcp]"
mureo setup cursor
```

CursorはMCPツール（169ツール）をサポートしますが、ワークフローコマンドとスキルには対応していません。

### CLIのみ

```bash
pip install "mureo[cli]"
mureo auth setup
mureo google-ads campaigns-list --customer-id 1234567890
```

### インストール内容の比較

| コンポーネント | `mureo setup claude-code` | `mureo setup cursor` | `mureo auth setup` |
|-------------|:---:|:---:|:---:|
| 認証（~/.mureo/credentials.json） | Yes | Yes | Yes |
| MCP設定 | Yes | Yes | Yes |
| 認証情報ガード（PreToolUseフック） | Yes | N/A | Yes |
| 10ワークフローコマンド（~/.claude/commands/） | Yes | N/A | No |
| 6スキル（~/.claude/skills/） | Yes | N/A | No |

### スキル一覧

| スキル | 用途 |
|-------|------|
| `mureo-google-ads` | Google広告ツールリファレンス（82ツール、パラメータ、例） |
| `mureo-meta-ads` | Meta広告ツールリファレンス（77ツール、パラメータ、例） |
| `mureo-shared` | 認証、セキュリティルール、出力フォーマット |
| `mureo-strategy` | STRATEGY.md / STATE.json のフォーマットと使い方 |
| `mureo-workflows` | オーケストレーションパラダイム、運用モードマトリクス、KPI閾値、コマンドリファレンス |
| `mureo-learning` | エビデンスベースのマーケティング判断フレームワーク（観察期間、サンプルサイズ、ノイズガード） |

### 追加のMCPサーバー接続

mureoは同じクライアントセッション内で他のMCPサーバー（GA4、CRMツール）と併用できます。`.mcp.json` に追加するだけで、ワークフローコマンドがそれらのデータを機会的に取り込みます。詳細は [docs/integrations.md](docs/integrations.md) を参照してください。

## 認証

### 対話型セットアップ（推奨）

```bash
mureo auth setup
```

セットアップウィザードは以下をガイドします：

1. **Google広告** — Developer Token + Client ID/Secret を入力、ブラウザでOAuth、Google広告アカウントを選択
2. **Meta広告** — App ID/Secret を入力、ブラウザでOAuth、Long-Lived Token を取得、広告アカウントを選択
3. **MCP設定** — `.mcp.json`（プロジェクト単位）または `~/.claude/settings.json`（グローバル）を自動生成

認証情報は `~/.mureo/credentials.json` に保存されます。Search ConsoleはGoogle広告と同じGoogle OAuth2認証情報を利用するため、追加認証は不要です。

### 環境変数（フォールバック）

| プラットフォーム | 変数 | 必須 |
|----------------|------|-----|
| Google広告 | `GOOGLE_ADS_DEVELOPER_TOKEN` | はい |
| Google広告 | `GOOGLE_ADS_CLIENT_ID` | はい |
| Google広告 | `GOOGLE_ADS_CLIENT_SECRET` | はい |
| Google広告 | `GOOGLE_ADS_REFRESH_TOKEN` | はい |
| Google広告 | `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | いいえ |
| Meta広告 | `META_ADS_ACCESS_TOKEN` | はい |
| Meta広告 | `META_ADS_APP_ID` | いいえ |
| Meta広告 | `META_ADS_APP_SECRET` | いいえ |

セットアップの確認：

```bash
mureo auth status
mureo auth check-google
mureo auth check-meta
```

## MCPサーバー

### Claude Codeでのセットアップ

**プロジェクトレベル**（推奨）— プロジェクトルートの `.mcp.json` に追加：

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

**グローバル** — `~/.claude/settings.json` に追加：

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

> ヒント：`mureo auth setup` でこの設定を自動生成できます。

### Cursorでのセットアップ

`.cursor/mcp.json` に追加：

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

### ツール一覧（169ツール）

- **Google広告：82ツール** — キャンペーン、広告グループ、広告、キーワード、予算、検索語、分析、RSA監査、B2B最適化、モニタリングなど
- **Meta広告：77ツール** — キャンペーン、広告セット、広告、クリエイティブ、オーディエンス、Conversions API、商品カタログ、リード広告など
- **Search Console：10ツール** — サイト管理、検索アナリティクス、URL検査、サイトマップ

完全なツール一覧は [英語版README](README.md#tool-list-169-tools) を参照してください。

## CLI

```bash
mureo google-ads campaigns-list --customer-id 1234567890
mureo meta-ads campaigns-list --account-id act_1234567890
mureo auth setup   # 対話型OAuthウィザード
```

## 戦略コンテキスト

2つのローカルファイルが戦略を意識した運用を駆動します。`/onboard` を実行すると対話型に生成されます。

- **STRATEGY.md** — ペルソナ、USP、ブランドボイス、目標、運用モード。詳細は [docs/strategy-context.md](docs/strategy-context.md)。
- **STATE.json** — キャンペーンスナップショット、アクションログ。ワークフローコマンドにより自動更新されます。

## アーキテクチャ

設計原則：

- **データベース不要** — 全ての状態は広告プラットフォームAPIまたはローカルファイル（`STRATEGY.md`、`STATE.json`）にあります。
- **LLM非依存** — mureoはLLMを埋め込みません。推論・計画・意思決定はエージェントの責務です。
- **イミュータブルなデータモデル** — 全てのdataclassに `frozen=True` を使用し、偶発的なミューテーションを防止。
- **認証情報はローカルに保存** — `~/.mureo/credentials.json` または環境変数から読み込み。公式広告プラットフォームAPI以外には送信しません。

ディレクトリ構造の詳細は [英語版README](README.md#architecture) および [docs/architecture.md](docs/architecture.md) を参照してください。

## 開発

```bash
git clone https://github.com/logly/mureo.git && cd mureo
pip install -e ".[dev,cli,mcp]"
pytest tests/ -v                              # テスト実行
pytest --cov=mureo --cov-report=term-missing  # カバレッジ付き
ruff check mureo/ && black mureo/ && mypy mureo/  # lint & format
```

Python 3.10以上が必要です。開発ガイドライン全般は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## ライセンス

Apache License 2.0
