# explainer_reel_kit.interactive — コード描画（render_mode: interactive）

ナレーションの時刻に合わせて、場面の指定（`scenes.yaml`）か Python の**場面コード**で 1 フレームずつ描き、ffmpeg で MP4 にする。
**PowerPoint を使わない**ので、PowerPoint の無い PC（Linux・会社の PC など）でも MP4 まで作れる。
依存は Pillow と ffmpeg だけ。書体は同梱の Noto Sans JP（`fonts/` の OTF 2 つ、SIL OFL 1.1）。
描画はこの PC の中だけで行い、ネットワークを使わない。

```text
台本 ──erkit make（voice・deck は slides と同じ）──▶ .pptx のスライドの時刻 ＋ durations.json
                                               └─▶ 中間データ（work/render-timeline.json）
中間データ ＋ 場面の指定（scenes/）──描く──▶ 無音 MP4 ──mux（slides と同じ）──▶ MP4 ──verify──▶ checks/
```

## 映像の作り方の切り替え

| モード | 映像 | 字幕 | 指定 |
|---|---|---|---|
| `slides`（既定） | PowerPoint で書き出す（今までの道） | なし | 何も書かない |
| `interactive` | 場面の指定で描く（このモジュール） | 中間データの cues から焼き込み＋SRT | 台本の `reel.render_mode: interactive`（kit-1.2.0）か、`erkit make --render-mode interactive`（台本より優先） |

`erkit make` の interactive は、ナレーション・.pptx（python-pptx で作る。スライドの時刻の正本）・音声の合成（mux、音量そろえ）を
slides と共通に使い、**書き出しの段だけ**を差し替える。場面の境界と音声の位置は .pptx のスライドの時刻なので、
同じナレーションなら slides と同じ位置に音声が入る。

## erkit make から呼ぶ入口（`pipeline.py`）

| 関数 | いつ | すること |
|---|---|---|
| `resolve_render_mode(command, doc)` | 台本を読んだ後 | `--render-mode` ＞ 台本の `reel.render_mode` ＞ slides。戻り値 `(mode, source)` |
| `precheck_scenes(storyboard, doc, scenes_dir=None)` | 出力フォルダを作る前（合成の前） | scenes.yaml を、台本の原稿から仮に置いた時刻で組み立てて試し描き。誤りは `InteractiveError`（`exit_code` 2） |
| `render_storyboard(storyboard, doc, out_dir, stem, ...)` | deck の後（書き出しの段の代わり） | 中間データ・SRT・作り直しの比較・文中の無音・無音 MP4 を作る |
| `verify_storyboard(out_dir, stem, scenes_dir, storyboard=...)` | mux の後 | 出来上がった MP4 を検証（要確認でも止めない） |

誤りはどれも `InteractiveError`（`stage`・`exit_code`: 2＝台本・scenes.yaml・引数の誤り、1＝描けない・ffmpeg の失敗）。

## 場面の指定と場面コードの置き場

台本のフォルダの `scenes/<reel id>/`（無ければ、直下に `scenes.yaml` か `.py` がある `scenes/`）。
**ツールは台本のフォルダの `scenes/` の下のコードだけを読み込んで実行する**（ほかの場所を指定すると止まる。人から受け取ったコードを読み込む用途は想定しない）。
台本と同じく `reels/` の下に置けば、公開のリポジトリには入らない（`.gitignore`）。

優先順位: その場面の Python の場面コード（`<場面 id>.py`・`index.py`）＞ `scenes.yaml` の指定 ＞ 既定の場面。

**既定の場面**（`scenes.default_scene`）: 台本のシーンは slides（`deck/builder.py` の `_scene_slide`）と同じものを同じ順に出す。
見出し・画像（細線は縮小の割合で太らせる）・来歴ラベル（`image.label`。撮影前は `撮影前（仮）`、文字だけのカード
`recipe_params.card` は出さない）・台本の注釈（赤枠・矢印。位置は slides と同じ `marks.json`、時刻は slides と同じ段落）。
来歴ラベルは必ず出る（消す設定は無い）。配置は `scenes.py` の `HEAD_BOX`・`IMAGE_BOX`・`LABEL_RIGHT`・`LABEL_TOP`（字幕帯の上）。画面テキスト（on_screen_text）は interactive では出さない（字幕の帯と重なるため）。
中間データの場面の `heading`・`label`・`placeholder`・`card`・`text`・`appear`・`view`・`annotations` は `annotate.py` が台本から作る。
画像の無い場面（intro・outro）は見出しと文のカード。

静止画は場面コードのフォルダの `assets/` と、その親の `assets/` から探す（`scenes/<reel id>/` なら `scenes/<reel id>/assets/` と `scenes/assets/`）。**台本のフォルダと出力フォルダの中のファイルだけ**を読む（URL・その外のファイルは誤り）。

### scenes.yaml

形の正本は `spec.json_schema()`（パッケージのデータ `data/schema/scenes.schema.json` はそこから作る。部品を変えたら
`python -m explainer_reel_kit.interactive schema`、同じか確かめるのは `schema --check`）。

```yaml
version: 1
scenes:
  s02:
    parts:
      - type: header
        title: しくみをつかむ
      - type: cards
        box: [96, 250, 1728, 220]     # [x, y, 幅, 高さ]（1920×1080。字幕帯 y 940 より上）。無ければ上から積む
        items:
          - {title: ① 暖かい空気, body: 水蒸気を含む, sentence: 1}   # その場面の 1 番目の文で出す
          - {title: ② 窓で冷える, body: 空気が冷やされる, sentence: 3}
      - type: callout
        text: 室温 20℃・湿度 60％なら露点は約 12℃
        at: 露点は                     # ナレーションの語句が読まれ始める時刻で出す
```

きっかけ（部品・項目の `at` / `sentence` / `delay`）:

- `sentence: 3`: その場面の 3 番目の文の始まり
- `at: "露点は"`: その場面のナレーションの中で、この語句が読まれ始める時刻。2 つ以上の文にあるときは `sentence` で文を決める
- どちらも無ければ場面の始まり。`delay` で秒をずらす。`until` で消す

読み込みの検証（知らない型・項目・動き、語句がナレーションに無い・2 つの文にある、文が無い、知らない列、文字のはみ出し）は描く前に止まる。

### 部品の一覧（11 種）

| 型 | 内容 | 動きの既定 |
|---|---|---|
| `header` | 見出し（上の帯。進行表示・ラベル） | `fade-in` |
| `heading` | 段の見出し | `fade-in` |
| `title` | 中央の題 | `fade-in` |
| `cards` | カードを読み上げ順に点灯 | `stagger`・強調 `roomhighlight` |
| `steps` | 手順の番号付きリスト | `stagger`・強調 `roomhighlight` |
| `table` | 表の行・列の強調（行・列は見出しの文字で指定） | `stagger`・強調 `roomhighlight` |
| `number` | 数値の強調 | `counter` |
| `image` | 画像と注釈（枠・引き出し線）。画像ごとに来歴ラベルを必ず出す（台本の画像は台本の `image.label`、ほかの静止画は `label`、無ければ `説明用再構成図`） | `clipreveal`・強調 `roomhighlight` |
| `compare` | 比較の左右 | `slidein`・強調 `roomhighlight` |
| `callout` | 要点の囲み・帯 | `stagger`・入れ替え `fadethrough` |
| `flow` | 流れ（札を矢印でつなぐ） | `stagger`・強調 `roomhighlight` |

動きの名前（`motion`・`emphasis`・`switch`）はモーション見本帳の見本の id。長さの既定は説明動画向け（`motion.VIDEO_DEFAULTS`）で、
見本帳の値（Web の画面向け）は `Motion.book` に残る。イージングは見本帳のまま。`speed` で長さを割る。

| scenes.yaml の値 | 役割 | 既定の長さ（説明動画） | 見本帳の値 |
|---|---|---|---|
| `fade` | 現れ方 | 0.4 | 1.5 |
| `fade-in` | 現れ方 | 0.4 | 1.7 |
| `stagger` | 現れ方 | 0.4 | 0.5 |
| `stagger-T03` | 現れ方 | 0.4 | 0.55 |
| `slidein` | 現れ方 | 0.4 | 0.6 |
| `clipreveal` | 現れ方 | 0.4 | 1 |
| `wipe` | 現れ方 | 0.4 | 1.2 |
| `cut` | 現れ方 | 0 | 0 |
| `typewriter` | 現れ方 | 0.01（1 文字ごと） | 0.01 |
| `roomhighlight` | 強調 | 0.3 | （無し） |
| `fill` | 強調 | 0.3 | 0.4 |
| `underline` | 強調 | 0.3 | 0.35 |
| `marker` | 強調 | 0.3 | 1 |
| `callout` | 強調 | 0.55 | 1.1 |
| `hotspot` | 強調 | 1.1（くり返しの周期） | 1.1 |
| `counter` | 数値 | 0.8 | 1.8 |
| `fadethrough` | 入れ替え | 0.09 | 0.09 |
| `beforeafter` | 比べ方 | 2.2 | 2.2 |

### Python の場面コード（部品で足りないとき）

- `scenes/<場面 id>.py` に `def scene(f, t, T)`、または `scenes/index.py` に `SCENES = {'<場面 id>': 関数}`
  （任意で `subtitle(f, frame, T)`＝字幕の描き方、`AT_WEIGHTS`＝`T.at` の推定の重み）
- `f`: 表示リスト（`f.text`・`f.text_box`・`f.rr`・`f.focus`・`f.veil`・`f.circ`・`f.path`・`f.img`・`f.tag`・`f.badge`）
- `t`: 秒（フレームの先頭）。状態を持たないので、どの秒の静止画もすぐ出せる
- `T`: 問い合わせ口。`T.S(文)`・`T.E(文)`・`T.at(文, 語)`・`T.by_id[場面]`。**秒を直書きしない**。文の id は `<場面 id>-<番号>`
- 道具: `from explainer_reel_kit.interactive.engine import *`、`from explainer_reel_kit.interactive.parts import Table, card_text`
- 例: `tests/fixtures/interactive/window-condensation-python/`（同じ絵を scenes.yaml で書いた例は `tests/fixtures/interactive/window-condensation/`）

## 中間データ（render timeline）

形の正本はパッケージのデータ `data/schema/render-timeline.schema.json`（`format: explainer-reel/render-timeline@1`）。

| 項目 | 内容 |
|---|---|
| `fps`・`width`・`height`・`total_frames` | 今は 30 fps・1920×1080 だけ |
| `scenes[]` | `id`・`title`・`start_frame`・`end_frame`（0 から切れ目なく total_frames まで）・`image`・`body`。台本のシーンは画面の決まり `heading`・`label`（来歴）・`placeholder`・`card`・`text`・`appear`・`view`・`annotations`（赤枠・矢印の位置と出す秒） |
| `sentences[]` | `id`（`<場面 id>-<番号>`）・`scene`・`paragraph`・`spoken`（原稿。`T.at` はここから語を探す）・`reading`（合成入力）・`subtitle`・`start_sec`・`end_sec`・`timing` |
| `cues[]` | 字幕。`sentence`・`text`・`start_frame`・`end_frame`（重ならない）・`lines`（2 行まで） |
| `meta` | `title`・`credit`（ナレーション音声のクレジット。最後の場面の左下に常に出す） |

台本から作るとき（`convert.from_storyboard`）:

- 場面の境界は .pptx のスライドの開始。ナレーションの WAV は「スライドの開始 ＋ 切替効果 ＋ pre_pause_sec」に置かれる（mux と同じ）
- **文の時刻は WAV の実尺から測る**（`sync.py`）: 合成の分割の境目は durations.json の `chunk_frames` から正確に、分割の中の文の境目は
  WAV の無音（0.15 秒以上）に寄せる（`timing: measured`）。`chunk_frames` の無い記録は、段落の開始（`paragraph_starts_sec`）から文字の重みで推定
  （`timing: estimated`）。固定尺の枠で無音を詰めた記録（`fit.cuts`）は詰めた後の秒に直す
- 字幕＝文ごと（文末の句点を落とす）。2 行に入らなければ読点の直後で分け、字幕の中の改行も読点の直後だけ
- 字幕の別表記（台本の `subtitles`、Markdown では `<!-- subtitle: … -->`）があれば、その段落の字幕は別表記の文。合成には使わない
- 時刻 → フレームは「その時刻以降の最初のフレーム」

## 出力（erkit make --render-mode interactive）

slides の出力に加えて:

```text
<出力フォルダ>/
  <名前>.srt                    字幕（焼き込みと同じ cues から。時刻は表示フレームの始まりをミリ秒に切り捨て）
  checks/                       verify.json・検証結果.md・screen_text.json・cue_points.json・ffprobe.json
  checks/resync.md・resync.json 作り直したときの比較（前の中間データがあれば）
  work/render-timeline.json     中間データ
  work/pauses.json              文中の無音（T.at が使う）
  work/interactive/build/       600 フレームごとの区間（入力のハッシュが同じなら使い回す）
  work/<名前>.silent.mp4        描いた無音 MP4（この後 mux でナレーションを入れる）
```

## 検証（verify）

| 手順 | 内容 |
|---|---|
| probe | 尺・解像度・fps・フレーム数を中間データと照合 |
| decode | 映像・音声を最後までデコードし、エラーの出力が無いこと |
| audio | 音声の正本（`--audio-ref`）と一致（正本が無ければ省く。erkit make は省く） |
| subs | 全フレームの字幕帯を走査し、字幕の表示フレームが cues と一致。MP4 の隣の SRT とも照合 |
| frames | 字幕・場面の切替の前後のフレームを MP4 から取り出し、描画結果と画素で比べる |
| text | 画面の文字を集め、`verify.yaml` の禁止語と照合 |

`verify.yaml`（場面コードのフォルダかその親。無くてもよい。題材の固有の語は公開のリポジトリに入れない）の書き方は `verify.py` の先頭。

## コマンド（`python -m explainer_reel_kit.interactive …`）

`--project` のフォルダの決まりの置き場: `scenes/`・`assets/`・`data/render-timeline.json`・`data/pauses.json`・`verify.yaml`
（`--timeline` / `--scenes` / `--pauses` / `--config` で変えられる。erkit make の出力なら `--timeline <出力>/work/render-timeline.json`）。

| サブコマンド | 内容 |
|---|---|
| `sheet --project P 秒 秒 …` | 指定した秒のフレームを 2×2 に並べた一覧画像（全編を描く前に静止画で確かめる） |
| `sheet --project P --cues [--scene ID]` | scenes.yaml の場面ごとに、きっかけの前・直後・終わりの 3 枚を並べる |
| `stills --project P 秒 …` | 指定した秒の静止画 |
| `render --project P --out X.mp4 [--audio-source 正本] [--verify]` | 全編を描いて MP4 にする |
| `analyze-audio --project P --audio 音声` | 音声から文中の無音を取り出す（`data/pauses.json`） |
| `verify --project P --video X.mp4` | 出来上がった MP4 の検証 |
| `gallery --out フォルダ [--type 型]` | 部品の見本の静止画（ダミーの中身） |
| `schema [--check]` | scenes.yaml の JSON スキーマを書き出す・同じか確かめる |

終了コード: 0 成功 / 1 検証が要確認・描けない / 2 引数・入力の誤り。PNG・MP4 はリポジトリに入れない。

## はまりやすい点を仕組みで防ぐ

| 点 | 防ぎ方 |
|---|---|
| 連結で時刻がずれる | 区間は 600 フレーム固定（30 の倍数）。場面の境界では切らない |
| 色がずれる | 書き出しも取り出しも bt709・limited を明示する |
| 図面の細線が消える | `f.img(..., mode='auto')`（既定の場面も）: 縮小の割合で線を太らせる |
| 表の行の取り違え | 表は行・列を見出しの文字でだけ指定（番号・無い見出しは誤り） |
| 文字のはみ出し | 入らなければ `LayoutError`（場面・秒・フレームを添えて止まる） |
| 字幕の改行 | 読点・句点の直後で 2 行まで。英数字の途中・禁則では折らない。3 行は誤り |

## 書体

`fonts/NotoSansJP-Regular.otf`・`NotoSansJP-Bold.otf`（Noto Sans JP、Version 2.004）。入手先・版・sha256 は [fonts/README.md](fonts/README.md)、
ライセンスは SIL Open Font License 1.1（`fonts/OFL.txt`）。slides の書体（PowerPoint）は変えない。
