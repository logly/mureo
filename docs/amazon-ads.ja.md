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
- `client_secret`（LwA アプリの client secret）— 下記の認可ウィザード
  に必須。その後の access トークン自動更新にも使われます

LwA のセキュリティプロファイルでもう 1 つだけ設定があります。
**リターン URL** を *Allowed Return URLs*（Login with Amazon ＞
対象のセキュリティプロファイル ＞ ウェブ設定）に登録してください。
Amazon が案内する直接広告主向けの方式は「自分が管理する任意の有効な
URL」で、mureo の既定は `https://amazon.com` です（そのまま登録すれば
十分）。同意後はそこへリダイレクトされ、アドレスバーからコードを
コピーするだけで、その URL 上で何かを配信する必要はありません。

`refresh_token` を自分で取得する必要は**ありません**。手順 2 の
ウィザードが発行します。

## 2. 設定 UI でセットアップ（推奨）

```bash
mureo configure
```

ブラウザでローカル設定 UI（`127.0.0.1` バインド）が開きます。手順:

1. **ダッシュボード**を開き、**プラグイン認証情報**セクションまで
   スクロールします。
2. **Amazon Ads** のカードを見つけます。
3. **クライアント ID** と**クライアントシークレット**を入力します。
4. 必要に応じて**リージョン**（`na` / `eu` / `fe`、既定 `na`）と
   **アカウントモード**（`dynamic` / `fixed`、既定 `dynamic`）を
   設定します。`fixed` の場合は**プロファイル ID** /
   **アカウント ID** / **マネージャーアカウント ID** のうち
   1 つ以上も入力してください。
5. **保存**をクリックします。
6. フォームの下にある **Amazon で認可する** で
   **Amazon の同意ページを開く**をクリックします。新しいタブで
   Amazon が開きます。
7. アクセスを許可すると、リターン URL にリダイレクトされます。
   ただのページ（404 のこともあります）で問題ありません。
8. ブラウザのアドレスバーから**アドレスを丸ごと**コピーし
   （`https://amazon.com/?code=ANxxxxx&scope=…` のような形）、
   **リダイレクト先のアドレス**欄に貼り付けて**認可を完了する**を
   クリックします。`code=` の値だけを貼り付けても動作します。

> アドレスは**そのまま**コピーしてください（mureo が `code`
> パラメータを読み取ります）。手で打ち直したり一部を削ったりすると、
> 「コードがありません」で失敗する典型的な原因になります。

mureo がコードを access トークン**と** refresh トークンに交換して
両方を保存し、同じ操作でツール一覧も更新します。認可コードの有効
期限は **5 分**です。過ぎてしまったら
**Amazon の同意ページを開く**をもう一度クリックしてください。

同じ **Amazon で認可する** ブロックは、セットアップウィザードの
Amazon ステップでも認証情報を保存した直後に表示されます。

値は `~/.mureo/credentials.json` の `amazon_ads` セクションに
`0o600` で保存されます。シークレット項目は書き込み専用で、次回の
編集時に空欄のままにすると保存済みの値が**保持**されます（消えま
せん）。リージョンだけ変えたいときにトークンを打ち直す必要は
ありません。

> **どういう種類のウィザードか。** Amazon の直接広告主向け同意には
> ローカルツールが待ち受けられるループバックコールバックがないため、
> これは Google / Meta のカードのような「自動で戻ってくる」方式では
> なく、**コード貼り付け方式**の誘導フローです。mureo が同意 URL を
> 生成して開き、あなたはリダイレクト先のアドレスを貼り付けます。
> 貼り付けたあとはすべて自動です。

すでに他の経路で `refresh_token` を持っている場合は、カードの
**リフレッシュトークン**欄に（クライアントシークレットとあわせて）
貼り付ければ認可ブロックは不要です。ターミナルだけで完結させたい
場合は[手動での認可](#付録-手動での認可フォールバック)を参照して
ください。

続けて手順 5（ツールマニフェスト生成）へ進んでください。認可
ウィザードを使った場合はツール一覧が更新済みなので省略できます。

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
| `refresh_token_obtained_at` | 任意 | 認可ウィザードが書き込む、現在の refresh トークンを取得した同意時刻（ISO 8601・UTC）。認証情報ではなくメタデータで、後述の再認可リマインドに使われる。無い場合は「不明」として扱い、警告も出さない |

## 5. ツールマニフェストを生成

```bash
mureo amazon refresh-manifest
```

認証付きで一度接続し、Amazon の MCP ツール一覧を取得して
**認証情報ファイルと同じ場所**に `amazon_tools.json` を書き出します
（標準構成では `~/.mureo/amazon_tools.json`）。mureo MCP サーバは
起動時にこのファイルを読むだけ（純粋・ネットワーク無し・資格情報
不要）。マニフェスト不在＝「Amazon ツール無し」で、起動失敗には
なりません。Amazon のツール構成が変わったときや再認可した後に
再実行してください。通常のトークン更新のために実行する必要は
ありません（mureo が自動で行います。後述）。

> マニフェストは常に認証情報ファイルに追従します。ホスト側プラグインが
> `credentials.json` の場所を変更する場合（マルチテナントのランタイム
> コンテキスト）もマニフェストは一緒に移動し、ブリッジ・CLI・
> `mureo configure` ダッシュボードのすべてが同じ 1 箇所を参照します。

## 6. Claude / mureo MCP サーバを再起動

Amazon のツールが Amazon 自身の名前（例 `campaign_management-*`,
`account_management-*`）で出現し、組み込みプラットフォームと同様に
監査・戦略ゲートされます。mutating 呼び出しは `STATE.json` の
`action_log`（`platform=plugin:mureo-amazon-ads-bridge`）へ観測窓
付きで昇格（#114 プラグイン安全層と同じ）。

## ロールバック：変更前状態の自動取得

Amazon への書き込みは**ロールバックできます**。下表のミューテーション
を実行する直前に、mureo が同じ認証済みブリッジ経由で対象の現在の状態を
読み取り、`action_log` エントリの `reversible_params` として記録します。
そのため `rollback_apply` は `NOT_SUPPORTED` を返す代わりに、**同じ
Amazon ツール**を**以前の値**で呼び直します。エージェントが書いた
ヒントには一切依存しません。

| ミューテーション | 読み取りツール | 復元する項目 |
|------------------|----------------|--------------|
| `campaign_management-update_campaign_state` | `query_campaign` | `state` |
| `campaign_management-update_campaign_budget` | `query_campaign` | `budgets` |
| `campaign_management-update_campaign` | `query_campaign` | `state` / `budgets` / `name` |
| `campaign_management-update_ad` | `query_ad` | `state` / `name` |
| `campaign_management-update_ad_group` | `query_ad_group` | `state` / `name` / `bid` |
| `campaign_management-update_target_bid` | `query_target` | `bid` |
| `campaign_management-update_target` | `query_target` | `state` / `bid` |
| `campaign_management-update_portfolio` | `query_portfolio` | `state` / `name` / `budget` |

対応付けは、ミューテーションが書き込むのと**同じ ID** で絞り込める
クエリツールが存在する場合に限って行っています。作成・削除・アカウント
単位の更新は対象外です（その「反転」は破壊的な呼び出しか、ID を捏造する
呼び出しになるため）。

### 正直な限界

- **ベストエフォートで、書き込みは絶対に止めない。** 読み取りが失敗して
  も（トークン失効・ネットワーク・想定外のレスポンス）ミューテーション
  はそのまま実行され、監査のみ（`reversible_params: null`）で記録され
  ます。取得失敗が書き込みを妨げたり変更したりすることはありません。
- **変更した項目のうち、読み戻せたものだけ。** ミューテーションが設定し
  ていてもクエリ応答に含まれなかった項目は復元しません（誤った反転は、
  反転しないことより悪いため）。そうした項目や、そもそも現在状態を読め
  なかったエンティティは、計画の **caveats** として列挙され、
  `rollback_plan_get` は完全な取り消しを装わず `partial` を返します。
- **リスクは 1 点に集中しています。** mureo は応答から決められたキー 1 つ
  だけを見てエンティティを取り出します。このキーは実アカウントで確認済み
  なのはキャンペーン（`campaigns`）と広告（`ads`）だけで、広告グループ /
  ターゲット / ポートフォリオは書き込み側の配列名（`adGroups`、`targets`、
  `portfolios`）からの推定です。推定が外れていた場合、そのツールは
  「たまに部分的に取得できる」のではなく**常に何も記録しない**、
  つまりこの機能が無かった頃と同じ挙動になります。誤った取り消しが
  行われることはありません。
- **広告プロダクト。** Amazon のクエリツールは `adProductFilter` が必須
  で、1 回につき**1 つ**しか指定できませんが、ミューテーション側の
  ペイロードには広告プロダクトが含まれません。mureo は既定値を勝手に
  決めることはせず、確度の高い順（その ID で以前に判明した広告プロダクト
  → 呼び出しが宣言した `adProduct` → 残り）に試し、全 ID が解決した時点
  で打ち切ります。最悪ケースは書き込み 1 回に対し読み取り 5 回ですが、
  同じエンティティへの再編集は 1 回で済みます（ID と広告プロダクトの
  対応をサーバプロセス内で記憶するため）。`query_portfolio` は広告
  プロダクト不要なので常に読み取り 1 回です。どれでも見つからなければ、
  誤った内容を記録するのではなく何も記録しません。
- **読み取り自体**は通常のブリッジ呼び出しです。他と同じく認証・トークン
  更新が効き、読み取りなので状態は変えません。実行はミューテーションの
  レート制限枠の内側なので、書き込みが連続しても読み取りが無制限に出る
  ことはありません。
- **書き込みが待たされることはありません。** 上限は二重で、1 回の読み取り
  につき **10 秒**、取得処理全体では探索回数によらず **15 秒**です。
  Amazon 側が遅い場合に失うのは最大でもこの制限時間だけで、その時点まで
  に取得できた分（間に合わなかったエンティティは caveats 扱い）で、
  あるいはロールバック情報なしで、書き込みはそのまま進みます。
  「反転できない書き込み」の方が「遅延する書き込み」よりましだからです。

## エージェントが Amazon について知っていること

同梱の foundation skill
[`skills/_mureo-amazon-ads/SKILL.md`](../skills/_mureo-amazon-ads/SKILL.md)
が、AI エージェントがこの面を触る前に読む資料です。85 ツールの
namespace 別一覧、`<namespace>-<verb>_<resource>`（ハイフン区切り）の
命名規則、無駄なターンを防ぐ呼び出し要件（`accessRequestedAccount`、
1 リクエストにつき ad product はちょうど 1 つ、グローバルアカウントは
`profileId` 必須、state 列挙は `ARCHIVED` / `ENABLED` / `PAUSED`）、
非同期レポートの流れ、そして正直なスコープ（output schema はどのツール
にも無い・分析は参考情報 #120・ガードレールは mureo が金額パスを宣言
している 13 個の課金ツールでは厳密で、その下でベストエフォートのパターン
走査も常に走る（形が変わった項目や新設項目も、名前が金額らしいままなら
この走査が拾う。あくまでパターンなので保証ではない）、それ以外のツールは
ベストエフォートのみ）を扱います。
Amazon の ad は状態が 1 つだけ（`state` は「設定された状態」で、配信
ステータスは存在しない）という点も明記しており、`/daily-check` と
`/sync-state` が `STATE.json` へ Amazon の ad を保存するときはこれに
従います。

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

## refresh トークンも失効します（365 日）

Amazon の LwA refresh トークンは長寿命ですが**永続ではありません**:

- **2026-07-30 以降**に発行された refresh トークンは、広告主が同意
  してから **365 日**で失効します。
- それ以前に発行されたトークンには固定の有効期限がないため、
  カウントダウンする対象がありません。

Amazon は発行時刻をクライアントに伝えないので、mureo が自分で記録
します。認可ウィザードが交換の時点で
`amazon_ads.refresh_token_obtained_at`（ISO 8601・UTC）を書き込み、
そのトークンが **335 日**を超えるとダッシュボードの Amazon カードに
**再認可の案内**が表示されます（Amazon が失効させる 30 日前の余裕）。

この記録が無い場合（ウィザード導入前の設定や、手で貼り付けた
refresh トークン）、mureo は**何も表示しません**。発行時刻が不明な
トークンは失効しない 2026-07-30 より前のものかもしれず、毎年警告を
出すのは誤りだからです。

実際に refresh トークンが失効すると、Amazon はトークン交換に
`invalid_grant` を返し、mureo はそれを明示します。この時点で mureo が
自動でできることはありません。

再認可の手順（失効前でも後でも）:

1. `mureo configure` の Amazon Ads カードを開き、**Amazon で認可する**
   のフロー（上の手順 2）をもう一度実行します。新しいトークンと新しい
   `refresh_token_obtained_at` で置き換わります。
2. UI を使わない場合は、**新しい** `refresh_token` を取得し
   （[手動での認可](#付録-手動での認可フォールバック)を参照）、
   カードの**リフレッシュトークン**欄／`AMAZON_ADS_REFRESH_TOKEN`／
   `~/.mureo/credentials.json` を更新します。次の Amazon ツール
   呼び出しで新しい access トークンが自動発行されます。
3. Amazon のツール構成も変わっている場合は
   `mureo amazon refresh-manifest` も再実行してください（UI の
   フローでは自動で実行されます）。

## なぜ mureo が経路に入るのか

公式 hosted MCP の中には、AI ホストに直接登録してホスト自身が接続・
認証する方式のものもあります。Amazon を mureo 経由のブリッジにして
いる理由は 2 つです。LwA 認証情報が `~/.mureo/credentials.json` に
留まり、ホスト側の MCP 設定に一切入らないこと。そして上記の自動発行・
自動更新は mureo が経路にいて初めて成立すること（失敗を検知し、
refresh トークンを交換し、再試行するのは mureo です）。代償として、
Amazon のツールは mureo MCP サーバが動いている間だけ利用できます。

## 付録: 手動での認可（フォールバック）

設定 UI が行っているのと同じ手順です。ターミナルだけで完結させたい
場合、コンテナ環境、デバッグ用に全文を載せます。どちらの手順も
リージョン別のホストを使います:

| リージョン | 認可 URL の接頭辞 | トークンエンドポイント |
|-----------|------------------|----------------------|
| `na` | `https://www.amazon.com/ap/oa` | `https://api.amazon.com/auth/o2/token` |
| `eu` | `https://eu.account.amazon.com/ap/oa` | `https://api.amazon.co.uk/auth/o2/token` |
| `fe` | `https://apac.account.amazon.com/ap/oa` | `https://api.amazon.co.jp/auth/o2/token` |

1. 次の URL をブラウザで開きます（1 行。`redirect_uri` はセキュリティ
   プロファイルの Allowed Return URLs に登録済みであること）:

   ```
   https://www.amazon.com/ap/oa?client_id=YOUR_CLIENT_ID&scope=advertising::campaign_management&response_type=code&redirect_uri=https%3A%2F%2Famazon.com
   ```

2. アクセスを許可し、リダイレクト先のアドレスバーから `code=` の値を
   コピーします。**有効期限は 5 分**です。

3. その 5 分以内に交換します:

   ```bash
   curl -X POST https://api.amazon.com/auth/o2/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=authorization_code" \
     -d "code=THE_CODE" \
     -d "redirect_uri=https://amazon.com" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET"
   ```

   レスポンスに `access_token`（`Atza|…`）、`refresh_token`
   （`Atzr|…`）、`expires_in` が含まれます。

4. `refresh_token`（と `client_secret`）を `amazon_ads` セクションに
   設定します（設定 UI のカード、`AMAZON_ADS_*` 環境変数、手編集の
   いずれか）。再認可リマインドを正しい日付から数えたい場合は、
   `refresh_token_obtained_at` に現在の UTC 時刻
   （例 `2026-07-31T09:15:00+00:00`）も入れてください。省略した場合、
   mureo は失効について何も言いません。

5. `mureo amazon refresh-manifest` を一度実行します。

## 注意

- **コード貼り付け方式の認可（自動で戻る方式ではない）**: Amazon の
  直接広告主向け同意にはループバックコールバックがないため、設定 UI は
  Amazon の同意ページを開き、リダイレクト先のアドレスを貼り付けて
  もらいます。Google / Meta のカードとの違いはこの形だけで、
  トークンの取得・保存・自動更新はどちらも mureo が行います。
- **改名なし**: ツールは Amazon の名前のまま（mureo は公式 MCP の
  ツールを改名しない＝Google/Meta 公式と同じ）。
- **深い mureo 分析なし**: mureo の native ツール名に紐づく
  プラットフォーム固有分析は Amazon には存在しません（#120 で追跡）。
  Amazon の read 結果は参考情報として扱ってください。
- **機密性のクラス**は、既に `~/.mureo/credentials.json` にある
  Google developer token / Meta access token と同一です。
