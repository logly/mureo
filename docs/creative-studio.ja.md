# Creative Studio（クリエイティブ生成）

> [English](creative-studio.md)

戦略に基づいたブリーフから、**クリエイターが作ったものと遜色ない広告クリエイティブ**
——文字なしのキービジュアルと、コピーまで合成した完成バナー——を、広告運用の
ワークフローから離れることなく生成します。Creative Studio は mureo 本体に
組み込まれた機能（有料アドオンではありません）で、あらゆるジャンルに使え、
画像生成 API のキーは自分のものを持ち込めます（BYO-key）。

---

## これは何か

「プロンプト → 画像 API → 完成」という素朴な作りでは、いかにも AI 的なバナーに
なります——日本語の文字化け、崩れたタイポグラフィ、ブランドから外れた配色。
Creative Studio がプロ品質で勝てるのは、**3 つのレイヤーを分離**し、それぞれ
得意な道具に任せるからです。

1. **ビジュアル層** — 画像生成モデルは**背景・キービジュアルのみ**（写真・
   イラスト・商品シーン・質感）を生成します。すべてのプロンプトに「文字を
   一切生成しない」制約を自動付与します。モデルはビジュアルは得意でも、文字
   ——とりわけ日本語——は致命的に苦手だからです。

2. **タイポグラフィ＆レイアウト層** — 見出し・本文・CTA・バッジ・ロゴは
   **HTML/CSS で組版し、ヘッドレス Chromium（Playwright）でレンダリング**します。
   日本語がピクセル単位で完璧に出るうえ、Web フォント・flexbox・グラデーション・
   シャドウが使え、デザイナーと同じ土俵に立てます。

3. **審美眼（アートディレクション）層** — エージェント自身がアートディレクターに
   なります。N 案を生成し、**各 PNG を実際に見て**、creative-refresh スキルの
   7 次元ルーブリックで採点し、上位を選抜、プロバイダの編集パスで弱点を修正して
   再採点し、基準を満たすまでループします。この反復こそが、「それらしく見えるだけ」
   と「実際に出稿できる」を分ける差です。全体の流れは
   [`/creative-generate`](#creative-generate-ワークフロー) スキルに実装されています。

---

## インストール

ビジュアル**生成**（ワークフローのステップ 1〜4）はコアインストールだけで動きます。
**合成**（HTML/CSS ＋ Chromium のタイポグラフィ層）には、オプションの `creative`
extra と Chromium ブラウザが必要です。

```bash
pip install 'mureo[creative]'     # jinja2 / playwright / pillow を追加
playwright install chromium       # Playwright 用の Chromium を初回のみダウンロード
```

合成用の依存は遅延インポートなので、コアインストールは軽量なままです。extra が
未インストールのとき `creative_studio_compose` は `pip install 'mureo[creative]'`
を促す明快なエラーを返します。

---

## プロバイダキー（自分のキーを持ち込む）

Creative Studio は **BYO-API-key** です。画像プロバイダは自分で選び、料金は
プロバイダに直接支払います。キーが設定されたプロバイダだけが「選択可能」になり、
エージェントは `creative_studio_providers_list` で一覧を出し、オペレーターが 1 つ
選びます（複数設定時は全プロバイダへのファンアウトも可能）。mureo は 3 つの
ビルトインを同梱し、サードパーティは `mureo.image_providers` エントリーポイント
グループで追加できます。

| プロバイダ | キー（認証フィールド） | 環境変数フォールバック | 編集パス |
|---|---|---|---|
| OpenAI（gpt-image） | `creative_studio.openai_api_key` | `OPENAI_API_KEY` | あり |
| Google（Gemini image / Imagen） | `creative_studio.gemini_api_key` | `GEMINI_API_KEY` | あり |
| fal.ai（FLUX / Recraft 等） | `creative_studio.fal_key` | `FAL_KEY` | なし |

推奨は `mureo configure` ダッシュボードでの登録です。**Setup** タブの
**Creative Studio（画像生成）** セクションを開くと、プロバイダごとにラベル付きの
マスク入力欄があり、✓/✗ の設定状態が表示され、`creative_studio` 認証情報セクション
に直接保存されます（空欄のままにすると保存済みのキーを保持。キーが 1 つでも保存済みなら
**削除** ボタンでセクション全体を消去できます）。ヘッドレス／CI 環境では上記の環境変数
フォールバックも利用できます。キーはログに出力されず、プロバイダのエラーメッセージも
リダクトされます。

> **おおよそのコスト感。** 各プロバイダは生成画像 1 枚ごとに課金します（現行の
> 定価でモデルや解像度により、おおむね 1 枚あたり数セント〜10 セント程度）。
> アートディレクションループはあえて複数案（`n >= 4`）を生成し、上位案を編集
> することもあるため、完成クリエイティブ 1 本につき画像呼び出しを数回〜十数回
> 見込んでください。正確な料金は各プロバイダの料金ページを確認してください。

---

## BRAND_KIT / kit.yml

軽量なブランドキットを与えると、生成バナーが「汎用テンプレート」ではなく
「そのブランドのもの」に見えるようになります。ワークスペースの
`./BRAND_KIT/kit.yml` から読み込まれ、`creative_studio_brand_kit_get` で参照
できます。**全フィールドが任意**で、フィールド単位で無難な既定値に劣化します
——ファイルが無い・空・壊れていても合成は失敗せず、使えなかったフィールドに
ついて警告を出すだけです。

```yaml
# ./BRAND_KIT/kit.yml
colors:
  primary:    "#1a1d29"   # #rgb または #rrggbb（大文字小文字問わず）
  secondary:  "#6b7280"
  accent:     "#4f46e5"
  text:       "#111827"
  background: "#ffffff"
fonts:
  heading: "Noto Sans JP"  # 安全な font-family 名のみ（[A-Za-z0-9 -_+.]、64 文字以内）
  body:    "Noto Sans JP"
logo: "logo.png"           # BRAND_KIT/ からの相対パス（png/jpg/jpeg/webp、10MB 以内）
logo_min_clear_px: 24      # 非負整数：ロゴ周囲のクリアスペース（px）
```

| キー | ロール / 型 | 既定値 |
|---|---|---|
| `colors` | `primary` / `secondary` / `accent` / `text` / `background`（hex） | 濃紺黒 / グレー / インディゴ / 濃黒 / 白 |
| `fonts` | `heading` / `body`（font-family 名） | `Noto Sans JP` |
| `logo` | `BRAND_KIT/` からの相対パス | なし |
| `logo_min_clear_px` | 整数（px） | `24` |

未知のキーや不正な値は無視されます（`BrandKitWarning` を発出）。不正な hex や
読み込めないロゴは、その 1 フィールドだけが既定値に劣化します。

---

## フォーマット行列

`creative_studio_compose` は、これらのフォーマットの任意の部分集合を 1 回の呼び出しで
レンダリングします。各フォーマットは**セーフエリア**（キープアウト余白）を持ち、
コピーやロゴがフォーマットの端やプラットフォーム UI と干渉しないようにします。

| フォーマット id | サイズ（px） | アスペクト | 掲載面 |
|---|---|---|---|
| `meta_feed_1x1` | 1080 × 1080 | square | Meta フィード |
| `meta_feed_4x5` | 1080 × 1350 | portrait | Meta フィード |
| `story_9x16` | 1080 × 1920 | vertical | Meta ストーリーズ（上 14% / 下 20% を UI 用に確保） |
| `gdn_300x250` | 300 × 250 | landscape | Google ディスプレイ（レクタングル中） |
| `gdn_336x280` | 336 × 280 | landscape | Google ディスプレイ（レクタングル大） |
| `gdn_728x90` | 728 × 90 | landscape | Google ディスプレイ（リーダーボード。余白 2% と狭め） |
| `gdn_160x600` | 160 × 600 | vertical | Google ディスプレイ（スカイスクレイパー。余白 2% と狭め） |
| `rda_landscape` | 1200 × 628 | landscape | レスポンシブディスプレイアセット |
| `rda_square` | 1200 × 1200 | square | レスポンシブディスプレイアセット |

コピーの配置を決めるレイアウトテンプレートは 3 種：`hero_overlay`（下 1/3 に
見出しバンド）、`split`（被写体の横にコピーパネル）、`minimal_badge`（質感の
均一な被写体の上に、中央寄せコピー＋小さなバッジチップ）。

### 日本語フォント

合成エンジンは日本語 2 書体のパイプライン——**Noto Sans JP**（本文）と
**Zen Kaku Gothic New** Bold（ディスプレイ）——を同梱し、`~/.mureo/fonts` に
初回のみチェックサム固定でダウンロードします。ダウンロードできない（オフライン
等）場合は、システムの日本語スタック（ヒラギノ / 游ゴシック / メイリオ）に
フォールバックするため、合成は豆腐（□）ではなく実際のグリフで出力されます。

---

## `/creative-generate` ワークフロー

`creative-generate` スキルが全体を 6 ステップで駆動します。

1. **ブリーフ** — STRATEGY.md（ペルソナ / USP / ブランドボイス）を読み、LP の
   URL があれば `google_ads_landing_page_analyze` / `google_ads_creative_research`
   を実行。ジャンル・オファー・トーン・対象フォーマットをオペレーターと確認。
2. **コピー** — エージェントがブランドボイスに沿って見出し/本文/CTA を 2〜3 案
   執筆。コピーは合成ステップにのみ渡し、**画像プロンプトには絶対に入れません**。
3. **ビジュアル** — `creative_studio_providers_list` の後、
   `creative_studio_generate_visual` を、テンプレートのコピー領域に合わせた
   ネガティブスペース指示付きの「文字なし」プロンプトで実行（`n >= 4`）。
4. **アートディレクションループ** — 各 PNG を `Read` して 7 次元ルーブリックで
   採点し、上位 1〜2 案を残して `creative_studio_edit_visual` で修正、再採点。
   合格基準：全次元が `<= 3` なし、かつ合計 `>= 28/35`、1 案あたり編集は最大 3 回。
5. **合成** — `creative_studio_compose` で選抜ビジュアル＋採用コピー＋テンプレート
   を対象フォーマットにレンダリング。合成後のバナーも再度読み、フォーマットごとに
   可読性・CTA 視認性・セーフエリア遵守を再確認。
6. **納品** — ギャラリー表（パス・フォーマット・テンプレート・スコア）と来歴
   manifest を提示し、承認後は既存のアップロードツール
   （`meta_ads_images_upload_file` / `google_ads_assets_upload_image`）に引き渡し。

Claude Code では `/creative-generate` で実行。Desktop / Cowork では自然言語で
目的を伝えれば起動します（「このキャンペーン用にバナーを 3 パターン作って」など）。

---

## 安全性に関する注意

- **スロットル。** すべてのプロバイダ呼び出しは共有のレートリミッタ
  （`CREATIVE_STUDIO_THROTTLE`）を通るため、ファンアウトでプロバイダ API を
  叩きすぎることはありません。
- **監査専用のアクションログ。** 生成 / 合成 / 編集の各 run は、STATE.json が
  ある場合に監査専用の `action_log` エントリ（来歴 manifest のパス付き）として
  記録されます。ローカルファイルを書くだけでプラットフォームの変更ではないため
  `reversible_params=None` です。可逆な記録は後段の既存アップロード /
  クリエイティブ作成ツール側で行われます。
- **文字なし制約。** 画像プロンプトには常に「文字を生成しない」制約が付与され
  ます。これは意図的です——画像モデルは文字（欧文でも不安定、日本語は壊滅的）の
  描画が不得意だからです。文字をモデルから外して HTML/CSS 層に置くことこそ、
  出力がプロっぽく見える理由です。コピーを画像プロンプト経由で回そうとしないで
  ください。
- **入力検証。** 生成・編集画像とブランドロゴ画像は、下流で使う前に検証されます。
  プロバイダのエンドポイントは固定ベンダーホスト（ユーザー指定 URL なし）なので、
  新たな SSRF 面はありません。
- **ガードレール。** STRATEGY.md の `## Guardrails` → `blocked_operations` に
  `creative_studio_generate_visual` を記載すると、mureo のポリシーゲートがその
  ツールを拒否します（ツール名マッチ、追加設定不要）。
- **Meta の開発モード公開の注意。** 画像アセットのアップロードは成功しても、
  **新規**クリエイティブの Meta への公開は **Live アプリ**が必要です——開発モードの
  アプリはブロックされます（エラー subcode **1885183**）。

---

## トラブルシューティング

**`Creative Studio composition requires the 'creative' extra: pip install 'mureo[creative]'`**
extra とブラウザを入れてください：`pip install 'mureo[creative]'` の後に
`playwright install chromium`。生成（ステップ 1〜4）は extra なしでも動きます。
extra が必要なのは合成だけです。

**`No image provider is configured…`**
プロバイダキーが未設定です。`mureo configure` ダッシュボードの `creative_studio`
セクションで登録するか、`OPENAI_API_KEY` / `GEMINI_API_KEY` / `FAL_KEY` を
export し、`creative_studio_providers_list` で「configured」表示を確認してください。

**`provider '<name>' does not support image editing`**
すべてのプロバイダに編集パスがあるわけではありません（fal.ai には無し）。編集
ループには OpenAI か Google を使うか、`provider` を省略して編集可能な先頭
プロバイダを自動選択させてください。

**合成した日本語が豆腐（□）になる、オフラインでフォントがおかしい**
同梱フォントのダウンロードに失敗し、システムのフォールバックスタックにも日本語
書体が無い状態です。日本語システムフォント（Noto Sans JP / ヒラギノ / 游ゴシック
/ メイリオ）を入れるか、再接続して次回合成時に `~/.mureo/fonts` を用意させて
ください。

**`creative_studio_*` ツールがそもそも出てこない**
`MUREO_DISABLE_CREATIVE_STUDIO=1` でファミリーが無効化されています。これを解除
して MCP サーバーを再起動してください。

---

## 関連ドキュメント

- ワークフロースキル: `mureo/_data/skills/creative-generate/SKILL.md`
- 既存バナーの採点: `mureo/_data/skills/creative-refresh/SKILL.md` → *Visual creative evaluation*
- はじめかた: [docs/getting-started.ja.md](getting-started.ja.md)
- アーキテクチャ: [docs/architecture.md](architecture.md)
