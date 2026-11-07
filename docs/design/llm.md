# 手元の LLM（erkit draft・erkit voice suggest・erkit llm check）

キットの本体はクラウドの AI を呼びません。**任意の段**として、この PC（か LAN の PC）で動く LLM を呼べます。
使うのは次の 3 つのコマンドだけで、ほかの段（`erkit make` など）は LLM を使いません。

| コマンド | すること | 送るもの |
|---|---|---|
| `erkit draft <台本の id> --source <資料> …` | 資料から台本の下書きを作り、`erkit check` で確かめて表示する | 資料・指示 |
| `erkit draft <台本の id> --update-marks` | 下書きに mark の名前を入れる（操作定義の `marks`・説明図の `data-mark` から） | 何も送らない |
| `erkit voice suggest <台本>` | 読み辞書への追記案を**表示する**（辞書は書かない） | 辞書の語・確認語と、それを含む 1 文 |
| `erkit llm check` | 接続・モデルの有無・応答までの時間 | 決まった短い文だけ |

`erkit doctor` は、任意の行として「手元の LLM（任意）」を表示します（モデルの一覧を聞くだけ）。見つからなくても「そろっています」は変わらず、`erkit make` の確かめにも入りません。

## 接続

- OpenAI 互換の API（`/v1/models`・`/v1/chat/completions`）。LM Studio・Ollama などのサーバー
- 標準ライブラリ（`urllib`）だけで呼ぶ。**プロキシを使わず、リダイレクトに従わない**
- 設定は `config/llm.yaml`（ひな形 [`config/llm.example.yaml`](../../config/llm.example.yaml)）。探す順は
  `--llm-config` ＞ 環境変数 `ERKIT_LLM_CONFIG` ＞ 今のフォルダの `config/llm.yaml` ＞ キットのフォルダの `config/llm.yaml` ＞ 組み込みの既定
- 組み込みの既定: `lmstudio`（`http://127.0.0.1:1234/v1`、既定）と `ollama`（`http://127.0.0.1:11434/v1`）
- モデル: `--model` ＞ `tasks.<用途>.model` ＞ `profiles.<名前>.model` ＞ **サーバーに読み込まれているモデル**（1 つだけのとき。2 つ以上なら `--model` を求める）。
  指定のモデルがサーバーに無ければ止める（別のモデルを勝手に使わない）
- 用途（tasks）: `draft`（台本の下書き）と `light`（読みの候補・長い資料の要点）。思考（thinking）・答えの上限・想定する文脈長を持つ

| 引数（共通） | 意味 |
|---|---|
| `--llm-config` | 設定ファイル |
| `--profile` | `profiles` の名前（既定 `default_profile`） |
| `--base-url` | 接続先の上書き（下の確かめはそのまま） |
| `--model` | モデルの id |
| `--llm-timeout` | 1 回の問い合わせのタイムアウト秒（既定 600） |

## 送り先の確かめ（外せない）

1. **接続先**（`route: local` だけ）: この PC（`127.0.0.0/8`・`::1`・`localhost`）か、LAN の IP アドレス
   （`10/8`・`172.16/12`・`192.168/16`・`169.254/16`・`fc00::/7`・`fe80::/10`）だけ。ほかのホスト名・IP は止める
2. **社外秘の区分**: 台本の区分（`storyboard.confidentiality()`）か `--confidentiality` が `general` 以外（未記入・書き間違いを含む）なら、
   **この PC の LLM だけ**。LAN の PC にも送らない

- どちらも `LLMClient` が**作るとき**と、**送る直前（毎回）**に確かめる。接続先と区分は作るときに決まり、後から変えられない
- 設定・引数・環境変数で外す方法は無い（`--base-url` で外を指しても止まる）
- **`route: cloud` と API キーは無い**。設定に `route: cloud`・`api_key`・`api_key_env` があればエラー。`Authorization` の見出しは送らない
- `erkit llm check` と `erkit doctor` は決まった短い文・モデルの一覧だけを送るので、`general` として LAN の PC も確かめられる（LAN なら「社外秘の台本には使えない」と表示）
- `erkit draft` は、社外秘のとき `--offline` と同じ確かめ（LLM と `--url` がこの PC か）を、何かを送る・作る前に行う

## erkit draft

```text
erkit draft <台本の id> --source <資料> [--source <資料> …] [--audience A|B|C] [--kind tool_intro|work_manual|explainer]
            [--capture diagram|web|manual] [--url URL] [--scenes N] [--title 題名]
            [--confidentiality confidential|general] [--offline] [--out フォルダ] [--retries N]
```

1. 資料（手元の UTF-8 のテキスト。何も取りに行かない）を読む
2. task `draft` のモデルに **小さな中間の JSON**（題名・要約・前提・冒頭・シーン・まとめ）を書かせる。LLM に Markdown は書かせない
3. **コード**が台本（Markdown、スキーマ kit-1.1.0）を組み立て、`storyboard.validate_storyboard` で検証する。
   スキーマ違反・シーン数の違い・Markdown の記号・検証の不合格は、**具体的な直し方を付けて**書き直しを頼む（既定 2 回）
4. 柔らかい確かめは注意として表示する: 資料にない単位つきの数値（作り話の疑い）・見出しの長さ・ナレーションの文の数・セレクタらしい書き方・**動画で触れない語**
5. `reels/<台本の id>/<台本の id>.storyboard.md` と記録 `draft.json` を書き、`erkit check` と同じ結果を表示する

- 出力は**上書きしない**（台本が既にあれば止める）。失敗したときは `draft.json` だけ（最後の答え・各回の問題を残す）
- 区分は既定で `confidential`。`general` にしてよいのは、資料が公開済みの情報だけだと**人が**確かめたとき
- 種別（`--kind`）: `explainer` のときは、構成の決まり（問い → しくみ → 比べる・条件 → 選び方・減らし方 → まとめ）を指示に足す
- 見る人（`--audience`）: `A` 初めての人（既定） / `B` よく使う人・詳しい人 / `C` 専門家・作る人。指示の文はこの言い方だけを使う
- 画像（`--capture`、全シーン共通）:

| 値 | 台本の画像 | `capture` | 下書きの後に人がすること |
|---|---|---|---|
| `diagram`（既定） | `generated`、`説明用再構成図`、`assets/sNN_<名前>.png` | `prompt`（図に描くもの） | `diagrams/` に HTML を書き、`tool: html` と `src` を足す |
| `web` | `web`、`実キャプチャ`、`captures/<id>/sNN_<名前>.png` | `url`・`steps` | 操作定義（`erkit record`）を作る |
| `manual` | `manual`、`実キャプチャ` | `instructions` | 画像を置く（置くまで `erkit check` は不合格） |

- 注釈（`recipe_params.mark`）は下書きでは書かない。mark の名前が決まったら `erkit draft <id> --update-marks` で入れる
  （YAML の行を**足すだけ**。ほかの行は 1 字も変えない。既に mark がある・recipe が `highlight_box` / `arrow_move` でない・名前が見つからないシーンはそのまま）
- 動画で触れない語: 設定の `avoid_words`（既定は空）。指示に「触れない」と書き、出てきたら注意を出す（大文字・小文字は区別しない）

### 文脈長に収める

task の `expected_context`（既定 8192）に、指示・資料・答えの上限（シーン数から: 800 ＋ 400 × シーン数、上限は task の `max_tokens`）が収まるようにする。

- 見積もりは多め（日本語など 1 字 ≈ 1 トークン、英数字 4 字 ≈ 1 トークン）。超えそうなときはサーバーで実際の数を測る（`max_tokens=1` の呼び出し。`--no-measure` で測らない）
- 収まらなければ、task `light` で資料を見出しごとの小片に分けて要点に縮める（数値・画面の項目名・手順の順番・注意は残す）→ まだ長ければもう一度 → それでも長ければ行を落とす → それでも収まらなければ、下書きを頼まずに止める
- 資料にない数値の確かめは、縮める前の全文に対して行う

## erkit voice suggest

`erkit voice kana` と同じくエンジン（AivisSpeech）の読みを集め、task `light` のモデルに「ナレーションでどう読むべきか」（カタカナ）を聞く。
長音・区切りの違いを除いて比べ、違う語だけを `entries` への追記案（YAML の行）として**表示する**。辞書のファイルは開いて読むだけで、書かない。

- 台本だけを受け付ける（区分を読むため）。区分が未記入なら社外秘
- 社外秘なら、音声合成エンジンも LLM もこの PC だけ

## 終了コード

| コード | 意味 |
|---|---|
| 0 | できた・合格 |
| 1 | 下書きが検証に通らない・LLM の失敗・接続できない・モデルが無い・社外秘の確かめで止めた・上書きを止めた |
| 2 | 引数・設定の誤り（`route: cloud`・API キーを含む）・資料が読めない・長すぎて収まらない（task `light` が無い） |

## 元の仕組みから持ち込まなかったもの

- PC での実用性の測定（bench）
- SketchUp の撮影（demo）を読む部分、Notion に触れない確かめ（`avoid_words` で一般化した）
- クラウドの AI の接続（`route: cloud`）と API キー
