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
| PowerPoint（書き出し。COM の登録） | デスクトップ版が要る。Windows 以外では「対象外」 |
| 音声合成エンジン（AivisSpeech） | AivisSpeech を入れて起動（`http://127.0.0.1:10101`） |
| 既定の声（ほのか / ノーマル、または設定の `voice.speaker`） | AivisSpeech の画面で声を入れるか、`voice.speaker` を変える |
| 出力先（書き込めるか・空き容量） | `output_root` / `ERKIT_OUTPUT_ROOT` を変える |

終了コード: 0 そろっている / 1 足りないものがある / 2 設定の誤り。

## erkit make

```text
erkit make <台本> [--serve 撮影するページのフォルダ] [--label 一言] [--dry-run] [--from 段] [--offline]
           [--allow-placeholders] [--no-capture] [--assets-root 画像のフォルダ] [--out-dir 出力フォルダ]
```

例: `erkit make examples/hello-kit.storyboard.md --serve examples/hello-page`

### 段

| 段 | すること | 省略するとき |
|---|---|---|
| `capture` | Web 画面を操作定義（`<reel id>.actions.yaml`）に従って撮る → `<撮影素材のルート>/web/<reel id>/` | Web のシーンが無い・`--no-capture`・`--assets-root` |
| `diagram` | 説明図の HTML を描く → `work/diagram/` | HTML の説明図のシーンが無い |
| `assets` | 画像を探して `work/assets/` にまとめる。画像の無いシーン・位置の決まらない注釈があれば止める（`--allow-placeholders` で灰色の枠・既定の位置で続ける） | — |
| `voice` | ナレーションの WAV と `durations.json` → `work/narration/` | — |
| `deck` | スライド（`<output_name>.pptx`）と確認用の一覧画像（`work/check/overlay.png`）。声のクレジットは設定の `voice.credits` から自動で入る | — |
| `export` | PowerPoint で無音の MP4 → `work/<output_name>.silent.mp4` | Windows 以外（.pptx まで作り、手順を表示する） |
| `mux` | ナレーションを重ねて `<output_name>.mp4`。Morph の変形で動画が少し長くなるずれを補正する | Windows 以外 |

### 出力

```text
<出力先のルート>/<YYYYMMDD>_<reel id>[_<一言>]/     同じ名前があれば -2, -3 …
  <output_name>.mp4 / <output_name>.pptx / run.json
  work/  diagram/  assets/  narration-input.json  narration/  <output_name>.silent.mp4  check/overlay.png
<撮影素材のルート>/web/<reel id>/                    Web の撮影（日付なし。撮り直すと上書き）
```

- 出力先のルート: `--output-root` ＞ `ERKIT_OUTPUT_ROOT` ＞ 設定の `output_root` ＞ ユーザーのフォルダの `ExplainerReelKit/output`
- 撮影素材のルート: `--captures-root` ＞ `ERKIT_CAPTURES_ROOT` ＞ 設定の `captures_root` ＞ ユーザーのフォルダの `ExplainerReelKit/captures`

### 実行の前に確かめること

1. **社外秘の台本（区分が未記入も）と `--offline`**: この PC の外へ出る設定が無いか。音声合成エンジンの URL、撮影の URL（`--url-map`・`--serve` で置き換えた後）がこの PC（`127.0.0.1`・`localhost`・`::1`・`file://`）か。LLM は使わない。1 つでも外なら**何も作らずに止める**（終了コード 1）。`--dry-run` でも確かめる
2. **前提**: 残りの段に要るもの（ブラウザ・操作定義・音声合成エンジンと声・PowerPoint・ffmpeg）を一度に確かめ、足りなければ**何も作らずに**全部を表示して止める

### 記録（run.json）

`format: explainer-reel-kit/run@1`。区分（`confidentiality`）、`--offline`、ネットワークの確かめの結果（`network_checks`）、声とクレジット、前提の確かめ（`prereq`）、段ごとの結果（`stages.<段>.status` = ok / skipped / failed と中身）、作ったファイル、注意（`warnings`）、失敗したときの再開のコマンド（`resume`）。

### 再開（--from）

- 段が失敗すると、`run.json` の `resume` と画面に「直したら、そこから」のコマンドが出る（`erkit make <台本> --from <段> --out-dir <出力フォルダ>`）
- `--out-dir` を省略すると、出力先のルートで、この台本（reel id）の最後の実行を探す
- `--from <段>` は、それより前の段が前回 ok か省略で終わっているときだけ使える
- Windows 以外で .pptx まで作ったものは、Windows で `--from export` から MP4 にできる

終了コード: 0 できた（Windows 以外で .pptx まで作ったときも 0） / 1 前提が足りない・社外秘の確かめで止めた・段が失敗した / 2 引数・台本の誤り。

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
