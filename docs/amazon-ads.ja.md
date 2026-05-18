# Amazon Ads（公式 MCP ブリッジ）— Phase 1

mureo が公式 Amazon Ads MCP へ代理接続します。mureo-native の
Google/Meta と同じ「受付方式」です:

```
Claude  →  ローカル mureo MCP  →  Amazon hosted MCP エンドポイント
```

認証情報は `~/.mureo/credentials.json` に保存（Claude は見ない）。
Amazon の全ツール呼び出しは mureo の監査 / スロットル / 戦略 /
rollback 安全層を通ります。

**Phase 1 の範囲（正直に）:** read 中心、下記マニフェスト方式。
Amazon のツール名はそのまま公開（taxonomy へ改名しない）— 他の
公式 MCP と同じ扱い。深いプラットフォーム固有分析と LwA access
トークンの自動更新は Phase 2。

## 1. Amazon 認証情報の取得（あなたが実施・mureo は代理入力しない）

**Login with Amazon (LwA) アプリ** ＋ **Amazon Ads API** アクセス権
のある Amazon Developer アカウントが必要です。そこから:

- `client_id`（LwA アプリの client id）
- `access_token`（LwA access トークン。**失効します** — 注意参照）
- 任意で `refresh_token` ＋ `client_secret`（Phase 2 自動更新用に記録。
  Phase 1 では未使用）

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
| `refresh_token`, `client_secret` | 任意 | Phase 2 自動更新用に記録 |
| `profile_id`, `account_id`, `manager_account_id` | 任意 | **Fixed** 専用（Fixed 発動には1つ以上必須） |

## 3. ツールマニフェストを生成

```bash
mureo amazon refresh-manifest
```

認証付きで一度接続し、Amazon の MCP ツール一覧を取得して
`~/.mureo/amazon_tools.json` に書き出します。mureo MCP サーバは
起動時にこのファイルを読むだけ（純粋・ネットワーク無し・資格情報
不要）。マニフェスト不在＝「Amazon ツール無し」で、起動失敗には
なりません。access トークン更新時や Amazon のツール変更時に再実行。

## 4. Claude / mureo MCP サーバを再起動

Amazon のツールが Amazon 自身の名前（例 `campaign_management-*`,
`account_management-*`）で出現し、組み込みプラットフォームと同様に
監査・戦略ゲートされます。mutating 呼び出しは `STATE.json` の
`action_log`（`platform=plugin:mureo-amazon-ads-bridge`）へ観測窓
付きで昇格（#114 プラグイン安全層と同じ）。

## 注意

- **トークン失効**: LwA access トークンは失効します。失効時は
  `~/.mureo/credentials.json` の `access_token` を更新し
  `mureo amazon refresh-manifest` を再実行。自動更新は Phase 2。
- **改名なし**: ツールは Amazon の名前のまま（mureo は公式 MCP の
  ツールを改名しない＝Google/Meta 公式と同じ）。native ツール名に
  紐づく深い mureo 分析は Phase 2。
- **機密性のクラス**は、既に `~/.mureo/credentials.json` にある
  Google developer token / Meta access token と同一です。
