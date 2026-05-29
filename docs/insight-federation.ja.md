# Insight federation — `mureo_consult_advisor`

> English version: [insight-federation.md](insight-federation.md)

mureo の `mureo_consult_advisor` MCP ツールは、診断ワークフロー中に
外部の **advisor server** に実務ノウハウを問い合わせる仕組みです。
advisor 側は自分のコーパスに対してベクトル検索を実行し、上位 k 件
の断片を返します。推論は operator マシン上の Claude が行います。
advisor server に LLM は不要 — 検索エンドポイントであり生成
エンドポイントではありません。

## この設計の理由

コーパス全体を毎回返す方式 (v0.9.18 時点で検討された "text-return"
案、issue [#163](https://github.com/logly/mureo/issues/163)) は、
1 回の呼び出しで advisor の全ノウハウを expose してしまいました。
v0.9.19 で採用した retrieval pattern は、コーパスを非公開のまま、
クエリにマッチした断片だけを表面化します。

- advisor server がコーパス・embedder・vector store を保持。
- mureo は operator の質問とローカルキャンペーン文脈を組み立てた
  クエリテキストを送信。
- server はクエリを embed → vector store を検索 → 上位 k 件の
  断片 (text + similarity) を返す。
- operator 側 Claude が断片を比較・適用して回答する。

## オペレーター側のセットアップ

`~/.mureo/insight_sources.json` を作成します:

```json
{
  "sources": [
    {
      "name": "acme",
      "transport": "stdio",
      "command": "acme-advisor-mcp",
      "tool": "vector_search",
      "top_k": 5
    },
    {
      "name": "benchmarks",
      "transport": "http",
      "url": "https://benchmarks.example/mcp",
      "headers": {"Authorization": "Bearer PASTE_TOKEN_LITERAL_HERE"},
      "tool": "vector_search",
      "top_k": 3,
      "timeout_sec": 8
    }
  ]
}
```

対応する transport:

| transport | mureo の利用ヘルパー              | 必須フィールド                       |
|-----------|-----------------------------------|--------------------------------------|
| `stdio`   | `mcp.client.stdio.stdio_client`   | `command` (＋任意で `args`, `env`)   |
| `sse`     | `mcp.client.sse.sse_client`       | `url` (＋任意で `headers`)           |
| `http`    | `mcp.client.streamable_http.streamablehttp_client` | `url` (＋任意で `headers`) |

per-source error isolation: 遅い／落ちている／壊れた応答を返す
advisor が 1 つあっても、他の advisor をブロックしません。
`timeout_sec` (default 10s) が各呼び出しを cap し、失敗は
「その advisor からは断片なし」に縮退します。

**シークレットはそのまま転送されます** — mureo は `env` や
`headers` の値に対して `${VAR}` 形式の環境変数展開を行いません。
リテラル値をペーストし、機密を含む場合は
`chmod 600 ~/.mureo/insight_sources.json` を実行してください。

**`env: {}` を明示すると subprocess は完全にシールされます** ——
「parent env を継承」ではありません。advisor を
`"env": {}` で起動した場合、operator の `OPENAI_API_KEY` や
クラウド認証情報、シェル履歴等は一切渡りません。env キー自体を
省略した場合のみ parent env が継承されます。最小権限原則に従う
挙動ですが、シェルスクリプト的な継承を期待する人には驚きうるので
明示しておきます。

## ツールの呼び出し

`mureo_consult_advisor` の引数:

- `question` (必須) — 調査したい具体的な質問。汎用文より
  具体文の方が当たりやすい:
  「Brand-Search の今週の CPA が 30% 上がっているのはなぜ?」
  ＞「Google 広告のコツ」
- `campaign_id` (任意) — 指定すると mureo がそのキャンペーンの
  name / status / daily_budget と直近の action_log を query に
  注入するので、advisor のベクトル検索が文脈付きでマッチング
  できます。

応答は単一の Markdown ブロックで、ヒットした advisor ごとに 1 つ
section が並びます:

```
## acme
- (similarity 0.92) CV が少ない時はマイクロコンバージョンを使う...
- (similarity 0.81) Brand Search の CPA インフレは通常...

---

## benchmarks
- (similarity 0.78) 日本 B2B 検索の CPA 中央値は約 4,200 JPY...
```

source が 1 件も設定されていなければ、本ドキュメントを案内する
ガイダンス文字列を返します。全 source が空応答だった場合は
その旨を明示するので、エージェントが無音でフォールバック
することはありません。

## advisor server を実装する

server 側で必要なツールは **1 つ** だけです。
`{query, top_k}` を受け取り、`{text, similarity, ...}` 形式の
断片を JSON 配列で返します。追加フィールド (`tags`, `case_id`,
ソース URL …) はそのまま agent へ転送されます。

FastMCP + sentence-transformers + ChromaDB を使った 30 行
程度のサンプル:

```python
import json
from fastmcp import FastMCP
from sentence_transformers import SentenceTransformer
import chromadb

embedder = SentenceTransformer("intfloat/multilingual-e5-base")
collection = chromadb.PersistentClient(path="./vectors").get_or_create_collection("kb")

server = FastMCP("acme-advisor")

@server.tool()
def vector_search(query: str, top_k: int = 5) -> str:
    query_vec = embedder.encode([f"query: {query}"]).tolist()[0]
    hits = collection.query(query_embeddings=[query_vec], n_results=top_k)
    fragments = [
        {
            "text": doc,
            "similarity": float(1 - dist),
            **(meta or {}),
        }
        for doc, dist, meta in zip(
            hits["documents"][0],
            hits["distances"][0],
            hits["metadatas"][0] or [{}] * len(hits["documents"][0]),
        )
    ]
    return json.dumps(fragments)

if __name__ == "__main__":
    server.run()
```

server に LLM は不要です。embedder + vector store + 1 ツール が
コントラクトの全てです。

## server 側のセキュリティ・スクレイピング対策仕様

mureo は **canonical かつ行儀の良いクライアント** です:
`top_k` を最大 50 に制限し、応答 1 回あたり 1 MiB で切り捨て、
断片テキストを 4 KiB で truncate し、advisor 間は並列に
fan-out します。これらは **operator のマシン** を守るための
制約であって、**あなたのコーパス** を守るものではありません。
mureo は operator のマシンで動くため、悪意のある operator
(あるいはそのマシン上で prompt injection に乗っ取られた agent)
は client 側の制限を回避できます。**乱用対策は全て server 側の
責務です。**

コーパスに何らかの価値があるなら、`vector_search` の全呼び出しを
untrusted と扱い、以下の制御を実装してください。

### 認証 (非公開コーパスなら必須)

mureo は `env` / `headers` をそのまま転送するので、
bearer token / API key / mTLS いずれも使えます:

- **stdio**: subprocess の env 経由でクレデンシャルを起動時に
  読み込む。operator は `~/.mureo/insight_sources.json` の
  `"env": {"ACME_API_KEY": "..."}` に値を入れます。
- **sse / http**: request header から `Authorization` を読む。
  operator は同ファイルの `"headers": {"Authorization": "Bearer ..."}`
  に値を入れます。mureo は `${VAR}` 展開を **行わない** ため、
  operator はリテラル値をペーストする想定です。

認証されていない呼び出しは MCP の `isError` 応答で拒否してください。
キーは定めたサイクルでローテーションし、1 キー = 1 テナント / 1
クォータバケットに紐付け、漏洩時の影響範囲を局所化します。

### キー単位のレートリミット (必須)

retrieval pattern は 1 回の呼び出しで N 件の断片を返します。
攻撃者は異なる query を多数投げることで、時間をかけて
コーパス全体をマッピングできます。**キー単位のスライディング
ウィンドウ** でレートリミットを設定してください:

- 妥当なデフォルト例: 1 キーあたり **60 calls / 分、1,000 calls
  / 日**。コーパスの価値に応じて調整します。
- 超過時は HTTP 429 (または MCP `isError` + 明確なメッセージ)
  を返します。mureo はその呼び出しを「断片なし」として扱い、
  WARNING ログを出します。

### キー単位のフラグメントクォータ (推奨)

呼び出し回数制限より高精度な防御として、**そのキーがこれまでに
見た fragment ID のユニーク数** を rolling window で追跡します。
たとえばコーパスの 5〜10% を見た時点で throttle または手動
レビュー要求に切り替えます。「微妙に異なる query で全体を
舐める」攻撃に対しては、call-rate 制限単体より遥かに有効です。

### クエリログと異常検知 (推奨)

各呼び出しについて、timestamp / API key / query 長 (または salt
付きハッシュ) / top_k / 返した fragment ID / クライアント IP
(HTTP・SSE) を記録します。以下のパターンを監視:

- 極端に短い／汎用的なクエリ (`"a"`、`"the"`、空 embedding)
  — コーパス偵察の可能性。
- 1 キーが短時間に異なるコーパス領域を横断するパターン。
- 1 キーに紐付く複数セッションが並列リクエストを出すパターン。

ML を使わなくても、ログに対する cron ジョブで大半の乱用は
検知できます。

### レスポンス整形 (推奨)

- **`top_k` を server 側でもクランプしてください。** mureo は
  `top_k <= 50` を強制しますが、手書き／悪意のある MCP client
  は強制しません。server 側でも clamp します。
- **テキストを出力時にサニタイズします。** クレデンシャル・
  PII・内部 URL・LLM が見出しとして誤認しうるセクションマーカー
  を除去します。mureo は render 時に `##` / `---` を defang
  しますが、コーパスを他所でも使う場合は source 側でもサニタイズ
  すべきです。
- **断片テキストを per-fragment で truncate** し、1 断片で全文
  書類が漏れる事態を防ぎます。
- **similarity スコアを丸めます** (例: 小数 2 桁)。生の距離値は
  embedding モデルや ANN パラメータを指紋化する手掛かりに
  なります。

### コーパス分割 (multi-tenant server で推奨)

server が複数テナントを背負っている場合、vector store を
テナント単位で partition し、各 API キーを 1 partition に
bind します。1 回の検索が partition をまたいではいけません。
「1 キー漏洩 → 全テナント情報開示」を防ぐ最も効果的な対策です。

### 運用上の衛生

- server は最小限の env だけで sandbox / container 内で
  動かしてください。operator は `"env": {}` を明示することで
  自分のシークレットを subprocess に渡さないよう shield
  できますが、server 側でも process 自体を untrusted と
  扱うのが安全です。
- MCP SDK と vector store クライアントのバージョンを pin
  してください。
- embedder の重みを更新するときは段階的にロールアウト
  してください。途中で切り替えるとキャッシュしているクライアント
  との similarity 意味論が破綻します。

### mureo が保証する事項

| 関心事                                  | mureo の保証                                   |
|----------------------------------------|------------------------------------------------|
| `env` / `headers` を verbatim 転送      | Yes (`${VAR}` 展開なし)                       |
| 1 call あたりの `top_k` 上限           | `<= 50` (config ロード時に検証)               |
| 1 call の応答バイト数 上限             | `1 MiB` 生 JSON                                |
| 1 fragment のテキスト 上限              | `4 KiB`                                        |
| パース対象 fragment 件数 上限          | `50`                                           |
| per-source タイムアウト                | `timeout_sec` (`<= 120s`, default `10s`)       |
| advisor 間の並列 fan-out               | Yes (`asyncio.gather`)                         |
| server 側レートリミット                 | **No** — server 実装者の責務                  |
| server 側認証                          | **No** — server 実装者の責務                  |
| server 側監査ログ                      | **No** — server 実装者の責務                  |

## ローカルの `/learn` ツールとの違い

| ユースケース                                | 使うツール                       |
|--------------------------------------------|---------------------------------|
| operator 自身の `/learn` 履歴を取り出す    | `mureo_learning_insights_get`   |
| 外部の共有ノウハウを参照する                 | `mureo_consult_advisor`         |

両ツールは共存します。v0.9.18 の `mureo_learning_insights_get` は
変更なし、v0.9.19 の `mureo_consult_advisor` がその隣に
外部参照面として追加されます。
