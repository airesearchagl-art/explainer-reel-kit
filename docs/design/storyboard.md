# 台本の仕様（スキーマ kit-1.2.0）

台本はキットのすべての段（説明図・撮影・ナレーション・スライド・書き出し）が共有する**唯一の約束事**です。
スキーマの正本は [`src/explainer_reel_kit/data/schema/storyboard.schema.json`](../../src/explainer_reel_kit/data/schema/storyboard.schema.json)。
書き方は [テンプレート](../../src/explainer_reel_kit/data/templates/storyboard.md) を見てください。一般の解説は [解説のひな形](../../src/explainer_reel_kit/data/templates/explainer.storyboard.md)（下の「kind: explainer」）。

## 構成

台本の最上位は `reel` / `intro` / `scenes[]` / `outro` の 4 つです。

| 部分 | 中身 |
|---|---|
| `reel` | 動画全体の情報（id、題名、版、見る人、種別、区分、出力名、声） |
| `intro` | 冒頭のスライド（固定のレイアウト）。何ができるか・前提・所要時間とナレーション |
| `scenes[]` | 本編。**1 シーン＝1 スライド＝主画像 1 枚**。見出しは行動で終える（例: 条件を入力する）。5〜8 シーンを推奨 |
| `outro` | まとめのスライド（固定のレイアウト）。確認すること・次の行動とナレーション |

Markdown で書くときは、先頭の `---` で囲んだ部分が `reel`、`## intro`・`## <シーン id>: <見出し>`・`## outro` の各見出しの下の ```` ```yaml ```` ブロックが項目、その下の文章がナレーションです（段落は空行で区切る。段落内の改行は詰める。HTML コメントは無視。ただし段落の直後の `<!-- subtitle: … -->` は字幕の別表記になる。下の節）。

## reel の項目

| 項目 | 値 |
|---|---|
| `schema_version` | 新しく書く台本は `kit-1.2.0`。`1.0.0` / `1.1.0` / `kit-1.0.0` / `kit-1.1.0` の台本もそのまま読める |
| `audience` | 見る人。`A` 初めての人 / `B` よく使う人・詳しい人 / `C` 専門家・作る人 |
| `kind` | `tool_intro`（ツールの紹介）/ `work_manual`（作業の手順）/ `explainer`（一般の解説。`kit-1.1.0` から） |
| `confidentiality` | 社外秘の区分（下の節） |
| `render_mode` | 映像の作り方。`slides`（PowerPoint で書き出す。今までの経路）/ `interactive`（場面の指定で 1 フレームずつ描き、字幕を付ける。PowerPoint を使わない）。省略は `slides`。`erkit make --render-mode` が台本より優先。`kit-1.2.0` から |
| `aspect` | `"16:9"`（いまはこれだけ。引用符で囲む） |
| `output_name` | .pptx / .mp4 のファイル名（拡張子なし） |
| `voice` | 任意。`engine`（いまは `aivisspeech`）、`speaker`（声）、`speed`、`volume` |

## 社外秘の区分（confidentiality）

| 値 | 意味 |
|---|---|
| `confidential` | 社外秘（所属先の外に出せない情報）を含む・**分からない** |
| `general` | 公開済みの情報・一般的な知識だけ |

- **書いていなければ `confidential`** として扱います（安全側）。`1.0.0` の台本、`General` のような書き間違いも `confidential` です
- 区分を読むのは `explainer_reel_kit.storyboard.confidentiality()` だけです。ほかの段はこの関数で区分を読みます
- `confidential` のとき、キットは AI への送信・撮影の URL・音声合成エンジンを、この PC の中だけに限ります（各段で実装）
- `1.1.0` / `kit-1.0.0` / `kit-1.1.0` / `kit-1.2.0` で区分が未記入なら、検証は警告を出します（`--strict` のときは不合格）。`1.0.0` の台本には区分を書けません（書くなら版を上げる）

## 画像（image）と撮影の指示（capture）

| `image.source` | 意味 | `capture` に書くこと |
|---|---|---|
| `web` | Web 画面の撮影 | `url`、`steps`（人が読む手順）、任意で `viewport` |
| `manual` | 人が用意する画像（**ファイルが必要**） | `instructions` |
| `generated` | 説明図など、作った画像 | `prompt`（何を描く図か）。HTML で描くなら `tool: html` と `src`（HTML のファイル） |

- `image.ref` は台本ファイルからの相対パス（`/` 区切り）。`manual` は実在が必要、ほかは各段が書き出す予定のパス
- `image.label` は画像の来歴: `実キャプチャ` / `途中成果` / `説明用再構成図`。**画面を捏造しない**ための区別です。説明図は `説明用再構成図`
- `capture.src` と `capture.tool: html` は kit-1.0.0 で足した項目です。`1.0.0` / `1.1.0` の台本で使うとエラーになります（版を `kit-1.0.0` にする）
- 元の仕組みにあった SketchUp の撮影（`source: sketchup`）とカタログ動画（`kind: catalog`）は、キットでは使えません（理由を付けたエラー）

## 字幕の別表記（subtitles）と固定尺の枠（slot_sec）

どちらも `intro`・各シーン・`outro` に書けます（`kit-1.2.0` から。前の版の台本で使うと `[version]` のエラー）。

**字幕の別表記**: 読み上げる原稿と、画面の字幕に出す文を分けたいとき（読みのためにかなで書いた語を、字幕では漢字や英字で出すなど）。
Markdown では、直したい段落のすぐ後に `<!-- subtitle: 字幕に出す文 -->` と書きます（空行を挟んでもよい。複数行でもよい）。

```markdown
エーサン用紙に印刷します。
<!-- subtitle: A3 用紙に印刷します。 -->
```

JSON の台本では、その場所の `subtitles` に `[{"paragraph": 段落の番号（1 から）, "text": "字幕に出す文"}]` と書きます
（上の例は `"subtitles": [{"paragraph": 1, "text": "A3 用紙に印刷します。"}]`）。

- 音声合成には使いません（読み上げるのは原稿だけ）。字幕だけ直したときは、前の WAV をそのまま使い回せます
- 前に段落が無い・同じ段落に 2 つある・中身が空なら、Markdown の読み込みでエラー。yaml ブロックの `subtitles` と `<!-- subtitle: -->` の両方に書くのもエラー
- 段落の番号が原稿の段落の数を超える・同じ番号が 2 つあると `[subtitles]` のエラー
- 字幕の文の数が原稿の段落と同じなら文ごとに、違えば段落の時間を文字の重みで分けて出します

**固定尺の枠**: `slot_sec: 秒`（0 より大きく 600 以下）。その場面の表示秒（切替効果の時間は含まない）を決めます。
ナレーションが短ければ後ろが無音、長ければ文の前後・文の間の無音を詰め、それでも収まらなければ止まって超過の秒数と選択肢を出します（音声は伸び縮みさせない）。

## レシピ（recipe）

`fade_sequence` / `highlight_box` / `arrow_move` / `morph_transition` / `text_build`。
`recipe_params` の形式はスキーマでは拘束しません（スライドの段の仕様で決めます）。赤枠・矢印は座標を手で書かず、
撮影・説明図が測った部品の名前（mark）で指すのが基本です（例 `recipe_params: {mark: input_area}`）。

## kind: explainer（一般の解説）

建築一般などの**一般の解説**の台本です（社外秘は関わらない題材を想定）。画像はふつう全シーン説明図（`generated`、`説明用再構成図`、HTML で描く）。

| 決まり | 内容 |
|---|---|
| 版 | `schema_version: kit-1.1.0`（kit-1.0.0 より前の版で `explainer` を書くとエラー） |
| 構成 | 問い（身近な場面）→ しくみ → 比べる・条件 → 選び方・減らし方 → まとめ（確認すること）。この順で並べる |
| 長さ | 本編 5〜7 シーン（外れると警告）、2〜3 分 |
| 説明図 | [解説の部品](diagram.md#解説の部品kind-explainer)（断面図・比較表・数値の範囲・フロー・カード・条件の分岐・たとえ）を使う |
| 出典 | 数値・規格の番号・事実は確かめたものだけ。台本の隣の `SOURCES.md` に資料名・URL・確かめた日。確かめていないものは `<!-- 未確認: … -->` と書き、ナレーションでは言わない |

構成の決まりは検証では強制しません（シーン数の警告だけ）。順番と中身は人が確かめます。
ひな形は `src/explainer_reel_kit/data/templates/explainer.storyboard.md` で、シーンの並び・各シーンで話すこと・使う部品・出典の一覧の置き場を書いてあります。

## 検証（erkit check）

| 種別 | 内容 | 結果 |
|---|---|---|
| `[schema]` | スキーマ違反（必須の欠落・型・列挙・capture と source の不一致） | 不合格 |
| `[kit]` | キットで使えないもの（SketchUp・カタログ） | 不合格 |
| `[version]` | kit-1.0.0 の項目を 1.0.0 / 1.1.0 の台本で使っている、`kind: explainer` を kit-1.1.0 より前の版で使っている、`render_mode`・`subtitles`・`slot_sec` を kit-1.2.0 より前の版で使っている | 不合格 |
| `[subtitles]` | 字幕の別表記の段落の番号が原稿に無い・重複 | 不合格 |
| `[recipe]` | 存在しないレシピ名 | 不合格 |
| `[scenes]` | シーンが 0 件 | 不合格 |
| `[image]` | manual 画像の参照切れ | 不合格 |
| `[id]` | シーン ID の重複、予約名 `intro` / `outro` | 不合格 |
| 警告 | シーン数が 5〜8 の外（`explainer` は 5〜7）／見出しが動詞で終わらない／web に capture がない／区分が未記入 | `--strict` のときだけ不合格 |

合格・不合格の行の下に、種別（例 `種別: explainer（一般の解説）`）を出します（`--quiet` で合格なら出さない）。

終了コード: 0 合格 / 1 不合格・読めない / 2 引数の誤り。

## 版の決まり

- 列挙値の追加・任意の項目の追加はマイナー（`kit-1.1.0`）、必須の項目の追加・意味の変更はメジャー（`kit-2.0.0`）
- `kit-1.1.0`: `kind` に `explainer` を足した（列挙値の追加）。kit-1.0.0 の台本はそのまま通る
- `kit-1.2.0`: 任意の項目 `reel.render_mode`・`subtitles`・`slot_sec` を足した。kit-1.1.0 以前の台本はそのまま通る（新しい項目を使うときだけ版を上げる）
- 読める版を減らすときはメジャー
