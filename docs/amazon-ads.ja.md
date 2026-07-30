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
公式 MCP と同じ扱い。LwA access トークンの自動更新は実装済み
（後述）。Amazon の native ツール名に紐づく深いプラットフォーム
固有分析は**まだありません**（#120 で追跡）— Amazon の分析結果は
参考情報として扱ってください。

## 1. Amazon 認証情報の取得（あなたが実施・mureo は代理入力しない）

**Login with Amazon (LwA) アプリ** ＋ **Amazon Ads API** アクセス権
のある Amazon Developer アカウントが必要です。そこから:

- `client_id`（LwA アプリの client id）
- `access_token`（LwA access トークン。**約 60 分で失効します**）
- `refresh_token` ＋ `client_secret` — 強く推奨。この 2 つが揃うと
  mureo が access トークンを自動更新します（後述）。無い場合は
  失効のたびに `access_token` を手で貼り替える必要があります。

## 2. `~/.mureo/credentials.json` に `amazon_ads` セクションを追加

```json
{
  "amazon_ads": {
    "client_id": "amzn1.application-oa2-client.xxxxx",
    "access_token": "Atza|xxxxx",
    "region": "na",
    "account_mode": "dynamic"
  }
}
```

| フィールド | 必須 | 説明 |
|-----------|------|------|
| `client_id` | 必須 | LwA アプリ client id |
| `access_token` | 必須 | LwA access トークン（`Atza|…`） |
| `region` | 任意（既定 `na`） | `na` / `eu` / `fe`。エンドポイント選択 |
| `account_mode` | 任意（既定 `dynamic`） | `dynamic`（都度 LLM に確認）/ `fixed` |
| `refresh_token`, `client_secret` | 推奨 | 両方揃うと access トークンの自動更新が有効になる |
| `profile_id`, `account_id`, `manager_account_id` | 任意 | **Fixed** 専用（Fixed 発動には1つ以上必須） |

## 3. ツールマニフェストを生成

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

## 4. Claude / mureo MCP サーバを再起動

Amazon のツールが Amazon 自身の名前（例 `campaign_management-*`,
`account_management-*`）で出現し、組み込みプラットフォームと同様に
監査・戦略ゲートされます。mutating 呼び出しは `STATE.json` の
`action_log`（`platform=plugin:mureo-amazon-ads-bridge`）へ観測窓
付きで昇格（#114 プラグイン安全層と同じ）。

## access トークンの自動更新

`refresh_token` と `client_secret` が**両方**ある場合、約 60 分の
失効は mureo が処理します。Amazon ツール呼び出しが最初に失敗した
時点で Login with Amazon の更新を 1 回だけ実行し
（リージョン別トークンホストへ `grant_type=refresh_token`）、
新しいトークンを `~/.mureo/credentials.json` に書き戻して、呼び出しを
1 回だけ再試行します。トークンや秘密情報がエラーメッセージ・ログに
出ることはありません。

- 1 呼び出しにつき更新 1 回・再試行 1 回。ループしません。
- Amazon が `invalid_grant` を返した場合は refresh トークン自体が
  無効です。広告主による再認可が必要で、mureo はその旨を明示します。
- `~/.mureo/credentials.json` に書き込めない場合（多くは JSON が
  壊れているケース。他プロバイダの認証情報を失わないよう mureo は
  壊れたファイルを上書きしません）、黙って再試行せずその理由を
  付けて失敗します。
- `mureo amazon refresh-manifest` は自動更新**しません**。保存済みの
  `access_token` をそのまま使います。更新はツール実行経路でのみ
  発生します。

`refresh_token` ＋ `client_secret` が無い場合は、失効時に
`~/.mureo/credentials.json` の `access_token` を手動で更新してください。

## なぜ mureo が経路に入るのか

公式 hosted MCP の中には、AI ホストに直接登録してホスト自身が接続・
認証する方式のものもあります。Amazon を mureo 経由のブリッジにして
いる理由は 2 つです。LwA 認証情報が `~/.mureo/credentials.json` に
留まり、ホスト側の MCP 設定に一切入らないこと。そして上記の自動更新
は mureo が経路にいて初めて成立すること（失敗を検知し、refresh
トークンを交換し、再試行するのは mureo です）。代償として、Amazon の
ツールは mureo MCP サーバが動いている間だけ利用できます。

## 注意

- **改名なし**: ツールは Amazon の名前のまま（mureo は公式 MCP の
  ツールを改名しない＝Google/Meta 公式と同じ）。
- **深い mureo 分析なし**: mureo の native ツール名に紐づく
  プラットフォーム固有分析は Amazon には存在しません（#120 で追跡）。
  Amazon の read 結果は参考情報として扱ってください。
- **機密性のクラス**は、既に `~/.mureo/credentials.json` にある
  Google developer token / Meta access token と同一です。
