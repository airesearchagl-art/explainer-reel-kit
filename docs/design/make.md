# 通し生成（erkit make）と環境の確認（erkit doctor）

## erkit doctor

動画を作るのに要るものがそろっているかを確かめ、無いものの入れ方を表示します。**キットが自動で入れることはありません。**

```text
erkit doctor [--config 設定] [--engine-url URL] [--channel msedge] [--skip-browser] [--json]
```

| 確かめるもの | 足りないとき（表示する入れ方） |
|---|---|
| Python 3.10 以上 | `winget install Python.Python.3.12` |
| Python のライブラリ（jsonschema・PyYAML・python-pptx・lxml・Pillow・playwright） | `python -m pip install -e ".[dev]"` |
| ブラウザ（撮影・説明図。実際に起動して閉じる） | `python -m playwright install chromium`、または `--channel msedge` |
| ffmpeg / ffprobe | `winget install Gyan.FFmpeg`（入れたらターミナルを開き直す） |
| PowerPoint（書き出し。COM の登録） | デスクトップ版が要る（slides だけ）。Windows 以外では「対象外」 |
| コード描画（interactive。Pillow・同梱の書体 Noto Sans JP） | `python -m pip install -e ".[dev]"` をやり直す。ffmpeg が無ければ注意。PowerPoint が使えないときは、最後に「interactive なら MP4 まで作れます」と表示する（`--json` では `routes`） |
| 音声合成エンジン（AivisSpeech） | AivisSpeech を入れて起動（`http://127.0.0.1:10101`） |
| 既定の声（ほのか / ノーマル、または設定の `voice.speaker`） | AivisSpeech の画面で声を入れるか、`voice.speaker` を変える |
| 出力先（書き込めるか・空き容量） | `output_root` / `ERKIT_OUTPUT_ROOT` を変える |

終了コード: 0 そろっている / 1 足りないものがある / 2 設定の誤り。

## erkit make

```text
erkit make <台本> [--serve 撮影するページのフォルダ] [--label 一言] [--dry-run] [--from 段] [--offline]
           [--allow-placeholders] [--no-capture] [--assets-root 画像のフォルダ] [--out-dir 出力フォルダ]
           [--render-mode slides|interactive] [--reuse-run 前の出力フォルダ] [--force]
```

- `--render-mode`: 映像の作り方。`--render-mode` ＞ 台本の `reel.render_mode` ＞ `slides`（[interactive.md](interactive.md)）
- `--reuse-run`: 前の出力フォルダの `work/narration` の WAV を使い回し、変わった段落だけ合成する（前の出力フォルダは読むだけ。[narration.md](narration.md) の「作り直しの決まり」）

例: `erkit make examples/hello-kit.storyboard.md --serve examples/hello-page`

### 段

| 段 | すること | 省略するとき |
|---|---|---|
| `capture` | Web 画面を操作定義（`<reel id>.actions.yaml`）に従って撮る → `<撮影素材のルート>/web/<reel id>/` | Web のシーンが無い・`--no-capture`・`--assets-root` |
| `diagram` | 説明図の HTML を描く → `work/diagram/` | HTML の説明図のシーンが無い |
| `assets` | 画像を探して `work/assets/` にまとめる。画像の無いシーン・位置の決まらない注釈があれば止める（`--allow-placeholders` で灰色の枠・既定の位置で続ける） | — |
| `voice` | ナレーションの WAV と `durations.json` → `work/narration/`。台本に `slot_sec` があれば、その場面を固定尺の枠に収める（収まらなければ失敗） | — |
| `deck` | スライド（`<output_name>.pptx`）と確認用の一覧画像（`work/check/overlay.png`）。声のクレジットは設定の `voice.credits` から自動で入る | — |
| `export` | slides: PowerPoint で無音の MP4 → `work/<output_name>.silent.mp4`。interactive: コード描画で無音の MP4・中間データ・`<output_name>.srt`（PowerPoint を使わない） | slides で Windows 以外（.pptx まで作り、手順を表示する） |
| `mux` | ナレーションを重ねて `<output_name>.mp4`。ナレーションのトラックを -16 LUFS・true peak -1.5 dBTP 以下にそろえる（下の節）。slides は Morph の変形で動画が少し長くなるずれも補正する | slides で Windows 以外 |
| `verify` | interactive だけ。出来上がった MP4 を検証し `checks/検証結果.md` に残す（要確認でも止めない） | — |

### 出力

```text
<出力先のルート>/<YYYYMMDD>_<reel id>[_<一言>]/     同じ名前があれば -2, -3 …
  <output_name>.mp4 / <output_name>.pptx / run.json
  work/  diagram/  assets/  narration-input.json  narration/  <output_name>.silent.mp4  check/overlay.png
<撮影素材のルート>/web/<reel id>/                    Web の撮影（日付なし。撮り直すと上書き）
```

- 出力先のルート: `--output-root` ＞ `ERKIT_OUTPUT_ROOT` ＞ 設定の `output_root` ＞ ユーザーのフォルダの `ExplainerReelKit/output`
- 撮影素材のルート: `--captures-root` ＞ `ERKIT_CAPTURES_ROOT` ＞ 設定の `captures_root` ＞ ユーザーのフォルダの `ExplainerReelKit/captures`

interactive の出力（`<output_name>.srt`・`checks/`・`work/render-timeline.json` など）は [interactive.md](interactive.md) の「出力」。

### 音量そろえ（mux。slides・interactive の両方）

- 連結したナレーションのトラック全体を測り、1 回目の測定値から決めた量で一律に上げ下げし、オーバーサンプリングした true peak リミッター（-2.0 dBTP。AAC にしたときの上がり分の余裕）で抑えて、-16 LUFS・true peak -1.5 dBTP 以下にそろえる。リミッターで小さくなった分は測り直して足す（3 回まで）
- 段落ごとの WAV と `durations.json` は変えない。無音だけのトラックはそろえずに通す
- 結果は `run.json` の `stages.mux.loudness`。目安（-16 ± 1 LUFS）から外れたとき・リミッターで大きく抑えたときは `warnings` に注意（止めない）

### 実行の前に確かめること

1. **社外秘の台本（区分が未記入も）と `--offline`**: この PC の外へ出る設定が無いか。音声合成エンジンの URL、撮影の URL（`--url-map`・`--serve` で置き換えた後）がこの PC（`127.0.0.1`・`localhost`・`::1`・`file://`）か。LLM は使わない。1 つでも外なら**何も作らずに止める**（終了コード 1）。`--dry-run` でも確かめる
2. **前提**: 残りの段に要るもの（ブラウザ・操作定義・音声合成エンジンと声・PowerPoint・ffmpeg。interactive は PowerPoint の代わりにコード描画の Pillow・書体）を一度に確かめ、足りなければ**何も作らずに**全部を表示して止める
3. **場面の指定（interactive）**: `scenes.yaml` を台本の原稿から仮に置いた時刻で組み立てて試し描きする。誤りは**何も作らずに**終了コード 2（`--dry-run` でも行う）

### 記録（run.json）

`format: explainer-reel-kit/run@1`。区分（`confidentiality`）、映像の作り方（`render_mode`: `mode`・`source`）、`--offline`、ネットワークの確かめの結果（`network_checks`）、声とクレジット、前提の確かめ（`prereq`）、段ごとの結果（`stages.<段>.status` = ok / skipped / failed と中身）、作ったファイル、注意（`warnings`）、失敗したときの再開のコマンド（`resume`）。

### 再開（--from）

- 段が失敗すると、`run.json` の `resume` と画面に「直したら、そこから」のコマンドが出る（`erkit make <台本> --from <段> --out-dir <出力フォルダ>`）
- `--out-dir` を省略すると、出力先のルートで、この台本（reel id）の最後の実行を探す
- `--from <段>` は、それより前の段が前回 ok か省略で終わっているときだけ使える。`--from verify` は interactive だけ
- `--render-mode` で作り方を選んだ実行は、再開のコマンドにも `--render-mode` が付く
- Windows 以外で .pptx まで作ったものは、Windows で `--from export` から MP4 にできる

終了コード: 0 できた（slides で Windows 以外のとき .pptx まで作っても 0。interactive の検証が要確認でも 0） / 1 前提が足りない・社外秘の確かめで止めた・段が失敗した / 2 引数・台本・scenes.yaml の誤り。

## 書き出し（Export-PptxToVideo.ps1）

パッケージのデータとして入っている PowerShell のスクリプト（ASCII だけ・BOM なし。Windows PowerShell 5.1 でも読める）。
PowerPoint の COM（`Presentation.CreateVideo`）で、スライドの自動切替の秒数とアニメーションの時刻どおりに無音の MP4 を書く。
`erkit make` が呼ぶほか、手でも呼べる（Windows 以外で `erkit make` が表示するコマンド）。

| 終了コード | 意味 |
|---|---|
| 0 | できた |
| 2 | 引数・入力の誤り（Windows 以外を含む） |
| 3 | 出力ファイルが既にある（`-Force` で上書き） |
| 4 | PowerPoint を起動できない・開けない |
| 5 | PowerPoint が書き出しに失敗した |
| 6 | 時間切れ |
