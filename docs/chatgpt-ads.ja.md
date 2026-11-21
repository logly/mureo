# ChatGPT Ads（同梱プロバイダ）

mureo は、ChatGPT Ads を支える API である OpenAI の **Advertiser API** を
通じて、**ChatGPT Ads** のアカウントを読み取り、変更します。プロバイダは
mureo 本体に同梱されており（`mureo/chatgpt_ads/`）、プロバイダ経路で
提供されます。Amazon Ads ブリッジやサードパーティのプロバイダプラグインと
同じ経路です:

```
Claude  →  local mureo MCP  →  https://api.ads.openai.com/v1
```

Ads API キーは mureo の認証情報ストアに留まり（Claude は見ません）、
すべての呼び出しが mureo のプラグイン安全層を通ります。監査証跡と
ツールごとのスロットルがかかり、アカウントを変更するツールではさらに
`action_log` への記録、ロールバック、各ツールが宣言した金額への
STRATEGY.md の上限が加わります（どの金額が対象かは[単位](#単位)を
参照）。

**範囲:** 読み取りツールが 10 個（広告アカウント、その利用上限、
キャンペーン、広告グループ、広告、インサイト、変更履歴）と、アカウントを
変更するツールが 11 個あります。変更ツールでできるのは、キャンペーン・
広告グループ・広告の一時停止と再開、キャンペーンの名前と配信期間の変更、
キャンペーンの予算の設定、広告グループの名前の変更、広告グループの入札設定、
アカウントの 1 日の利用上限の設定です。さらに 6 個のツールがキャンペーン・
広告グループ・広告を作成（常に一時停止の状態）・アーカイブし、3 個のツールが
それを支えます。画像アップロード、広告のプレビュー、地域の検索です（#995）。
6 個のツールがカスタムオーディエンスを読み取り、作成し、メンバーを入れます
（[カスタムオーディエンス](#カスタムオーディエンス)を参照）。5 個のツールが
コンバージョン計測を設定し、レポートを返します
（[コンバージョン計測](#コンバージョン計測)を参照）。
mureo の外でアカウントに加えられた変更は、アカウントの監査ログから
取り込みます（[変更の取り込み](#変更の取り込み)を参照）。API はベータ版で
項目がよく増えるため、オブジェクトと行はすべてプラットフォームが送ったとおりに
返します。未知の項目や列挙値もそのままです。

## 1. Ads API キーを作成する

キーは **Ads Manager の設定ページ**で、ご自身の広告アカウント用に作成します。
1 つのキーで扱える広告アカウントは 1 つです。mureo はキーが属するアカウントを
読み取ります。それがどのアカウントかは `chatgpt_ads_account_get` でわかります。

Advertiser API のキーは OpenAI プラットフォームの API キーとは別物です。
mureo が ChatGPT Ads のために `OPENAI_API_KEY`（Creative Studio が画像生成に
使うもの）を読むことはありません。

## 2. キーを mureo に渡す

```bash
mureo configure
```

**Ads API キー**（Ads API key）欄にキーを貼り付けて保存します。入力できる
場所は 2 つあります:

- ステップウィザード: プラットフォームの選択で **ChatGPT Ads** を選ぶと、
  認証のステップにこの欄が出ます。
- ダッシュボード: **接続先の認証情報**（Connection credentials）セクションの
  **ChatGPT Ads** タブ。

値は `~/.mureo/credentials.json` の `chatgpt_ads` セクションに保存されます:

```json
{
  "chatgpt_ads": {
    "api_key": "..."
  }
}
```

この欄はシークレット項目です。✓ 設定済み / ✗ 未設定 のどちらかを表示し、
入力欄は常に空です。空のまま保存すると保存済みの値が保持されます。ツールは
キーの有無にかかわらず一覧に出ます。キーは呼び出しのたびに読み込むため、
保存したあとに MCP サーバーを再起動する必要はありません。

### 環境変数

| 変数 | 必須 | 説明 |
|------|------|------|
| `CHATGPT_ADS_API_KEY` | 何も保存されていない場合 | `chatgpt_ads` セクションに使えるキーが無いときだけ読み込む |

空の値と空白だけの値は、どちらの置き場所でも未設定として扱います。

### プロバイダを無効にする

プロバイダは既定で登録されます。MCP サーバーまたは `mureo configure` を
起動する前に `MUREO_DISABLE_CHATGPT_ADS=1`（文字列 `1` ちょうど）を設定すると、
プロバイダを丸ごと外せます。ChatGPT Ads のツールは一覧に出ず、認証情報の
カードも表示されず、サーバーの `instructions` に ChatGPT Ads の配信モデルの行も
入りません（[エージェントに伝えられること](#エージェントに伝えられること)を
参照）。

## ツール

どのツールもアカウントの引数を取りません（キーがアカウントを決めます）。
スキーマに無い引数は拒否します。読み取りツールには `readOnlyHint` が
付きます。アカウントを変更するツールは[変更](#変更)、[作成](#作成)、
[アーカイブ](#アーカイブ)に、オーディエンスと計測のツールは
[カスタムオーディエンス](#カスタムオーディエンス)と
[コンバージョン計測](#コンバージョン計測)に載せています。

| ツール | API | 引数（既定値） |
|------|-----|----------------------|
| `chatgpt_ads_account_get` | `GET /ad_account` | *（なし）* |
| `chatgpt_ads_account_spend_limits_get` | `GET /ad_account/spend_limit_windows` | *（なし）* |
| `chatgpt_ads_campaigns_list` | `GET /campaigns` | `name`、`include_serving_issues`（false）、`limit`（50） |
| `chatgpt_ads_campaigns_get` | `GET /campaigns/{campaign_id}` | `campaign_id`（必須）、`include_serving_issues`（false） |
| `chatgpt_ads_ad_groups_list` | `GET /ad_groups` | `campaign_id`、`name`、`limit`（50） |
| `chatgpt_ads_ad_groups_get` | `GET /ad_groups/{ad_group_id}` | `ad_group_id`（必須） |
| `chatgpt_ads_ads_list` | `GET /ads` | `ad_group_id`、`name`、`limit`（50） |
| `chatgpt_ads_ads_get` | `GET /ads/{ad_id}` | `ad_id`（必須） |
| `chatgpt_ads_insights_report` | `GET /ad_account/insights`、`/campaigns/{id}/insights`、`/ad_groups/{id}/insights`、`/ads/{id}/insights` | `period`（`last_30d`）、`level`（`campaign`）、`campaign_id` / `ad_group_id` / `ad_id` のうち最大 1 つ、`time_granularity`（`none`）、`metrics`（配信指標のセット）、`attribution_window_days`（API の既定値）、`limit`（1000） |
| `chatgpt_ads_change_history_list` | `GET /audit_logs` | `period`（`last_7d`）、`campaign_id`、`ad_group_id`、`ad_id`、`limit`（50） |
| `chatgpt_ads_ads_preview` | `POST /ads/{ad_id}/preview` | `ad_id`（必須） |
| `chatgpt_ads_locations_search` | `GET /geo_lookup/search` | `query`（必須、`q` として送信）、`limit`（20） |

- **ID**（`campaign_id`、`ad_group_id`、`ad_id`）は
  `^[A-Za-z0-9_-]{1,128}$` に一致する必要があります。一致しないものは
  リクエストを送る前に拒否します。
- **`include_serving_issues`** は `include[]=serving_issues` を付けます。
  キャンペーンが配信されていない理由をプラットフォームが返します。
- **`name`** は 1 行（どこにも改行を含まない）で 3〜1000 文字、空白だけでは
  ないものです。
- **`limit`** は 1〜1000 です。一覧ツールは API のカーソル
  （`has_more` / `last_id` → `after`）をたどって、その件数がそろうまで行を集め、
  1 つの平らな JSON 配列で返します。カーソルは返しません。`limit` を超えた行は
  知らせずに捨てます。日次のインサイトレポートはエンティティごと・日ごとに 1 行を
  返すため、`limit` は少なくとも「エンティティ数 × 日数」が必要です。
- **単体の取得**はプラットフォームのオブジェクトをそのまま返します。
- **`chatgpt_ads_account_spend_limits_get`** はアカウントの利用上限を
  そのまま返します。期間指定の上限、有効または予定中の 1 日のルール
  （`daily_limit` / `daily_limits`。使用済みと残りの micros を含む）、
  `revision`、開始日として指定できる最も早い日です。応答するのは請求書払いの
  アカウントと、請求を管理できるキーに限られます。
- **`chatgpt_ads_ads_preview`** はプラットフォームのプレビューをそのまま
  返します。`data[].body` は 24 時間で期限が切れる HTML の iframe
  スニペットです。これは `POST` ですが、キャンペーン・広告グループ・広告を
  変更しません（プラットフォームは期限付きのプレビューのスナップショットを
  描画して保存します）。そのため読み取りとして扱い、`GET` と同じく
  再試行します。下書きの広告はプレビューできません。
- **`chatgpt_ads_locations_search`** は地域と市場を名前で検索します。
  `query` は 1〜200 文字で空白だけではないもの、`limit` は 1〜100 です。
  応答（`query`、`count`、`id`・`name`・`canonical_name`・`type`・
  `country_code` と親の項目を持つ `results`）はそのまま返します。結果の `id` は
  キャンペーン作成の `targeting.locations.include` に入れます。

### 変更

| ツール | API | 引数 |
|------|-----|-----------|
| `chatgpt_ads_campaigns_pause` / `_enable` | `POST /campaigns/{campaign_id}/pause` / `/activate` | `campaign_id`（必須） |
| `chatgpt_ads_ad_groups_pause` / `_enable` | `POST /ad_groups/{ad_group_id}/pause` / `/activate` | `ad_group_id`（必須） |
| `chatgpt_ads_ads_pause` / `_enable` | `POST /ads/{ad_id}/pause` / `/activate` | `ad_id`（必須） |
| `chatgpt_ads_campaigns_update` | `POST /campaigns/{campaign_id}` | `campaign_id`（必須）、`name` / `start_time` / `end_time` のうち 1 つ以上 |
| `chatgpt_ads_campaigns_update_budget` | `GET /campaigns/{campaign_id}` のあと `POST /campaigns/{campaign_id}` | `campaign_id`、`budget`（どちらも必須）、`current_daily_budget`、`projected_total_daily_budget` |
| `chatgpt_ads_ad_groups_update` | `POST /ad_groups/{ad_group_id}` | `ad_group_id`、`name`（どちらも必須） |
| `chatgpt_ads_ad_groups_update_bid` | `POST /ad_groups/{ad_group_id}` | `ad_group_id`、`bidding_config`（どちらも必須） |
| `chatgpt_ads_account_daily_spend_limit_set` | `GET /ad_account/spend_limit_windows` のあと `POST /ad_account/daily_spend_limit` | `amount_micros`（必須） |

各ツールはプラットフォームの応答をそのまま返します。更新後のキャンペーン、
広告グループ、広告、またはアカウントの上限の場合は変更後のアカウントの
利用上限です。アーカイブは別のツールで、元に戻せません
（[アーカイブ](#アーカイブ)を参照）。予算と入札の変更は、汎用の更新ツールの
項目ではなく、それぞれ専用のツールにしています。mureo はプラットフォームの
変更履歴を `action_log` と照合するとき（`mureo_external_changes_import`）、
記録された変更の種類をツール名から読み取るためです。予算の変更を汎用の
キャンペーン編集の名前で記録すると、mureo 自身の予算変更だと見分けられなく
なります。

- **一時停止と再開**は本文を送りません。`enable` はエンティティを再び
  費用が発生しうる状態に戻します。すでに一時停止中のキャンペーンへの
  一時停止は受け付けられ、キャンペーンが変わらないまま返ります。
- **`name`** は 1 行（どこにも改行を含まない）で 3〜1000 文字、空白だけでは
  ないものです。
- **`start_time` / `end_time`** は 946684800（2000-01-01）から
  4102444800（2100-01-01）までの Unix 秒、またはその端を消す `null` です。
  キーがあれば（`null` でも）変更し、キーを省いた項目はそのままです。
- **`budget`** は新しい予算オブジェクトの全体です。
  `daily_spend_limit_micros` と `lifetime_spend_limit_micros` のどちらか
  または両方で、それぞれ 1000000 以上、ほかの項目は入れません。
  プラットフォームはオブジェクト全体を置き換えるため、省いたキーは消えます。
  金額は前の金額に足されるのではなく、置き換わります。プラットフォームは、
  すでに使った金額を下回る通算予算を拒否します。広告グループの実効入札額を
  下回る日予算を拒否することもあります。
- **予算の種類は変えられません。** ツールはまずキャンペーンを読み取り
  （リクエストが 1 回増えます）、現在の予算が持つ金額（`null` 以外の値）と
  送るキーを比べます。違う場合（日予算を通算予算として送った、金額を 1 つ
  足した、または 1 つ外した）は何も変えずに
  `{"status": "refused", "error": "budget_kind_change", ...}` を返し、
  両方のキーの組を示します。現在の予算がどちらの金額も持たない場合は、
  同じ拒否を `budget_unreadable` で返します。予算の種類は Ads Manager で
  変えてください。`daily_spend_limit_micros` を含まない予算を送ると、
  キャンペーンの日予算の上限が消えてしまい、日予算の上限では捉えられません。
- **`current_daily_budget` / `projected_total_daily_budget`** は任意の
  0 以上の数値で、micros ではなく**アカウント通貨の単位**です（75.0 は
  75.00）。キャンペーンの現在の日予算と、変更後のアカウント全体の
  キャンペーン合計の日予算を表します。これらはプロバイダ共通の予算の文脈キー
  です。STRATEGY.md の上限 `max_daily_budget_increase_pct` と
  `max_total_daily_budget` がこれを読み、無い場合はこの 2 つの上限を判定
  できません。値は検査しますが、プラットフォームには送りません。取り消し
  操作にも含めません。
- **`bidding_config`** は新しい入札設定の全体で、プラットフォームはこれも
  丸ごと置き換えます。項目は `billing_event_type`（`impression` または
  `click`、必須）、`strategy`（`fixed_bid`、`maximize_clicks`、
  `maximize_conversions`）、`max_bid_micros`（1〜30400000000000）、
  `custom_audience_bid_multipliers`（`custom_audience_id` と
  `bid_multiplier_micros` を持つ要素の配列。`custom_audience_id` は英字・数字・
  `_`・`-` からなる 1〜128 文字の ID、`bid_multiplier_micros` は
  100000〜10000000 で、1000000 が 1.0 倍）です。
  `strategy` と `max_bid_micros` を両方省くと自動入札になります。応答では
  `automated_bid`、クリックのキャンペーンでは `maximize_clicks` と表示されます。
  固定入札は `strategy` / `max_bid_micros` ではなく、`target_strategy`
  （クリック課金では `target_cpc`）と `target_micros` として読み戻されます。
  インプレッション課金の入札額は 1,000 回あたりではなく 1 回あたりです
  （CPM / 1000）。
- **入札の上限が及ぶ範囲。** `max_cpc_bid_per_ad_group` と
  `max_bid_amount_per_ad_set` はどちらも `max_bid_micros` だけを読みます。
  運用者がどちらを書いたかは広告グループの課金イベントとは関係がないため、
  設定されているものはそれぞれ入札額を抑えます。オーディエンスの入札
  調整率（最大 10 倍）と、入札額を持たない戦略（自動入札、
  `maximize_clicks`、`maximize_conversions`）はこれらの上限の対象外です。
  インプレッション課金では金額が 1 回あたり（CPM = 金額 × 1000）なので、
  クリック単価の上限では実質的に抑えられません。費用を抑えるのは
  キャンペーンの予算です。
- **`amount_micros`** は 0 以上の整数です。プラットフォームは通貨の最小単位の
  倍数を想定していますが、mureo はそれを検査しません。STRATEGY.md の上限
  `max_daily_budget_per_campaign` もこの金額を抑えます。上限はアカウント
  全体のものですが、mureo のポリシーゲートは `amount_micros` 引数を、宣言の
  有無にかかわらず micros の日予算として読むためです。

ここと次の節で引いているプラットフォームの規則（どの予算と上限を拒否するか、
どのアカウントとキーがアカウントの上限を使えるか）は API リファレンスの
ものです。mureo 自身はそれを強制しません。

引数はすべて最初のリクエストの前に検査します。整数を想定する場所に bool や
float を渡すと拒否します。

### アカウントの 1 日の利用上限

アカウントの上限はすべてのキャンペーンで共有され、アカウントのタイムゾーンの
午前 0 時に更新されます。プラットフォームがこれを提供するのは請求書払いの
アカウントで、請求を管理できるキーに限られます。そうでない場合の応答は
`feature_not_enabled` か API エラーです。その日にすでに計上された費用を
下回る金額への引き下げは、プラットフォームが拒否します
（`budget_window_amount_below_spend`）。

`chatgpt_ads_account_daily_spend_limit_set` は、まず利用上限を読み取ります。
送るリクエストの形には期間の ID が無いため、1 日のルールが複数あるとき
どれを指すかを示せません。有効または予定中のルールが 2 つ以上ある場合は
何も変えずに
`{"status": "refused", "error": "multiple_daily_spend_limits", "detail": ...}`
を返し、Ads Manager を案内します。それ以外の場合は、読み取った `revision`
（応答に無ければ 0）を `expected_revision` に入れて金額を送ります。そのため、
間に加えられた変更を黙って上書きすることはありません。また書き込みの前に、
応答が JSON オブジェクトでない場合、`revision` が 0 以上の整数でない場合、
`daily_limits` が配列でない場合、`daily_limit` がオブジェクトでない場合
（どちらも `null` は可）は、何も変更していないことを示す API エラーで
止まります。`daily_limits` が空でない配列ならそれがルールの一覧で、そうで
なければ 1 つの `daily_limit` がルールです（無い、または `null` ならルール
なし）。

### 作成

| ツール | API | 引数 |
|------|-----|-----------|
| `chatgpt_ads_campaigns_create` | `POST /campaigns` | `name`、`budget`、`bidding_type`（必須）、`targeting`、`start_time`、`end_time`、`conversion_event_setting_ids`、`projected_total_daily_budget`、`idempotency_key` |
| `chatgpt_ads_ad_groups_create` | `POST /ad_groups` | `campaign_id`、`name`、`bidding_config`（必須）、`context_hints`、`idempotency_key` |
| `chatgpt_ads_ads_create` | `POST /ads` | `ad_group_id`、`name`、`creative`（必須）、`idempotency_key` |
| `chatgpt_ads_images_upload_file` | `POST /upload`（multipart の項目 `file`） | `file_path`（必須） |

各作成ツールは新しいプラットフォームのオブジェクトをそのまま返します。
その `id` が次の階層の作成に必要です（キャンペーン → 広告グループ → 広告）。

- **常に一時停止の状態。** 作成ツールは `status` を取りません。mureo は常に
  `"status": "paused"` を送り、`status` 引数は拒否します。作成した
  キャンペーン、広告グループ、広告は `status` `paused` を返します。mureo で
  作成したものは、対応する `*_enable` ツールを呼ぶまで費用が発生しません。
- **`budget`** は `daily_spend_limit_micros` と
  `lifetime_spend_limit_micros` のちょうど 1 つを取ります（1000000 以上。
  両方とどちらも無しはプラットフォームが拒否し、mureo も送る前に拒否します）。
  プラットフォームは通貨ごとの最低額を下回る日予算も 400 で拒否し、その
  メッセージに最低額が micros で示されます（JPY では 2,500,000,000）。mureo は
  これを事前に検査しません。STRATEGY.md の
  `max_daily_budget_per_campaign` は通算予算を抑えません。
  `lifetime_spend_limit_micros` だけの作成は、金額がどれほど大きくてもこの
  上限を通ります。その金額を抑えるのは `max_lifetime_budget_per_campaign`
  だけです。
- **`bidding_type`**（`impressions`、`clicks`、`conversions`）は、
  キャンペーンを作成したあとは変えられません。プラットフォームはこれを
  広告グループの入札と組み合わせます。`impressions` はインプレッション課金と
  `fixed_bid`、`clicks` はクリック課金と `fixed_bid` または
  `maximize_clicks`、`conversions` はクリック課金と `fixed_bid` または
  `maximize_conversions` で、コンバージョンイベント設定がちょうど 1 つ
  必要です。最大化の戦略には日予算が必要です。mureo はこれらの規則をツールの
  説明に書き、判定はプラットフォームに任せます。広告グループの作成ツールは、
  もう 1 回読み取らないとキャンペーンの `bidding_type` を知らないためです。
- **`targeting`** はそのまま渡します。どの階層でも、文書化されたキーだけを
  受け付けます。`locations` / `excluded_locations`（`countries` は最大 250 個の
  ISO 3166-1 alpha-2 コード、`include` は最大 2500 個の地域オブジェクトで、
  その `id` は `chatgpt_ads_locations_search` から得る）、`custom_audiences` /
  `excluded_custom_audiences`（`ids`、最大 1000 個）、`platforms.included`
  （`ios_app`、`android_app`、`web`、`desktop_web`、`ios_web`、
  `android_web`）です。省くとプラットフォームの既定値が適用されます。
  `include` オブジェクトの説明的な項目（`name`、`type`、`country_code`、
  `region_code`。検索結果から写すもの）は、それぞれ最大 255 文字です。
- **mureo 独自の上限。** 次の項目にはプラットフォームが上限を示していない
  ため、1 回のリクエスト本文の大きさを抑えるために mureo が上限を決めています。
  `countries` は最大 250 個（ISO 3166-1 が割り当てているコードは 249 個）、
  オーディエンスの ID と `conversion_event_setting_ids` はそれぞれ最大
  1000 個、`include` の説明的な項目は 1 項目あたり最大 255 文字、
  `context_hints` の各要素は 1〜1000 文字です。スキーマとハンドラーの両方が、
  リクエストの前にこれを強制します。
- **`start_time` / `end_time`** はキャンペーンの更新と同じ範囲の Unix 秒です。
  `null` は拒否します。代わりにキーを省いてください。
- **`conversion_event_setting_ids`**（最大 1000 個）と `targeting` の中の ID は、
  上の ID の規則に従います。
- **`projected_total_daily_budget`** は予算ツールと同じ任意の文脈キーです
  （通貨の単位で、検査し、送らない）。これで `max_total_daily_budget` を
  判定できます。`current_daily_budget` は新しいキャンペーンには意味が無いため、
  提供していません。
- **`bidding_config`** は `chatgpt_ads_ad_groups_update_bid` と同じ
  オブジェクトで、入札の上限が及ぶ金額も同じです
  （[入札の上限が及ぶ範囲](#変更)を参照）。
- **`context_hints`** は配置の手がかりになる自由記述の文字列で、最大 2000 個、
  各 1〜1000 文字です。配信対象を厳密に決める規則ではありません。
- **`creative`** は 1 枚画像のチャットカードで、mureo が提供する唯一の
  クリエイティブの種類です。`type` は `chat_card`、`title` は 1 行で 3〜50
  文字、`body` は最大 100 文字です。`target_url` は `http` / `https` の
  ランディングページです（最大 2048 文字、必須。ホストが必要で、
  `user:password@` のようなユーザー情報、バックスラッシュ、空白、制御文字は
  拒否します。mureo はページを取得せず、取得はプラットフォームが自身の審査で
  行うため、mureo が見るのは形だけです）。`file_id` は画像アップロードで
  得たもので、`image_crop`（`x`、`y`、`width`、`height`。それぞれ 0〜1 の
  割合。`file_id` があるときだけ）も指定できます。複数画像と商品テンプレートの
  クリエイティブは提供していません。
- **審査。** 広告は作成時に `review_status` `in_review` を返し、のちに
  `approved` または `rejected` になります。`chatgpt_ads_ads_get` で読み取って
  ください。

**冪等キー。** 各作成ツールは `Idempotency-Key` ヘッダーを送ります。値は
`idempotency_key` 引数（英字・数字・`_`・`-` からなる 1〜255 文字）か、mureo が
呼び出しごとに 1 回生成するキーです。1 回の呼び出しの試行はすべて同じキーを
使います。プラットフォームの文書によると、同じキーで繰り返したとき、一致する
以前の作成がプラットフォームから見えていれば、重複して作らずに既存の
オブジェクトを返します。そのため作成は、ほかの変更と違って 5xx で再試行します
（`GET` と同じく合計最大 3 回）。再試行は通常のバックオフを待ってから
繰り返します。処理中の作成が繰り返しの時点で見えているかどうかは文書化されて
いません。同じキーで繰り返すと、同じ ID の以前のエンティティが返り、応答には
キーが `user_external_id` として入ります。同じキーで本文が違う繰り返しも
拒否されず、以前のエンティティがそのまま返ります。そのため、キーを別の
エンティティに使い回してはいけません。作成が 5xx、JSON でない成功の本文、
通信エラー、呼び出しの期限切れで終わった場合、エラー文の最後には
「適用された可能性がある」の文の代わりにキーが入ります: `The entity may have been
created; repeat the call with idempotency_key="<key>" and the same arguments:
when the platform can see the earlier create it returns that entity instead of
creating a second one.` キーは秘密情報ではありません。

**画像。** `chatgpt_ads_images_upload_file` は、何かを送る前に、mureo のほかの
画像アップロードと同じ方法でローカルのファイルを検査します。拡張子は `.jpg`、
`.jpeg`、`.png`、`.webp` のいずれかであること。ファイルが存在し、通常の
ファイルで、中身が拡張子の示す形式だと判定されること（画像でないファイルや、
画像へのリンクに画像の拡張子が付いていても拒否します）。`..` を含む場所は
拒否します。ファイルは最大 30MB です（プラットフォームは大きさの上限を
示していません。この上限は mureo の Meta Ads の画像アップロードと同じです）。
プラットフォームはクリエイティブの画像に JPEG、PNG、WebP で 640×640 ピクセル
以上を求めていますが、mureo はそれを検査しません。ファイルはファイル名と、
拡張子に対応する content type を付けて送ります。ファイルを開くのは 1 回だけで、
検査したバイト列がそのまま送るバイト列です。返った `file_id` は
`creative.file_id` に入れます。アップロードは 5xx や通信エラーでは再試行
しません（429 はほかのリクエストと同じく再試行します）。
プラットフォームや通信のエラーに、ファイルの場所や中身のバイト列が引用される
ことはありません。拒否した場所は引数のエラーで示します。

**作成を元に戻す。** 取り消し操作は記録されず、`rollback_apply` で作成を
元に戻すことはできません。エンティティは呼び出しの前には ID を持たないため
です。手で元に戻すには、一時停止のままにしておくか（費用は発生しません）、
確信が持てた時点で対応する `*_archive` ツールでアーカイブします（元に戻せません）。

### アーカイブ

| ツール | API | 引数 |
|------|-----|-----------|
| `chatgpt_ads_campaigns_archive` | `POST /campaigns/{campaign_id}/archive` | `campaign_id`（必須） |
| `chatgpt_ads_ad_groups_archive` | `POST /ad_groups/{ad_group_id}/archive` | `ad_group_id`（必須） |
| `chatgpt_ads_ads_archive` | `POST /ads/{ad_id}/archive` | `ad_id`（必須） |

アーカイブは本文を送らず、更新後のオブジェクトをそのまま返します。これは
**元に戻せません**。プラットフォームには復元の操作が無く、mureo は取り消し
操作を記録せず、`rollback_plan_get` はそのエントリを非対応として報告します。
これらのツールには `destructiveHint` が付きます（オーディエンスのメンバー削除も
同じです。[カスタムオーディエンス](#カスタムオーディエンス)を参照）。元に戻せる
形で費用を止めるには、一時停止を使ってください。
キャンペーンをアーカイブしても、その広告グループと広告はアーカイブされません。
それらは状態を保ち、1 つずつアーカイブします。アーカイブしたキャンペーンは
`chatgpt_ads_campaigns_list` の既定の応答に含まれません。広告グループを
アーカイブするとその広告もアーカイブされるかどうかは、文書化されていません。

### カスタムオーディエンス

| ツール | API | 引数（既定値） |
|------|-----|----------------------|
| `chatgpt_ads_audiences_list` | `GET /custom_audiences` | `intended_use`（`inclusion` \| `exclusion` \| `bid_multiplier`）、`limit`（50） |
| `chatgpt_ads_audiences_get` | `GET /custom_audiences/{custom_audience_id}` | `audience_id`（必須） |
| `chatgpt_ads_audiences_create` | `POST /custom_audiences` | `name`（必須）、`description` |
| `chatgpt_ads_audiences_members_add` | `POST /custom_audiences/{custom_audience_id}/add` | `audience_id`、`file_path`、`identifier_type`（必須）、`idempotency_key` |
| `chatgpt_ads_audiences_members_remove` | `POST /custom_audiences/{custom_audience_id}/remove` | `audience_id`、`file_path`、`identifier_type`（必須）、`idempotency_key` |
| `chatgpt_ads_audiences_operations_get` | `GET /custom_audiences/{custom_audience_id}/operations/{operation_id}` | `audience_id`、`operation_id`（必須） |

オーディエンスの ID の引数は、どのツールでも `audience_id` です（mureo の
ほかのオーディエンスツールが使う名前）。値はパスに入れて送ります。

- **オーディエンスの作成。** `chatgpt_ads_audiences_create` が送るのは
  `name`（1 行で 3〜1000 文字、空白だけではないもの）と、指定されたときの
  `description`（最大 1000 文字。プラットフォームは上限を示していないため、
  mureo は名前と同じ上限を使います）だけです。ファイルは送らないため、
  オーディエンスは空の状態で始まります。空のオーディエンスには、アカウントで
  小規模オーディエンスが有効になっている必要があります。新しいオーディエンスは
  状態 `rockset_ingest_pending` を返し、その後 `ready` になります。使う前に
  `ready` を待ってください。作成から数秒間は `chatgpt_ads_audiences_list` に
  出ないことがあります。プラットフォームはこの呼び出しに冪等キーを用意して
  いません。応答が失われた場合、エラーは「適用された可能性がある」の文で
  終わります。リファレンスは、もう 1 つ作る前にオーディエンスの一覧を確かめる
  ように書いています。
- **利用の条件。** 配信対象として、または入札調整に使うオーディエンスには、
  一致したユーザーが 25,000 人以上必要です。除外には最低人数がありません。
  EEA またはスイスを配信対象とするキャンペーンでは、カスタムオーディエンスは
  使えません。
- **権利と同意。** アップロードするのは、この目的に使う権利と同意を得ている
  ファーストパーティデータだけにしてください。これは運用者の責任で、mureo は
  確認しません。

**識別子ファイル。** 追加と削除のツールは、識別子を引数として受け取りません。
ツールの引数は mureo の監査証跡に書かれ、モデルを通るためです。代わりに
ローカルのファイルを読みます:

- **形式。** UTF-8 のテキスト（バイトオーダーマークは可）、拡張子は `.txt` か
  `.csv`、1 行に 1 つの識別子、見出し行なし。どの行も `identifier_type` が示す
  種類（`email`、`phone`、`gaid`、`email_sha256`、`phone_number_sha256`）を
  持ちます。前後の空白は取り除き、空行は飛ばし、正規化後の重複は捨てます。
  その結果、ファイルには 1〜10,000 個の異なる識別子が必要です（リファレンスの
  インラインの小規模更新の経路）。識別子が無いファイルは
  `file_path holds no identifiers; give one per line` で拒否し、それより多い
  ファイルは件数を示して分割を求めます。1 行は 1 つの値です。引用符で囲んだ値や
  カンマ区切りの行は無効な行です。プラットフォーム自身の CSV アップロードの
  形式（見出し行あり、複数列）はこのファイルとは別物です。その 1 列だけを
  書き出してください。
- **場所の規則**は画像アップロードと同じです。ファイルが存在し、通常の
  ファイルで、最大 2 MiB であること。`..` を含む場所は拒否します。ファイルを
  開くのは 1 回だけで、読んだバイト列がそのまま解析するバイト列です。
- **ハッシュ化するもの。** `email` は前後の空白を取り、小文字にします
  （ドット、プラスのタグ、アポストロフィは残します）。そのうえで単純な ASCII の
  アドレスである必要があります。空白を含まない表示可能な ASCII だけで、`@` が
  ちょうど 1 つあってその両側に文字があり、`"` `,` `;` `:` `<` `>` `(` `)` `[`
  `]` `\` を含まず、ドメインがドットを含み、ドットやハイフンで始まらず終わらない
  ことです。ASCII 以外の文字を含むアドレスは拒否します。プラットフォームが
  それをどう正規化するかをリファレンスが示していないためです。そうした
  アドレスはご自身でハッシュ化し、`email_sha256` で渡してください。有効な
  アドレスは UTF-8 のバイト列の SHA-256 を小文字の 16 進で、種類
  `email_sha256` として送ります。`phone` はスペース、ハイフン、ドット、括弧を
  取り除いたうえで E.164（`+`、1〜9 の先頭の数字、全体で 7〜15 桁）である
  必要があり、`+` を含めてハッシュ化し、種類 `phone_number_sha256` として
  送ります。`+` と国番号の無い番号は無効で、国の推測はしません。括弧で囲んだ
  国内の頭の 0 を含む番号（`+44 (0)20 ...`）も無効です。括弧を取ると、番号の
  一部ではない 0 が残るためです。`email_sha256` と `phone_number_sha256` の行は
  16 進 64 文字である必要があり、小文字にします。`gaid` はすべて 0 ではない
  ハイフン区切りの正規の UUID である必要があります。小文字にし、プラット
  フォームの求めに従ってハッシュ化せずに送ります。
- **端末から出るもの。** ダイジェストと生の広告 ID だけで、
  `{"identifiers": [{"identifier_type", "identifier"}, ...]}` の形です。
  平文の種類 `email` と `phone` は送らず、ファイルの場所も送りません。
- **無効な行が 1 つでもあれば呼び出しを拒否します。** リクエストの前に、
  `ValueError` が無効な行の数と最大 10 個の行番号を示します。メッセージ、
  ログの行、結果のどれも、ファイルの行を引用しません（一部であっても）。
  UTF-8 として正しくないファイルは、そのバイト列を引用せずに拒否します。
- **監査証跡**は呼び出しの引数を記録するため、ファイルの場所と識別子の種類は
  残りますが、識別子は残りません。追加や削除のプラットフォームのエラーでは、
  ダイジェストや広告 ID のように見えるものを、文を返す前・ログに書く前に
  `***` に置き換えます。

**非同期の操作。** 追加と削除は、プラットフォームの操作オブジェクトを
そのまま返します（`operation_id`、`status` は `processing`、`succeeded`、
`failed` のいずれか、失敗時は `failure_reason`）。`processing` でなくなるまで
`chatgpt_ads_audiences_operations_get` で状態を確かめてください。
`succeeded` は操作が終わったことを示し、すべての識別子がユーザーに一致した
ことは示しません。オプトアウトの一覧から作った削除では、アップロードした
ときと違う表記からハッシュ化した行は、誰も削除しません。

**削除は破壊的です。** `chatgpt_ads_audiences_members_remove` には、
アーカイブと同じく `destructiveHint` が付きます。削除したものは戻らず、
削除によってオーディエンスが、配信対象と入札調整に必要な一致ユーザー
25,000 人を下回ることがあります。

**冪等キー。** プラットフォームは追加と削除に `Idempotency-Key` を求めます。
mureo は作成ツールとまったく同じく、`idempotency_key` 引数か、呼び出しごとに
1 回生成するキーを送り、5xx では同じキーと本文で再試行します。リファレンスに
よると、同じキーで繰り返すと最初に受け付けた操作を返すか再開し、その際に
新しい本文を確かめないことがあります。そのため追加や削除が 5xx、JSON でない
成功の本文、通信エラー、期限切れで終わった場合、エラーは次の文で終わります:
`The operation may have been accepted;
repeat the call with idempotency_key="<key>", the same arguments and the same
file: a repeat with that key returns or resumes the first accepted operation
instead of starting a second one.` キーを使い回すのは、同じ呼び出しを
再試行するときだけにしてください。

**取り消し操作なし。** 追加も削除も取り消し操作を記録せず、`rollback_apply`
で元に戻すこともできません。追加したものを削除すると、追加の前から
オーディエンスにいたメンバーも消えてしまうため、反対の呼び出しは復元に
なりません。オーディエンスの作成も取り消し操作を記録しません。

### コンバージョン計測

| ツール | API | 引数（既定値） |
|------|-----|----------------------|
| `chatgpt_ads_pixels_list` | `GET /conversions/pixels` | `limit`（50） |
| `chatgpt_ads_pixels_create` | `POST /conversions/pixels` | `name`（必須） |
| `chatgpt_ads_conversion_events_list` | `GET /conversions/event_settings` | `limit`（50） |
| `chatgpt_ads_conversion_events_create` | `POST /conversions/event_settings` | `name`、`event_type`、`source_id`（必須）、`custom_event_name` |
| `chatgpt_ads_conversions_report` | `POST /conversions/insights` | `period`（`last_30d`）、`level`（`campaign`）、`entity_ids`、`group_by_entity`、`time_granularity`、`breakdown`、`attribution_time_basis`、`attribution_window_days`、`view_through_attribution_window_days`、`include_events`、`event_names`、`include_zero_rows` |

- **ピクセル。** ピクセルはウェブのコンバージョンの発生元です。作成ツールは
  常に `client_type` `web` を送ります。文書化されている値はこれだけです。
  応答には、イベント設定が受け取る発生元の ID である `id` と、JavaScript
  ピクセルの初期化に使う `pixel_id` が入ります。イベント設定が受け取るのは
  `pixel_id` ではありません。ピクセルは API では編集も削除もできません。
- **イベント設定は恒久的です。** API にはコンバージョンイベント設定を編集・
  削除するエンドポイントが無いため、作成ツールの説明の冒頭にそのことを
  書いています。`name` は 1 行で 1〜1000 文字です（プラットフォームが示すのは
  最小 1 だけで、最大はありません）。`event_type` は ID のパターンに従い、
  文書化されている値は `app_installed`、`app_opened`、
  `appointment_scheduled`、`checkout_started`、`contents_viewed`、`custom`、
  `items_added`、`lead_created`、`order_created`、`page_viewed`、
  `registration_completed`、`subscription_created`、`trial_started` です。
  `custom_event_name` は `event_type` が `custom` のときに必須で、それ以外では
  拒否します。英字・数字・`_`・`-` からなる 1〜64 文字で、英字か数字で始まり
  英字か数字で終わります（プラットフォームは標準のイベント名も拒否し、小文字に
  します）。`source_id` はピクセルの `id` 1 つで、`source_ids: [source_id]` と
  して送ります。リファレンスには `Client data source not found` の応答が載って
  おり、これは `source_id` がこのアカウントのピクセルではないことを示します。
  `attribution_window_days` は引数にありません。設定はあとから変えられないため、
  すべての設定を、リファレンスが示す唯一の値である 30 で作成します。
- **冪等キーなし。** どちらの作成ツールも冪等キーを持ちません。応答が失われると
  「適用された可能性がある」の文で終わります。もう一度作る前に一覧を確かめて
  ください。新しいコンバージョンイベント設定は、作成から数秒間
  `chatgpt_ads_conversion_events_list` に出ないことがあります。
- **機能の有効化。** リファレンスによると、アカウントでコンバージョンが有効に
  なっていない場合、ピクセルのコレクションは `404 Not found` を返します。
  ピクセルの一覧と作成では、mureo は 404 を `feature_not_enabled` の結果として
  報告します。イベント設定やコンバージョンのレポートからの 404 は、通常の意味の
  まま（`API error: HTTP 404 ...` の文）です。ピクセルもイベント設定もまだ無い
  アカウントは、それだけでは無効扱いになりません。一覧は空で返り、作成は
  受け付けられます。
- **レポート。** `chatgpt_ads_conversions_report` はプラットフォームの応答を
  そのまま返します。`data` の行には `entity_id`、該当する場合は `date` /
  `country` / `device`、`conversions`（選んだ期間内のクリックとビュースルーの
  合計）、`click_through_conversions`、`view_through_conversions`、
  `order_created_attributed_sales` が入ります。`include_events` を指定すると
  イベントごとの `attributed_events` も入り、ほかに `count` と
  `account_currency` が入ります。これは何も変更しない `POST` なので、
  `readOnlyHint` が付き、`GET` と同じく再試行し、失敗時に変更が適用された
  可能性を示すことはありません。
- **レポートの引数。** `period`、`level`、`time_granularity`、
  `attribution_window_days` は `chatgpt_ads_insights_report` と同じ名前と値を
  取ります（`level` は `campaign`、`ad_group`、`ad`）。
  期間は 1 つの `time_ranges` の要素になり、リファレンスが示す JSON で符号化した
  文字列 `{"type":"unix_range","start":"<unix seconds>","end":"<unix seconds>"}`
  の形で、アカウントのタイムゾーンでの丸 1 日単位、終わりは含まない形です。
  `entity_ids` はその階層の ID で 1〜100 個（リファレンスは上限を示していません。
  1 回のリクエスト本文の大きさを抑えるための上限です）、`group_by_entity` が
  true（プラットフォームの既定値）の間は必須です。`group_by_entity` が false で
  `entity_ids` が無い場合、行はアカウント全体を対象にします。`breakdown` は
  `country` か `device`、`attribution_time_basis` は `ad_event_time` か
  `conversion_time`、`view_through_attribution_window_days` は 0 か 1 です。
  `include_events` は `include: ["attributed_events"]` を送ります。
  `event_names`（最大 256 文字で空白だけではない名前を 1〜500 個）は
  `include_events` が true でなければ拒否します。`include_zero_rows` は真偽値
  です。送るのは指定したキーと、`aggregation_level` と `time_ranges` だけなので、
  それ以外はすべてプラットフォームの既定値が適用されます。
- **レポートの制限。** ページ送りはありません。集計行が 2,000 行（または
  イベントの行が 2,000 行）を超えると、プラットフォームが 413 で拒否します。
  `entity_ids` か期間を絞ってください。コンバージョンは遅れて計上され、
  直近の日はまだ増えることがあります。少なくとも 1 日待ってください。
- **インサイトレポートとの違い。** 費用や配信の指標と並べてコンバージョンを
  見るなら `chatgpt_ads_insights_report` を、目標の合計、クリックスルーと
  ビュースルーの件数、売上、イベントの詳細を見るならこのレポートを使います。
  インサイトの `conversions` 指標もクリックとビュースルーの合計です。両者を
  比べるのは、エンティティ、日付、期間、時刻の基準が同じときだけにしてください。

### 変更の記録とロールバック

`STATE.json` のあるディレクトリで MCP サーバーが動いている場合、各変更は
その `action_log` に、ツール名と変更したエンティティ（`campaign_id`、
広告グループの ID、`ad_id`）とともに記録されます。アカウント単位の利用上限の
変更はエンティティを持たないため、そのエントリはキャンペーン、広告グループ、
広告のどれも示しません。エラーで終わった呼び出しは記録されません。

変更を送る前に、mureo は読み取りツールの 1 つで変更前の状態を読み取ります。
この読み取りはほかのツール呼び出しと同じく実行され、全体で 15 秒に制限
されます（その中で再試行することがあります。[制限](#制限)を参照）。そのうえで
`rollback_apply` が実行できる取り消し操作を記録します。取り消し操作が持つ値は
すべて、その取り消し操作のツールが引数に対して行うのと同じ検査を通って
いるため、記録された取り消し操作はツールが受け付けるものです:

| 変更 | 記録する取り消し操作 | 取り消し操作を記録しない場合 |
|--------|-------------------|------------------|
| 一時停止 | 対応する `_enable` | エンティティが変更前に `active` でなかった（すでに一時停止中、アーカイブ済みなど） |
| 再開 | 対応する `_pause` | エンティティが変更前に `paused` でなかった |
| `chatgpt_ads_campaigns_update` | 呼び出しが設定した各項目の変更前の値を持つ同じツール | 変更前の値がツールの検査を通る項目が 1 つも無い |
| `chatgpt_ads_campaigns_update_budget` | 変更前の予算の `null` でない金額をすべて持つ同じツール | 変更前の予算がどちらの金額も持たない、または持つ金額のどれかがツールの検査を通らない（文字列、float、0、その他 1000000 未満の値） |
| `chatgpt_ads_ad_groups_update` | 変更前の名前を持つ同じツール | 変更前の名前が無い、またはツールの検査を通らない |
| `chatgpt_ads_ad_groups_update_bid` | 変更前の入札設定を持つ同じツール。変更前が固定入札（`target_strategy` / `target_micros`）なら、変更前の金額で `fixed_bid` として | 変更前の設定にあるもののどれかがツールの検査を通らない: `impression` と `click` 以外の `billing_event_type`、ツールが受け付ける戦略でも `automated_bid` でもない戦略、使えない `max_bid_micros`・`target_micros`・調整率、1000 個を超える調整率。または、設定が mureo の知らない `target_strategy`（クリック課金の `target_cpc` 以外）を持つ、両方の形（`target_*` と `strategy` または `max_bid_micros`）を持つ、mureo の知らないキーを持つ |
| `chatgpt_ads_account_daily_spend_limit_set` | 変更前の金額を持つ同じツール | 変更前に 1 日のルールが無かった（上限の削除は別の操作）、2 つ以上あった、またはその金額がツールの検査を通らない |

キャンペーンの更新では、変更前の値が検査を通らない項目は取り消し操作から外し、
その caveats に名前を挙げます。`rollback_plan_get` はその計画を partial として
報告します。予算、入札設定、広告グループの名前は、丸ごと復元するか、まったく
復元しないかのどちらかです。プラットフォームは予算と入札のオブジェクトを丸ごと
置き換えるため、一部だけ復元すると上限や調整率が消えてしまいます。呼び出しより
低い通算予算を設定する予算の取り消し操作には、すでに使った金額を下回る
通算予算をプラットフォームが拒否する、という caveat が付きます。変更前が
`automated_bid` の設定は `strategy` も `max_bid_micros` も付けずに復元し、
変更前が固定入札（`target_strategy` `target_cpc` と `target_micros` として
読み戻される）の場合は、`max_bid_micros` に変更前の金額を入れた `fixed_bid`
として復元します。mureo の知らない `target_strategy` を持つ設定、両方の形を
持つ設定、mureo の知らないキーを持つ設定は、取り消し操作を記録しません。
プラットフォームはオブジェクトを丸ごと置き換えるため、キーを落としたり推測
したりすると、別の設定を復元してしまうからです。`null` の値は無いものとして
扱います。変更前の読み取りが失敗するか時間切れになった場合、変更は取り消し
操作なしで実行され、ログにはエラーの型だけを書きます。

作成、アーカイブ、画像アップロードも `action_log` に記録されますが、取り消し
操作はありません（[作成を元に戻す](#作成)と[アーカイブ](#アーカイブ)を参照）。
アーカイブはアーカイブしたエンティティを示します。作成は、作るエンティティを
示せません。その ID は呼び出しが返ってはじめて存在するためです。広告グループの
作成はその `campaign_id` を、広告の作成はその広告グループを記録し、
キャンペーンの作成と画像アップロードはエンティティを記録しません。
オーディエンスの追加と削除はオーディエンスを示し（`entity_type: "audience"`）、
取り消し操作を記録しません。オーディエンス、ピクセル、イベント設定の作成は
エンティティを示さず、取り消し操作も記録しません。

ChatGPT Ads には学習期間のリセットの規則を登録していません。プラット
フォームの文書がそれを示していないためです。そのため
`mureo_learning_reset_preflight` は、これらのツールのリセットのリスクを
`unknown` と報告します。

### インサイト

- **範囲と階層。** 範囲の ID がエンドポイントを決めます（無ければアカウント
  全体）。`level`（`account` | `campaign` | `ad_group` | `ad`）は行の
  エンティティを決め、範囲と同じかそれより下の階層である必要があります。
  既定値は `campaign` で、広告グループか広告に範囲を絞った場合はその範囲の
  階層です。
- **指標。** 配信指標: `impressions`、`clicks`、`spend`、`ctr`、
  `cpc`、`cpm`（既定のセット）。コンバージョン指標: `conversions`、`cpa`、
  `post_click_cvr`、`order_created_attributed_sales`、`order_created_roas`。
  それ以外の名前や、同じ名前の重複は拒否します。各行にはエンティティの ID と名前も入り、
  `time_granularity` が `daily` のときは `readable_time` も入ります。
- **粒度。** `none`（期間全体でエンティティごとに 1 行）か
  `daily` です。mureo は常にどちらかを送るため、API 自身の既定値
  （`daily`）が適用されることはありません。
- **アトリビューション。** `attribution_window_days`（7、14、30）は
  コンバージョン指標のクリックの計測期間を決めます。省くと API の既定値（30）が
  適用されます。ビュースルーの計測期間は公開していないため、API の既定値
  （1 日）が適用されます。

### 変更履歴

`chatgpt_ads_change_history_list` は監査ログのエントリをそのまま返します（`id`、
`ts`、`actor_id`、`actor_type`、`audit_log_type`、`obj_type`、`obj_id`、
`item_name`、`changes`）。`period` は Unix 秒の `start_time` / `end_time` として
送ります。範囲は、広告アカウントのタイムゾーンでの初日の午前 0 時から最終日の
最後の 1 秒までです。既定の `last_7d` は昨日までの丸 7 日間で、今日は含み
ません。今日の変更を見るには `today` を渡してください。

## 変更の取り込み

`mureo_external_changes_import` は、mureo の外で（Ads Manager や別の API
クライアントで）広告アカウントに加えられた変更を、同じ監査ログから
`action_log` に記録します。プロバイダはこの変更フィードをツールとともに登録
するため、`plugin:mureo-chatgpt-ads:chatgpt_ads` に対して応答します。
`MUREO_DISABLE_CHATGPT_ADS=1` のときはフィードもありません。取り込みの記録と
重複排除の方法は [change-import.md](change-import.md) を参照してください。

- **取り込むもの。** 取り込みの 1 回の実行が求めた期間内に `ts` がある
  監査ログのエントリが、それぞれ 1 つの `external_change:<TYPE>` エントリに
  なります。`<TYPE>` はエントリの `obj_type` を大文字のスネークケースにした
  もの（`Campaign` → `CAMPAIGN`、`AdGroup` → `AD_GROUP`）です。操作は
  `audit_log_type` の最初の語（`update_campaign` → `UPDATE`）、変更された項目は
  `changes` のうち値を持つキーです。変更された項目は 1 エントリにつき最大 20 個で、
  エントリが示す順に並び、それぞれ英字・数字・`_`・`.` からなります（最大
  64 文字）。監査ログは `changes` にリソースのすべての項目を並べ、そのエントリで
  変わらなかった項目を null にするため、null のキーは変更された項目では
  ありません。ID と操作者は、英字・数字・`_ . : @ -` からなる場合（最大
  200 文字）だけ残します。自由記述の `item_name` は
  写さず、`actor_type` は読みません。これは操作者の種類を示すもので、変更した
  クライアントを示すものではないためです。使える `ts` を持たないエントリや、
  期間外の日付のエントリは飛ばし、注記で件数を示します。未来の日付のエントリが
  1 つあるだけで、次の実行の開始が現在より後にずれてしまうためです。
- **どのアカウントか。** 1 つの API キーが読むのは 1 つの広告アカウントで、
  キーは端末上のすべてのワークスペースで共有されます。STATE.json にこの
  プラットフォーム用に記録するアカウント ID は、`chatgpt_ads_account_get` が
  返す `id` である必要があります。フィードは監査ログを読む前に
  `GET /ad_account` を読みます。キーが別のアカウントを読む場合は何も取り込まず、
  結果は `unavailable` です（理由にはどちらの ID も書きません）。STATE.json に
  アカウント ID が無い場合は確認を飛ばし、結果にその旨の注記が付きます。
- **古い順に、1 回 1,000 件まで。** 期間は古い順に読み、1 回の実行で取り込むのは
  最大 1,000 件です。上限に達した実行は `truncated: true` を示し、その注記に
  どの時刻まで読んだかが書かれます。取り込みをもう一度実行してください。次の
  実行は、取り込んだ最も新しい変更から続けます。mureo 自身の変更は保存されない
  ため、その位置を動かしません。次の実行が同じ位置で止まる場合は、注記が示す
  `since` を渡してください。上限に達した実行で、エントリが古い順に返って
  こなかった場合や、最初の 1,000 件の日付がわからない場合は、何も取り込まず
  `error` の結果となり、期間内のエントリが 1,000 件以下になる `since` を明示する
  よう求めます。
- **エンティティを持つエントリ。** キャンペーンのエントリは `campaign_id` を、
  広告グループのエントリは広告グループ（`entity_type: "ad_group"`、
  `entity_id`、加えてその `campaign_id`）を、広告のエントリは `ad_id`（加えて
  その `campaign_id`。広告グループではない）を示します。これらは変更ツールが
  記録するのと同じエンティティなので、mureo 自身の一時停止・再開、アーカイブ、
  予算、入札、名前、配信期間の変更は、ツール名、対象、10 分の時間幅で
  見分けられ（[change-import.md](change-import.md#deduplication) の説明の
  とおり）、二重には取り込まれません。
- **作成とアーカイブ。** 作成の記録は作ったエンティティを示せないため、mureo が
  作成したキャンペーン、広告グループ、広告の監査ログのエントリは外部の変更として
  取り込まれます。これはそれらしいエントリに対する重複排除の判定で、
  プラットフォームは作成をどう報告するかを公開していません。監査ログは
  アーカイブを `status` の変更として報告し、アーカイブのツール名も状態の変更と
  して読まれるため、mureo 自身のキャンペーン・広告グループ・広告のアーカイブは、
  一時停止・再開と同じくツール名、対象、時間幅で見分けられます。変更された
  項目を示さないアーカイブのエントリは、状態の変更ではなくキャンペーン・
  広告グループ・広告の編集として読まれるため、3 つとも外部の変更として
  取り込まれます。
- **監査ログに入るもの。** API キーで行った変更のエントリは、Ads Manager で
  行ったものと同じ `actor_type` を持ち、操作者としてユーザーの ID を持つため、
  エントリから両者は区別できません。画像アップロードとカスタムオーディエンスの
  作成は記録されません。一時停止とアーカイブは `changes` の `status` キーで
  報告されます。すでに一時停止中のキャンペーンへの一時停止は、変更された項目の
  無いエントリとして記録されるため、mureo が一時停止を送った場合でも外部の
  変更として取り込まれます。
  `obj_type` の値には `Campaign`、`AdGroup`、`Ad`、`AdAccount`、
  `AdsManagerApiKey`、`ClientDataSource`、`ConversionEventSetting` があります。
- **常に外部の変更として取り込むもの。** アカウント単位の変更（1 日の
  利用上限）と、キャンペーン・広告グループ・広告以外のリソースのエントリは
  エンティティを持たないため、mureo が行ったものでも外部の変更として取り込まれ
  ます。重複排除は変更された項目の名前も読むため、変更された項目が 20 個を
  超えるエントリは、mureo が行ったものでも外部の変更として取り込まれることが
  あります。
- **見えないもの。** プラットフォームは、監査ログのエントリをどれだけの期間
  保持するかも、どの変更を記録するかも公開していません。そのため、期間内が
  空であることは、アカウントに変化が無かった証拠にはなりません。どの結果にも
  注記でその旨が書かれます。
- **失敗。** キーが無い・拒否された場合、広告アカウントの応答に使える `id` が
  無い場合、そしてすべての API エラーは、プラットフォームの `error` の結果と
  して報告され、変更の無い期間として扱われることはありません。

## 期間とタイムゾーン

`period` は Meta Ads のツールと同じ語彙を取ります: `today`、
`yesterday`、`last_7d`、`last_14d`、`last_30d`、`last_90d`（昨日までの丸 N 日間）、
`this_month`、`last_month`、または明示的な
`YYYY-MM-DD..YYYY-MM-DD`（両端を含む）。`today` と `this_month` も
受け付けます。最終日が今日の範囲に、プラットフォームは 200 を返します。

相対的な値は、**広告アカウントのタイムゾーンでの今日**、つまり
`GET /ad_account` が返す `timezone` を基準に解決します。API が日付の範囲を
そのタイムゾーンで読むためです。午前 0 時の前後では、アカウントの今日と
ホストの今日が 1 日ずれます。
アカウントがタイムゾーンを示さない場合や、ホストのタイムゾーンデータベースが
知らないタイムゾーンの場合は UTC を使います。このため、インサイトと変更履歴の
ツールはレポートの前に `GET /ad_account` を 1 回送ります。Windows には
システムのタイムゾーンデータベースが無いため、mureo はそこで `tzdata`
パッケージをインストールします。

365 日を超える期間は拒否します。

## 単位

| 値 | 単位 |
|-------|------|
| キャンペーンと広告グループの予算と入札額、アカウントの利用上限、変更ツールがプラットフォームに送るすべての金額 | アカウント通貨の **micros**（1,000,000 = 1 単位） |
| `bid_multiplier_micros` | 倍率の micros（1,000,000 = 1.0 倍） |
| インサイトの `spend`、`cpc`、`cpm` | アカウント通貨の**主単位**（12.50 = 12.50） |
| インサイトの `ctr` | 比率 |

mureo はどれも変換しません。それぞれの値はその単位のまま読んでください。
変更ツールは、STRATEGY.md の上限（通貨の単位で書く）が読む金額を `micros` で
宣言しているため、1,000,000 で割ってから比べます:

| 上限 | 読む値 | 抑えないもの |
|-----|-------|----------------|
| `max_daily_budget_per_campaign` | `budget.daily_spend_limit_micros`、およびアカウントの `amount_micros` | |
| `max_lifetime_budget_per_campaign` | `budget.lifetime_spend_limit_micros` | |
| `max_daily_budget_increase_pct`、`max_total_daily_budget` | 呼び出し側が渡したときの `current_daily_budget` / `projected_total_daily_budget`（通貨の単位） | それらを省いた呼び出し |
| `max_cpc_bid_per_ad_group`、`max_bid_amount_per_ad_set` | `bidding_config.max_bid_micros` | オーディエンスの調整率、入札額を持たない戦略、金額が 1 回あたりになるインプレッション課金 |

## データの鮮度

API のレポートの文書より:

| 指標 | 文書の記述 |
|---------|-----------------------------|
| インプレッション、クリック、CTR | "Can become available within minutes. Recent values may change as processing completes." |
| 費用、CPC、CPM | "Reflect finalized activity and can update later than impressions and clicks." |
| コンバージョンと購入の成果 | "Allow at least one day for conversion data to appear." |

"Current-day and current-month reports can contain partial periods."
当日の行は暫定として扱い、最新の費用を最新のクリック数で割って CPC を求めない
でください。返された `cpc` を使ってください。

## 制限

- **プラットフォームのレート制限。** API は、広告アカウントと IP アドレスの
  両方で、エンドポイントごとに毎分 600 リクエスト、全体で毎分 1,200 リクエストの
  制限をかけます。
- **mureo のスロットル。** ChatGPT Ads の各ツールは独自のスロットル（毎秒 8 回、
  バースト 5）を宣言しているため、プラグイン共有のバケットではなく、ツールごとに
  専用のバケットを持ちます。スロットルが数えるのはツールの呼び出しです。一覧
  ツールの 1 回の呼び出しが複数ページのリクエストを送ることがあり、変更が書き込む
  前に行う読み取り（取り消し操作のための変更前の読み取り、
  `chatgpt_ads_campaigns_update_budget` のキャンペーンの読み取り、
  `chatgpt_ads_account_daily_spend_limit_set` の利用上限の読み取り）は数えません。
- **再試行。** 429 か 5xx が返った `GET` は、合計最大 3 回試します。`POST` は
  429 のときだけ再試行します。429 はリクエストを処理せずに返されるためです
  （未確認です。
  [実アカウントでまだ確かめていないこと](#実アカウントでまだ確かめていないこと)を
  参照）。`POST` の 5xx は最終結果です。応答が失われる前に変更が適用された
  可能性があり、繰り返すと二重に適用されかねないためです。ただし一部の `POST` は
  `GET` と同じく 5xx で再試行します。キャンペーン・広告グループ・広告を変更しない
  広告のプレビュー（期限付きのプレビューのスナップショットを保存する）、読み取る
  だけのコンバージョンのレポート、冪等キーを持つ作成とオーディエンスの追加・削除
  です（[作成](#作成)と[カスタムオーディエンス](#カスタムオーディエンス)を参照）。
  30 秒以下の数値の `Retry-After` ヘッダーがあれば、それが待ち時間になります。
  それより長いものは待たず、応答をすぐに報告します。使えるヘッダーが無い場合、
  待ち時間は 1 秒から倍々に増えます。最後の試行での 429 や 5xx は API エラーと
  して報告します。通信エラーは再試行しません。
- **ページの大きさ。** ページは、API の最大値とまだ必要な行数のうち小さいほうで
  要求します。キャンペーン、広告グループ、広告、カスタムオーディエンス、
  ピクセル、コンバージョンイベント設定は 500、監査ログは 100、インサイトは
  2000 です。
- **レポートの期間。** 最大 365 日です。API が時間単位以外の配信レポートを
  保持するのは直近 365 日で、コンバージョン指標にはアカウントのタイムゾーンでの
  丸 1 日単位、最大 365 日の期間が必要です。
- **タイムアウト。** リクエストごとに 30 秒、ツールの呼び出し全体（すべての
  ページ、再試行、バックオフの合計）で 120 秒です。時間切れになった呼び出しは
  `API error: the call did not finish within 120 seconds` として報告します。
  変更ツールでは、その文に続けて変更が適用された可能性があることを書き、作成と
  オーディエンスの追加・削除では、繰り返すときに使う冪等キーを示します
  （[失敗時の返り値](#失敗時の返り値)を参照）。取り消し操作を記録するための
  読み取りには、別に 15 秒の制限があります。
- **ページ数の上限。** 1 回の呼び出しで要求するのは最大 50 ページです。それより
  多く必要な一覧は、短いまま返すのではなく、`limit` を下げるか絞り込みを狭める
  よう求める API エラーとして報告します。続きの行があると示しながらカーソルが
  進まないページも、同じく報告します。

## 失敗時の返り値

| 状況 | 結果 |
|-----------|--------|
| キーが保存されておらず、`CHATGPT_ADS_API_KEY` も未設定 | `{"status": "auth_error", "auth_cause": "no_credentials", "detail": ...}`。detail は `mureo configure` の ChatGPT Ads のカードと `CHATGPT_ADS_API_KEY` を示す |
| 401、または機能の有効化によるものではない 403 | `{"status": "auth_error", "auth_cause": "token_invalid", "detail": "ChatGPT Ads rejected the API key: ..."}` |
| エラーコードが `_disabled` か `_not_enabled` で終わる、またはメッセージに `is not enabled` / `not enabled for` を含む 403 か 404 | `{"status": "error", "error": "feature_not_enabled", "detail": ...}`: この広告アカウントではその機能が有効になっていない |
| その他のエラー応答（400、通常の 404、409、413、422、5xx、再試行後の 429） | 文 `API error: HTTP <status> (<code>): <message>`。`(<code>)` は本文が正しい形のコードを持つときだけ。本文が JSON オブジェクトでないかメッセージを持たない場合は、メッセージの代わりに `no readable error detail in the response body` |
| JSON でない成功の応答 | 文 `API error: HTTP <status>: the response body is not JSON`。変更ツールでは下の結びが付く |
| 2xx で本文が空の変更（204、または空白だけ） | `{}`: プラットフォームは変更を受け付け、何も返さなかった |
| 通信エラー | 文 `API error: transport error (<error class>)` |
| 呼び出しの期限切れ、ページ数の上限、進まない一覧のカーソル | 文 `API error: ...`（[制限](#制限)を参照） |
| 5xx、JSON でない成功の本文、通信エラー、呼び出しの期限切れで終わった変更ツール | 同じ文で、結びが `The change may have been applied; check the account before retrying.` |
| 同じ形で終わった作成 | 同じ文で、`idempotency_key` で繰り返すよう求める文で結ぶ。プラットフォームから以前の作成が見えていれば、繰り返すと以前のエンティティが返る（[作成](#作成)を参照） |
| 同じ形で終わったオーディエンスの追加・削除 | 同じ文で、操作向けの `idempotency_key` で繰り返すよう求める文で結ぶ（[カスタムオーディエンス](#カスタムオーディエンス)を参照） |
| ピクセルの一覧または作成での 404 | `{"status": "error", "error": "feature_not_enabled", "detail": ...}`: この広告アカウントではコンバージョンが有効になっていない |
| `Client data source not found` が返ったイベント設定の作成 | 通常の `API error:` の文: `source_id` がこのアカウントのピクセルではない |
| 画像ファイルが無い、通常のファイルでない、別の種類、中身が拡張子の示す形式と判定されない、30MB 超、`..` を含む名前 | mureo 共通の画像検査からの `FileNotFoundError` または `ValueError`。リクエストの前 |
| 識別子ファイルが無い、通常のファイルでない、`.txt` / `.csv` でない、2 MiB 超、`..` を含む名前、UTF-8 でない | `FileNotFoundError` または `ValueError`。リクエストの前で、ファイルのバイト列は引用しない |
| 無効な行を含む識別子ファイル | 件数と最大 10 個の行番号を示す `ValueError`。リクエストの前で、行は引用しない |
| 識別子が無い、または異なる識別子が 10,000 個を超える識別子ファイル | `ValueError`: `file_path holds no identifiers; give one per line`、または異なる識別子の件数とファイルの分割を求める文。リクエストの前 |
| 1 日のルールが 2 つ以上ある `chatgpt_ads_account_daily_spend_limit_set` | `{"status": "refused", "error": "multiple_daily_spend_limits", "detail": ...}`。変更の前 |
| 利用上限の応答が JSON オブジェクトでない、使えない `revision` を持つ、または想定外の形の 1 日のルールを持つ `chatgpt_ads_account_daily_spend_limit_set` | 文 `API error: ...; nothing was changed`。変更の前 |
| 予算の種類を変えることになる `chatgpt_ads_campaigns_update_budget` | `{"status": "refused", "error": "budget_kind_change", "detail": ...}`。変更の前。現在の予算がどちらの金額も持たない場合は `budget_unreadable` |
| 引数が無い、または形が正しくない | `ValueError`。リクエストの前に発生 |

プラットフォームはエラーを
`{"error": {"message", "type", "param", "code"}}` の形で返します。`code` は
`null` のことがあります。400 の応答の中には、`type` が `server_error` でコードが
無く、メッセージ自体がステータスで始まる（`"400: ..."`）ものがあり、その場合の
文は `API error: HTTP 400: 400: ...` になります。コードの例は `invalid_api_key`
（401）と `integer_above_max_value`（400、最大値を超える `limit`）です。
通常の 404 のメッセージは `Not found: <id>` です。

5xx、JSON でない成功の本文、通信エラー、期限切れで終わった変更は、応答が
失われる前にプラットフォームに届いている可能性があります。もう一度試す前に、
対応する `*_get` ツールでエンティティを読み取ってください。確かめずに呼び出しを
繰り返すと、二重に適用されかねません。作成は例外です。エラーが示す
`idempotency_key` と同じ引数で繰り返してください。その繰り返しも失敗した場合は、
新しいキーで作成する前に名前で一覧を確かめてください
（`chatgpt_ads_campaigns_list`、`chatgpt_ads_ad_groups_list`、
`chatgpt_ads_ads_list` に `name` を指定）。オーディエンスの追加・削除も同じく、
そのキー、同じ引数、同じファイルで繰り返します。オーディエンス、ピクセル、
イベント設定の作成にはキーがありません。もう一度作る前に、オーディエンス、
ピクセル、イベント設定の一覧を確かめてください。

プラットフォームのメッセージを引用するのは、本文が JSON オブジェクトのときだけ
です。メッセージは 1 行にまとめ、表示できない文字を取り除き、mureo の秘密情報の
除去を通し、200 文字で切ります。JSON でない本文（たとえば中継サーバーの
エラーページ）は引用しません。API キーが結果、エラーメッセージ、ログの行に
出ることはありません。エラーの本文を読む前にキーの値そのものを `***` に
置き換え、通信エラーはクラス名だけで報告し、エラー応答はそれを生んだ
リクエストを含めずに読みます。

## エージェントに伝えられること

プロバイダは**プラットフォームの配信モデル**を登録します。一次情報の出典付きの
1 段落で、MCP サーバーが ChatGPT Ads のツールを提供している間、それを
`instructions` に書き込みます。そのため、プロバイダが有効な場合（既定）、
サーバーの `instructions` には "Platform delivery models" の下に
`chatgpt_ads` の行が入ります。その行が伝えるのは、配信はオークションで決まり、
オークションが実際の CPC を決めること、各広告グループの課金イベントが
インプレッションとクリックのどちらに課金するかを決め、コンバージョン最適化の
入札でも有効なクリックごとに課金されること、予算と入札額は micros であること、
コンバージョンは少なくとも 1 日遅れて届くことです。
[`plugin-authoring.md`](plugin-authoring.md#declaring-your-platforms-delivery-model-optional)
を参照してください。

foundation skill
[`skills/_mureo-chatgpt-ads/SKILL.md`](../skills/_mureo-chatgpt-ads/SKILL.md)
が、各ツールを使う場面、単位、当日の暫定データ、各失敗を運用者にどう伝えるかを
扱います。

STATE.json のプラットフォームキーは `plugin:mureo-chatgpt-ads:chatgpt_ads` です。

## 現在の非対応

- **作成後の編集。** 作成したあとに広告のクリエイティブ、キャンペーンの
  配信対象、広告グループの context hints を変えるツールはありません。期間指定の
  利用上限を変えるツールや、アカウントの 1 日の上限を削除するツールもありません。
  1 枚画像のチャットカード以外のクリエイティブ（複数画像、商品テンプレート）は
  提供していません。
- **パートナーアクセス。** OAuth もパートナーキーもありません。mureo は
  `OpenAI-Ad-Account` ヘッダーを送らないため、読むのは広告主のキーが対象と
  する広告アカウントだけです。
- **ほかの API。** 一括 API、ホテルのフィード、商品フィードはありません。
- **ほかのオーディエンスとコンバージョンの操作。** オーディエンスの置き換え、
  統合、アーカイブ、オーディエンスの操作の取り消しと再開、操作の一覧、ファイル
  からのオーディエンスの作成、コンバージョン API キー、最近のコンバージョン
  イベントの読み取りはありません。
- **ほかのインサイトのオプション。** `chatgpt_ads_insights_report` は
  セグメント、絞り込み、並べ替え、0 件の行の取得、アトリビューションの時刻の
  基準を取りません。
  `chatgpt_ads_conversions_report` は `breakdown`、
  `include_zero_rows`、`attribution_time_basis` を取りますが、絞り込みと
  並べ替えは取りません。どちらのレポートも時間単位や月単位の集計はありません。
- **BYOD。** ChatGPT Ads は BYOD モードに含まれません。
- **mureo 独自の分析。** 異常検知の基準値など、Google Ads と Meta Ads の
  ツールに紐づく分析は ChatGPT Ads にはありません。分析結果は参考情報として
  扱ってください。

## 実アカウントでまだ確かめていないこと

ツールは公開されている API リファレンスと OpenAPI の文書に沿って書かれ、
記録した応答でテストし、実際の広告アカウントでも動かしています。次の点は
まだ確かめていません:

- **`Retry-After`。** 429 の応答がこれを持つかどうか、持つならどの形か。
- **機能の有効化。** アカウントで有効になっていない機能が、どのステータス
  コードとエラーコードを返すか。リファレンスが示しているのは、フィードの API の
  `product_feed_api_disabled` と `product_feed_delta_api_disabled` だけです。
- **コンバージョン指標の名前。** 配信指標は、リファレンスの正規の形である
  `<level>.<metric>`（たとえば `campaign.impressions`）で要求します。
  コンバージョン指標は、リファレンスの例にならって裸の名前
  （`conversions`、`cpa`、...）で要求します。すべてのコンバージョン指標がその
  形で受け付けられるかは確かめていません。
- **上限が 1 つだけの `budget`。** 日予算だけ、または通算予算だけを持つ
  キャンペーンの予算で、もう一方のキーが無いか、`null` か、0 か。無いと `null` は
  未設定として扱います。0 は存在するものとして扱い、ツールの検査を通らないため、
  そうした予算は取り消し操作を記録せず、その予算への変更は予算の種類の変更として
  拒否します。
- **予算の種類の変更。** 予算のキーが変わったとき（日予算から通算予算へ、
  またはキーを 1 つ足した・外した）にプラットフォームが何を返すか。mureo は
  そうした変更を送る前に拒否します。
- **本文の無い応答の変更。** プラットフォームが変更に本文の無い応答（204）を
  返すことがあるか。mureo はその場合 `{}` を返します。
- **変更への 429。** 429 が常にリクエストを処理せずに返されるかどうか。
  `POST` を 429 で再試行するのはこれが前提です。
- **`automated_bid` の往復。** 応答は戦略 `automated_bid` を示すことがあり、
  リクエストでは `strategy` と `max_bid_micros` を省いてこれを表します。それを
  送り返して同じ設定に戻るかは確かめていません。
- **インプレッション課金の固定入札。** クリック課金の固定入札は、
  `target_strategy` `target_cpc` と `target_micros` として読み戻されます。
  インプレッション課金の固定入札が何として読み戻されるかは確かめていないため、
  そうした設定は取り消し操作を記録しません。
- **`expected_revision`。** mureo が読んだあとに revision が進んでいた場合に
  プラットフォームが何を返すか、また 1 日のルールが無いアカウントが revision 0 を
  受け付けるか。
- **取り消し操作が読む項目。** `status` の値 `active` と `paused`、キャンペーンの
  最上位の `start_time` / `end_time`、上に書いた形の `budget` と
  `bidding_config`、1 日のルールの `amount_micros` は、API リファレンスと
  OpenAPI の文書が示すとおりです。実際の応答が違った場合、影響を受ける変更は
  取り消し操作なしで、または caveat 付きで記録され、エラーは出ません。
- **一時停止や再開の繰り返し。** すでに一時停止中の広告グループや広告への
  一時停止、すでに有効なエンティティへの再開が、変わらないまま受け付けられるか、
  エラーが返るか。
- **監査ログの語彙。** リファレンスが示すエントリの例は 1 つで、キャンペーンの
  名前の変更（`audit_log_type` `update_campaign`、`obj_type` `Campaign`、
  `name` キーを持つ `changes`）です。変更の取り込みが想定する広告グループと
  広告の表記（`AdGroup`、`Ad`）は監査ログが使うものです
  （[変更の取り込み](#変更の取り込み)を参照）。
  `audit_log_type` と `obj_type` の値、および `changes` のキーの全体は
  公開されていません。
- **監査ログでの再開。** 再開が、一時停止やアーカイブと同じく `changes` の
  `status` キーで報告されるか。そうでない場合、mureo 自身の再開は見分けられず、
  外部の変更として取り込まれます。
- **オーディエンスの操作。** 追加や削除がどれだけの間 `processing` のままか、
  また 10,000 個の識別子の上限に近いインラインのリクエストにプラットフォームが
  どう応答するか。
- **追加や削除の繰り返し。** 同じキーで繰り返したとき、リファレンスの説明の
  とおり最初の操作が返るか。
- **コンバージョンの機能の有効化。** プラットフォームがコンバージョンを有効に
  していないアカウントで、ピクセルの一覧と作成が `404 Not found` を返し、それ
  以外を返さないか。
  そのときイベント設定のパスが何を返すか（mureo はその応答を通常のエラーとして
  報告します）。また `Client data source not found` の応答のステータス。
- **`source_ids`。** リファレンスによると、イベント設定が受け取る値はピクセルの
  `id`（`pixel_id` ではない）です。実際のアカウントでは確かめていません。
- **`time_ranges`。** レポートは、リファレンスの例を JSON で符号化した文字列の
  形で、Unix 秒を文字列にし、終わりを含まない形で送ります。ほかの形は
  試していません。
- **並び順。** `order=asc` がページをまたいで古い順にエントリを返すか。上限に
  達した変更の取り込みの実行は、次の実行に新しいエントリだけを残すためにこれに
  頼っています。上限に達した実行で順序の乱れたエントリを見た場合は、何も
  取り込みません。
- **アカウント ID。** `GET /ad_account` の `id` が、STATE.json に記録された
  アカウント ID と比べるべき値であること。両者が違う場合、変更の取り込みは
  その期間を拒否します。
- **冪等な再実行。** 処理中の作成が繰り返しの時点で見えているかどうか。mureo
  自身の 5xx の再試行は先に通常のバックオフを待ちます。プラットフォームが
  再実行を文書化しているのは、一致する以前の作成が見えている場合だけです。
- **アップロードの大きさの上限。** プラットフォームは画像の大きさの上限を
  示していません。30MB の上限は mureo のものです。プラットフォームの上限が
  それより小さければ、API エラーとして現れます。
- **アーカイブの連鎖。** 広告グループをアーカイブするとその広告もアーカイブ
  されるかどうか。

## 規約

キーは広告主自身の広告アカウントのものです。プラットフォームの規約は API キーを
他者と共有することを制限しています。他人が発行したキーを使う前に、規約を
確かめてください。

## 契約フィクスチャの更新

`tests/fixtures/chatgpt_ads_openapi_subset.json` には、ツールが呼ぶ各操作に
ついて、メソッド、パスのテンプレート、クエリパラメーターの名前、`POST` では
リクエスト本文の最上位のプロパティ名を、OpenAPI の文書から抜き出して並べて
います。メソッド、パス、パラメーター名、本文のキーがここに無いリクエストは、
テストが失敗にします。API が変わったあとに更新する手順:

1. API の概要からリンクされている OpenAPI の文書
   （`https://developers.openai.com/ads/openapi.json`）をダウンロードします。
   そのパスは `https://api.ads.openai.com/v1` からの相対です。
2. フィクスチャの各操作について、`paths["<path>"].<method>.parameters` の下で
   `"in": "query"` を持つ各パラメーターの `name` を写します。`array` 型の
   パラメーターでは、リファレンスの例が送る角括弧付きの表記（`include[]`、
   `fields[]`、`time_ranges[]`）も並べます。`POST` では、その `requestBody` が
   参照するスキーマ（`application/json`）のプロパティ名を `body` の下に並べます。
   リクエスト本文の無い操作は空の配列にします。
3. `openapi_version` と `_comment` を、文書の `info.version` と読んだ日付に
   設定し、`mureo/chatgpt_ads/_api.py` の `OPENAPI_VERSION` と
   `OPENAPI_READ_ON` もそれに合わせます。
4. `pytest tests/test_chatgpt_ads_client.py tests/test_chatgpt_ads_tools.py tests/test_chatgpt_ads_mutations.py` を実行します。
   失敗すると、契約から外れたリクエストが示されます。
