# 4. 台本

構成の表を、台本（`.storyboard.md`）にします。台本は動画のすべての段が読む**唯一の約束事**です。
仕様は [docs/design/storyboard.md](../design/storyboard.md)、ひな形は [テンプレート](../../src/explainer_reel_kit/data/templates/storyboard.md)、書いた例は [samples/u-value/u-value.storyboard.md](../../samples/u-value/u-value.storyboard.md)。

## 自分の題材のフォルダを作る（人が打つコマンド）

サンプルを写して、名前を変えます（例: 題材の id を `glass-choice` にする）。

```powershell
New-Item -ItemType Directory reels -Force | Out-Null
if (-not (Test-Path reels\_shared)) { Copy-Item samples\_shared reels\_shared -Recurse }
Copy-Item samples\u-value reels\glass-choice -Recurse
Rename-Item reels\glass-choice\u-value.storyboard.md glass-choice.storyboard.md
Rename-Item reels\glass-choice\u-value.actions.yaml glass-choice.actions.yaml
```

- 説明図の共通の CSS（`samples\_shared`）も `reels\_shared` に写します。説明図の HTML（`reels\<id>\diagrams\…`）は CSS を `../../_shared/diagram.css` で読むので、サンプルと同じ書き方のまま使えます
- 台本の `id` と操作定義の `reel_id` を、新しい id（`glass-choice`）に書き換えます。操作定義のファイル名は `<id>.actions.yaml` です
- `reels\` は自分の作業のフォルダです。社外秘の台本を含むことがあるので、キットのリポジトリに commit しないでください

## 台本の形

```markdown
---
id: u-value
title: 窓の断熱性能（U 値）の見方
schema_version: kit-1.0.0
audience: A
kind: tool_intro
confidentiality: general
aspect: "16:9"
output_name: u_value
---

# 窓の断熱性能（U 値）の見方

## intro
（yaml ブロック: summary・prerequisites・duration_note）
ナレーション

## s01: 熱の逃げ方を知る
（yaml ブロック: where・image・recipe・recipe_params・capture）
ナレーション（段落ごとに空行）

## outro
（yaml ブロック: summary・checks・next）
ナレーション
```

| 書くところ | 決まり |
|---|---|
| 先頭の `---` の中（reel） | `id` は英小文字・数字・`-`・`_`。`confidentiality` は聞き取りで**人が決めた**値。`aspect` は必ず引用符で囲む |
| `## s01: 見出し` | シーン id（`s01`…）と、行動で終わる見出し。id は重複させない。`intro`・`outro` は使えない |
| yaml ブロック | 見出しのすぐ下に ```` ```yaml ```` で。`image.ref` は台本ファイルからの相対パス（`/` 区切り） |
| ナレーション | yaml ブロックの下の文章。**段落（空行で区切る）＝赤枠 1 つ**。`mark` を 3 つ並べたら段落も 3 つ |
| HTML コメント | `<!-- -->` の中は読まれない。数値の根拠や作り方のメモに使う |

## ナレーションの書き方

- 話し言葉で、1 文を短く（目安 40 字まで）。1 段落は 1〜3 文
- 画面に出す文字（`on_screen_text`）とナレーションは同じにしない。画面は要点、声は説明
- **読み間違いやすい語は、読みで書きます**: 英字（`U 値` → 「ユー値」、`Low-E` → 「ローイー」）、数字と単位（`1 m²` → 「一平方メートル」、`15℃` → 「十五度」）、記号
- 分野の用語の読みは、読み辞書でもそろえられます（[06-review.md](06-review.md)）
- 数値は根拠のあるものだけ。製品で変わる値は「目安」「およそ」と言い、範囲で示します

## 出典の決まり

**規格の番号・出典・数値は、そのセッションで確かめたものだけを書きます。記憶で書きません。**

- 確かめる＝渡された資料で見つけた、またはそのセッションで原典（規格・公的な資料・メーカーの資料）を開いて読んだ
- 確かめていないものは、台本の HTML コメントに「未確認」と書き（例 `<!-- 未確認: 規格の番号 -->`）、最後の報告に挙げます。ナレーションでは番号を言わない・「〜の規格」のように一般的に言う、などで逃がします
- 確かめたものは、資料の名前と場所（頁・節・URL）をコメントか別のファイル（サンプルの `SOURCES.md` のように）に書きます
- AI が覚えている規格の番号・年版・数値は、正しく見えても「未確認」です

## 検証する（人が打つコマンド）

```powershell
erkit check samples\u-value\u-value.storyboard.md
erkit check --strict samples\u-value\u-value.storyboard.md
```

自分の台本なら `erkit check reels\glass-choice\glass-choice.storyboard.md` のようにパスを変えます。

| 表示 | 意味 |
|---|---|
| `OK …（区分: general、エラー 0、警告 0）` | 合格。区分が意図どおりかも見る |
| `NG …` と `[schema]` `[recipe]` `[id]` `[image]` など | 不合格。行の中身を読んで直す |
| `警告:` | 合格だが直した方がよい（シーン数・見出しの形・区分が未記入など）。`--strict` では不合格 |

**`erkit check` が通るまで直します**。エージェントは自分で実行して直し、チャットだけの AI には表示をそのまま貼って直してもらいます（[prompts/03-storyboard.md](../../prompts/03-storyboard.md) の最後）。

## AI に任せること

- 構成の表から台本を書く。区分は聞き取りで人が決めた値をそのまま書く（変えない）
- 出典の決まり（上）を守る。未確認の数値・事実は一覧にして人に渡す
- 説明図のシーンは `capture.tool: html` と `capture.src`（次の段で書く HTML）まで書く
- チャットだけの AI: [prompts/03-storyboard.md](../../prompts/03-storyboard.md) を貼る

## 次へ

[05-visuals.md](05-visuals.md) で説明図を描き、画面を撮ります。
