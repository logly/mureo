<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/logo-dark.png">
    <img src="docs/img/logo.png" alt="mureo" width="300">
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a>
</p>

## mureoとは

mureoは、AIエージェントが広告アカウントを自動運用するためのフレームワークです。インストールすると、AIエージェント（Claude Code、Cursorなど）がGoogle広告・Meta広告・Search Console・GA4を横断して、配信診断・検索語分析・予算評価・入稿チェックなどを実行できるようになります。すべての操作はあなたのビジネス戦略（`STRATEGY.md`）に基づいて行われます。

mureoには学習の仕組みもあります。エージェントの分析を修正したり運用上の気づきを共有すると、`/learn` でナレッジベースに保存できます。保存した知識は次回以降のセッションで自動的に読み込まれるため、使い続けるほどエージェントがあなたのアカウントの特性を理解し、より的確な判断ができるようになります。


## 特徴

### 戦略に基づいた判断

広告操作の前に、エージェントはまず `STRATEGY.md` を読みます。ペルソナ、USP、ブランドボイス、目標、運用モードなど、あなたのビジネス戦略が定義されたファイルです。数値だけを追いかけるのではなく、ビジネスの目的に沿った判断をします。

例えば `/creative-refresh` は、広告コピーを考える前にまずペルソナとUSPを確認します。`/budget-rebalance` は現在の運用モードを踏まえてから予算配分を提案します。`/rescue` はゴールの優先度に照らして、何から対処すべきかを判断します。

### 媒体横断の分析

Google広告、Meta広告、Search Console、GA4を1つのワークフローでまとめて処理します。

- `/daily-check` -- 全媒体の配信状況・広告パフォーマンス・自然検索のトレンド・サイト内行動を一括取得し、相関させて1つのレポートにまとめます。
- `/search-term-cleanup` -- 有料キーワードと自然検索の順位を突き合わせ、無駄な重複出稿を洗い出します。
- `/competitive-scan` -- オークション分析と自然検索の順位データを統合して、競合の全体像を把握します。

設定済みの媒体はエージェントが自動検出します。後からMeta広告を追加しても、全コマンドがそのまま対応します。

### 広告運用の専門知識

配信が出ない原因の自動特定（予算不足、入札設定ミス、広告の不承認など）、検索語の検索意図による分類、予算の使い方の効率評価、RSA広告の入稿チェックとアセットごとの成果分析、LPの解析、デバイス別のCPA差異の検出など、ベテラン運用者が経験で身につけている判断基準がワークフローに組み込まれています。

### 学習する運用ノウハウ

エージェントの分析を修正したり、運用で気づいたことを `/learn` でナレッジベースに保存できます。保存した知識は次回以降のセッションで自動的に読み込まれるため、同じ間違いを繰り返しません。1つのキャンペーンで得た知見が、アカウント内の似た状況にも活かされます。

```
あなた: 「それは本当のCPA悪化じゃない。この業界はGW期間は毎年こうなる」
エージェント: 保存します。次回同じパターンを検知したら季節要因として報告します。

→ ナレッジベースに記録
→ 以降の /daily-check や /rescue で自動的に考慮
```

<details>
<summary>全機能一覧を展開</summary>

| 領域 | 機能 |
|------|------|
| **診断** | 配信停止・低下の原因自動特定、学習期間の検出、入札戦略の分類、CV未発生キャンペーンの原因分析 |
| **パフォーマンス** | 期間比較、コスト急騰の原因調査、アカウント全体の健全性チェック、CPA/CV目標の進捗追跡 |
| **検索語** | N-gram分布、検索意図の分類、追加/除外候補の自動評価、有料 vs 自然検索の重複分析 |
| **クリエイティブ** | RSA入稿チェック（禁止表現、文字幅、広告の有効性予測）、アセット別の成果分析、LP解析、広告とLPの一貫性チェック |
| **予算** | キャンペーン横断の配分分析、再配分の提案、予算効率の評価 |
| **競合** | オークション分析、インプレッションシェアの推移、自然検索順位との相関 |
| **Meta広告** | 配置別分析（Facebook/Instagram/Audience Network）、コスト悪化の原因調査、A/B比較、クリエイティブ改善提案 |
| **モニタリング** | 配信目標の達成度評価、CPA/CV目標の追跡、デバイス別分析、B2B向けチェック |

</details>

## ワークフローコマンド

| コマンド | できること |
|---------|----------|
| `/onboard` | 接続媒体の検出、STRATEGY.md（戦略ファイル）の作成、STATE.json（状態ファイル）の初期化 |
| `/daily-check` | 全媒体の配信状況・成果を一括チェック。自然検索やサイト行動データがあれば相関分析も実施 |
| `/rescue` | パフォーマンス急落時の緊急対応。広告側の問題かサイト側の問題かを切り分け |
| `/search-term-cleanup` | 検索語の整理。自然検索との重複や無駄な出稿の洗い出し |
| `/creative-refresh` | ペルソナ・USP・自然検索キーワードを踏まえた広告コピーの更新 |
| `/budget-rebalance` | 自然検索でカバーできている領域を考慮した予算の再配分 |
| `/competitive-scan` | 広告と自然検索の両面から競合状況を分析 |
| `/goal-review` | 複数媒体・データソースを横断した目標進捗の評価。運用方針の変更を提案 |
| `/weekly-report` | 全媒体を横断した週次レポートの作成 |
| `/sync-state` | STATE.jsonを各媒体の最新データで更新 |
| `/learn` | 運用で得た知見をナレッジベースに保存。次回以降のセッションに自動で反映 |

### はじめ方

```bash
pip install mureo
mureo setup claude-code

# Claude Code上で：
/onboard          # 初回：戦略と状態をセットアップ
/daily-check      # 日次：全キャンペーンをチェック
/rescue           # パフォーマンス悪化時
```

### 例：`/creative-refresh` の実行フロー

```
あなた: /creative-refresh

エージェントがSTRATEGY.mdを読み込む:
  ペルソナ: "予算制約のあるSaaSマーケター"
  USP: "AIで広告運用工数を週10時間削減"
  ブランドボイス: "データ駆動、誇張なし"

STATE.jsonから接続媒体を検出:
  → Google広告 + Meta広告

各媒体・データソースからデータを取得:
  → クリエイティブ監査     → Google広告で成果の低いアセット3件
  → LP解析               → 訴求ポイント：無料トライアル、ROI改善
  → Search Console        → "広告運用自動化"が自然検索で高クリック
  → GA4                   → 料金ページの直帰率が高い

戦略に沿って広告コピーを作成:
  Google広告: "AIで広告運用時間60%削減"     ← ペルソナの課題から着想
  Meta広告:   "広告レポート地獄からの脱出..." ← ブランドボイスに合わせたSNS向けの表現

入稿チェック後、承認を求める:
  "Google広告の見出し3件とMeta広告2件の差し替えを提案します。理由は..."

あなたが承認 → 各媒体の広告を更新。
```

## クイックスタート

### 事前に必要なもの

- **Google広告** — [Google Ads API の Developer Token](https://developers.google.com/google-ads/api/docs/get-started/dev-token) と、OAuth用の Client ID / Client Secret
- **Meta広告** — [Meta for Developers](https://developers.facebook.com/) でアプリを作成し、App ID / App Secret を取得（開発モードのままで構いません）

いずれも `mureo auth setup` の対話型ウィザードが手順を案内します。

### Claude Code（推奨）

```bash
pip install mureo
mureo setup claude-code
```

このコマンド1つですべて完了します：
1. Google広告 / Meta広告の認証（OAuth）
2. Claude Code用のMCPサーバー設定
3. 認証情報ガード（AIエージェントが認証ファイルを読めないようにブロック）
4. ワークフローコマンド（`/daily-check`、`/rescue`、`/learn` など）
5. スキル（ツールリファレンス、戦略ガイド、判断の仕組み、診断ナレッジ）

セットアップ後、Claude Codeで `/onboard` を実行してください。

### Cursor

```bash
pip install mureo
mureo setup cursor
```

CursorはMCPツールを利用できますが、ワークフローコマンドとスキルには対応していません。

### CLIのみ（認証管理）

```bash
pip install mureo
mureo auth setup
mureo auth status
```

### インストール内容

| 構成要素 | `mureo setup claude-code` | `mureo setup cursor` | `mureo auth setup` |
|---------|:---:|:---:|:---:|
| 認証（~/.mureo/credentials.json） | Yes | Yes | Yes |
| MCP設定 | Yes | Yes | Yes |
| 認証情報ガード | Yes | N/A | Yes |
| ワークフローコマンド | Yes | N/A | No |
| スキル | Yes | N/A | No |

### スキル一覧

| スキル | 内容 |
|-------|------|
| `mureo-google-ads` | Google広告ツールのリファレンス |
| `mureo-meta-ads` | Meta広告ツールのリファレンス |
| `mureo-shared` | 認証、セキュリティルール、出力フォーマット |
| `mureo-strategy` | STRATEGY.md / STATE.json の仕様と使い方 |
| `mureo-workflows` | 運用モード、KPI閾値、コマンドリファレンス |
| `mureo-learning` | データに基づく判断の仕組み（観察期間、サンプルサイズ、ノイズの排除） |
| `mureo-pro-diagnosis` | 運用で蓄積するナレッジベース（`/learn` で記録） |

### GA4（Google Analytics 4）の接続

GA4のMCPサーバーを接続すると、ワークフローコマンドがコンバージョン率やユーザー行動のデータも自動で取り込みます。GA4がなくても全コマンドは動作します。

[Google Analytics MCP](https://github.com/googleanalytics/google-analytics-mcp) を使ったセットアップ手順：

1. GCPプロジェクトで以下のAPIを有効化（リンクをクリックして「有効にする」）：
   - [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com)
   - [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com)

2. インストールと認証：

   ```bash
   pipx install analytics-mcp

   gcloud auth application-default login \
     --scopes https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform
   ```

3. `~/.claude/settings.json` にmureoと並列で追加：

   ```json
   {
     "mcpServers": {
       "mureo": {
         "command": "python",
         "args": ["-m", "mureo.mcp"]
       },
       "analytics-mcp": {
         "command": "pipx",
         "args": ["run", "analytics-mcp"],
         "env": {
           "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/application_default_credentials.json",
           "GOOGLE_PROJECT_ID": "your-gcp-project-id"
         }
       }
     }
   }
   ```

### その他のMCPサーバー

mureoは他のMCPサーバーと併用できます。CRMツールなどのMCPを同じセッションに追加すれば、ワークフローコマンドがそのデータも活用します。詳細は [docs/integrations.md](docs/integrations.md) を参照してください。

## 認証

### セットアップ（推奨）

```bash
mureo auth setup
```

対話型のウィザードが案内します：

1. **Google広告** — Developer Token + Client ID/Secret を入力 → ブラウザでOAuth → アカウント選択
2. **Meta広告** — App ID/Secret を入力 → ブラウザでOAuth → 広告アカウント選択。Metaアプリは**開発モードのまま**で問題ありません（App Reviewは不要です）。OAuthの際に `business_management` の権限警告が表示されますが、ビジネスポートフォリオ経由のページ管理に必要なため、そのまま承認してください。
3. **MCP設定** — Claude Code / Cursor用の設定ファイルを自動生成

認証情報は `~/.mureo/credentials.json` に保存されます。Search ConsoleはGoogle広告と同じOAuth認証を使うため、追加の設定は不要です。

### 環境変数（代替手段）

| 媒体 | 変数 | 必須 |
|------|------|-----|
| Google広告 | `GOOGLE_ADS_DEVELOPER_TOKEN` | はい |
| Google広告 | `GOOGLE_ADS_CLIENT_ID` | はい |
| Google広告 | `GOOGLE_ADS_CLIENT_SECRET` | はい |
| Google広告 | `GOOGLE_ADS_REFRESH_TOKEN` | はい |
| Google広告 | `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | いいえ |
| Meta広告 | `META_ADS_ACCESS_TOKEN` | はい |
| Meta広告 | `META_ADS_APP_ID` | いいえ |
| Meta広告 | `META_ADS_APP_SECRET` | いいえ |

### 確認

```bash
mureo auth status          # 認証状態の確認
mureo auth check-google    # Google広告の認証情報を表示（マスク済み）
mureo auth check-meta      # Meta広告の認証情報を表示（マスク済み）
```

## ツール一覧

- **Google広告** — キャンペーン（検索/ディスプレイ）、広告グループ、検索広告（RSA）、ディスプレイ広告（RDA）、キーワード、予算、検索語、分析、RSA監査、B2B最適化、モニタリングなど
- **Meta広告** — キャンペーン、広告セット、広告、クリエイティブ、オーディエンス、Conversions API、商品カタログ、リード広告など
- **Search Console** — サイト管理、検索アナリティクス、URL検査、サイトマップ

全ツールの詳細は [英語版README](README.md#tool-list) を参照してください。

## 設計方針

- **データベース不要** — 状態は広告プラットフォームのAPIまたはローカルファイルに保持
- **LLMを内蔵しない** — mureoはデータの取得と分析を担当し、判断はエージェント側が行います
- **データは不変** — すべてのデータモデルで `frozen=True` を使用し、意図しない変更を防止
- **認証情報はローカルに保存** — 公式の広告プラットフォームAPI以外には一切送信しません

ディレクトリ構造の詳細は [docs/architecture.md](docs/architecture.md) を参照してください。

## 開発

```bash
git clone https://github.com/logly/mureo.git && cd mureo
pip install -e ".[dev]"
pytest tests/ -v                              # テスト実行
pytest --cov=mureo --cov-report=term-missing  # カバレッジ付き
ruff check mureo/ && black mureo/ && mypy mureo/  # lint & format
```

Python 3.10以上が必要です。詳細は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

## ライセンス

Apache License 2.0
