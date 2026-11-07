# explainer_reel_kit.llm — 手元の LLM（任意の段）

設計と使い方は [docs/design/llm.md](../../../docs/design/llm.md)。ここはコードの地図です。

| ファイル | 中身 |
|---|---|
| `client.py` | OpenAI 互換の API のクライアント（標準ライブラリだけ。プロキシなし・リダイレクトなし・API キーなし）。**社外秘の確かめ**を作るときと送る直前に行う |
| `config.py` | `config/llm.yaml` の読み込み、接続先の確かめ（この PC / LAN / それ以外）、用途（tasks）の既定 |
| `confidentiality.py` | 区分の値（`general` 以外はすべて `confidential`）。台本の区分は `storyboard.confidentiality()` で読む |
| `errors.py` | 失敗の種類と終了コード（キットの考え方: 0 / 1 / 2） |
| `offline.py` | 「この PC の外へ出ないか」の確かめ（`erkit draft --offline` と社外秘のとき） |
| `structured.py` | 生成 → 確かめ → 書き直しの依頼（JSON の答え。問題は短く具体的に） |
| `jsonout.py` | 答えから JSON を取り出す（コードブロック・前置き・`<think>` を除く） |
| `thinking.py` | 思考の切り替え（auto / off / on）の送り方と、断られたときの代わり |
| `budget.py` | 文脈長の予算（多めの見積もりと、サーバーでの実測） |
| `condense.py` | 長い資料を task `light` で要点に縮める（小片 → もう一度 → 行を落とす） |
| `draft.py` | `erkit draft`: 中間の JSON → コードで台本（kit-1.1.0）を組み立て → 検証 |
| `marks.py` | `erkit draft --update-marks`: 操作定義の `marks` と説明図の `data-mark` から名前を入れる |
| `readings.py` | `erkit voice suggest`: エンジンの読みと LLM の候補を比べ、辞書への追記案を表示する |
| `cli.py` | `erkit draft` と `erkit llm check`、共通の引数（`--llm-config` など） |

## 守ること

- 送り先の確かめを外す引数・設定・環境変数を足さない。`route: cloud` と API キーを足さない
- `LLMClient` の接続先と区分は読み取り専用。別の送り先には新しいクライアントを作る（そこで確かめ直す）
- LLM に台本の Markdown を書かせない（中間の JSON だけ）。組み立てと検証はコード
- 辞書・台本を上書きしない（`voice suggest` は表示だけ、`draft` は既にある台本で止まる）

## 出力の予算

台本の下書きの答えの上限は、シーン数から `800 ＋ 400 × シーン数`（上限は task の `max_tokens`、既定 4096）。

- 800: 題名・要約・前提・冒頭・まとめと JSON のキー
- 400 / シーン: 見出し・場所・画面の文・ナレーション（2〜3 文）・確認・手順 1〜3

答えが上限で切れたら、何を短くするかを具体的に書いて頼み直し、上限を文脈に収まるぶんだけ増やす。

## テスト

`tests/llm/`。偽の OpenAI 互換サーバー（127.0.0.1 の本物のソケット、モデルなし）を使い、ネットワークは使わない。
送り先の確かめのテストは、接続を開こうとしたら失敗にする（`no_socket`）。
