# コード描画（render_mode: interactive）

ナレーションの時刻に合わせて、場面の指定（`scenes.yaml`）か Python の場面コードで 1 フレームずつ描き、ffmpeg で MP4 にする映像の作り方です。
**PowerPoint を使わない**ので、PowerPoint の無い PC（Linux・PowerPoint の入っていない Windows）でも、キットのコマンドだけで MP4 まで作れます。
使い方の手順は [05-visuals.md](../guide/05-visuals.md)（場面の指定）と [07-export.md](../guide/07-export.md)（書き出し）。実装の説明は [src/explainer_reel_kit/interactive/README.md](../../src/explainer_reel_kit/interactive/README.md)。

## 映像の作り方の切り替え

| モード | 映像 | 字幕 | 指定 |
|---|---|---|---|
| `slides`（既定） | PowerPoint で .pptx を書き出す | なし | 何も書かない |
| `interactive` | 場面の指定・場面コードで描く | 焼き込み ＋ SRT | 台本の `reel.render_mode: interactive`（kit-1.2.0）か `erkit make --render-mode interactive` |

優先順位: `--render-mode` ＞ 台本の `reel.render_mode` ＞ `slides`。`run.json` の `render_mode` に、使ったモードと決めた所（`command` / `storyboard` / `default`）を残します。

## erkit make の段

| 段 | slides | interactive |
|---|---|---|
| `capture`・`diagram`・`assets` | 同じ | 同じ（説明図・撮影画像は既定の場面で使う） |
| `voice` | ナレーションの WAV と durations.json | 同じ（`--reuse-run`・`slot_sec` も同じ） |
| `deck` | .pptx（python-pptx） | 同じ。.pptx のスライドの時刻が場面の境界と音声の位置の正本 |
| `export` | PowerPoint で無音 MP4 | **コード描画**で無音 MP4・中間データ・SRT |
| `mux` | ナレーションを重ねる（音量そろえ・Morph の伸びの補正） | ナレーションを重ねる（音量そろえ。Morph の補正はしない） |
| `verify` | — | 出来上がった MP4 の検証（要確認でも止めない） |

- **合成の前の確かめ**: interactive で `export` を含む実行は、出力フォルダを作る前（ナレーションの合成の前）に、場面の指定を台本の原稿から仮に置いた時刻で組み立てて試し描きします。誤りは終了コード 2（`--dry-run` でも行う）。結果は `run.json` の `scenes_check`
- **前提の確かめ**: interactive は PowerPoint を確かめず、コード描画（Pillow・同梱の書体）と ffmpeg を確かめます
- `--from verify` は interactive だけ。`--from export` は描き直し（場面の指定を直したとき）
- 社外秘の台本でも、描画・書き出し・検証はこの PC の中だけ。ネットワークを使わず、静止画は台本のフォルダと出力フォルダの中のファイルだけを読みます（`run.json` の `network_checks` に「コード描画」の行）

## 場面の指定と場面コードの置き場

台本のフォルダの `scenes/<reel id>/`（無ければ、直下に `scenes.yaml` か `.py` がある `scenes/`）。どちらも無ければ、すべて既定の場面です。

- **キットは台本のフォルダの `scenes/` の下のコードだけを読み込んで実行します**（人から受け取ったコードを読み込む用途は想定しない）
- 優先順位: その場面の Python の場面コード（`<場面 id>.py`・`index.py`）＞ `scenes.yaml` ＞ 既定の場面
- **既定の場面**: 台本のシーンは slides と同じものを同じ順に出す。上から見出し（シーンの見出し）・画像（説明図の PNG・撮影画像。細い線は縮小の割合で太らせる）・画面テキスト（`on_screen_text`。`text_build` は 1 行ずつ）、画像の右下の外に**来歴ラベル**（`image.label` の `実キャプチャ`・`説明用再構成図` など）。来歴ラベルは**必ず出て、消す設定はありません**（撮影前の仮の枠は `撮影前（仮）`。文字だけのカード `recipe_params.card` は slides と同じく出さない）。字幕の帯（y 940 から）には重ねません
  - 配置（1920×1080。slides の 13.333×7.5 インチを 1 インチ ＝ 144 px で当てる。本家の interactive と同じ値）:

    | 出すもの | interactive | slides |
    |---|---|---|
    | 見出し | x 72、縦の中心 104、56px・太字。入らなければ 36px まで縮める（それでも入らなければ 2 行） | HEAD_BOX、28pt・太字 |
    | 画像 | 枠 (72, 180, 1776, 724) に縦横比を保って収める | IMAGE_BOX |
    | 区分の表示 | 右端 1848・上端 912、20px・控えめな色、右寄せ。撮影前は `撮影前（仮）` | LABEL_BOX、10pt |
    | 赤枠 | 線 9px（縁の中心）。フェード 0.4 秒 → 点滅 1 回 0.6 秒（前半は隠れる）。2 つ目からは前の枠を 0.3 秒で消してから | 4.5pt・同じ時間 |
    | 矢印 | 130 × 65px。出発点に 0.3 秒で現れ、到着点へ 1.2 秒で動く | 0.9 × 0.45in・同じ時間 |
    | 画面テキスト（on_screen_text） | **出さない**（slides の位置だと字幕の帯と重なるため）。注釈の出る時刻の計算には slides と同じく数える | TEXT_BOX |
  - **注釈は台本のとおり**: 赤枠・矢印の位置は slides と同じ `marks.json`（`recipe_params.mark`・`box`・`to`）、色は slides と同じ赤。出す時刻も slides と同じ決め方で、枠が複数でナレーションの段落の数と同じなら枠 k は段落 k の始まり（違えば均等に割る）、矢印は見出し・画像の後に現れて動く。`zoom` は slides と同じ範囲を切り出し、`zoom: per_mark` は段落の始まりで次の枠の範囲へ移る。効果がスライドの秒に収まらなければ slides と同じく同じ比率で縮める
  - 画像の無い場面（intro・outro）は見出しと文のカード。outro に画像があれば左に文、右に画像と来歴ラベル
- 静止画: 場面コードのフォルダの `assets/` と、その親の `assets/`
- 例: [samples/u-value/scenes/u-value/scenes.yaml](../../samples/u-value/scenes/u-value/scenes.yaml)

## scenes.yaml

形の正本は [scenes.schema.json](../../src/explainer_reel_kit/data/schema/scenes.schema.json)（`interactive/spec.py` の `json_schema()` から作る。部品を変えたら `python -m explainer_reel_kit.interactive schema`、同じか確かめるのは `schema --check`）。

```yaml
version: 1
scenes:
  s02:                                 # 場面 id（intro・シーンの id・outro）
    gap: 40                            # 任意。box の無い部品を上から積むときの間（px）
    parts:                             # 上から順に描く（後の部品が上に重なる）
      - type: header
        title: しくみをつかむ
      - type: cards
        box: [96, 250, 1728, 220]      # [x, y, 幅, 高さ]（1920×1080。字幕の帯 y 940 より上）
        items:
          - {title: ① 暖かい空気, body: 水蒸気を含む, sentence: 1}
          - {title: ② 窓で冷える, body: 空気が冷やされる, sentence: 3}
      - type: callout
        text: 室温 20℃・湿度 60％なら露点は約 12℃
        at: 露点は
```

### きっかけ

部品にも項目にも書けます。秒は書きません。

| 書き方 | 時刻 |
|---|---|
| 何も書かない | 場面の始まり（項目なら部品と一緒） |
| `sentence: 3` | その場面の 3 番目の文の始まり（文はその場面のナレーションを段落をまたいで上から数える。文の id は `<場面 id>-<番号>`） |
| `at: "露点は"` | その語句が読まれ始める時刻（文の中の文字の重みと、WAV の文中の無音から推定）。場面の 2 つ以上の文にある語句は `sentence` と一緒に |
| `delay: 0.5` | 上の時刻から何秒ずらすか（-5〜30） |
| `until: {sentence: 5}` | 部品: ここで消す。項目: ここで示すのをやめる |

項目の並び（cards・steps・table の rows・number・image・flow・compare の左右）:

- `show: each`（既定。項目は自分のきっかけで現れる）／ `show: all`（部品と一緒に現れ、項目のきっかけは示すだけ）
- 読んでいる間（自分のきっかけ → 次の項目のきっかけ・`until`・場面の終わり）は `emphasis` の動きで示す
- `dim`（読んでいない項目を沈める量。0 で沈めない）、`keep: true`（読み終えた項目を沈めない）、項目の `focus: false`（示さない）・`focus: {sentence: 4, until: {sentence: 5}}`

### 描く前に止まる誤り

知らない型・項目・動き、場面 id が台本に無い、語句がナレーションに無い・2 つの文にある、文が無い、表の知らない列、文字が枠に入らない（きっかけの直後・動きの終わり・場面の終わりで試し描きする）。
誤りは `scenes.yaml scenes.s02.parts[1]（cards）.items[0]: …` の形で場所を示します。

### 部品（11 種）

| 型 | 描くもの | 主な項目 | 動きの既定 |
|---|---|---|---|
| `header` | 画面の上の見出し（色の帯・題・罫線）、右上の進行表示と札、左下の注記 | `title`・`size`・`label`・`progress`・`foot` | `fade-in` |
| `heading` | 場面の中の見出し 1 行（番号の丸・続きの文・上の罫線） | `text`・`size`・`badge`・`sub`・`align`・`rule` | `fade-in` |
| `title` | 中央の題（大きさの違う行を縦に。行ごとにきっかけ） | `lines` | `fade-in` |
| `cards` | カードを読み上げ順に点灯（横・縦・格子、番号の丸・間の矢印・下の括弧） | `items`・`columns`・`numbered`・`arrows` | `stagger`・`emphasis: roomhighlight` |
| `steps` | 番号付きの手順（印 number・check・cross・dot・arrow、縦・横） | `items`・`marker`・`direction`・`boxed` | `stagger`・`roomhighlight` |
| `table` | 表の行・列の強調（**行・列は見出しの文字で指す**） | `columns`・`widths`・`rows`・`highlights`・`theme` | `stagger`・`roomhighlight` |
| `number` | 数値の強調（大きな数字・単位・説明、割合の帯） | `items`（`value`・`unit`・`caption`・`ratio`） | `counter` |
| `image` | 画像を並べる・重ねて切り替える、注釈（枠・丸・注目点・引き出し線）。画像ごとに来歴ラベルを右下の外に必ず出す（下の注） | `images`（`src`・`label` など）・`annotations` | `clipreveal`・`roomhighlight` |
| `compare` | 左右の比較（題・本文・要点・結論・画像） | `left`・`right` | `slidein`・`roomhighlight` |
| `callout` | 要点の囲み・帯・札・面、同じ場所で入れ替わる文、語句のマーカー | `text` か `texts`・`style`・`mark` | `stagger`・`switch: fadethrough` |
| `flow` | 札・箱・文字を横に並べて矢印でつなぐ | `items`・`arrows` | `stagger`・`roomhighlight` |

**画像の来歴ラベル（`image`・`compare` の画像）**: 画像ごとに右下の外へ必ず出し、消す項目はありません。

- 台本の画像（中間データの場面の画像と同じファイル。中身が同じなら `scenes/assets/` に写したものも）: 台本の `image.label`。部品の `label` に違う値を書くと書き方の誤り（終了コード 2）
- それ以外の静止画（`scenes/assets/` などに置いたもの）: 部品の `label`（`実キャプチャ`・`途中成果`・`説明用再構成図`）。書かなければ `説明用再構成図`。キットはその画像の来歴を確かめられないので、実際の画面と名乗らない方に倒します。実際に撮った画面なら `label: 実キャプチャ` と書きます
- Python の場面コード（`f.img`）で画像を出すときは、来歴を `f.text` で自分で書きます（キットは止めません）

どの型にも `box`・きっかけ（`at`・`sentence`・`delay`）・`until`・`speed` が書けます。
色の名前: `text`・`text2`・`text3`・`teal`・`teal_d`・`amber`・`blue`・`green`・`coral`・`ink`・`line`。
部品の見本の静止画（ダミーの中身）は `python -m explainer_reel_kit.interactive gallery --out フォルダ`（PNG はリポジトリに入れない）。

### 動き

`motion`（現れ方）・`emphasis`（読んでいる所の示し方）・`switch`（入れ替え方）に名前を書きます。名前はモーション見本帳の見本の id にそろえ、長さの既定は説明動画向けに短くしてあります（見本帳の値は `interactive/motion.py` の `Motion.book`）。`speed` で長さを割ります（0 より大きく 4 まで。`speed: 2` で半分）。

| 値 | 役割 | 既定の長さ（秒） |
|---|---|---|
| `fade`・`fade-in`・`stagger`・`stagger-T03`・`slidein`・`clipreveal`・`wipe` | 現れ方 | 0.4 |
| `cut` | 現れ方 | 0 |
| `typewriter` | 現れ方（1 文字ずつ） | 1 文字 0.01 |
| `roomhighlight`・`fill`・`underline`・`marker` | 強調 | 0.3 |
| `callout` | 強調（点 → 引き出し線 → 注記） | 0.55 |
| `hotspot` | 強調（くり返し） | 周期 1.1 |
| `counter` | 数値 | 0.8 |
| `fadethrough` | 入れ替え | 0.09 ＋ 0.21 |
| `beforeafter` | 比べ方（左右の画像） | 2.2 |

ぼかし・拡大縮小・3D は描かず、位置と濃さだけを使います。

## Python の場面コード（部品で足りないとき）

- `scenes/<reel id>/<場面 id>.py` に `def scene(f, t, T)`、または `index.py` に `SCENES = {'<場面 id>': 関数}`（任意で `subtitle(f, frame, T)`＝字幕の描き方、`AT_WEIGHTS`＝`T.at` の推定の重み）
- `f`: 表示リスト（`f.text`・`f.text_box`・`f.rr`・`f.focus`・`f.veil`・`f.circ`・`f.path`・`f.img`・`f.tag`・`f.badge`）。文字が入らなければ `LayoutError` で止まる
- `t`: 秒（フレームの先頭）。状態を持たないので、どの秒の静止画もすぐ出せる
- `T`: 時刻の問い合わせ。`T.S(文)`・`T.E(文)`・`T.at(文, 語)`・`T.by_id[場面]`。**秒を直書きしない**
- 道具: `from explainer_reel_kit.interactive.engine import *`、`from explainer_reel_kit.interactive.parts import Table, card_text`
- 字幕の帯（y 940 より下）には描かない
- 例: [tests/fixtures/interactive/window-condensation-python/](../../tests/fixtures/interactive/window-condensation-python/)（同じ絵を scenes.yaml で書いた例は [window-condensation/](../../tests/fixtures/interactive/window-condensation/)）

## 中間データ（render timeline）と字幕

形の正本は [render-timeline.schema.json](../../src/explainer_reel_kit/data/schema/render-timeline.schema.json)（`format: explainer-reel/render-timeline@1`）。30 fps・1920×1080。

- 場面の境界は .pptx のスライドの開始。ナレーションの WAV は「スライドの開始 ＋ 切替効果 ＋ pre_pause_sec」に置かれる（mux と同じ）
- **文の時刻は WAV の実尺から測る**: 合成の分割の境目は durations.json の `chunk_frames` から、分割の中の文の境目は WAV の無音（0.15 秒以上）に寄せる（`timing: measured`）。`chunk_frames` の無い記録は文字の重みで推定（`timing: estimated`）。固定尺の枠で無音を詰めた記録は詰めた後の秒に直す
- **字幕** = 文ごと（文末の句点を落とす）。2 行に入らなければ読点の直後で分ける（英数字の途中・禁則では折らない。3 行は誤り）。字幕どうしは重ならない
- 字幕の別表記（台本の `subtitles`、Markdown では `<!-- subtitle: … -->`）があれば、その段落の字幕は別表記の文。合成には使わない（[storyboard.md](storyboard.md)）
- **SRT と焼き込みは同じ cues から作る**（時刻は表示フレームの始まりをミリ秒に切り捨て）
- ナレーション音声のクレジットは、最後の場面の左下に出す

## 出力（slides の出力に加えて）

```text
<出力フォルダ>/
  <output_name>.srt              字幕
  checks/                        検証結果.md・verify.json・screen_text.json・cue_points.json・ffprobe.json
  checks/resync.md・resync.json  作り直したときの前後の比較（前の中間データがあるとき）
  work/render-timeline.json      中間データ
  work/pauses.json               文中の無音（T.at が使う）
  work/interactive/build/        600 フレームごとの区間（入力のハッシュが同じなら使い回す）
  work/<output_name>.silent.mp4  描いた無音 MP4
```

## 検証（verify）

| 手順 | 内容 |
|---|---|
| probe | 尺・解像度・fps・フレーム数を中間データと照合 |
| decode | 映像・音声を最後までデコードし、エラーの出力が無いこと |
| audio | 音声の正本と一致（正本を渡したときだけ。`erkit make` は省く） |
| subs | 全フレームの字幕の帯を調べ、字幕の表示フレームが cues と一致。MP4 の隣の SRT とも照合 |
| frames | 字幕・場面の切り替わりの前後のフレームを MP4 から取り出し、描画結果と画素で比べる |
| text | 画面の文字を集め、`verify.yaml` の禁止語と照合 |

`verify.yaml` は場面コードのフォルダかその親に置きます（無くてもよい。書き方は `interactive/verify.py` の先頭）。題材の固有の語は公開のリポジトリに入れません。
`erkit make` は要確認でも止めず（終了コード 0）、`run.json` の `stages.verify`（`stage_status` は `needs_review`）と `warnings` に残します。

## 道具（python -m explainer_reel_kit.interactive）

`erkit make` の出力フォルダを使うときは、`--project <出力フォルダ> --timeline <出力フォルダ>/work/render-timeline.json --pauses <出力フォルダ>/work/pauses.json --scenes <場面のフォルダ>` を渡します。

| サブコマンド | 内容 |
|---|---|
| `sheet --cues [--scene ID]` | scenes.yaml の場面ごとに、きっかけの直前・直後・動きの終わりの 3 枚を並べた一覧画像（`checks/sheets/`） |
| `sheet 秒 秒 …` | 指定した秒のフレームを 2×2 に並べた一覧画像 |
| `stills 秒 …` | 指定した秒の静止画 |
| `render --out X.mp4` | 全編を描いて MP4 にする |
| `analyze-audio --audio 音声` | 音声から文中の無音を取り出す |
| `verify --video X.mp4` | 出来上がった MP4 の検証 |
| `gallery --out フォルダ [--type 型]` | 部品の見本の静止画 |
| `schema [--check]` | scenes.yaml の JSON スキーマを書き出す・同じか確かめる |

終了コード: 0 成功 / 1 検証が要確認・描けない / 2 引数・入力の誤り。

## はまりやすい点を仕組みで防ぐ

| 点 | 防ぎ方 |
|---|---|
| 連結で時刻がずれる | 区間は 600 フレーム固定（30 の倍数）。場面の境界では切らない |
| 色がずれる | 書き出しも取り出しも bt709・limited を明示する |
| 図面の細線が消える | 縮小の割合で線を太らせる（既定の場面も） |
| 表の行の取り違え | 行・列は見出しの文字でだけ指定（番号・無い見出しは誤り） |
| 文字のはみ出し | 入らなければ場面・秒・フレームを添えて止まる |

## 書体と依存

依存は Pillow と ffmpeg だけ。書体は同梱の Noto Sans JP（Regular・Bold の OTF、SIL OFL 1.1。[fonts/README.md](../../src/explainer_reel_kit/interactive/fonts/README.md)、[THIRD_PARTY.md](../../THIRD_PARTY.md)）。`erkit doctor` の「コード描画」の行で確かめます。
