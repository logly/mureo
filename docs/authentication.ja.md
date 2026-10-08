# 認証ガイド (Authentication Guide)

> [English](authentication.md)

## 推奨セットアップ

ほとんどの人にとって、いちばん簡単なのは 1 コマンドのセットアップ:

```bash
# Claude Code 利用者 (認証 + MCP + コマンド + skills + 認証ガード)
mureo setup claude-code

# Cursor 利用者 (認証 + MCP のみ)
mureo setup cursor

# OpenAI Codex CLI 利用者 (MCP + 認証ガード + ワークフロー skills + 共有 skills)
mureo setup codex

# Gemini CLI 利用者 (拡張マニフェスト + MCP)
mureo setup gemini

# CLI だけで済ませる場合 (認証のみ、ターミナルで対話入力)
mureo auth setup

# ブラウザ設定 UI — localhost で動き、ターミナル入力は不要
# (廃止された `mureo auth setup --web` の後継)
mureo configure
```

### `--skip-auth` と非対話実行

`mureo setup …` の各サブコマンドは `--skip-auth` を受け付けます。OAuth を実行せずに、MCP 設定・認証ガード・(対応ホストでは)コマンド/skill ファイルだけをインストールします。ダブルクリック型インストーラの導線のように、認証を後から Claude Code の `/onboard`、Codex の `$onboard`、あるいは本物のターミナルでの `mureo auth setup` で済ませる場合に便利です。

`mureo setup …` を AI エージェントのサブプロセス (Claude Code の Bash ツール、Codex など) から呼び出すと、制御端末 (TTY) がないため `--skip-auth` が自動的に補われます。`typer.confirm` のプロンプトでハングしないようにするためです。stdout のバナーが、あとで `Terminal.app` から認証を終わらせるようオペレーターに伝えます。

各サブコマンドは `--google-ads/--no-google-ads` と `--meta-ads/--no-meta-ads` も明示的に公開しているので、プロンプトなしでどのプラットフォームを設定するかを指定できます。`--skip-auth` と併用した場合 (または非 TTY 下) は警告を出して無視されます。

### `mureo configure` — ブラウザ設定 UI

> `mureo auth setup --web` は**廃止**されました。そのブラウザ認証情報フローは統合された `mureo configure` UI の一部になっています。

ターミナル入力を安全に受け取れない AI エージェントから mureo を案内された場合、あるいは単に GUI を使いたい場合は `mureo configure` を選んでください。localhost のランダムなポートに短命の HTTP サーバーを立ててブラウザで開き、HTML フォームと標準的な OAuth リダイレクトによる Google Ads / Meta Ads / GA4 の認証情報入力 (各項目は対応するコンソールへディープリンク) に加え、ダッシュボードの *Plugin credentials* セクションにある **Amazon Ads** カードの **Authorize with Amazon** フローで LwA トークンを取得 (Amazon の同意にはループバックコールバックがないため、コードを貼り付ける案内付きのフローです。mureo が同意ページを開き、リダイレクト先のアドレスを貼り戻します。[amazon-ads.ja.md](amazon-ads.ja.md) 参照) もできます。さらに Claude のホスト選択、基本セットアップ (MCP サーバー + 認証ガードフック + skills)、公式 MCP プロバイダの追加、プラットフォームごとの mureo-native / 公式 MCP の切り替え、Demo/BYOD の雛形作成も行えます。フラグ: `--no-browser`、`--timeout-seconds N` (アイドル時の停止、既定 600)。セキュリティ強化 (CSRF ローテーション、OAuth `state` の再検証、DNS リバインディング対策、localhost に固定したリダイレクト検証、汎用化したエラー表示、POST サイズ上限、CSP) も同じものが適用されます。`SECURITY.md` 参照。

認証ステップは、すでにディスクにあるものを再利用します。Google の refresh token が保存済みなら (Google Ads と Search Console は 1 本を共有) Google の認可ステップはスキップされ、UI がそう表示します。新しいトークンを発行したいときのために **Re-authorize Google** ボタンが出ます。

**UI で何かが失敗したとき**、画面上のメッセージは意図的に汎用的です (エラー表示がトークンの素材を反映してはいけません)。原因は configure のログ — `~/.mureo/logs/configure.log` — にあります。起動時にパスが表示され、全プラットフォームで書き出されます。他では見えないもの、つまり失敗した Meta トークンの更新や永続化できなかった更新、拒否されたアカウント一覧の取得、パースできない `credentials.json` も含まれます。`MUREO_LOG_LEVEL=DEBUG mureo configure` で詳細度を上げられます。どのレベルでも、ログ行がトークン・シークレット・認証情報の値を持つことはありません。[cli.md — Configure log](cli.md#configure-log) 参照。

## 認証情報のしくみ

mureo は `~/.mureo/credentials.json` から認証情報を読み込み、ファイルが無いか不完全な場合は環境変数にフォールバックします。

## credentials.json の形式

`~/.mureo/credentials.json` を次の構造で作成します:

```json
{
  "google_ads": {
    "client_id": "YOUR_OAUTH_CLIENT_ID",
    "client_secret": "YOUR_OAUTH_CLIENT_SECRET",
    "refresh_token": "YOUR_REFRESH_TOKEN",
    "login_customer_id": "1234567890",
    "developer_token": "OPTIONAL_LEGACY_TOKEN"
  },
  "meta_ads": {
    "access_token": "YOUR_ACCESS_TOKEN",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET"
  }
}
```

`developer_token` は任意 (レガシー): Google は 2026-09-09 に developer token の発行を終了しました。保存されていれば送りますが、API 側は無視します。将来のメジャーバージョンでは拒否される予定です。

使うプラットフォームだけ書けば十分です。たとえば Google Ads だけを使うなら `meta_ads` セクションは省略できます。

### Google Ads のフィールド

| フィールド | 必須 | 説明 |
|-------|----------|-------------|
| `developer_token` | いいえ | レガシー。Google は 2026-09-09 に developer token の発行を終了。保存されていれば送るが、API 側は無視する。 |
| `client_id` | はい | OAuth 2.0 クライアント ID |
| `client_secret` | はい | OAuth 2.0 クライアントシークレット |
| `refresh_token` | はい | OAuth 2.0 refresh token |
| `login_customer_id` | いいえ | マネージャーアカウント ID (MCC)。省略時は対象の `customer_id` がフォールバックとして使われる。 |

### Meta Ads のフィールド

| フィールド | 必須 | 説明 |
|-------|----------|-------------|
| `access_token` | はい | Meta Graph API のアクセストークン (ユーザートークンまたはシステムユーザートークン) |
| `app_id` | いいえ | Meta の App ID |
| `app_secret` | いいえ | Meta の App Secret |

## 環境変数へのフォールバック

`~/.mureo/credentials.json` が無いか必須フィールドを欠いている場合、mureo は環境変数にフォールバックします。

### Google Ads

| 変数 | 必須 | 説明 |
|----------|----------|-------------|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | いいえ | レガシー。Google は 2026-09-09 に developer token の発行を終了。保存されていれば送るが、API 側は無視する。 |
| `GOOGLE_ADS_CLIENT_ID` | はい | OAuth 2.0 クライアント ID |
| `GOOGLE_ADS_CLIENT_SECRET` | はい | OAuth 2.0 クライアントシークレット |
| `GOOGLE_ADS_REFRESH_TOKEN` | はい | OAuth 2.0 refresh token |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | いいえ | マネージャーアカウント (MCC) の customer ID |

### Meta Ads

| 変数 | 必須 | 説明 |
|----------|----------|-------------|
| `META_ADS_ACCESS_TOKEN` | はい | Graph API のアクセストークン |
| `META_ADS_APP_ID` | いいえ | Meta の App ID |
| `META_ADS_APP_SECRET` | いいえ | Meta の App Secret |

### Amazon Ads

| 変数 | 必須 | 説明 |
|----------|----------|-------------|
| `AMAZON_ADS_CLIENT_ID` | はい | Login with Amazon (LwA) アプリケーションのクライアント ID |
| `AMAZON_ADS_REFRESH_TOKEN` | 条件付き | LwA の refresh token — クライアントシークレットと合わせて、mureo がアクセストークンの発行と更新を行う |
| `AMAZON_ADS_CLIENT_SECRET` | 条件付き | LwA アプリケーションのクライアントシークレット |
| `AMAZON_ADS_ACCESS_TOKEN` | 条件付き | LwA のアクセストークン (約 60 分で失効) |
| `AMAZON_ADS_REGION` | いいえ | `na` / `eu` / `fe` (既定は `na`) |
| `AMAZON_ADS_ACCOUNT_MODE` | いいえ | `dynamic` / `fixed` (既定は `dynamic`) |
| `AMAZON_ADS_PROFILE_ID` | いいえ | fixed アカウントモードのみ |
| `AMAZON_ADS_ACCOUNT_ID` | いいえ | fixed アカウントモードのみ |
| `AMAZON_ADS_MANAGER_ACCOUNT_ID` | いいえ | fixed アカウントモードのみ |

「条件付き」とは、クライアント ID に加えて `AMAZON_ADS_ACCESS_TOKEN` **か**、`AMAZON_ADS_REFRESH_TOKEN` と `AMAZON_ADS_CLIENT_SECRET` の**両方**、のどちらかという意味です。[amazon-ads.ja.md](amazon-ads.ja.md) 参照。

**解決順序**: credentials.json が優先されます。環境変数は、credentials.json の該当セクションが無いか不完全な場合にのみ参照されます。

## 手で作るのはどれか

プラットフォームのコンソールで手で作るものは、次の 2 つだけです:

- **Google** — **OAuth クライアント**。ここから `client_id` と `client_secret` が得られます。
- **Meta** — **アプリ**。ここから `app_id` と `app_secret` が得られます。

残りは mureo が取得します:

- **`refresh_token` (Google) とアクセストークン (Meta の Long-Lived Token) は mureo が取得します。** 上記の組を `mureo configure` のブラウザ画面か `mureo auth setup` に入力すれば、mureo が同意フローを実行し、正しいスコープ付きで保存します (`mureo auth setup` は Google の **Client ID** / **Client Secret** と Meta の **App ID** / **App Secret** を入力として受け取ります — `auth_setup.py`)。
- **`developer_token` (Google) はもう不要です。** Google は 2026-09-09 に developer token の発行を終了しました。保存されていれば mureo は送りますが、API 側は無視し、将来のメジャーバージョンでは拒否される予定です。
- **`login_customer_id` (Google)** はマネージャーアカウント (MCC) 経由でアカウントに到達する場合だけ関係します。
- 広告プラットフォーム側で Google Ads が要求するのは、**同意に使う Google アカウントが対象の広告アカウントにアクセス権を持っていること**です。Google Ads のマネージャーアカウント (MCC) は必須ではありません。

OAuth クライアントだけでは足りないものが 1 つあります: **Google 側は OAuth クライアントを作るだけでは本番アカウントを触れません。Cloud プロジェクトにアクセスレベルが必要で、その申請は別物です。** API を有効化して付与されるのは **Test** アクセスで、これはテストアカウントにしか届きません。本番アカウントには最低でも **Explorer** が必要です。Explorer は Google Ads API の **Overview** ページから申請し、ブランド確認は不要です。下の [アクセスレベル](#アクセスレベル) を参照。

## Google Ads の認証情報を取得する

### 1. Google Ads API のアクセス (Google Cloud Console)

1. [Google Cloud Console](https://console.cloud.google.com/) を開き、新しいプロジェクトを作成 (または既存のものを選択) する。
2. **APIs & Services > Library** から **Google Ads API** を有効化する。有効化した時点でプロジェクトに **Test** アクセスが付与される。
3. Google Ads API の **Overview** ページから、実際に必要なアクセスレベルを申請する (下の表を参照)。Google Ads のマネージャーアカウントは不要。
4. アクセスレベルは**このプロジェクト**に属する。プロジェクト内で作る OAuth クライアントはすべてプロジェクトのアクセスレベルを継承する。2026-09 の移行以降、アクセスレベルは developer token ではなく、OAuth 認証情報を発行した Cloud プロジェクトの属性である。

アクセス管理とブランド確認はどちらも **Google Cloud Console** で行います。旧 API Center は廃止されました。

#### アクセスレベル

| レベル | 本番アカウント | 1 日の操作上限 | 到達条件 |
|---|---|---|---|
| **Test** | 不可 — テストアカウントのみ | 15,000 | Google Ads API を有効化した時点で自動付与 |
| **Explorer** | **可** | 本番 **2,880** / テスト 15,000 | Google Ads API の **Overview** ページから申請。**ブランド確認は不要** |
| **Basic** | 可 | 15,000 (本番・テストとも) | **Cloud プロジェクトのブランド確認が前提条件**。そのうえで **Overview** ページから申請 |
| **Standard** | 可 | 無制限 | 手動監査 — Required Minimum Functionality への準拠を示す必要がある |

**まずは Explorer から始めるのが普通です。** Explorer はプロジェクトがテストアカウントと本番アカウントの両方に対して Google Ads API のリクエストを行えるようにするもので、Google はこれを「ほとんどの開発者が API を使い始め、基本的な自動化を組むには十分」と説明しています。ただしアカウント作成・ユーザー管理・プランニングツール・課金サービスは制限されます。**Basic** を取るには、まず Cloud プロジェクトのブランド確認が必要です。そのうえで申請すると、Google がプロジェクトを自動的に Basic へ上げることがあります。

出典:
[Access levels](https://developers.google.com/google-ads/api/docs/access-levels)、
[API policy — access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels)、
[Developer token](https://developers.google.com/google-ads/api/docs/get-started/dev-token)。

### 2. OAuth 2.0 のクライアント ID とシークレット

1. **同じプロジェクト**で **Google Auth Platform > Clients** を開く。これが現行の導線。旧来の **APIs & Services > Credentials** の導線も今のところ有効で、どちらも同じ OAuth クライアントに到達する ([Google Cloud ヘルプ](https://support.google.com/cloud/answer/15549257))。
2. **OAuth client ID** を作成する (旧導線では **Create Credentials > OAuth client ID**)。
3. アプリケーションの種類に **Desktop app** を選ぶ。
4. **Client ID** と **Client Secret** をコピーする。

> **公開ステータスを「テスト (Testing)」のままにすると refresh token は 7 日で失効する。**
> OAuth 同意画面を **外部 (External)** ユーザータイプで構成し、公開ステータスが
> **Testing** のままの Google Cloud プロジェクトが発行する refresh token は
> **7 日**で失効します。ただし、要求するスコープが name / email address /
> user profile の部分集合である場合は除きます。mureo が要求するのは
> `https://www.googleapis.com/auth/adwords` で、これはその除外に**当たりません**。
> つまり Testing のままのプロジェクトでは 7 日ごとに再認証が必要になります。
> 「しばらく動いていたのに突然 API が通らなくなる」の典型的な原因がこれです。
> 本番運用するなら公開ステータスを **本番 (In production)** にしてください。
> **内部 (Internal)** ユーザータイプにはこの 7 日制限は適用されません。出典:
> [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)。

> **refresh token は 1 Google アカウント × 1 OAuth クライアントあたり 100 本まで。**
> 上限は OAuth 2.0 クライアント ID ごと・Google アカウントごとに、現在 **100** 本です。
> 上限に達すると、新しい refresh token の作成が**最も古いものを警告なしに無効化します**。
> `mureo auth setup` / `mureo configure` での再認証は毎回新しい refresh token を発行する
> ので、再認証を繰り返すとこの枠を消費します。出典:
> [Using OAuth 2.0 to Access Google APIs](https://developers.google.com/identity/protocols/oauth2)。

### 3. Refresh token

`google-auth-oauthlib` ライブラリで refresh token を取得します:

```python
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    },
    scopes=["https://www.googleapis.com/auth/adwords"],
)
flow.run_local_server(port=8080)
print("Refresh token:", flow.credentials.refresh_token)
```

あるいは [Google OAuth Playground](https://developers.google.com/oauthplayground/) を `https://www.googleapis.com/auth/adwords` スコープで使います。

> **スコープが重要。** refresh token は Google Ads のスコープ `https://www.googleapis.com/auth/adwords` を*必ず*持っている必要があります。別のスコープで発行した refresh token を流用すると、Google Ads API の呼び出しが実行時に `ACCESS_TOKEN_SCOPE_INSUFFICIENT` で失敗します。`mureo configure` / `mureo auth setup` はこのスコープ (と Search Console) を自動で要求するので、手で発行したトークンより優先してください。出典: [Google Ads API — OAuth 2.0 scopes](https://developers.google.com/google-ads/api/docs/oauth/overview)。

### 既存ユーザー (developer token からの移行)

Google は、2026-09-09 の前 90 日間に承認済み developer token で API 呼び出しを行ったすべての Cloud プロジェクトのアクセスレベルを移行しました。設定を確認するには:

1. プロジェクトの **Google Ads API > Overview** ページを開き、表示されているアクセスレベルを確認する。
2. この連携を担当する開発者がプロジェクトの **owner** または **editor** IAM ロールを持っていることを確認する。
3. credentials.json の古い `developer_token` は残しても削除してもよい。mureo はもう必要としない。

移行時点で保留中だった Basic アクセスの申請はすべてクローズされました。自分の申請がそれに当たる場合は、**Overview** ページから再度申請してください。

## Meta Ads の認証情報を取得する

### App Review が必要になるとき、ならないとき

**自分の広告アカウントを自分で運用するだけなら App Review は不要です。** アプリが
**開発モード (development mode)** のあいだは、`ads_management` / `ads_read` /
`pages_*` / `leads_retrieval` は、そのアプリに **管理者 (admin)** /
**開発者 (developer)** / **テスター (tester)** のいずれかのロールを持つ利用者に対して
認可画面に出ます。つまり、自分 (自社) の広告アカウントを自分のアプリで運用するだけ
なら、審査に出すものはありません。

App Review — つまり **Advanced Access** — が必要になるのは、**アプリにロールを持たない
利用者**にそのアプリを使わせる場合です。ライブモードに切り替えると、認可画面には
App Review で承認されたものだけが出ます。

出典:
[App Roles](https://developers.facebook.com/docs/development/build-and-test/app-roles)、
[Permissions Reference](https://developers.facebook.com/docs/permissions/)。

**「App Review は不要」は権限の話であって、すべての話ではありません。** アプリのモードは、
このページの後ろで説明している 2 つのことも決めるので、実務上の分岐はこうなります:

| アプリのモード | App Review | localhost の OAuth (ブラウザログイン) | 広告クリエイティブの作成 | 使う認証情報 |
|---|---|---|---|---|
| **開発モード** | 不要 | **可** | **不可** — エラー subcode 1885183 | ブラウザ OAuth で取得した Long-Lived Token |
| **ライブモード** | アプリにロールを持たない利用者に使わせる場合のみ必要 | **不可** — 同意画面で拒否される | 可 | **システムユーザートークン** — [アクセストークン](#アクセストークン) 節の選択肢 C |

つまり、データを読むだけなら開発モードのアプリで足ります。新しい広告クリエイティブを
公開するには、ライブアプリと選択肢 C のシステムユーザートークンが必要です。

### 権限 (OAuth スコープ)

`mureo configure` / `mureo auth setup` はサインイン時に次のスコープを自動で要求します。手で列挙する必要はありません。完全な一覧の正は `mureo/auth_setup.py` の `_META_OAUTH_SCOPES` です:

| スコープ | できること |
| --- | --- |
| `ads_management` | キャンペーン・広告セット・広告・予算・入札の作成/編集 |
| `ads_read` | 広告データとインサイトの読み取り |
| `business_management` | ビジネスポートフォリオ経由で到達する広告アカウントの解決 (サインイン中に権限の警告が出ることがあるが、必須であり受け入れて問題ない) |
| `pages_show_list` | リンクできる Facebook ページの一覧取得 |
| `pages_manage_ads` | ページに紐づく広告の管理 |
| `pages_read_engagement` | ページの投稿と写真の読み取り (Boost Post フロー用に投稿を一覧する `meta_ads_page_posts_list`、Instant Form のカバーを選ぶために既存のページ写真を一覧する `meta_ads_pages_photos_list`) |
| `leads_retrieval` | リード広告 / Instant Form からのリード取得 |

補足:

- `public_profile` はすべての Facebook Login で既定で付与され、明示的に要求する必要がないため上の表には入っていません。
- 「Page Public Metadata Access」/「Page Public Content Access」は**不要**です。mureo は自分が管理しているページに対してのみ操作し (`/me/accounts` とビジネス所有のページからページアクセストークンを解決する)、任意の公開ページを触ることはありません。
- `pages_manage_posts` は v0.14.0 までは要求していましたが、現在は要求しません。Instant Form のカバー用にページ写真をアップロードするためのものでしたが、カバーはページが既に持っている写真から選ぶ方式 (`meta_ads_pages_photos_list`) になり、これは `pages_read_engagement` + `pages_show_list` で読めます。以前に発行されたトークンは付与済みの権限を持ち続けますが、mureo はそれを使う処理を一切持たないので、外すために何かする必要はありません。
- 新しいスコープが追加されたバージョンに mureo を上げたあとは、`mureo auth setup` を再実行する (または `mureo configure` で再認証する) ことで、新しい権限付きでトークンを再発行してください。既存のトークンが後からスコープを得ることはありません。スコープを削る場合は再認証は不要です。

### アクセストークン

**選択肢 A: Graph API Explorer (テスト用)**

1. [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/) を開く。
2. 自分のアプリを選ぶ。
3. **Generate Access Token** をクリックする。広告の読み書きには `ads_management` + `ads_read` が最低限。ページ・リード広告・Instant Form の機能を試すには上の表から `pages_*` / `leads_retrieval` を足す。
4. 得られるトークンは短命 (1〜2 時間)。

**選択肢 B: Long-Lived Token (本番用)**

1. Graph API Explorer で短命のユーザートークンを取得する。
2. それを長命トークン (60 日) に交換する:

```bash
curl -X POST "https://graph.facebook.com/v26.0/oauth/access_token" \
  -d "grant_type=fb_exchange_token" \
  -d "client_id=YOUR_APP_ID" \
  -d "client_secret=YOUR_APP_SECRET" \
  -d "fb_exchange_token=SHORT_LIVED_TOKEN"
```

> **GET ではなく POST を使う。** Graph の `/oauth/access_token`
> エンドポイントはこれらのパラメータをリクエストボディで受け取れるので、
> `client_secret` とトークンを URL (およびリクエスト/プロキシのログ) の
> 外に保てます。mureo 自身のトークン交換も同じ理由でフォームボディとして
> POST しています。

**選択肢 C: システムユーザートークン (自動化に推奨 — ライブアプリでは必須)**

アプリのモードと App Review の関係は、上の **App Review が必要になるとき、ならないとき**
を参照してください。

ビジネスマネージャの**システムユーザートークン**は、Meta の認証情報として最も堅牢で、
多くのオペレーターにとっては端から端まで通る*唯一*の手段です:

- **ライブモードのアプリは localhost の configure UI から OAuth を完了できません。**
  Facebook が自身の同意画面で `http://localhost` のリダイレクトを拒否するため、
  mureo のコールバックに到達する前に失敗します。ブラウザログインは行き止まりに
  なります。システムユーザートークンはブラウザのリダイレクトを必要としません。
- **開発モードのアプリは広告クリエイティブを作成できません。** 画像アセットの
  アップロードは成功しても、**新規**クリエイティブを Meta に公開するには
  **ライブアプリ**が必要で、開発モードのアプリはエラーサブコード **1885183** で
  ブロックされます。ライブアプリで発行したシステムユーザートークンならこれを
  回避できます。

発行手順 (4 ステップ):

1. **ビジネス設定 → システムユーザー** で **管理者 (Admin)** ロールのシステム
   ユーザーを作成する。
2. そのシステムユーザーに**広告アカウント** (広告の管理) と**ページ**
   (コンテンツの管理) を割り当てる。
3. **自分のライブアプリ**に対してトークンを生成する。mureo に期限を追跡・更新
   させたい場合は **60 日の有効期限**を選ぶ。スコープは
   `ads_management`、`ads_read`、`business_management`、`pages_manage_ads`、
   `pages_read_engagement` を選ぶ (ページ / リード広告 / Instant Form の機能には
   上の表の残りの `pages_*` / `leads_retrieval` も足す)。
4. 生成されたトークンをコピーする。

**configure UI でのトークン入力。** `mureo configure` の Meta Ads 認証ステップで、
*Login with Facebook* の隣にある **"Paste a system-user token"** を開き、トークンを
貼り、**Validate token** をクリックし (付与されたスコープと欠けているスコープが
報告され、そのトークンで到達できる広告アカウントが一覧される)、広告アカウントを
選んで **Save** します。

**これらのトークンはたいてい期限切れになります。** ビジネス設定は新しいシステム
ユーザートークンに **60 日**の有効期限を選ばせます。期限なしで発行されたトークンは
まったく失効しません。mureo は Meta Graph の `debug_token` エンドポイントにどちらで
あるかを問い合わせ、答えをトークンの隣に記録します — 日付なら `token_expires_at`、
Meta の「never」判定なら `token_never_expires`。日付がある場合、ステータスカードは
残り日数を数え、**14** 日を切ると警告します。「never」の場合は失効しないと表示して
そのままにします。mureo が恒久トークンを交換することはありません。交換すれば 60 日
のものに置き換えてしまうからです。

**その検査を可能にしているのが App ID と App Secret です。** Meta はトークンを発行した
アプリに対してのみ、そのトークンを説明します: `debug_token` は*アプリアクセストークン*
(`app_id|app_secret`) で認証する GET であり、システムユーザートークンは自分自身を
検査できません。したがってカードの**任意項目である App ID と App Secret** は 2 つの
役割を持ちます:

- **期限を読む** — この組がないと mureo は検査を完全にスキップし、カードは期限が
  未追跡であることと、埋めるべき 2 つのフィールド名を表示します。これはエラーでは
  なく、保存を妨げることもありません。トークンはどちらでも保存され、動きます。
  Meta が検査を*拒否*した場合 (多くはその組がトークンを発行したアプリとは別の
  アプリのものである場合) は、カードはそう表示します。
- **60 日トークンを更新する** — 失効の 1 週間前に、Meta が文書化している期限付き
  システムユーザートークンの交換を使います (`grant_type=fb_exchange_token` に
  `set_token_expires_in_60_days` を付ける。[Install Apps, Generate, Refresh, and Revoke
  Tokens](https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens)
  参照)。期限なしで発行されたトークンは、何が保存されていても更新されません。

この組を空のままにしても壊れません。mureo が日付を表示・追跡できないだけです。
すでに保存された値は、再入力せずにトークンを貼り直したときも保持され、その後の
貼り付け時の検査にはその値が使われます。

このカードを優先してください。Setup タブの **mureo Credentials (advanced)** フォームから
`META_ADS_ACCESS_TOKEN` を保存することもできます。手で入れたトークンは入力どおりに
保存され、自動更新の時計には乗りません (この書き込みは `token_obtained_at`、
`token_expires_at`、`token_type`、`token_never_expires` をクリアします。いずれも
置き換えられるトークンを説明するものであり、このフォームは新しい値を得るための
Graph 呼び出しをしないからです)。ただし 1 フィールドを書くだけなので、トークンの
検証もしませんし、期限の読み取りも、広告アカウントの選択もできません。

### App ID と App Secret

1. [Meta for Developers](https://developers.facebook.com/) を開く。
2. 自分のアプリ > **Settings > Basic** に移動する。
3. **App ID** と **App Secret** をコピーする。

基本的な用途では任意ですが、**貼り付けたトークンの期限を読むには必須**で、**自動トークン更新にも必須**です (後述)。Meta はトークンを発行したアプリに対してのみそのトークンを説明するので、この組はそのアプリのものでなければなりません。

### リダイレクト URI

**Products > Facebook Login > Settings** の **Valid OAuth Redirect URIs** に
`http://localhost` を — ポートなしで — 登録します。mureo は空きポートを自動で選び、
`http://localhost:<port>/callback` にコールバックします (`mureo/auth_setup.py` の
`_generate_meta_auth_url` と `run_meta_oauth`。対話セットアップが表示する前提条件も
この 3 ステップです)。ポート番号を固定で登録する必要はありません。

## Meta Ads トークンの自動更新

mureo は Long-Lived Token を失効前に自動で更新できるので、手でトークンを交換し直す必要はもうありません。

### しくみ

1. `mureo auth setup` が Meta Ads のトークンを保存するとき、`credentials.json` に ISO 8601 のタイムスタンプ `token_obtained_at` を記録します。configure UI の貼り付けカードは加えて、そのトークンについて Meta の `debug_token` が報告した内容を記録します — 期限があれば `token_expires_at`、無ければ `token_never_expires: true`。この検査には発行元アプリの app ID と secret が必要で、無ければ何も記録されず、期限は未追跡のままになります。
2. Meta Ads の認証情報が読み込まれるたびに、mureo はトークンが更新時期かどうかを確認します。
3. **`token_never_expires` が立っている場合**、他に何が保存されていてもトークンは交換されません。Meta が恒久だと報告したものを 60 日のトークンに取り替えるのは格下げです。
4. **`token_expires_at` が分かっている場合**、更新時期はその日付の **7 日前**です。貼り付けられたシステムユーザートークンにとって正しい時計はこれだけです。60 日の寿命のどの時点で発行されたものか分からないので、経過時間は残り時間をほとんど語りません。
5. **分かっていない場合**、mureo はトークンの経過時間にフォールバックします: **53 日以上**。mureo 自身が発行した長命ユーザートークンの約 60 日の寿命に対して 7 日の余裕を取った値です。
6. いずれの場合も、mureo は Meta Graph API 経由で新しいトークンに交換します。`set_token_expires_in_60_days=true` が付くのは **`token_type` が `SYSTEM_USER` の場合だけ**です。Meta がこのパラメータを文書化しているのはシステムユーザートークンの更新についてであって、長命ユーザートークンの交換についてではなく、2 つを見分けられるのはトークン自身の種別だけです。新しいトークン・タイムスタンプ・期限は `credentials.json` に原子的に書き戻されます。
7. これは Meta クライアントを開くすべての経路で走ります: MCP tool と、#726 以降は `mureo_analytics_run` とレポート skills の背後にあるアナリティクスアダプタです。

### 必要なもの

| フィールド | 必須 | 理由 |
|-------|----------|-----|
| `app_id` | はい | トークンの検査 (`debug_token`) とトークン交換 API 呼び出しに必要 |
| `app_secret` | はい | 同じ — 両者で、どちらの呼び出しも認証に使うアプリアクセストークンを構成する |
| `token_obtained_at` | 自動 | `mureo auth setup` と貼り付けカードが書き込む。手で追記も可 (ISO 8601 形式) |
| `token_expires_at` | 自動 | 貼り付けカードが Meta の `debug_token` から書き込み、更新ごとにも書かれる。存在する場合は 53 日ルールを「この日付の 7 日前」に置き換える |
| `token_type` | 自動 | Graph の `debug_token` の判定。貼り付けカードだけが書き込む。`SYSTEM_USER` ならシステムユーザー向けの更新を選び、無いか他の値なら文書化済みのユーザートークン交換を使う |
| `token_never_expires` | 自動 | Graph のもう一方の `debug_token` 判定 (`expires_at: 0`)。貼り付けカードだけが書き込む。`true` のとき mureo はトークンを決して交換せず、期限についても警告しない |

`app_id` または `app_secret` が無い場合、自動更新は黙ってスキップされ、既存のトークンがそのまま使われます。

`token_never_expires` は JSON のブール値でなければなりません。それ以外の値 (文字列の `"false"` を含む) は mureo がログに記録して無視し、期限を確定できなかったトークンとして扱います。

**認証情報が mureo 自身のファイルの外にある場合** — `mureo.runtime_context_factory` プラグインで `MetaAdsCredentials` を自前で組むホスト — その保管先が `token_never_expires` を引き継がないと、「決して更新しない」保証は適用されません。無ければこのフィールドは `False` が既定となり、app ID と secret と並んで保存された恒久トークンが 60 日のものに交換されうるままです。これは #740 以前の挙動であり、それより悪くなることはありませんが、修正でもありません。

### 自動更新フィールド付きの credentials.json

```json
{
  "meta_ads": {
    "access_token": "YOUR_ACCESS_TOKEN",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET",
    "token_obtained_at": "2025-12-01T00:00:00Z",
    "token_expires_at": "2026-01-30T00:00:00Z",
    "token_type": "SYSTEM_USER"
  }
}
```

### 更新が起きない場合

自動更新は認証情報の読み込み時に走るので、2 か月使われていない mureo や、Meta が
拒否し続ける交換は、古びたトークンをディスクに残します。ダッシュボードの
**mureo integrations** リストはまさにそれを見ています: 53 日を超えると Meta の行は
トークンの経過日数とそれが意味することを表示し、隣にその場でシステムユーザー
トークンのカードを開く **Re-authenticate** ボタンを出します。セットアップ
ウィザードを再実行する必要はありません。

この経過日数の警告は、mureo が交換できたはずのトークンにだけ出ます: `app_id` /
`app_secret` が無ければ見逃した交換は存在せず、`token_obtained_at` のスタンプなしで
保存されたトークンは mureo が経過日数を知りえません。

**期限**の警告は別で、そのような条件はありません。`token_expires_at` がディスクに
あればいつでも、Meta の行は残り日数を表示し、14 を切ると警告します。まさに自動延長が
*できない*インストールこそ、その通知を最も必要とするからです。`/daily-check` は同じ
カウントダウンを **Watch** の所見として、すでに失効したトークンを **Action needed**
として報告するので、失敗した実行ではなく朝のレポートで届きます。

### 安全面のしくみ

- **同時実行の保護** — `asyncio.Lock` が複数の更新試行の同時実行を防ぎます。
- **原子的なファイル書き込み** — 認証情報はまず一時ファイルに書かれ、その後リネームされるので、破損しません。
- **0600 パーミッション** — 認証情報ファイルは所有者のみに制限されます。
- **穏当なフォールバック** — 更新が何らかの理由で失敗した場合 (ネットワークエラー、期限切れの app secret など)、mureo は既存のトークンで続行し、警告をログに出します。tool 呼び出しがブロックされることはありません。

## 対話セットアップウィザード

`mureo auth setup` (`mureo setup claude-code` の一部としても呼ばれます) は認証を対話形式で案内します:

1. **Google Ads OAuth** — Client ID/Secret を入力し (developer token は任意)、ブラウザで OAuth を開き、アカウントを選択。
2. **Meta Ads OAuth** — App ID/Secret を入力し、ブラウザで OAuth を開き、Long-Lived Token を取得し、アカウントを選択。
3. **MCP 設定** — グローバル (`~/.claude/settings.json`) かプロジェクト単位 (`.mcp.json`) を選択。

### プロジェクト単位の MCP 設定 (`.mcp.json`)

プロジェクト単位の配置を選ぶと、`mureo auth setup` はプロジェクトルートに `.mcp.json` を作ります:

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

`.mcp.json` に対応する AI エージェント (Claude Code など) は、そのプロジェクトディレクトリで作業するときに mureo MCP サーバーを自動的に見つけて接続します。

## 認証情報を確認する

セットアップの確認には `mureo auth` コマンドを使います:

```bash
# 全プラットフォームの認証状態を表示
mureo auth status

# Google Ads の認証情報を確認 (値はマスク表示)
mureo auth check-google

# Meta Ads の認証情報を確認 (値はマスク表示)
mureo auth check-meta
```

`mureo auth status` の出力例:

```
=== Authentication Status ===

Google Ads: Authenticated
Meta Ads: Authenticated
```

`mureo auth check-google` の出力例:

```json
{
  "developer_token": "***************abcd",
  "client_id": "123456789.apps.googleusercontent.com",
  "client_secret": "***************wxyz",
  "refresh_token": "***************efgh",
  "login_customer_id": "1234567890"
}
```

`developer_token` はレガシートークンが保存されていない限り `null` です。保存されている場合は上のようにマスク表示されます。

シークレットはマスクされ、末尾 4 文字だけが表示されます。これにより、値をさらさずに正しい認証情報が読み込まれていることを確認できます。
