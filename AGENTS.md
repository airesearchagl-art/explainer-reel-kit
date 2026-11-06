# AGENTS.md — このリポジトリで説明動画を作るエージェントへ

このファイルは、利用者がふだん使う AI のエージェント（Claude Code・Codex・Cursor・Copilot・Gemini CLI・手元の LLM など）が最初に読む入口です。
詳しい手順は [docs/guide/](docs/guide/README.md) にあります。各段の前に、その段の手順書を読んでください。

## 1. このリポジトリですること

利用者と対話して**台本**（Markdown 1 枚）を書き、キットのコマンド `erkit` で説明動画（MP4）にします。

```text
題材の聞き取り → 見る人 → 構成 → 台本 → 説明図・撮影 → 確認 → MP4
```

- あなた（エージェント）の仕事は、人と対話して台本・説明図の HTML・操作定義を**書くこと**と、`erkit` を呼んで結果を読み、直すことです
- 動画を作る処理はすべて `erkit` が持っています。キットの本体はクラウドの AI を呼びません
- 例として、サンプル題材 [samples/u-value/](samples/u-value/README.md)（窓の断熱性能の見方）を見てください

## 2. 最初に区分を決める

**資料を読む前に**、この動画の材料に社外秘（所属先の外に出せない情報）が含まれるかを人に聞き、台本の `confidentiality` に書きます。

| 区分 | 意味 |
|---|---|
| `general` | 公開済みの情報・一般的な知識だけ |
| `confidential` | 社外秘を含む・**分からない**（書いていなければこちら） |

守ること:

- 区分が決まるまで、資料を読まない・開かない・どこにも送らない
- `confidential` のとき、**あなたがクラウドで動いているなら、資料を受け取らずに止まります**。手元で動く AI（LM Studio・Ollama など）で進めるよう人に伝えてください（[confidentiality.md](docs/guide/confidentiality.md)）
- 区分を `confidential` から `general` に変えるのは**人だけ**です。あなたは下げません（`general` から `confidential` に上げるのはかまいません）
- どの AI を使ってよいかは、所属先のルールに従います。キットは、対話に使う AI までは止められません

## 3. 進め方

| 段 | 手順書 | 人に確かめること |
|---|---|---|
| 0 準備 | [00-setup](docs/guide/00-setup.md) | `erkit doctor` の結果（足りないものは人が入れる） |
| 1 聞き取り | [01-intake](docs/guide/01-intake.md) | 区分、何を説明するか、資料、見る人 |
| 2 見る人 | [02-audience](docs/guide/02-audience.md) | A・B・C のどれか |
| 3 構成 | [03-outline](docs/guide/03-outline.md) | シーンの一覧（見出し・画像の種類）。**台本を書く前に見せる** |
| 4 台本 | [04-storyboard](docs/guide/04-storyboard.md) | ナレーションの言い回し、数値の根拠 |
| 5 説明図・撮影 | [05-visuals](docs/guide/05-visuals.md) | 確認画像（枠や矢印が指したいものに重なっているか） |
| 6 確認 | [06-review](docs/guide/06-review.md) | 試作の .pptx、読みの確認 |
| 7 書き出し | [07-export](docs/guide/07-export.md) | できた MP4 |

各段の終わりで人に見せ、よいと言われてから次へ進みます。

## 4. 守ること

- 台本は仕様（[docs/design/storyboard.md](docs/design/storyboard.md)）に合わせ、**`erkit check` が通るまで直します**
- **画面を捏造しない**: 実際に撮った画面は `実キャプチャ`、説明図は `説明用再構成図`（`image.label`）。説明図で実際の画面のふりをしない
- 赤枠・矢印の位置は**座標を書かず**、mark の名前で指します（説明図は `data-mark`、撮影は操作定義の `marks`）
- 数値・事実には根拠を付けます（台本のコメントか、別のファイル）。分からないことは人に聞き、作らない
- MP4・WAV・.pptx・撮影画像・説明図の PNG を commit しません。秘密情報（パスワード・トークン・個人の情報）を書きません
- キットの本体（`src/`）は変えません。直したい所があれば人に伝えます

## 5. コマンド

キットのフォルダで、仮想環境を有効にしてから使います（Windows なら `.\erkit.ps1` でも同じ）。

| コマンド | すること |
|---|---|
| `erkit doctor` | 要るものがそろっているか |
| `erkit check samples/u-value/u-value.storyboard.md` | 台本の検証と区分の表示（`--strict` で警告も不合格） |
| `erkit diagram samples/u-value/u-value.storyboard.md --out output/u-value --overlay output/u-value/check-diagram.png` | 説明図の HTML を PNG と注釈位置に |
| `erkit capture samples/u-value/u-value.storyboard.md --check` | 操作定義と台本の突き合わせだけ（ブラウザ不要） |
| `erkit capture samples/u-value/u-value.storyboard.md --serve samples/u-value/app --out output/u-value --overlay output/u-value/check-capture.png` | Web 画面の撮影 |
| `erkit voice kana samples/u-value/u-value.storyboard.md` | ナレーションの読みの確認（AivisSpeech が要る） |
| `erkit make samples/u-value/u-value.storyboard.md --serve samples/u-value/app --dry-run` | 通し生成の段の順番を表示するだけ |
| `erkit make samples/u-value/u-value.storyboard.md --serve samples/u-value/app` | 台本から MP4 まで |

終了コード（どのコマンドも同じ考え方）:

| コード | 意味 | あなたがすること |
|---|---|---|
| 0 | できた・合格 | 次の段へ |
| 1 | 不合格・足りないものがある・失敗した段がある・社外秘の確かめで止めた | 表示を読んで直す。足りないソフトは人に入れてもらう |
| 2 | 引数・台本・設定の誤りで始められない | コマンドか台本を直す |

`erkit make` が途中で止まったら、表示される「直したら、そこから」のコマンド（`--from`）で続きから作れます。
