# 5. 説明図と撮影

台本の各シーンの画像を用意します。どの場合も、赤枠・矢印の位置は**座標を書かず**、部品の名前（mark）で指します。

| 画像 | すること | 仕様 |
|---|---|---|
| 説明図（`generated` ＋ `tool: html`） | HTML を書き、`erkit diagram` で PNG と注釈位置にする | [diagram.md](../design/diagram.md) |
| Web 画面（`web`） | 操作定義を書くか記録し、`erkit capture` で撮る | [capture-web.md](../design/capture-web.md) |
| 人が用意する画像（`manual`） | ファイルを `image.ref` の場所に置く | [storyboard.md](../design/storyboard.md) |
| コード描画の場面（映像の作り方が `interactive` のときだけ。任意） | 場面の指定 `scenes.yaml` を書き、`erkit make` の `--dry-run` と sheet で確かめる | [interactive.md](../design/interactive.md) |

映像の作り方は 2 つです（台本の `reel.render_mode`、または `erkit make` の `--render-mode`。[07-export.md](07-export.md)）。

- **slides**（既定）: スライド（.pptx）を PowerPoint で MP4 に書き出す。この手順書の「説明図」「Web 画面の撮影」だけで足ります
- **interactive**: PowerPoint を使わず、キットが 1 フレームずつ描いて MP4 にする（字幕の焼き込みと SRT つき）。説明図と撮影画像はそのまま使え、読み上げに合わせて動かしたい場面だけ「コード描画の場面」（下の節）を書きます

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

## コード描画の場面（interactive のときだけ）

interactive では、場面ごとに**場面の指定**（`scenes.yaml`）を書くと、カード・表・手順などの部品が、ナレーションの読み上げに合わせて現れ、読んでいる所を示します。
**書かなくても MP4 まで作れます**（書かない場面は既定の場面: slides と同じく、見出し・説明図や撮影画像・**来歴ラベル**（`実キャプチャ`・`説明用再構成図`。必ず出る）・**台本の赤枠と矢印**（marks.json の位置に、slides と同じ段落で）を字幕の上に出す。台本の画面テキスト（`on_screen_text`）は、字幕の帯と重なるため interactive では出しません。画像の無い intro・outro は見出しと文のカード）。
手本は [samples/u-value/scenes/u-value/scenes.yaml](../../samples/u-value/scenes/u-value/scenes.yaml)（説明図の s01・s02 を部品で描き、撮影の s03〜s05 と intro は既定の場面）。

### 置き場

台本のフォルダの `scenes\<reel id>\scenes.yaml`（サンプルなら `samples\u-value\scenes\u-value\scenes.yaml`）。

- キットは**台本のフォルダの `scenes\` の下だけ**を読みます。台本と同じく `reels\` の下に置けば、公開のリポジトリには入りません
- サンプルを写して自分の題材にしたときは、`scenes\u-value` のフォルダ名も新しい reel id に変えます（例 `Rename-Item reels\glass-choice\scenes\u-value glass-choice`）。名前が合わないと、すべて既定の場面になります
- 静止画を部品で出すときは `scenes\<reel id>\assets\` か `scenes\assets\` に置きます（台本のフォルダと出力フォルダの中のファイルだけを読む。URL は読まない）

### 書き方

```yaml
version: 1
scenes:
  s01:                                # 場面 id（台本の intro・シーンの id・outro）
    parts:                            # 上から順に描く（後の部品が上に重なる）
      - type: header
        title: 熱の逃げ方を知る
        label: 説明用再構成図          # 説明図の中身を描く場面は、実際の画面のふりをしない
      - type: cards
        box: [96, 250, 1728, 300]     # 置く範囲 [x, y, 幅, 高さ]（1920×1080）。無ければ上から積む
        columns: 3
        items:
          - {title: 伝導, body: ガラスや枠そのものを、熱が伝わる, at: 伝導}
          - {title: 対流, body: 冷やされた空気が下に流れて熱を運ぶ, at: 対流}
          - {title: 放射, body: 部屋から冷たいガラスへ、熱が飛ぶ, at: 放射}
```

- 画面は 1920×1080。**字幕の帯（y 940 より下）には描きません**（字幕はキットが描く）
- 文字・数値は台本（画面の文字・ナレーション）と根拠のファイルにあるものだけ。説明図と同じく、数値には根拠を付けます
- 場面の指定は Python を書かない書き方です。形の正本は [scenes.schema.json](../../src/explainer_reel_kit/data/schema/scenes.schema.json)、項目と動きの詳しい表は [interactive.md](../design/interactive.md)

### きっかけ（いつ現れるか）

部品にも、項目（カードの 1 枚・表のセルなど）にも書けます。**秒は書きません**（ナレーションを直すと秒が変わるため）。

| 書き方 | 現れる時刻 |
|---|---|
| 何も書かない | 場面の始まり |
| `sentence: 3` | その場面のナレーションの 3 番目の文の始まり（段落をまたいで上から 1, 2, 3 …） |
| `at: 露点は` | その場面のナレーションで、この語句が読まれ始める時刻。2 つ以上の文にある語句は `sentence` と一緒に書いて文を決める |
| `delay: 0.5` | 上の時刻から秒をずらす（負でもよい） |
| `until: {sentence: 5}` | 部品: ここで消す。項目: ここで示すのをやめる |

### 部品（11 種）

| 型 | 描くもの | 動きの既定 |
|---|---|---|
| `header` | 画面の上の見出し（右上に進行表示と札 `label`） | `fade-in` |
| `heading` | 場面の中の見出し 1 行 | `fade-in` |
| `title` | 中央の題（大きさの違う行を縦に） | `fade-in` |
| `cards` | カードを読み上げ順に点灯（横・縦・格子、間の矢印） | `stagger`・強調 `roomhighlight` |
| `steps` | 番号付きの手順（印 number・check・cross など） | `stagger`・強調 `roomhighlight` |
| `table` | 表の行・列の強調。**行・列は見出しの文字で指す**（番号では指さない） | `stagger`・強調 `roomhighlight` |
| `number` | 数値の強調（大きな数字・単位・割合の帯） | `counter` |
| `image` | 画像と注釈（枠・丸・注目点・引き出し線）。来歴ラベルは画像ごとに必ず出る（台本の画像は台本の `image.label`。`scenes\assets\` に置いた静止画は `label:` で書き、書かなければ `説明用再構成図`） | `clipreveal`・強調 `roomhighlight` |
| `compare` | 左右の比較 | `slidein`・強調 `roomhighlight` |
| `callout` | 要点の囲み・帯。同じ場所で文を入れ替える | `stagger`・入れ替え `fadethrough` |
| `flow` | 札を矢印でつなぐ流れ | `stagger`・強調 `roomhighlight` |

- 動きは `motion`（現れ方）・`emphasis`（読んでいる所の示し方）・`switch`（入れ替え方）に名前で書き、`speed: 2` で長さを半分にします。名前と長さの一覧は [interactive.md](../design/interactive.md)
- 部品の見本の静止画（ダミーの中身）: `python -m explainer_reel_kit.interactive gallery --out "$env:TEMP\erkit-gallery"`

### 確かめる（全編を描く前に）

1. **書き方の確かめ**（何も作らない。ナレーションの合成もしない）。知らない型・項目、ナレーションに無い語句、枠からはみ出す文字は、ここで終了コード 2 で止まり、`scenes.yaml scenes.s02.parts[1]（cards）.items[0]: …` の形で場所が出ます

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --render-mode interactive --dry-run
```

2. **静止画で見る**（sheet）。一度 interactive で MP4 まで作った出力フォルダ（[07-export.md](07-export.md)）の中間データを使い、場面の指定の場面ごとに、きっかけの直前・直後・動きの終わりの 3 枚を並べた一覧画像を作ります

```powershell
$o = (Get-ChildItem "$env:USERPROFILE\ExplainerReelKit\output" -Directory -Filter "*_u-value*" | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
python -m explainer_reel_kit.interactive sheet --project $o --timeline "$o\work\render-timeline.json" --pauses "$o\work\pauses.json" --scenes samples\u-value\scenes\u-value --cues
Invoke-Item "$o\checks\sheets"
```

文字のはみ出し・強調の位置・読み上げとのずれを見ます。決まった秒の絵を見るときは `--cues` の代わりに秒を並べます（`--name s02 20 25 30`。2×2 の一覧）。
直したら、ナレーションを作り直さずに描き直せます（[07-export.md](07-export.md) の `--from export`）。

### Python の場面コード（部品で足りないときの逃げ道）

部品で描けない独自の図だけ、`scenes\<reel id>\<場面 id>.py` に `def scene(f, t, T)` を書きます。同じ場面に両方あれば Python が先です。

- 秒を直書きせず、`T.S('s02-3')`（文の始まり）・`T.at('s02-6', '露点は')`（語句の時刻）で指します
- キットは台本のフォルダの `scenes\` の下のコードだけを読み込んで実行します。**人から受け取ったコードを置かない**でください
- 例: [tests/fixtures/interactive/window-condensation-python/](../../tests/fixtures/interactive/window-condensation-python/)（同じ絵を scenes.yaml で書いた例が [window-condensation/](../../tests/fixtures/interactive/window-condensation/)）。道具の一覧は [interactive.md](../design/interactive.md)

## AI に任せること

- 説明図の HTML を書く（[prompts/04-diagram-html.md](../../prompts/04-diagram-html.md)）。`erkit diagram` が失敗したら理由を読んで直す
- 種別が `explainer` なら、上の表で部品を選び、見本を写して書き換える（新しい形を一から描かない）
- 操作定義を書く・直す（記録したものに `wait_for` を足すなど）。セレクタは `data-testid` を優先する
- 確認画像は人に見せて、枠の位置がよいか確かめてもらう
- interactive なら、場面の指定（`scenes.yaml`）を書き、`--dry-run` で書き方の誤りが無くなるまで直す。まず部品で書き、Python の場面コードは部品で描けないときだけ。sheet の一覧画像は人に見せて確かめてもらう

## 次へ

[06-review.md](06-review.md) で試作して確かめます。
