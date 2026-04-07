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

**mureo** は、AIエージェントがマーケティングの目標達成 — 認知獲得、リード獲得、売上向上、リテンション改善 — に向けて自律的に動けるようにするフレームワークです。

ビジネス戦略をもとに、何を・いつ・なぜすべきかをエージェントに判断させるオーケストレーション層を提供します。将来、GoogleやMetaが公式MCPサーバーを提供した場合には、そちらへの切り替えも可能です。mureoの価値はAPIラッパーではなく、その上にある **戦略とオーケストレーション** にあります。

- **戦略に基づく判断** — `STRATEGY.md` にペルソナ・USP・ブランドボイス・目標・運用モードを定義。エージェントは数値だけでなく、あなたのビジネス戦略に基づいて判断します。
- **10個のワークフローコマンド** — `/daily-check`、`/rescue`、`/creative-refresh` などのスラッシュコマンドが、戦略と適切なツールを正しい順序で連携させ、マーケティング運用全体をガイドします。
- **プラットフォーム横断** — Google広告、Meta広告、Search Console、GA4を横断してオーケストレート。単一ツールでは不可能な、統合的な判断を可能にします。
- **分析・診断のドメイン知識を内蔵** — 30以上の理由コードによるキャンペーン診断、検索語のインテント分析、予算効率スコアリング、RSA広告バリデーションなど、APIの生データを実行可能なインサイトに変換します。
- **169個のMCPツール** — Claude Code、Cursorなど、MCPに対応したAIエージェントから利用できます。CLIはセットアップと認証管理専用です。
- **データベース不要・LLM非依存** — mureoはエージェントの「手」であり「脳」ではありません。状態は全てローカルファイル（`STRATEGY.md`、`STATE.json`）に保持され、判断はエージェント側に委ねられます。

### 分析・診断機能

| 機能 | 説明 |
|------|------|
| **キャンペーン診断** | 配信状態の分析（30以上の理由コード）、学習期間の検出、入札戦略の分類 |
| **パフォーマンス分析** | 期間比較、コスト増加の原因調査、アカウント全体のヘルスチェック |
| **検索語分析** | N-gram分布、インテントパターンの検出、追加/除外候補の自動スコアリング |
| **予算効率** | キャンペーン横断の予算配分分析と再配分の提案 |
| **RSA広告バリデーション** | 禁止表現の検出、文字幅の計算、自動修正、広告の有効性予測 |
| **RSAアセット監査** | アセット単位のパフォーマンス分析と差し替え/追加提案 |
| **デバイス分析** | デバイス別のCPAギャップ検出、コンバージョンゼロのデバイス特定 |
| **競合分析** | インプレッションシェアのトレンド分析 |
| **B2B最適化** | B2B業種向けのキャンペーン診断と提案 |

### クリエイティブ・ランディングページ

| 機能 | 説明 |
|------|------|
| **ランディングページ分析** | HTML解析（SSRF対策付き）、CTA・特徴・価格の抽出、業種推定 |
| **クリエイティブリサーチ** | LP・既存広告・検索語・キーワード提案を統合したリサーチ |
| **メッセージマッチ評価** | 広告コピーとLPの整合性チェック |

### モニタリング・ゴール評価

| 機能 | 説明 |
|------|------|
| **配信ゴール評価** | キャンペーンの状態を critical / warning / healthy に分類 |
| **CPA / CV ゴール追跡** | 実績と目標のギャップ分析、トレンド検出 |
| **ゼロコンバージョン診断** | コンバージョンが発生しないキャンペーンの原因特定 |

### Meta広告分析

| 機能 | 説明 |
|------|------|
| **配置分析** | Facebook / Instagram / Audience Network 別のパフォーマンス比較 |
| **コスト調査** | CPA悪化の原因特定 |
| **広告比較** | 同一広告セット内のA/Bテスト分析 |
| **クリエイティブ提案** | パフォーマンスデータに基づく改善提案 |
| **PIIハッシュ化** | Conversions API向けの個人情報ハッシュ処理 |

### インフラ

| 機能 | 説明 |
|------|------|
| **レート制限** | トークンバケット+時間あたり上限でAPI BANを防止 |
| **Meta トークン自動更新** | Long-Lived Tokenの期限切れ前に自動で延長 |
| **戦略コンテキスト** | STRATEGY.md（Markdown）+ STATE.json でファイルベースに状態管理 |
| **セキュリティ** | パストラバーサル防止、拡張子ホワイトリスト、認証情報ガード |

## ワークフローコマンド

mureoはClaude Code向けに10個のスラッシュコマンドを提供します。各コマンドは戦略ファイル（`STRATEGY.md`）を読み込んだ上で、169個のMCPツールから必要なものを自動選択して実行します。

### コマンドの動作原理

コマンドは特定のツールをハードコードしません。エージェントに対して「何をすべきか」を指示し、ツールの選択はエージェントが判断します。

1. STATE.jsonから設定済みプラットフォームを検出
2. 各プラットフォームに適したMCPツールを選択・実行
3. Search Console（自然検索）やGA4（サイト行動）のデータがあれば統合
4. クロスプラットフォームで統一されたインサイトを生成
5. 書き込み操作は必ずユーザーの承認を得てから実行

| レイヤー | 役割 | 例（`/creative-refresh`） |
|---------|------|--------------------------|
| **mureo** | データ取得、分析、バリデーション | 全プラットフォームのクリエイティブ監査、LP分析 |
| **AIエージェント** | ツール選択、判断、生成 | ペルソナ+USPに沿ったクリエイティブの作成 |
| **あなた** | 最終承認 | 変更内容のレビューと承認 |

### コマンド一覧

| コマンド | 用途 | データソース |
|---------|------|------------|
| `/onboard` | 初期セットアップ（戦略定義、アカウント接続） | 全プラットフォーム |
| `/daily-check` | 日次のヘルスチェック + 自然検索・サイト行動の相関分析 | 広告 + Search Console + GA4 |
| `/rescue` | パフォーマンス悪化時の緊急対応 | 広告 + GA4 |
| `/search-term-cleanup` | 検索語の整理（有料/自然の重複分析を含む） | 広告 + Search Console + GA4 |
| `/creative-refresh` | クリエイティブの更新（自然検索キーワードも活用） | 広告 + Search Console + GA4 |
| `/budget-rebalance` | 自然検索カバレッジを考慮した予算の再配分 | 広告 + Search Console + GA4 |
| `/competitive-scan` | 有料・自然を統合した競合分析 | 広告 + Search Console + GA4 |
| `/goal-review` | 複数データソースを横断した目標進捗の評価 | 全データソース |
| `/weekly-report` | 週次の運用レポート | 全データソース |
| `/sync-state` | STATE.jsonの手動同期 | 全プラットフォーム |

### はじめ方

```
# Claude Code上で
/onboard          # 初回：戦略と状態をセットアップ
/daily-check      # 日常：全キャンペーンをチェック
/rescue           # パフォーマンス悪化時
```

### 例：`/creative-refresh` のフロー

```
あなた: /creative-refresh

エージェントがSTRATEGY.mdを読み込む:
  ペルソナ: "予算制約のあるSaaSマーケター"
  USP: "AIで広告運用工数を週10時間削減"
  ブランドボイス: "データ駆動、誇張なし"

エージェントがSTATE.jsonからプラットフォームを検出:
  → Google広告 + Meta広告

各ツール・データソースを呼び出す:
  → 各広告プラットフォームのクリエイティブ監査 → 低パフォーマンス3件
  → LP分析 → 訴求点：無料トライアル、ROI改善
  → Search Console → "広告運用自動化"がオーガニックで高クリック
  → GA4 → 料金ページの直帰率が高い

プラットフォーム別にコピーを生成:
  Google広告: "AIで広告運用時間60%削減"
  Meta広告: "広告レポート地獄からの脱出..."

バリデーション後、承認を求める:
  "Google広告3件とMeta広告2件の差し替えを提案します。理由は..."

あなたが承認 → 各プラットフォームの更新ツールを実行。
```

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
4. 10個のワークフローコマンド
5. 6個のスキル（ツールリファレンス、戦略ガイド、エビデンスベース判断）

セットアップ後、Claude Codeで `/onboard` を実行してください。

### Cursor

```bash
pip install mureo
mureo setup cursor
```

CursorはMCPツール（169ツール）を利用できますが、ワークフローコマンドとスキルには対応していません。

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
| 10ワークフローコマンド | Yes | N/A | No |
| 6スキル | Yes | N/A | No |

### スキル一覧

| スキル | 内容 |
|-------|------|
| `mureo-google-ads` | Google広告の82ツールのリファレンス |
| `mureo-meta-ads` | Meta広告の77ツールのリファレンス |
| `mureo-shared` | 認証、セキュリティルール、出力フォーマット |
| `mureo-strategy` | STRATEGY.md / STATE.json の仕様と使い方 |
| `mureo-workflows` | 運用モード、KPI閾値、コマンドリファレンス |
| `mureo-learning` | エビデンスベースの判断フレームワーク（観察期間、サンプルサイズ、ノイズガード） |

### GA4（Google Analytics 4）の接続

mureoのワークフローコマンドは、GA4のMCPサーバーが接続されていればコンバージョン率やユーザー行動のデータを自動的に取り込みます。GA4は任意であり、なくても全コマンドは動作します。

[Google Analytics MCP](https://github.com/googleanalytics/google-analytics-mcp) を使ったセットアップ手順：

```bash
# インストール
pipx install analytics-mcp

# 認証（gcloud CLIが必要）
gcloud auth application-default login \
  --scopes https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform
```

`~/.claude/settings.json` にmureoと並列で追加：

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

前提条件：GCPプロジェクトで **Google Analytics Admin API** と **Google Analytics Data API** を有効化してください。

### その他のMCPサーバー

mureoは任意のMCPサーバーと併用できます。CRMツールなどのMCPを同じセッションに追加すれば、ワークフローコマンドがそのデータも活用します。詳細は [docs/integrations.md](docs/integrations.md) を参照してください。

## 認証

### セットアップ（推奨）

```bash
mureo auth setup
```

対話型のウィザードが以下をガイドします：

1. **Google広告** — Developer Token + Client ID/Secret を入力 → ブラウザでOAuth → アカウント選択
2. **Meta広告** — App ID/Secret を入力 → ブラウザでOAuth → 広告アカウント選択
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

## ツール一覧（169ツール）

- **Google広告：82ツール** — キャンペーン、広告グループ、広告、キーワード、予算、検索語、分析、RSA監査、B2B最適化、モニタリングなど
- **Meta広告：77ツール** — キャンペーン、広告セット、広告、クリエイティブ、オーディエンス、Conversions API、商品カタログ、リード広告など
- **Search Console：10ツール** — サイト管理、検索アナリティクス、URL検査、サイトマップ

全ツールの詳細は [英語版README](README.md#tool-list-169-tools) を参照してください。

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
