<p align="center">
  <img src="docs/img/logo.png" alt="mureo" width="300">
</p>

<p align="center">
  <strong>あなたの運用ノウハウを学習する広告運用フレームワーク。</strong><br>
  AIエージェントに戦略コンテキスト、プラットフォーム横断の視点、<br>
  そしてセッションごとに蓄積する運用知識を与え、経験豊富なマーケターのように広告を運用させます。
</p>

<p align="center">
  <a href="README.md">English</a>
</p>

---

**初日** -- エージェントがGoogle広告とMeta広告をチェックし、30以上の理由コードで配信問題を診断し、オーガニック検索データと突き合わせます。手動チェックより既に網羅的です。

**30日後** -- あなたは何度かエージェントを修正しました。「そのCPA急騰は季節要因」「このアカウントは月曜にいつも落ちる」「B2Bクライアントではその指標は無視して」。すべての修正はナレッジベースに保存されています。今やエージェントはあなたより先に季節パターンを検知し、誤報をスキップし、**あなたのアカウントにとって本当に重要な問題** だけを報告します。

**これがmureoです。** AIエージェントが生のAPIアクセスだけでは得られない3つのものを手に入れます：あなたのビジネス戦略、プラットフォーム横断の視点、そして使うほど蓄積する運用ノウハウ。

---

## しくみ

### 運用ノウハウが蓄積する

ほとんどのAIツールは毎回ゼロから始まります。mureoは運用ノウハウを蓄積します。

エージェントの分析を修正したり、インサイトを共有したとき、`/learn-diagnosis` で永続的なナレッジベースに保存できます。エージェントは毎セッションの開始時にこのナレッジベースを読み込みます。あなたの修正が複利で効く -- 同じミスを二度と繰り返さず、あるキャンペーンで学んだことをアカウント全体の似た状況に適用します。

```
あなた: 「それは本当のCPA悪化じゃない。この業界はGW期間は毎年こうなる」
エージェント: 保存します。次回同じパターンを検知したら季節要因として報告します。

→ 診断ナレッジベースに記録
→ 以降の /daily-check や /rescue で自動的に考慮されます
```

これはセッション終了で消えるプロンプトメモリではありません。セッション間で永続し、時間とともに成長し、**あなたのアカウント固有の運用** にエージェントを最適化していく構造化されたナレッジファイルです。

### 戦略がファーストクラスのインプット

すべての操作は `STRATEGY.md` から始まります -- ペルソナ、USP、ブランドボイス、目標、運用モード。エージェントは指標を最適化するのではなく、あなたのビジネス目標に向かって最適化します。

```
/creative-refresh はペルソナとUSPを読んでから見出しを1本書く。
/budget-rebalance は運用モードを確認してから1円を動かす。
/rescue はゴールを照合してから何を最優先で直すか決める。
```

### プラットフォーム横断オーケストレーション

ほとんどのツールは1つのプラットフォームを自動化します。mureoはGoogle広告、Meta広告、Search Console、GA4を1つのワークフローで横断的に処理します：

- `/daily-check` -- 全プラットフォームから配信状況、広告パフォーマンス、オーガニックトレンド、サイト行動を一括取得し、相関させて1つのヘルスレポートにまとめます。
- `/search-term-cleanup` -- 有料キーワードとオーガニック順位を突き合わせ、無駄な重複を排除します。
- `/competitive-scan` -- オークションインサイトとオーガニック順位データを統合して、競合の全体像を把握します。

エージェントは設定済みプラットフォームを自動検出します。後からMeta広告を追加しても、全コマンドが自動で適応します。

### 組み込みのマーケティング知識

30以上の理由コードによるキャンペーン診断。検索語のインテント分類。予算効率スコアリング。RSA広告のバリデーションとアセット監査。ランディングページ分析。デバイス別CPAギャップ検出。経験豊富な広告運用者が頭の中に持っている知識が、すべてのワークフローに組み込まれています。

<details>
<summary>全機能一覧を展開</summary>

| 領域 | 機能 |
|------|------|
| **診断** | 30以上の配信理由コード、学習期間検出、入札戦略分類、ゼロコンバージョン原因特定 |
| **パフォーマンス** | 期間比較、コスト急騰調査、アカウント横断ヘルスチェック、CPA/CVゴール追跡 |
| **検索語** | N-gram分布、インテントパターン検出、追加/除外候補スコアリング、有料vsオーガニック重複分析 |
| **クリエイティブ** | RSAバリデーション（禁止表現、文字幅、広告の有効性予測）、アセット別パフォーマンス監査、LP分析、メッセージマッチ評価 |
| **予算** | キャンペーン横断の配分分析、再配分提案、効率スコアリング |
| **競合** | オークションインサイト、インプレッションシェアトレンド、オーガニック順位相関 |
| **Meta広告** | 配置分析（Facebook/Instagram/Audience Network）、コスト調査、A/B比較、クリエイティブ提案 |
| **モニタリング** | 配信ゴール評価、CPA/CVゴール追跡、デバイス分析、B2B向けチェック |

</details>

## ワークフローコマンド

| コマンド | 機能 |
|---------|------|
| `/onboard` | プラットフォーム検出、STRATEGY.md生成、STATE.json初期化 |
| `/daily-check` | プラットフォーム横断のヘルスチェック + オーガニック・サイト行動の相関分析 |
| `/rescue` | 緊急パフォーマンス修復：プラットフォーム側 vs サイト側の原因切り分け |
| `/search-term-cleanup` | 有料/オーガニックの重複排除を含む検索語の整理 |
| `/creative-refresh` | ペルソナ・USP・オーガニックキーワードを活用したクリエイティブ更新 |
| `/budget-rebalance` | オーガニックカバレッジを考慮した横断的な予算最適化 |
| `/competitive-scan` | 有料 + オーガニックを統合した競合分析 |
| `/goal-review` | 複数データソースを横断した目標進捗の評価と運用モード提案 |
| `/weekly-report` | プラットフォーム横断の週次運用レポート |
| `/sync-state` | STATE.jsonをライブデータから更新 |
| `/learn-diagnosis` | 診断インサイトをナレッジベースに保存（次回以降のセッションに反映） |

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

STATE.jsonからプラットフォームを検出:
  → Google広告 + Meta広告

プラットフォーム横断でデータを取得:
  → クリエイティブ監査     → Google広告で低パフォーマンス3件
  → ランディングページ分析 → 訴求点：無料トライアル、ROI改善
  → Search Console         → "広告運用自動化"がオーガニックで高クリック
  → GA4                    → 料金ページの直帰率が高い

戦略に基づいてコピーを生成:
  Google広告: "AIで広告運用時間60%削減"  ← ペルソナのペインポイント
  Meta広告:   "広告レポート地獄からの脱出..." ← ブランドボイス + SNS向けフォーマット

バリデーション後、承認を求める:
  "Google広告3件とMeta広告2件の差し替えを提案します。理由は..."

あなたが承認 → 各プラットフォームの更新を実行。
```

### 分析・ドメイン知識（組み込み）

<details>
<summary>全機能一覧を展開</summary>

**キャンペーン診断・パフォーマンス**

| 機能 | 説明 |
|------|------|
| キャンペーン診断 | 配信状態分析（30以上の理由コード）、学習期間検出、入札戦略分類 |
| パフォーマンス分析 | 期間比較、コスト増加の原因調査、アカウント全体のヘルスチェック |
| 検索語分析 | N-gram分布、インテントパターン検出、追加/除外候補の自動スコアリング |
| 予算効率 | キャンペーン横断の予算配分分析と再配分提案 |
| デバイス分析 | デバイス別のCPAギャップ検出、ゼロコンバージョンデバイス特定 |
| 競合分析 | インプレッションシェアのトレンド分析 |
| B2B最適化 | B2B業種向けのキャンペーン診断と提案 |

**クリエイティブ・ランディングページ**

| 機能 | 説明 |
|------|------|
| RSA広告バリデーション | 禁止表現検出、文字幅計算、自動修正、広告の有効性予測 |
| RSAアセット監査 | アセット単位のパフォーマンス分析と差し替え/追加提案 |
| ランディングページ分析 | HTML解析（SSRF対策付き）、CTA・特徴・価格の抽出、業種推定 |
| クリエイティブリサーチ | LP + 既存広告 + 検索語 + キーワード提案を統合したリサーチパッケージ |
| メッセージマッチ評価 | 広告コピー <-> LP の整合性スコアリング（Playwrightによるスクリーンショット対応） |

**モニタリング・ゴール評価**

| 機能 | 説明 |
|------|------|
| 配信ゴール評価 | キャンペーン状態 + 診断 + パフォーマンス -> critical / warning / healthy 分類 |
| CPA / CVゴール追跡 | 実績 vs 目標のギャップ分析、トレンド検出 |
| ゼロコンバージョン診断 | コンバージョンが発生しないキャンペーンの原因特定 |

**Meta広告分析**

| 機能 | 説明 |
|------|------|
| 配置分析 | Facebook / Instagram / Audience Network 別のパフォーマンス比較 |
| コスト調査 | CPA悪化の原因特定 |
| 広告比較 | 同一広告セット内のA/Bテスト分析 |
| クリエイティブ提案 | パフォーマンスデータに基づく改善提案 |

</details>

## クイックスタート

### Claude Code（推奨）

```bash
pip install mureo
mureo setup claude-code
```

このコマンド1つで全てが完了します：
1. Google広告 / Meta広告の認証（OAuth）
2. Claude Code用MCP設定
3. 認証情報ガード（AIエージェントによる認証ファイルの読み取りをブロック）
4. ワークフローコマンド（`/daily-check`、`/rescue`、`/learn-diagnosis` など）
5. スキル（ツールリファレンス、戦略ガイド、エビデンスベース判断、診断ナレッジ）

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

### インストール内容の比較

| コンポーネント | `mureo setup claude-code` | `mureo setup cursor` | `mureo auth setup` |
|-------------|:---:|:---:|:---:|
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
| `mureo-learning` | エビデンスベースの判断フレームワーク（観察期間、サンプルサイズ、ノイズガード） |
| `mureo-pro-diagnosis` | 学習する診断ナレッジベース（`/learn-diagnosis` で蓄積） |

### GA4（Google Analytics 4）の接続

mureoのワークフローコマンドは、GA4のMCPサーバーが接続されていればコンバージョン率やユーザー行動のデータを自動的に取り込みます。GA4は任意であり、なくても全コマンドは動作します。

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

mureoは任意のMCPサーバーと併用できます。CRMツールなどのMCPを同じセッションに追加すれば、ワークフローコマンドがそのデータも活用します。詳細は [docs/integrations.md](docs/integrations.md) を参照してください。

## 認証

### セットアップ（推奨）

```bash
mureo auth setup
```

対話型のウィザードが以下をガイドします：

1. **Google広告** — Developer Token + Client ID/Secret を入力 → ブラウザでOAuth → アカウント選択
2. **Meta広告** — App ID/Secret を入力 → ブラウザでOAuth → 広告アカウント選択。Metaアプリは**開発モードのまま**で問題ありません（App Reviewは不要です）。OAuthの際に `business_management` の権限警告が表示されますが、ビジネスポートフォリオ経由のページ管理に必要なため、そのまま承認してください。
3. **MCP設定** — Claude Code / Cursor用の設定ファイルを自動生成

認証情報は `~/.mureo/credentials.json` に保存されます。Search ConsoleはGoogle広告と同じOAuth認証を利用するため、追加の設定は不要です。

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

### 確認

```bash
mureo auth status          # 認証状態の確認
mureo auth check-google    # Google広告の認証情報を表示（マスク済み）
mureo auth check-meta      # Meta広告の認証情報を表示（マスク済み）
```

## ツール一覧

- **Google広告** — キャンペーン、広告グループ、広告、キーワード、予算、検索語、分析、RSA監査、B2B最適化、モニタリングなど
- **Meta広告** — キャンペーン、広告セット、広告、クリエイティブ、オーディエンス、Conversions API、商品カタログ、リード広告など
- **Search Console** — サイト管理、検索アナリティクス、URL検査、サイトマップ

全ツールの詳細は [英語版README](README.md#tool-list) を参照してください。

## 設計原則

- **データベース不要** — 状態は広告プラットフォームAPIまたはローカルファイルに保持
- **LLM非依存** — mureoにLLMは組み込みません。判断はエージェントの責務です
- **イミュータブルなデータモデル** — dataclass は全て `frozen=True`
- **認証情報はローカル保存** — 公式API以外には送信しません

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
