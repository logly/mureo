# Amazon Ads（公式 MCP ブリッジ）

mureo が公式 Amazon Ads MCP へ代理接続します。mureo-native の
Google/Meta と同じ「受付方式」です:

```
Claude  →  ローカル mureo MCP  →  Amazon hosted MCP エンドポイント
```

認証情報は `~/.mureo/credentials.json` に保存（Claude は見ない）。
Amazon の全ツール呼び出しは mureo の監査 / スロットル / 戦略 /
rollback 安全層を通ります。

**範囲（正直に）:** read 中心、下記マニフェスト方式。
Amazon のツール名はそのまま公開（taxonomy へ改名しない）— 他の
公式 MCP と同じ扱い。LwA access トークンの自動発行・自動更新は
実装済み（後述）。Amazon の native ツール名に紐づく深いプラット
フォーム固有分析は**まだありません**（#120 で追跡）— Amazon の
分析結果は参考情報として扱ってください。

## 1. Amazon 認証情報の取得（あなたが実施・mureo は代理入力しない）

**Login with Amazon (LwA) アプリ** ＋ **Amazon Ads API** アクセス権
のある Amazon Developer アカウントが必要です。そこから:

- `client_id`（LwA アプリの client id）— 常に必須
- `refresh_token` ＋ `client_secret` — **推奨**。この 2 つが揃うと
  mureo が短命な access トークンを自動で発行・更新するため、以後
  貼り替える作業がなくなります
- `access_token` — 上記ペアがあれば任意。LwA access トークンで
  **約 60 分で失効**します。refresh トークンを使わない場合のみ設定し、
  失効のたびに手で貼り替えてください。

## 2. 設定 UI でセットアップ（推奨）

```bash
mureo configure
```

ブラウザでローカル設定 UI（`127.0.0.1` バインド）が開きます。手順:

1. **ダッシュボード**を開き、**プラグイン認証情報**セクションまで
   スクロールします。
2. **Amazon Ads** のカードを見つけます。
3. **クライアント ID** と、**リフレッシュトークン** ＋
   **クライアントシークレット**（推奨）または
   **アクセストークン**のいずれかを入力します。
4. 必要に応じて**リージョン**（`na` / `eu` / `fe`、既定 `na`）と
   **アカウントモード**（`dynamic` / `fixed`、既定 `dynamic`）を
   設定します。`fixed` の場合は**プロファイル ID** /
   **アカウント ID** / **マネージャーアカウント ID** のうち
   1 つ以上も入力してください。
5. **保存**をクリックします。

値は `~/.mureo/credentials.json` の `amazon_ads` セクションに
`0o600` で保存されます。シークレット項目は書き込み専用で、次回の
編集時に空欄のままにすると保存済みの値が**保持**されます（消えま
せん）。リージョンだけ変えたいときにトークンを打ち直す必要は
ありません。

> Amazon のブラウザサインイン（ワンクリックの OAuth 同意）ウィザードは
> まだありません。カードは貼り付け式のフォームです。Google / Meta の
> カードとの違いはこの点だけです。

続けて手順 5（ツールマニフェスト生成）へ進んでください。

## 3. 代替手段: 環境変数

コンテナや CI で運用していて認証ファイルを配置したくない場合は、
以下の環境変数を使えます。`~/.mureo/credentials.json` の
`amazon_ads` セクションが有効な組み合わせを持つ場合はそちらが
**優先**され、環境変数はフォールバックとしてのみ参照されます
（Google / Meta と同じ規則）。

| 変数 | 必須 | 説明 |
|------|------|------|
| `AMAZON_ADS_CLIENT_ID` | 必須 | LwA アプリ client id |
| `AMAZON_ADS_REFRESH_TOKEN` | 下記参照 | LwA refresh トークン（`Atzr\|…`） |
| `AMAZON_ADS_CLIENT_SECRET` | 下記参照 | LwA アプリの client secret |
| `AMAZON_ADS_ACCESS_TOKEN` | 下記参照 | LwA access トークン（`Atza\|…`） |
| `AMAZON_ADS_REGION` | 任意（既定 `na`） | `na` / `eu` / `fe`。エンドポイント選択 |
| `AMAZON_ADS_ACCOUNT_MODE` | 任意（既定 `dynamic`） | `dynamic` / `fixed` |
| `AMAZON_ADS_PROFILE_ID` | 任意 | **Fixed** 専用 |
| `AMAZON_ADS_ACCOUNT_ID` | 任意 | **Fixed** 専用 |
| `AMAZON_ADS_MANAGER_ACCOUNT_ID` | 任意 | **Fixed** 専用 |

「下記参照」＝ `AMAZON_ADS_CLIENT_ID` に加えて、
`AMAZON_ADS_ACCESS_TOKEN` **または**
`AMAZON_ADS_REFRESH_TOKEN` と `AMAZON_ADS_CLIENT_SECRET` の**両方**。
これに満たない場合、mureo は Amazon を「未設定」として扱います。

## 4. フォールバック: `~/.mureo/credentials.json` を手で編集

UI も環境変数も結局このセクションを作るだけなので、手編集も
引き続き有効です:

```json
{
  "amazon_ads": {
    "client_id": "amzn1.application-oa2-client.xxxxx",
    "refresh_token": "Atzr|xxxxx",
    "client_secret": "amzn1.oa2-cs.v1.xxxxx",
    "region": "na",
    "account_mode": "dynamic"
  }
}
```

| フィールド | 必須 | 説明 |
|-----------|------|------|
| `client_id` | 必須 | LwA アプリ client id |
| `refresh_token` ＋ `client_secret` | 推奨 | 両方揃うと access トークンの自動発行・自動更新が有効になる |
| `access_token` | 上記ペアが無い場合のみ必須 | LwA access トークン（`Atza\|…`）。約 60 分で失効 |
| `region` | 任意（既定 `na`） | `na` / `eu` / `fe`。エンドポイント選択 |
| `account_mode` | 任意（既定 `dynamic`） | `dynamic`（都度 LLM に確認）/ `fixed` |
| `profile_id`, `account_id`, `manager_account_id` | 任意 | **Fixed** 専用（Fixed 発動には1つ以上必須） |

## 5. ツールマニフェストを生成

```bash
mureo amazon refresh-manifest
```

認証付きで一度接続し、Amazon の MCP ツール一覧を取得して
`~/.mureo/amazon_tools.json` に書き出します。mureo MCP サーバは
起動時にこのファイルを読むだけ（純粋・ネットワーク無し・資格情報
不要）。マニフェスト不在＝「Amazon ツール無し」で、起動失敗には
なりません。Amazon のツール構成が変わったときや再認可した後に
再実行してください。通常のトークン更新のために実行する必要は
ありません（mureo が自動で行います。後述）。

## 6. Claude / mureo MCP サーバを再起動

Amazon のツールが Amazon 自身の名前（例 `campaign_management-*`,
`account_management-*`）で出現し、組み込みプラットフォームと同様に
監査・戦略ゲートされます。mutating 呼び出しは `STATE.json` の
`action_log`（`platform=plugin:mureo-amazon-ads-bridge`）へ観測窓
付きで昇格（#114 プラグイン安全層と同じ）。

## access トークンの自動発行・自動更新

`refresh_token` と `client_secret` が**両方**ある場合、`access_token`
に触る必要はありません:

- **初回利用時。** `access_token` が未保存なら、mureo は最初の転送
  呼び出しの**前に** Login with Amazon の交換を 1 回だけ実行し
  （リージョン別トークンホストへ `grant_type=refresh_token`）、
  発行されたトークンを `~/.mureo/credentials.json` に書き込んでから
  処理を続行します。
- **失効時（約 60 分）。** Amazon ツール呼び出しが最初に失敗した
  時点で更新を 1 回だけ実行し、新しいトークンを保存して、呼び出しを
  1 回だけ再試行します。

いずれの場合も**1 回のディスパッチにつき LwA 交換は 1 回だけで、
ループしません**。トークンや秘密情報がエラーメッセージ・ログに
出ることはありません。

- `~/.mureo/credentials.json` に書き込めない場合（多くは JSON が
  壊れているケース。他プロバイダの認証情報を失わないよう mureo は
  壊れたファイルを上書きしません）、黙って再試行せずその理由を
  付けて失敗します。
- `mureo amazon refresh-manifest` も同じ方法でトークンを発行します。
  `access_token` が未保存で `refresh_token` ＋ `client_secret` がある
  場合、LwA 交換を 1 回だけ実行してトークンを保存してからマニフェスト
  を生成します。そのため refresh トークンのみの構成でも、最初の
  コマンドからそのまま動作します（access トークンを貼り付ける必要は
  ありません）。なお、保存済みの access トークンが失効している場合の
  再発行は行いません。401 で失敗したら、ツール呼び出しでトークンが
  更新されたあとに再実行するか、`access_token` を空にして新規発行を
  促してください。

`refresh_token` ＋ `client_secret` が無い場合は、失効時に
`access_token` を手動で更新してください（設定 UI の Amazon Ads
カード、`AMAZON_ADS_ACCESS_TOKEN`、または
`~/.mureo/credentials.json` のいずれか）。

## refresh トークンも失効します（およそ 1 年ごと）

Amazon の LwA refresh トークンは長寿命ですが**永続ではありません**。
おおむね年 1 回の再認可を見込んでください。refresh トークンが無効に
なると Amazon はトークン交換に `invalid_grant` を返し、mureo は
「再認可が必要」であることを明示します。この時点で mureo が自動で
できることはありません。

復旧手順:

1. LwA アプリを Amazon で再認可し、**新しい** `refresh_token` を
   取得します。
2. `mureo configure` の Amazon Ads カードの**リフレッシュトークン**
   欄に貼り付けて保存します（または `AMAZON_ADS_REFRESH_TOKEN` /
   `~/.mureo/credentials.json` を更新）。
3. 次の Amazon ツール呼び出しで、そこから新しい access トークンが
   自動発行されます。Amazon のツール構成も変わっている場合は
   `mureo amazon refresh-manifest` も再実行してください。

## なぜ mureo が経路に入るのか

公式 hosted MCP の中には、AI ホストに直接登録してホスト自身が接続・
認証する方式のものもあります。Amazon を mureo 経由のブリッジにして
いる理由は 2 つです。LwA 認証情報が `~/.mureo/credentials.json` に
留まり、ホスト側の MCP 設定に一切入らないこと。そして上記の自動発行・
自動更新は mureo が経路にいて初めて成立すること（失敗を検知し、
refresh トークンを交換し、再試行するのは mureo です）。代償として、
Amazon のツールは mureo MCP サーバが動いている間だけ利用できます。

## 注意

- **ブラウザサインインは未対応**: 設定 UI の Amazon カードは貼り付け
  式フォームです。Google / Meta のカードにあるワンクリック OAuth 同意
  ウィザードは今後の対応です。
- **改名なし**: ツールは Amazon の名前のまま（mureo は公式 MCP の
  ツールを改名しない＝Google/Meta 公式と同じ）。
- **深い mureo 分析なし**: mureo の native ツール名に紐づく
  プラットフォーム固有分析は Amazon には存在しません（#120 で追跡）。
  Amazon の read 結果は参考情報として扱ってください。
- **機密性のクラス**は、既に `~/.mureo/credentials.json` にある
  Google developer token / Meta access token と同一です。
