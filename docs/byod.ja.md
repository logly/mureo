# BYOD: 自分のアカウントのデータで mureo を試す

OAuth クライアントの登録も、Google Ads Developer Token の申請も、SaaS への
サインアップも要りません。**Google Ads Script でスプレッドシートに書き出す
（または Meta 広告マネージャからエクスポートする）→ XLSX を mureo に渡す**
だけで、5分後には Claude Code から `/daily-check` が走ります。

mureo がこの XLSX を **ローカルのファイルとして読むだけ** で、外部に通信は
発生しません。スプレッドシートはあなた自身の Google Drive に置かれ、mureo
専用のクレデンシャルも一切登場しません。

> **対応状況 (Phase 2)** Google Ads（mureo の Google Ads Script 経由）と
> Meta Ads（広告マネージャの Excel エクスポート経由）の 2 プラットフォーム
> を Sheet bundle で取り込めます。GA4 / Search Console は引き続き real-API
> 認証で接続するパスを使ってください（`docs/authentication.md` 参照）。

---

## なぜ BYOD なのか

ローカル完結で広告分析をやるときの最大のハードルは、OAuth の登録と
Developer Token の審査（数日〜数週間）です。BYOD はそこを丸ごとスキップ
できます。

- デモデータではなく、**実アカウントのデータ**で mureo の挙動を試せる
- データは XLSX で手元に置くだけ。組織のデータガバナンス審査も不要
- すでに走らせた `mureo setup claude-code` の MCP 設定で、追加設定なしに
  そのまま動く
- Google Workspace の **組織アカウント**で個人 GCP プロジェクトの自動作成が
  ブロックされている環境でも問題なく動作する（Google Ads Scripts は Apps
  Script ではなく広告マネージャ自体のランタイムで動くため）
- **構造的に read-only**: `create_*` / `update_*` / `pause_*` などの
  ミューテーション系メソッドは全て `{"status": "skipped_in_byod_readonly"}`
  を返します

---

## 5 分でセットアップ

### Step 1 — mureo をインストール

```bash
pip install mureo
mureo setup claude-code --skip-auth   # MCP 設定だけ。OAuth は走らせない
```

### Step 2a — Google Ads Script を実行（任意）

Google Ads にログイン → **ツールと設定 → 一括操作 → スクリプト → +**
の順に開きます。

`scripts/sheet-template/google-ads-script.js` の中身をエディタに丸ごと
ペーストし、上部の `TARGET_SHEET_URL` を自分のスプレッドシート URL に
書き換えます（新規スプレッドシートでも OK）。「**承認**」→「**実行**」を
クリック。

スプレッドシートに 4 つのタブ（`campaigns` / `ad_groups` / `search_terms`
/ `keywords`）が書き込まれれば成功です。Auction insights は意図的に外し
ています — Google Ads Scripts からこのデータには到達できないため、
`/competitive-scan` で競合分析を行いたい場合は `mureo auth setup` で
real-API 経由を使ってください。

### Step 2b — Meta 広告マネージャからエクスポート（任意）

広告マネージャ画面で **レポート → カスタマイズ → エクスポート**。

「mureo BYOD」という名前で 1 度だけテンプレを保存しておくのがおすすめ
です。それ以降は **保存済みレポート → mureo BYOD → エクスポート** で
2 クリックです。

**おすすめのレポート設定:**

- レベル: **広告**
- 内訳: **時間別 → 日別** + **配信 → 配置 / プラットフォーム /
  デバイスプラットフォーム**
- 列: キャンペーン名 / 広告セット名 / 広告名 / 結果 / 結果インジケーター /
  消化金額 (JPY) / インプレッション / リーチ / リンククリック /
  フリークエンシー

**多言語対応**: mureo の Meta アダプタは英語 / 日本語 / 简体中文 /
繁體中文 / 한국어 / Español / Português / Deutsch / Français の **9 言語**
で実エクスポートを検証済みです。広告マネージャの言語を切り替える必要は
ありません。

**`Excel (.xlsx)`** 形式で書き出してください。

### Step 3 — XLSX をダウンロードして mureo に取り込み

スプレッドシートの **ファイル → ダウンロード → Microsoft Excel (.xlsx)**
で保存。あとは XLSX を mureo に渡すだけです。

```bash
# Google Ads
mureo byod import ~/Downloads/<google-ads-bundle>.xlsx

# Meta Ads（広告マネージャからエクスポートしたファイル）
mureo byod import ~/Downloads/<meta-ads-export>.xlsx
```

Claude Code から取り込んでもらう場合は、ターミナルを触らずに
「ダウンロードした XLSX を mureo に取り込んで」と頼むだけで Claude Code
が同じコマンドを走らせます（初回は permission 確認が出ます）。

実行ログの例:

```
=== mureo byod import ===

  [google_ads] format: mureo_sheet_bundle_google_ads_v1
    421 rows, date range 2026-04-01..2026-04-30
    written to /Users/you/.mureo/byod/google_ads/
      - campaigns.csv
      - metrics_daily.csv
      - ad_groups.csv
      - keywords.csv
      - search_terms.csv

Mode summary:
  google_ads        BYOD (421 rows, 2026-04-01..2026-04-30)
  meta_ads          not configured (no BYOD data, no credentials.json)

Next: ask Claude Code: 'Run /daily-check'
```

### Step 4 — Claude Code に診断を依頼

`STRATEGY.md` がある任意のディレクトリで Claude Code を開き
（なければ `mureo onboard` で生成）、こう打つだけです:

> Run /daily-check

mureo の MCP サーバーが取り込み済みのデータを自動検出します — `--byod`
フラグを付けたりする必要はありません。エージェントは実データに対して
キャンペーン推移分析・検索語のギャップ・キーワードの品質スコアなどを
ひととおり走らせます。

---

## CLI リファレンス

| コマンド | 説明 |
|---|---|
| `mureo byod import <file.xlsx>` | Sheet bundle を取り込む。対象プラットフォームに既にデータがあると拒否される |
| `mureo byod import <file.xlsx> --replace` | 既存の BYOD データを上書きして取り込む |
| `mureo byod status` | プラットフォーム別のモード（BYOD / real API / 未設定）を表示 |
| `mureo byod remove --<platform>` | 1 プラットフォームの BYOD データを削除（`--google-ads` / `--meta-ads`） |
| `mureo byod clear` | `~/.mureo/byod/` をまるごと削除 |
| `mureo byod clear --yes` | 確認プロンプトをスキップ |

`--byod` のような有効化フラグはどこにもありません。各ツール呼び出しの
タイミングで `~/.mureo/byod/manifest.json` の有無を見て、プラットフォーム
ごとに自動判定しています。BYOD と real-API 認証の両方を同時に使うことも
できます（次の節を参照）。

---

## モード判定の仕組み

```
┌──────────────────────────────┐
│ mureo byod import bundle.xlsx│──▶ ~/.mureo/byod/manifest.json
└──────────────────────────────┘                │
                                                ▼
                                  ┌───────────────────────┐
   Claude Code ─────MCP──────────▶│ mureo MCP server      │
                                  │                       │
                                  │  per-tool dispatch    │
                                  │  byod_has(platform)?  │
                                  └─────┬───────────────┬─┘
                                  yes   │             no │
                                        ▼                ▼
                              ┌────────────────┐  ┌─────────────────┐
                              │ Byod*Client    │  │ create_*_client │
                              │ (CSV を読む)   │  │ (live API)      │
                              └────────────────┘  └─────────────────┘
```

`byod_has(platform)` が `True` を返すのは、次の 4 条件をすべて満たした
ときです:

1. `~/.mureo/byod/manifest.json` が存在し、JSON として読める
2. `schema_version` が現バージョンに対応している（現在は `1`）
3. 対象プラットフォームが `platforms` に登録されている
4. `~/.mureo/byod/<platform>/` ディレクトリが実際にディスクにある

`~/.mureo/byod/google_ads/` を手動で消したのに manifest を残したまま、
といった食い違いがあると mureo は警告を出して real-API モードにフォール
バックします。

---

## BYOD と real API を併用するパターン

| 状態 | 動作 |
|---|---|
| Google Ads だけ取り込み済 / Meta は未設定 | Google Ads = bundle / Meta = real API |
| Meta だけ取り込み済 / Google Ads は未設定 | Meta = bundle / Google Ads = real API |
| 両方取り込み済 | 両方 = bundle |
| 何も取り込まない | 全部 real API |
| `mureo byod clear` 実行後 | 全部 real API |

GA4 と Search Console は常に real-API 経由です。Sheet bundle の対象
プラットフォームには含まれません。

---

## BYOD で何が制限されるか

mureo BYOD は **設計レベルで read-only** です。エージェントはデータ分析・
診断・改善案の提案までは行えますが、実アカウントへの書き込みは絶対に
発生しません。具体的には、BYOD クライアントの以下の接頭辞を持つメソッドが
すべて `{"status": "skipped_in_byod_readonly", ...}` を返します:

`create_`, `update_`, `delete_`, `remove_`, `add_`, `send_`, `upload_`,
`pause_`, `resume_`, `enable_`, `disable_`, `apply_`, `publish_`,
`submit_`, `attach_`, `detach_`, `approve_`, `reject_`, `cancel_`,
`set_`, `patch_`

---

## real API モードに戻す

```bash
mureo byod remove --google-ads          # 1 プラットフォームだけ戻す
# または
mureo byod clear                         # 全 BYOD データを削除
```

`mureo byod clear` は `~/.mureo/credentials.json` には触りません。
real-API の OAuth トークンは BYOD のリセットを跨いで残ります。削除後は
Claude Code を再起動してください — mureo MCP サーバーが起動時に
manifest の不在を検知し、自動的に credentials.json ベースに切り替えます。

`not configured` と表示されたプラットフォームについては、
`mureo auth setup`（または `mureo auth setup --web`）で
`~/.mureo/credentials.json` を埋めれば real API で動き始めます。

---

## プライバシー保証

- **完全ローカル**: 取り込んだデータをどこにもアップロードしません。
  ネットワーク隔離テストが `httpx.AsyncClient.send` と
  `urllib.request.urlopen` をパッチし、BYOD モードでのツール dispatch
  および bundle 取り込みの両方で外部通信が **0 件** であることを保証
  しています
- **mureo 管理の OAuth は存在しない**: Google Ads Script はあなた自身の
  Google Ads アカウントの権限で動きます。BYOD パスについては mureo 専用の
  GCP プロジェクトも OAuth クライアントもありません
- **パストラバーサル防御**: bundle importer は `~/.mureo/byod/` の外には
  絶対に書き込まない実装になっています

---

## bundle importer が認識するタブ

| 出力元 | タブの目印 | → mureo の CSV |
|---|---|---|
| Google Ads Script | `campaigns`（必須） | `campaigns.csv` + `metrics_daily.csv` |
| Google Ads Script | `ad_groups` | `ad_groups.csv` |
| Google Ads Script | `keywords` | `keywords.csv` |
| Google Ads Script | `search_terms` | `search_terms.csv` |
| Meta Ads エクスポート | ヘッダに日付列 + `Campaign name` + `Impressions` を含むシート | `meta_ads/{campaigns,ad_sets,ads,metrics_daily}.csv` |

Google Ads アダプタは上記タブのうち最低 1 つが含まれていれば dispatch
されます。Meta アダプタは Meta 広告マネージャ式のヘッダを検出した
ときだけ dispatch されます。両者は混ざらないように作られていて
（Google Ads Script は短形の `campaign`、Meta は長形の `Campaign name`
を使う）、1 つの workbook に両方のデータが入ることはありません。

---

## BYOD では取れないもの

- **GA4 / Search Console** は real-API 認証（`mureo auth setup`）で。
  Sheet bundle のパイプラインには含まれません
- **`/rescue` の予算操作などミューテーション系**: 提案までは出ますが
  実行はブロックされます — BYOD は read-only です
- **OAuth トークンの自動更新**: BYOD はトークン自体を持たないため
  発生しません

real API の全機能を使いたくなったときは、`mureo auth setup`（または
`mureo auth setup --web`）でクレデンシャルを設定し、`mureo byod clear`
で BYOD モードを抜けてください。

---

## Google Ads の追加分析ツール

Sheet bundle の `search_terms` タブは、既存の Google Ads MCP ツール経由で
そのまま使えます。

| ツール | 返すもの |
|---|---|
| `google_ads.search_terms.report` | 検索語ごとに 1 行: campaign_name / ad_group_name / impressions / clicks / cost / conversions / ctr / average_cpc |

`google_ads.auction_insights.get` / `analyze` は BYOD では空を返します
（Google Ads Scripts からこのデータが取れないため）。競合シェアを見たい
場合は `mureo auth setup` で real API に切り替えてください。

---

## トラブルシューティング

### `Error: <file>: failed to open as XLSX`

スプレッドシートの **ファイル → ダウンロード → Microsoft Excel (.xlsx)**
で書き出したファイルを使っているか確認してください。Google Sheets ネイ
ティブ形式 / ODS / CSV だと弾かれます。

### `Error: <file>: no recognized tabs found`

bundle importer は前述のタブのうち少なくとも 1 つを期待します。
Google Ads Script が実際にデータを書き出せているか、スプレッドシートを
開いてタブを確認してみてください。

### `BYOD data for 'google_ads' already exists.`

`--replace` を付けて上書きするか、先に `mureo byod remove --google-ads`
で削除してから再取り込みしてください。

### `mureo byod status` は BYOD active と出るのに `/daily-check` がデータを返さない

`mureo byod status` を見て、MCP サーバーログに「manifest references X
but X is missing on disk」という警告が出ていないか確認してください。
プラットフォームのディレクトリだけ手動で削除してしまった場合は、
`mureo byod import --replace` で再取り込みするか
`mureo byod remove --<platform>` で manifest を整合させてください。

---

## 関連ドキュメント

- スクリプトテンプレート: `scripts/sheet-template/README.md`
- CLI リファレンス: `docs/cli.md`
- アーキテクチャ: `docs/architecture.md`
- real API 認証: `docs/authentication.md`
