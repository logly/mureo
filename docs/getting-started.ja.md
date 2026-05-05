# はじめかた (Getting Started)

mureo は**ローカルで動く、AI広告運用チーム**です。本ガイドでは **モード**（どのデータを使うか）と **ホスト**（エージェントを動かす場所）を選び、対応する手順をたどります。

「自分はどの組み合わせがいいの?」だけ知りたい方は、末尾の [どの組み合わせを選ぶか](#どの組み合わせを選ぶか) を参照。

---

## モード × ホスト 早見表

| | Claude Code | Claude Desktop チャット | Cowork (Desktop) |
|---|---|---|---|
| **デモ** (合成データ) | `mureo setup claude-code --skip-auth` + `mureo demo init --scenario seasonality-trap` | `mureo install-desktop --with-demo seasonality-trap` | チャットと同じ + Cowork でワークスペースフォルダを接続 |
| **BYOD** (自前 XLSX) | `mureo setup claude-code --skip-auth` + `mureo byod import bundle.xlsx` | `mureo install-desktop` + `mureo byod import bundle.xlsx` | チャットと同じ + フォルダ接続 |
| **認証** (Live API) | `mureo setup claude-code` (OAuth ウィザード) | `mureo install-desktop` + `mureo auth setup --web` | チャットと同じ + フォルダ接続 |

**ホストの違い:**

- **Claude Code** — `/<name>` で skill 起動可、`Read` / `Write` / `Bash` / MCP すべて使える、ターミナル/IDE 上で動作。
- **Claude Desktop チャット** — 自然言語のみ。`Read` / `Write` / `Bash` は **無し**、MCP のみ。「日次チェックして」のように依頼。
- **Cowork** (Desktop) — チャットと同じ MCP に加えて、接続したフォルダ内のファイル読み書きが可能。非エンジニアが「目で見ながら」操作したい場合に最適。

---

# デモ (合成シナリオ)

mureo は 4 つのデモシナリオを内蔵しています: `seasonality-trap` / `halo-effect` / `hidden-champion` / `strategy-drift`。それぞれ `STRATEGY.md` / `STATE.json` / 合成 XLSX バンドルを生成します。

## A. デモを Claude Code で試す (5 分)

```bash
pip install mureo
mureo setup claude-code --skip-auth      # MCP + skills + 認証ガード、OAuth はスキップ
mureo demo init --scenario seasonality-trap
```

その後、デモワークスペースで Claude Code を開き:

```
/daily-check
```

期待結果: シナリオ合成データに基づくマルチプラットフォーム健全性レポート、Goal 進捗サマリー、(シナリオによっては)異常検知と推奨アクション。

シナリオ切替: `mureo demo init --scenario halo-effect --force`。

## B. デモを Claude Desktop チャットで試す (10 分)

```bash
pip install mureo
mureo install-desktop --workspace ~/mureo --with-demo seasonality-trap
```

このコマンドが行うこと:
1. `~/mureo/` を作成し、シナリオ一式 (`STRATEGY.md` / `STATE.json` / 合成 XLSX バンドル) を展開。
2. ラッパースクリプト `~/.local/bin/mureo-mcp-wrapper.sh` を生成し、MCP サーバーをワークスペースに固定。
3. `~/Library/Application Support/Claude/claude_desktop_config.json` に `mureo` を登録。

その後 **Claude Desktop を完全終了** (`⌘Q`) → 再起動。

チャットタブで:

```
キャンペーンを日次チェックして
```

Claude が自然言語から skill を選んで `mureo_*` MCP tool を呼び出し、STRATEGY/STATE とデモデータを読みます。

> **slash メニューに skill が出ない?** Claude Desktop の slash ピッカーには claude.ai に登録済みの skill のみ表示されます。[Anthropic Skills マーケット](https://github.com/anthropics/claude-plugins-official) に mureo が掲載されるまでは、(a) 自然言語で依頼するか、(b) [`mureo/_data/skills/<name>/SKILL.md` を claude.ai 管理画面で手動アップロード](#claudeai-へのスキル手動登録) してください。

## C. デモを Cowork で試す (10 分)

Cowork は Claude Desktop の「自律実行」タブ — チャットと同じ MCP に加え、接続したフォルダのファイル読み書きが可能。

```bash
pip install mureo
mureo install-desktop --workspace ~/mureo-demo --with-demo seasonality-trap
```

Claude Desktop を **再起動** → **Cowork** タブに切替。

1. Cowork の **Connectors** / フォルダ選択を開く。
2. `~/mureo-demo` フォルダを **接続**。
3. Cowork で:
   ```
   日次チェックして
   ```

Cowork は MCP tool 経由(ラッパー越し)と Read/Write 経由の両方で `~/mureo-demo` を扱え、エージェントから見える情報量が最も豊富です。

> **なぜフォルダ接続するのか?** `mureo_strategy_get` / `mureo_state_*` MCP tool は接続なしでも動きますが、Cowork の Read/Write を併用するとエージェントが生バンドルファイルを直接見たり、ロールバックプランを書き出したりできます。両経路は同じワークスペース cwd を共有するので、どちらの更新も即座に他方に見えます。

---

# BYOD (Bring Your Own Data — 自前の XLSX バンドル)

BYOD は、実際の Google Ads / Meta Ads データを **読み取り専用エクスポート** で mureo に渡す方式です。OAuth フローは不要、ミューテーション系 tool は書き込みを拒否するので実アカウントを誤操作する心配がありません。

## Step 1 — データファイルを取得する

| プラットフォーム | エクスポート方法 | 所要時間 |
|---|---|---|
| **Google Ads** | Google Sheet テンプレート (Apps Script) → Sheet を埋める → `.xlsx` でダウンロード | アカウントごとに約 5 分(初回のみ) |
| **Meta Ads** | Ads Manager → Reports → 保存済みレポート (mureo テンプレート) → 2 クリックで XLSX エクスポート | 約 2 分 |

詳細手順:
- [`docs/byod.ja.md#google-ads-setup`](byod.ja.md#google-ads-setup) — Google Ads テンプレート + 入力手順
- [`docs/byod.ja.md#meta-ads-setup`](byod.ja.md#meta-ads-setup) — Meta Ads 保存済みレポート (9 言語対応: English / 日本語 / 简体中文 / 繁體中文 / 한국어 / Español / Português / Deutsch / Français)

エクスポートは独立しているので、片方だけでも開始できます(あとから追加可)。Search Console / GA4 は BYOD 非対応 — Live API のみ。

## Step 2 — ファイルの置き場所

XLSX 自体は一時的な入力で、import 後はデータが `<workspace>/byod/<platform>/` (または `install-desktop` 未実行時はグローバルの `~/.mureo/byod/<platform>/`) 配下に展開されます。

| セットアップ | XLSX の推奨置き場所 |
|---|---|
| **Code** (CLI 直叩き) | 任意の場所(例: `~/Downloads/mureo-google-ads.xlsx`) |
| **Desktop チャット** | 任意 — ただし `~/mureo/` 内が便利(MCP サーバーのワークスペースなので) |
| **Cowork** | **接続フォルダ内** (`~/mureo/`) — Cowork サンドボックスから見える必要あり |

ファイル名は自由(import 時にパスを指定)。

## Step 3 — ファイルを取り込む (import)

> **現状**: BYOD import はターミナル実行のみ(ロードマップ Phase 4 で `mureo_byod_import` MCP tool 化予定)。それまでは下記コマンドをシェルで。

```bash
mureo byod import ~/Downloads/mureo-google-ads.xlsx
mureo byod import ~/Downloads/mureo-meta-ads.xlsx     # Meta は後から追加 OK
```

データの配置先は `mureo install-desktop` 実行有無で変わります:

- **ラッパーあり** (`install-desktop` 実行済み): ラッパーはチャット起動時に `MUREO_BYOD_DIR=<workspace>/byod` を export しますが、CLI 単体は従来 default を使います。CLI からワークスペースに明示的に書き込みたい場合:
  ```bash
  MUREO_BYOD_DIR=$HOME/mureo/byod mureo byod import ~/Downloads/mureo-google-ads.xlsx
  ```
- **ラッパーなし** (CLI 直叩き、`install-desktop` 未実行): 常に `~/.mureo/byod/<platform>/` に書き込み(従来 default)。

> **デモから本番データへ切り替えるとき**: ワークスペースを分ければ衝突しません。`mureo install-desktop --workspace ~/mureo-demo --with-demo ...` と `mureo install-desktop --workspace ~/mureo-real --force` で独立した BYOD ストアが 2 つ作れます。詳細は [docs/byod.ja.md](byod.ja.md)。

## Step 4 — ワークフローを実行

### Claude Code
```
/daily-check
```

### Claude Desktop チャット
```
日次チェックして
```

### Cowork
チャットと同じ。フォルダ接続済みなら、Cowork は `<workspace>/byod/google_ads/manifest.json` を直接開いて取込内容を確認することもできます。

## BYOD で動くもの

- 読み取り専用分析: `daily-check` / `weekly-report` / `goal-review` / `search-term-cleanup`(分析)/ `competitive-scan`(限定的 — auction insights は BYOD バンドルに含まれない)/ `creative-refresh`(提案のみ)。
- ミューテーション系 tool (`rescue` / `budget-rebalance` / `creative-refresh` 実行 / search-term apply) は `{"status": "skipped_in_byod_readonly"}` を返して書き込みを拒否。実際に変更を適用したい場合は Live API へ移行。

---

# 認証 (Live API)

mureo を Google Ads / Meta Ads API に直結する方式。**実際にキャンペーンを変更する** (`/rescue` / `/budget-rebalance` / `/creative-refresh` / `mureo rollback apply`) には必須。GA4 / Search Console もこの経路でのみ使えます。

## Step 1 — 認証情報を取得

| プラットフォーム | 必要なもの |
|---|---|
| **Google Ads** | [Developer Token](https://developers.google.com/google-ads/api/docs/get-started/dev-token) + OAuth Client ID + Client Secret |
| **Meta Ads** | [Meta for Developers](https://developers.facebook.com/) の App ID + App Secret(開発モードで OK) |
| **GA4 / Search Console** | OAuth ログインのみ(developer token 不要、ウィザードが処理) |

> **承認の所要時間**: Google Ads developer token の承認は 1〜3 週間かかることがあります。待ちの間は BYOD で運用 → 承認後に Auth へ移行が現実的。

認証情報は `~/.mureo/credentials.json` (権限 `0600`) に保存されます。手動編集不要 — ウィザードが処理します。

## Step 2 — OAuth ウィザードを実行

ホストごとに手順が異なります。

### A. Code で認証

```bash
pip install mureo
mureo setup claude-code             # interactive OAuth wizard が setup の一部として走る
```

setup コマンドはローカル Web ウィザードを `http://127.0.0.1:<random-port>/` で起動し、各 token / secret を入力するフォームを表示。同じブラウザ内で OAuth フローも完結します。`--no-google-ads` / `--no-meta-ads` で個別に skip 可能。

### B. Desktop チャットで認証

```bash
pip install mureo
mureo install-desktop --workspace ~/mureo
mureo auth setup --web              # ブラウザベースの OAuth ウィザード
```

Claude Desktop を再起動。チャットタブで:

```
日次チェックして
```

MCP サーバーが `~/.mureo/credentials.json` から認証情報を自動読み込みします。

### C. Cowork で認証

Desktop チャットと同じ — Cowork は同じ MCP entry を共有します。`install-desktop` + `auth setup` 完了後、Cowork で **ワークスペースフォルダを接続** (`~/mureo`) すれば、エージェントがローカルファイルも参照可能に。

> **Phase 4 プレビュー**: `mureo_auth_setup` MCP tool が追加されると、チャット内から OAuth ウィザードを起動できるようになります。それまでは `mureo auth setup --web` をターミナルで一度実行する必要あり。

## Step 3 — 動作確認

```bash
mureo auth status
mureo auth check-google             # マスク済み出力で確認
mureo auth check-meta
```

その後 BYOD Step 4 と同じワークフローを試してみてください。

---

## どの組み合わせを選ぶか

30 秒の判断ツリー:

1. **試したいだけ?** → デモ + Code または Desktop チャット。5〜10 分で完結。元に戻すのも簡単(workspace ディレクトリを消すだけ)。
2. **自分のアカウントはあるが、developer token はまだ?** → BYOD。エクスポート含めて 10〜15 分。読み取り専用なので安全。
3. **developer token 承認済みで実行までしたい?** → Auth (Live API)。初回 30〜60 分。`/rescue` や `/budget-rebalance` の実反映には必須。

| こんな人は… | これを選ぶ |
|---|---|
| 合成データで mureo を評価したい | **デモ + Code** |
| 非エンジニアにデモを見せたい | **デモ + Desktop チャット**(install 後はターミナル不要) |
| エージェントに最も豊富な情報を持たせたい | **デモ + Cowork**(フォルダアクセスあり) |
| 自分のアカウントで分析だけしたい | **BYOD + Code**(または Desktop チャット / Cowork) |
| 実際にキャンペーンを変更したい | **Auth + Code**(現状 `/rescue` を end-to-end で実行できるのは Code のみ) |

ホストごとの skill 起動方法:

| ホスト | skill の起動 | 補足 |
|---|---|---|
| Claude Code | `/daily-check` / `/budget-rebalance` ... | 操作系 10 + foundation 6 すべてローカルで利用可 |
| Claude Desktop チャット | 自然言語(「日次チェックして」) | claude.ai に登録された skill のみ表示(手動 upload またはマーケット経由) |
| Cowork | 自然言語 | チャットと同じ登録要件 |

---

## claude.ai へのスキル手動登録

> [Anthropic Skills マーケット](https://github.com/anthropics/claude-plugins-official) に mureo が掲載されるまで、Desktop / Cowork ユーザーは手動登録できます:

1. claude.ai を開く → **Skills** 管理ページへ。
2. 操作系 skill を 1 つずつアップロード: `mureo/_data/skills/<name>/SKILL.md` (10 ファイル: `daily-check` / `budget-rebalance` / `search-term-cleanup` / `creative-refresh` / `rescue` / `goal-review` / `weekly-report` / `competitive-scan` / `onboard` / `sync-state`)。
3. Foundation skill (`_mureo-*`) は他 skill が PREREQUISITE で参照する辞書 — 登録は任意ですが推奨(エージェントが tool 選択を間違える確率が下がる)。
4. Claude Desktop を再起動。

---

## トラブルシューティング

**「Workspace not found」 / `[Errno 30] Read-only file system`**
`mureo install-desktop` を `--workspace` 無しで走らせたか、Claude Desktop が `cwd` 設定を尊重していない可能性。明示的に再実行: `mureo install-desktop --workspace ~/mureo --force`。ラッパースクリプトが cwd を強制するので、Desktop の既知のバグを回避できます。

**Connectors UI に `mureo` MCP が出てこない**
Claude Desktop を完全終了 (`⌘Q`) して再起動。設定は完全起動時のみ再読み込みされます。

**自前データに切り替えてもデモの BYOD データが残る**
両方を同じワークスペースに入れたか、両方が legacy グローバル `~/.mureo/byod/` を指していた可能性。`--workspace` を分ける(`~/mureo-demo` と `~/mureo-real` 等)、または `mureo byod clear` でリセット。

**Code で `/daily-check` 等の slash command が出ない**
`ls ~/.claude/skills/` を確認 — `daily-check` ディレクトリが無ければ `mureo setup claude-code` を再実行。あるのに slash ピッカーに出ない場合は Claude Code を再起動。

詳細は [docs/byod.ja.md](byod.ja.md), [docs/authentication.md](authentication.md), [docs/cli.md](cli.md) を参照。
