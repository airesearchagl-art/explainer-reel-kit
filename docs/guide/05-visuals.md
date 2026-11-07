# 5. 説明図と撮影

台本の各シーンの画像を用意します。どの場合も、赤枠・矢印の位置は**座標を書かず**、部品の名前（mark）で指します。

| 画像 | すること | 仕様 |
|---|---|---|
| 説明図（`generated` ＋ `tool: html`） | HTML を書き、`erkit diagram` で PNG と注釈位置にする | [diagram.md](../design/diagram.md) |
| Web 画面（`web`） | 操作定義を書くか記録し、`erkit capture` で撮る | [capture-web.md](../design/capture-web.md) |
| 人が用意する画像（`manual`） | ファイルを `image.ref` の場所に置く | [storyboard.md](../design/storyboard.md) |

## 説明図（HTML）

1 シーン 1 ファイル。サンプルの [diagrams/s01_heat_paths.html](../../samples/u-value/diagrams/s01_heat_paths.html) が手本です。

- 共通の CSS を読みます: `<link rel="stylesheet" href="../../_shared/diagram.css">`（HTML のファイルからの相対パス。`reels\<id>\diagrams\` に置き、`reels\_shared` に CSS を写してある場合。[04-storyboard.md](04-storyboard.md)）
- 大きさは **2420×1000 px**（CSS が決めています）。文字は 32px 未満にしません
- 指したい要素に `data-mark="名前"` を付けます（英小文字・数字・`_`、1 つの図で同じ名前は 1 回）。台本の `recipe_params.mark` と同じ名前にします
- **外の URL を読みません**（Web フォント・CDN・外の画像・`fetch`）。ネットワークを止めて描くので、読もうとするとそのシーンは失敗します。だから社外秘の台本でも使えます
- 色は意味で使います（青＝操作・入力、緑＝結果、黄＝注意、灰＝その他）。赤は注釈とぶつかるので使いません
- `image.label` は必ず `説明用再構成図`

人が打つコマンド:

```powershell
erkit diagram samples\u-value\u-value.storyboard.md --out output\u-value --overlay output\u-value\check-diagram.png
if ($LASTEXITCODE -eq 0) { Invoke-Item output\u-value\check-diagram.png }
```

確認画像で、赤枠が指したい部品に重なっているかを見ます。失敗したシーンは `output\u-value\diagram-result.json` に理由が出ます。
Chromium を入れていなければ、`erkit diagram samples\u-value\u-value.storyboard.md --out output\u-value --channel msedge` のように `--channel msedge` を付けます。

### 解説の部品の選び方（kind: explainer）

解説の説明図は、共通の CSS の**部品 7 種**で描きます。見本（[samples/_parts/](../../samples/_parts/README.md)）を写して、文字と数値を書き換えます。クラスと決まりの正本は [diagram.md の「解説の部品」](../design/diagram.md#解説の部品kind-explainer)。

| 話したいこと | 部品 | 見本 | 赤枠を付ける単位（見本の data-mark） | 気をつけること |
|---|---|---|---|---|
| 身近なものにたとえて問いを出す | たとえ | [analogy.html](../../samples/_parts/analogy.html) | 身近なもの・本題・対応表（`everyday` `topic` `mapping`） | たとえは本題と同じしくみのものを選ぶ |
| 層の重なりで、どこが効くかを見せる | 断面図 | [section.html](../../samples/_parts/section.html) | 層（`layer_…`） | 模式で実寸ではないと図に書く |
| 原因から結果までの順番 | フロー | [flow.html](../../samples/_parts/flow.html) | 段（`step_1`〜`step_4`） | 1 段に 1 文。3〜4 段 |
| 2〜4 種類を観点で比べる | 比較表 | [compare.html](../../samples/_parts/compare.html) | 行（`row_…`） | おすすめの行は `class="best"`。評価の根拠は SOURCES.md に |
| 数値の目安を範囲で見せる | 数値の範囲 | [range.html](../../samples/_parts/range.html) | 帯・目安の線（`band_…` `target`） | 出典のある値だけ。帯の位置は目盛りから計算する（値 ÷ 目盛りの最大 × 100 %） |
| 条件で答えが分かれる | 条件の分岐 | [branch.html](../../samples/_parts/branch.html) | 問い・答え（`question` `leaf_…`） | 問い 1 つから 2〜3 本 |
| 並べて見せる（減らし方・まとめ・条件） | カード | [cards.html](../../samples/_parts/cards.html) | カード（`card_1`〜） | 2〜4 枚。すぐできる順に |

- 写す: `Copy-Item samples\_parts\cards.html reels\cold-draft\diagrams\s06_cards.html`（`reels\_shared` を写してあること。[04-storyboard.md](04-storyboard.md)）
- 写したら、CSS の参照を `href="../_shared/diagram.css"` から `href="../../_shared/diagram.css"` に直す（ファイルの場所が 1 段深くなるため）
- 色は意味で 4 色まで（`.c-blue` 断熱・冷たい、`.c-amber` 日射・暖かい・注意、`.c-teal` 結果・おすすめ、`.c-gray` その他）。1 本の動画の中で同じ意味には同じ色
- 見本の値・評価は説明のための例です。必ず確かめた値に書き換えるか、値を消します
- 全部品を 1 枚で見比べる: `erkit diagram samples/_parts/parts.storyboard.md --out output/parts --overlay output/parts/parts-overview.png`

## Web 画面の撮影

台本の `capture.steps` は人が読む手順です。機械が実行する操作と、指したい部品（marks）は**操作定義**（`<id>.actions.yaml`）に書きます。手本は [samples/u-value/u-value.actions.yaml](../../samples/u-value/u-value.actions.yaml)。

### 操作定義を作る方法

| 方法 | 向いているとき |
|---|---|
| AI に書かせる（ページの HTML を見せて、セレクタを書かせる） | 自分で作ったページで、`data-testid` が付いているとき |
| 記録モード（人がクリックして作る。AI に送らない） | 他の人が作ったページ・社外秘の画面・セレクタが難しいとき |

記録モード（人が打つコマンド。ブラウザが開きます）:

```powershell
erkit record --url http://127.0.0.1:8000/index.html --serve samples\u-value\app --reel u-value --out output\u-value-recorded.actions.yaml
```

F8 でシーンを区切る、Shift＋クリックで mark にする（名前を入れる）、F10 で終わる。既にあるファイルは上書きしません。

### 撮る（人が打つコマンド）

```powershell
erkit capture samples\u-value\u-value.storyboard.md --check
erkit capture samples\u-value\u-value.storyboard.md --serve samples\u-value\app --out output\u-value --overlay output\u-value\check-capture.png
if ($LASTEXITCODE -eq 0) { Invoke-Item output\u-value\check-capture.png }
```

- `--check` はブラウザを開かず、台本と操作定義が合っているかだけを確かめます
- `--serve <フォルダ>` は、そのフォルダをこの PC だけで配信して撮ります（台本の `http://127.0.0.1:8000/…` が置き換わる）。ネットワークなしで動きます
- **社外秘の台本は、この PC の中の URL しか撮りません**（外の URL があれば、ブラウザを開く前に止まります）
- 撮った画像に個人の情報（ブラウザのプロフィール名・通知など）が映っていないかも確かめます

## AI に任せること

- 説明図の HTML を書く（[prompts/04-diagram-html.md](../../prompts/04-diagram-html.md)）。`erkit diagram` が失敗したら理由を読んで直す
- 種別が `explainer` なら、上の表で部品を選び、見本を写して書き換える（新しい形を一から描かない）
- 操作定義を書く・直す（記録したものに `wait_for` を足すなど）。セレクタは `data-testid` を優先する
- 確認画像は人に見せて、枠の位置がよいか確かめてもらう

## 次へ

[06-review.md](06-review.md) で試作して確かめます。
