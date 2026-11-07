# 説明図の書き方（erkit diagram）

説明図は **HTML で描きます**。`erkit diagram <台本>` が、ネットワークを止めたブラウザ（Playwright）で HTML を開いて PNG にし、
赤枠・矢印で指したい部品の位置を `<画像名>.marks.json` に書きます。台本には座標を書かず、部品の**名前**で指します。

```text
diagrams/s01.html（data-mark="名前" を付ける）
        ↓  erkit diagram <台本>
assets/s01.png（2420×1000） ＋ assets/s01.marks.json（explainer-reel/marks@1、source: generated）
        ↓  台本の recipe_params: {mark: 名前}
スライドで赤枠（highlight_box）・矢印（arrow_move）がその部品に出る
```

## 台本の書き方

```yaml
## s01: 台本を書く
image:
  source: generated
  ref: assets/s01_storyboard.png     # 書き出す先（台本ファイルからの相対）
  label: 説明用再構成図              # 説明図は必ずこれ（画面を捏造しない）
recipe: highlight_box
recipe_params:
  mark: scene_block                  # HTML の data-mark="scene_block"
capture:
  tool: html
  src: diagrams/s01_storyboard.html  # 1 シーン 1 ファイル
  prompt: 台本の構成（冒頭・シーン・まとめ）を示す説明図
```

- 対象は `image.source: generated` かつ `capture.tool: html` のシーンだけ。`prompt` だけのシーン（人が描く図など）は描きません
- `image.label` が `説明用再構成図` でなければ、描く前に止めます
- 矢印は `recipe_params: {to: {mark: 名前}, from_side: left}`。複数の枠は `mark: [名前, 名前]`（ナレーションの段落ごとに切り替わる）

## HTML の書き方

```html
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="../../samples/_shared/diagram.css">  <!-- 共通の CSS（相対パス） -->
</head>
<body>
<div class="wrap">
  <div class="row">
    <div class="card" data-mark="input_card">
      <div class="tag blue">入力</div>
      <div class="t">条件を入れる</div>
      <div class="s">幅・高さ・用途</div>
    </div>
    <div class="arrow">→</div>
    <div class="card" data-mark="result_card">
      <div class="tag teal">結果</div>
      <div class="t">数値を比べる</div>
      <div class="s">3 つの案を並べる</div>
    </div>
  </div>
  <div class="card center"><div class="s">一言でまとめる（<span class="strong">強調</span>）</div></div>
</div>
</body>
</html>
```

| 決まり | 理由 |
|---|---|
| 図の大きさは **2420×1000 px**（共通の CSS が `html, body` に指定） | スライドの画像枠（12.333in × 5.1in ≒ 2.42:1）に合わせる。はみ出した部分は写らない（結果に注記が出る） |
| `data-mark="名前"` は英小文字・数字・`_`、**1 つの図で同じ名前は 1 回** | 台本の `mark:` と突き合わせる。重複・書き間違いはそのシーンを失敗にする |
| 指す要素は見えていて、8px 以上 | 非表示・小さすぎる・図の外（面積の 95% 未満しか中にない）は失敗。既定の位置で出さない |
| **外の URL を読まない**（Web フォント・CDN・外の画像・`fetch`） | ネットワークを止めて描く。読もうとしたらそのシーンを失敗にし、画像も書かない。だから社外秘の台本でも使える |
| 画像を使うなら、台本のフォルダの中のファイルを相対パスで | `file://` と `data:` だけ読める |
| JavaScript は使ってよい（読み込みの後、フォントを待ってから撮る） | 図を組み立てる程度に。アニメーションは止めて撮る |

## 共通の CSS（`samples/_shared/diagram.css`）

元の試作（紹介動画の説明図を Python の文字列で描いていたもの）で読みやすかった大きさと並べ方を、クラスにしたものです。

| クラス | 使いどころ | 大きさの目安 |
|---|---|---|
| `.wrap` | 全体の枠。上下 50px・左右 70px の余白の中で縦に並べ、中央に寄せる（間 34px） | — |
| `.row`（`.row.tight`） | カードを横に並べる（間 36px、tight は 18px）。幅は `style="flex:1.2"` の比で分ける | — |
| `.card`（`.center` `.accent` `.warn`） | 白いカード（角丸 22px・枠 3px）。1 枚に「タグ → 見出し → 本文」まで | 中は 3〜5 行 |
| `.t`（`.t.sm`） | カードの見出し | 62px（sm 50px） |
| `.s`（`.s.sm`） | 本文 | 46px（sm 36px） |
| `.tag.blue` / `.teal` / `.amber` / `.gray` | カードの種類のラベル（入力・結果・注意・その他） | 36px |
| `.arrow` | カードの間の流れ（文字の →） | 80px（tight の中は 48px） |
| `.code`（`.hl`） | コード・ファイルの並び（`.hl` は強調の背景） | 42px |
| `.term` | 端末の画面の**説明図**（実際の画面の撮影ではない） | — |

- 動画では横 1920px 前後に縮むので、**文字は 32px 未満にしない**
- カードは横に 2〜4 枚、縦に 2 段まで。6 段の流れは `.row.tight` に小さめのカード（見出し 44px・本文 32px）を並べる
- 色は意味で使う（青＝操作・入力、緑＝結果・安全、黄＝注意・止める、灰＝その他）。赤は注釈（赤枠）とぶつかるので使わない
- 指したいもの（赤枠の対象）は、カード 1 枚か、`.hl` を付けた 1 かたまりにする（文字 1 つを指すと枠が小さすぎる）

## 共通の CSS の参照の仕方

共通の CSS の正本は **`samples/_shared/diagram.css`** の 1 つです（パッケージには入れません。キットのフォルダで使います）。
説明図の HTML から、**その HTML のある場所からの相対パス**で読みます（`erkit diagram` は `file://` を読めます）。

| HTML の置き場所 | `<link rel="stylesheet" href="…">` |
|---|---|
| `samples/<題材>/diagrams/` | `../../_shared/diagram.css` |
| `samples/_parts/`（部品の見本） | `../_shared/diagram.css` |
| `reels/<台本の id>/diagrams/`（`erkit draft` の出力の隣） | `../../../samples/_shared/diagram.css` |
| `examples/` の下 | `../../samples/_shared/diagram.css` |

- キットの外に台本を置くときは、`diagram.css` を台本のフォルダに写して `diagrams/` から `../diagram.css` で読む（写した CSS はキットを更新しても変わらない）
- 図だけの調整は、HTML の `<style>` に書く（共通の CSS は変えない）

## 解説の部品（kind: explainer）

一般の解説（[台本の kind: explainer](storyboard.md)）でよく使う図を、共通の CSS の部品にしました。
見本の HTML は [`samples/_parts/`](../../samples/_parts/README.md) に 1 部品 1 ファイルで置いてあり、**写して文字と数値を書き換えれば**使えます。
解説のひな形（`src/explainer_reel_kit/data/templates/explainer.storyboard.md`）の各シーンは、どの部品を使うかと、見本の mark の名前を書いてあります。

| 部品 | 見本 | 外側のクラス | 中の要素 | 見本の data-mark | 使うシーン |
|---|---|---|---|---|---|
| 断面図（層の重なり） | `section.html` | `.section` | `.side.in` / `.side.out`（室内・室外）、`.layer`（層。幅は `style="flex:…"`、`.thin` は薄い層）、`.section-caption` | `layer_glass_in` `layer_air` `layer_coat` | しくみ |
| 比較表 | `compare.html` | `table.compare` | `thead th`（観点）、`tbody th`（比べるもの）、`tr.best` / `td.best`（おすすめ）、`.good` / `.weak` | `row_single` `row_double` `row_coated`（行に付ける） | 比べる |
| 数値の範囲（帯と目安） | `range.html` | `.range` | `.lane`（1 行）＞ `.lane-label` と `.track` ＞ `.band`（`style="left:…%;width:…%"`、狭い帯は `.narrow` と `<em>`）、`.axis` ＞ `.tick`・`.unit`・`.target`（目安の線） | `band_single` `band_double` `band_coated` `target` | 条件 |
| フロー（矢印の流れ） | `flow.html` | `.flow` | `.step`（`.num`・`b`・`span`）、`.to`（矢印） | `step_1`〜`step_4` | しくみ |
| カード（2〜4 枚） | `cards.html` | `.cards` | `.card` に `.badge`（番号）、`.tag`・`.t.sm`・`.s.sm` | `card_1`〜`card_3` | 減らし方・まとめ |
| 条件の分岐 | `branch.html` | `.branch` | `.q`（問い）、`.stem`、`.paths` ＞ `.path` ＞ `.cond`（条件）と `.leaf`（答え） | `question` `leaf_cold` `leaf_sun` `leaf_both` | 選び方 |
| たとえ（身近なもの） | `analogy.html` | `.analogy` と `.map` | `.side`（身近なもの・本題）、`.eq`（≒）、`.map` の `.l`・`.mid`・`.r`（対応） | `everyday` `topic` `mapping` | 問い |

決まり:

- **色は意味で 4 色まで**: `.c-blue`（断熱・冷たい・入力）、`.c-amber`（遮熱・日射・暖かい・注意）、`.c-teal`（結果・おすすめ・安全）、`.c-gray`（その他・比べる相手）。
  1 本の動画の中で同じ意味には同じ色を使う。赤は注釈の赤枠とぶつかるので使わない
- 文字は 32px 未満にしない（部品の既定は 34〜58px）。図の題は `.part-title`（54px）、注記は `.part-note`（36px）
- 数値の範囲の帯の位置は、目盛りに合わせて計算する（値 ÷ 目盛りの最大 × 100 %）。目で合わせない
- 図の中の数値は、出典のあるものだけ（[台本の出典の決まり](storyboard.md)）。見本の値は説明のための例で、出典のある値ではない
- 断面図は模式で、実寸ではないと図の中に書く（`.part-title` か `.section-caption`）
- 指したい部品（赤枠）は、層・行・帯・段・カード・答えの単位で `data-mark` を付ける（8px 以上。線は `.target` のように幅のある箱で包む）

全部品の一覧（確認画像）を作るコマンドは [`samples/_parts/README.md`](../../samples/_parts/README.md) にあります。

## コマンド

```bash
erkit diagram examples/hello-kit.storyboard.md                       # 台本のフォルダに assets/… を書く
erkit diagram examples/hello-kit.storyboard.md --out OUT --overlay OUT/check.png
erkit diagram 台本 --only s02                                         # 一部だけ
```

| 結果 | 内容 |
|---|---|
| `<出力先>/<image.ref>` | 2420×1000 の PNG。描き直すたびに上書き（前回の画像と marks は先に消す） |
| `<画像名>.marks.json` | `explainer-reel/marks@1`、`source: generated`、`how: "data-mark: <div>"`（[注釈位置の仕様](marks.md)） |
| `<出力先>/diagram-result.json` | シーンごとの状態（ok / failed）・理由・注記、`network: blocked` |
| `--overlay` の PNG | 枠を描き込んだ確認画像（枠が指したい部品に重なっているかを目で確かめる） |

終了コード: 0 すべて描けた / 1 失敗したシーンがある / 2 台本・HTML の不備で始められない（ブラウザが起動できないときも 2）。
ブラウザは Playwright の Chromium（`python -m playwright install chromium`）か、`--channel msedge`（Windows の Edge）。

生成した PNG・marks.json・結果は commit しません（`.gitignore`）。
