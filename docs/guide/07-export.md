# 7. 書き出し

## 映像の作り方を選ぶ

| 作り方 | 映像 | 字幕 | 要るもの | 向いているとき |
|---|---|---|---|---|
| `slides`（既定） | スライド（.pptx）を PowerPoint で MP4 に書き出す | なし | Windows ＋ PowerPoint（デスクトップ版） | PowerPoint で動きを直したい |
| `interactive` | キットが 1 フレームずつ描いて MP4 にする（**PowerPoint を使わない**） | 焼き込み ＋ SRT | どの OS でも（Pillow と書体はキットに入っている） | PowerPoint の無い PC、字幕が要る、読み上げに合わせて画面を動かしたい |

どちらも、ナレーション・.pptx・音声の合成（音量そろえ）は同じです。違うのは書き出しの段だけです。

- 台本で決める: `reel.render_mode: interactive`（台本の版を `kit-1.2.0` にする。[storyboard.md](../design/storyboard.md)）
- コマンドで決める: `--render-mode interactive`（台本より優先。台本を変えずに試せる）
- `erkit doctor` の「コード描画（interactive）」の行が `OK` なら、PowerPoint が無くても interactive で MP4 まで作れます

## MP4 まで作る（slides）

AivisSpeech を起動し、PowerPoint は閉じておきます（書き出しの間、キットが PowerPoint を動かします）。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app
if ($LASTEXITCODE -eq 0) { Invoke-Item "$env:USERPROFILE\ExplainerReelKit\output" }
```

段の順番: 撮影（capture）→ 説明図（diagram）→ 素材をまとめる（assets）→ ナレーション（voice）→ スライド（deck）→ 書き出し（export）→ 音声の合成（mux）。
最初に残りの段に要るもの（ブラウザ・操作定義・音声合成エンジンと声・PowerPoint・ffmpeg）を一度に確かめ、足りなければ何も作らずに止まります。

できるもの:

```text
ユーザーのフォルダ\ExplainerReelKit\output\<日付>_u-value\
  u_value.mp4        ナレーション付きの動画
  u_value.pptx       PowerPoint で直せるスライド
  run.json           記録（区分・段ごとの結果・再開のコマンド）
  work\              ナレーションの WAV・無音の動画・素材・確認画像
```

出力先は `--output-root`、環境変数 `ERKIT_OUTPUT_ROOT`、`config\kit.yaml` の `output_root` の順で変えられます。

## PowerPoint を使わずに MP4 まで作る（interactive）

AivisSpeech を起動しておきます。PowerPoint は要りません（開いていても使いません）。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --render-mode interactive
if ($LASTEXITCODE -eq 0) { Invoke-Item "$env:USERPROFILE\ExplainerReelKit\output" }
```

段の順番は slides と同じで、書き出し（export）の中身がコード描画に変わり、最後に検証（verify）が付きます。

- 最初に、場面の指定（`scenes.yaml`。[05-visuals.md](05-visuals.md)）を、ナレーションを合成する前に確かめます。誤りがあれば出力フォルダを作らずに終了コード 2 で止まります
- 場面の指定が無い場面は既定の場面（説明図・撮影画像をそのまま出す）。場面の指定を 1 つも書かなくても MP4 まで作れます
- .pptx も作ります（python-pptx で作るので PowerPoint は要らない）。場面の切り替わりの時刻はこの .pptx のスライドの時刻から取るので、slides と同じナレーションなら同じ位置に音声が入ります
- 社外秘の台本でも、描画・書き出しはこの PC の中だけで行い、ネットワークを使いません（静止画は台本のフォルダと出力フォルダの中だけを読む）

slides の出力に加えて、できるもの:

```text
<日付>_u-value\
  u_value.srt                字幕（MP4 に焼き込んだものと同じデータから）
  checks\検証結果.md          検証の結果（人が読む）。verify.json・screen_text.json・cue_points.json・ffprobe.json も
  checks\resync.md           作り直したときの前後の比較（--reuse-run のとき）
  work\render-timeline.json  中間データ（場面・文・字幕の時刻）。sheet で使う
  work\pauses.json           文の中の無音
  work\interactive\build\    描いた区間（入力が同じなら次も使い回す）
```

### 検証（verify）

interactive は最後に MP4 を確かめ、`checks\検証結果.md` に残します。

| 確かめること | 内容 |
|---|---|
| 尺・解像度・コマ数 | 中間データと合っているか |
| デコード | 映像・音声を最後まで読んでエラーが無いか |
| 字幕 | 全フレームの字幕の帯を調べ、字幕の出る時刻が中間データと合っているか。隣の SRT とも合っているか |
| 絵 | 字幕・場面の切り替わりの前後のフレームが、描いたものと同じか |
| 画面の文字 | 画面に出した文字を集め、禁止の語（任意の `verify.yaml`）が無いか |

要確認があっても MP4 は残し、終了コード 0 で終わります（表示と `run.json` の `warnings`、`stages.verify` に残る）。**`検証結果.md` は毎回見て**、要確認の行を直します。

### 字幕

- 字幕は文ごとに出ます（文末の句点は出さない）。2 行に入らなければ読点の後で分けます
- 読み上げる原稿と字幕の文を分けたいときは、段落のすぐ後に字幕の別表記を書きます（台本の版は `kit-1.2.0`）。合成には使わないので、字幕だけを直したときは WAV を作り直しません

```markdown
ユー値が小さいほど、熱を通しにくい窓です。
<!-- subtitle: U 値が小さいほど、熱を通しにくい窓です。 -->
```

- SRT は MP4 の隣にできます（動画の公開先に字幕として付けられます）。slides では字幕は付きません

## 音量そろえ（slides・interactive の両方）

音声の合成（mux）で、ナレーションのトラック全体を **-16 LUFS、true peak -1.5 dBTP 以下**にそろえてから MP4 に入れます。どちらの作り方でも同じです。

- 全体を同じ量だけ上げ下げし、強い音だけをリミッターで抑えます（文ごとの大きさの差はそのまま）。ナレーションの WAV と `durations.json` は変えません
- 結果は `run.json` の `stages.mux.loudness` に残り、目安（-16 ± 1 LUFS）から外れたときは注意を出します（止めない）

出来上がりの MP4 を自分で測るときは、PowerShell で次のようにします（Windows PowerShell 5.1 でも読めます。`$mp4` は自分の MP4 のパスに）。最後の 2 行が統合ラウドネス（`I:` の LUFS）と true peak（`Peak:` の dBFS）です。

```powershell
$mp4 = "$env:USERPROFILE\ExplainerReelKit\output\ka08-interactive\u_value.mp4"
ffmpeg -hide_banner -nostats -i $mp4 -map a:0 -af ebur128=peak=true -f null - 2>&1 | Select-String -Pattern '^\s+(I|Peak):' | Select-Object -Last 2
```

`I:` が -16 ± 1 LUFS、`Peak:` が -1.5 以下なら目安どおりです。ffmpeg を使わずに見るなら、出力フォルダの `run.json` の記録を読みます（`stages.mux.loudness.after` の `lufs` と `true_peak`）。

```powershell
(Get-Content "$env:USERPROFILE\ExplainerReelKit\output\ka08-interactive\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json).stages.mux.loudness.after
```

## 場面の長さを決める（slot_sec）

音楽や別の映像に合わせるなど、場面の長さを決めたいときは、台本のその場面に `slot_sec: 秒` を書きます（台本の版は `kit-1.2.0`。[storyboard.md](../design/storyboard.md)）。

- ナレーションが短ければ、後ろが無音になります
- 長ければ、音声を伸び縮みさせずに、文の前後と文の間の無音を詰めます
- それでも入らなければ、ナレーションの段で止まり、超えた秒数と「話速を上げる・文を短くする・枠を延ばす」の選択肢を表示します

## 途中で止まったとき（続きから）

段が失敗すると、「直したら、そこから」のコマンドが表示され、`run.json` の `resume` にも残ります。
原因を直したら、その段から作り直します。`--out-dir` を省くと、この台本の最後の実行を続けます。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --from voice
```

`--from` に書ける段: `capture` / `diagram` / `assets` / `voice` / `deck` / `export` / `mux`、interactive はさらに `verify`（それより前の段が前回うまく終わっているときだけ）。
interactive を `--render-mode` で選んだときは、続きのコマンドにも `--render-mode interactive` を付けます（表示されるコマンドには付いています）。

ナレーションを書き換えた後は、変わったシーンの WAV を作り直すため `--force` を付けます（付けないと、上書きせずに止まります）。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --from voice --force
```

### interactive で描き直す・検証し直す

場面の指定（`scenes.yaml`）だけを直したときは、ナレーションを作り直さずに、書き出しの段から描き直します。検証だけをやり直すときは `--from verify` です。

```powershell
erkit make samples\u-value\u-value.storyboard.md --render-mode interactive --from export
erkit make samples\u-value\u-value.storyboard.md --render-mode interactive --from verify
```

## ナレーションを直して作り直す（変わった段落だけ合成）

読み辞書やナレーションを直したら、前の出力フォルダを `--reuse-run` に渡して、新しい出力フォルダに作り直します。
前の WAV のうち、内容が同じ段落はそのまま使い、**変わった段落だけ**をエンジンに送ります（前の出力フォルダは読むだけ）。

```powershell
$prev = (Get-ChildItem "$env:USERPROFILE\ExplainerReelKit\output" -Directory -Filter "*_u-value*" | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --render-mode interactive --reuse-run $prev --label 読み直し
```

- どの段落を合成したかは、新しい出力フォルダの `work\narration\durations.json` の `synthesized_paragraphs` に残ります
- interactive なら、変わった文とその前後・場面の切り替わりのずれを `checks\resync.md` で確かめられます
- 字幕の別表記だけを直したときは、合成は 0 件です

## 読みを文ごとに確かめる（erkit voice review）

作った後に、文ごとの読みを表と試聴ページで確かめます（AivisSpeech を起動しておく）。`--run` には `erkit make` の出力フォルダを渡します。

```powershell
$o = (Get-ChildItem "$env:USERPROFILE\ExplainerReelKit\output" -Directory -Filter "*_u-value*" | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
erkit voice review samples\u-value\u-value.storyboard.md --run $o
if ($LASTEXITCODE -eq 0) { Invoke-Item "$o\checks\listen.html" }
```

| できるもの（出力フォルダの `checks\`） | 中身 |
|---|---|
| `review.tsv` | 文ごとに 原稿・字幕・合成に送った文（辞書の後）・エンジンの読み・書き起こし・印（Excel で開ける） |
| `listen.html` | 印の付いた文だけを並べた試聴ページ。▶ でその文だけを再生する |

- 印: `ずれ`（書き起こしが原稿と違う）・`辞書`（辞書で読みを直した語がある）・`確認語`（辞書の確認語がある）。読みの正否は、エンジンの読みと耳で決めます
- 書き起こしは任意です。`pip install faster-whisper` で入れたときだけ行い、この PC の中で動かします（初回はモデルのファイルを取得します。音声・原稿は送りません）。入れていなければ書き起こしの列を空にして続けます（`--no-transcribe` でも省ける）
- 社外秘の台本では、エンジンの URL がこの PC でなければ止まります
- 読みを直したら、上の `--reuse-run` で作り直します

## PowerPoint で直してから書き出し直す（slides）

キットが作った .pptx を PowerPoint で直し、同じ名前で保存してから、書き出しの段から作り直せます。

```powershell
erkit make samples\u-value\u-value.storyboard.md --from export
```

- 直してよいもの: 文字の言い回し・位置・大きさ、図形の色
- **スライドの枚数・順番・自動切替の秒数・アニメーションの時刻は変えない**でください。ナレーションとの合わせ（mux）がずれます。変えたいときは台本を直して `--from deck` から作り直します
- 台本から作り直すと、PowerPoint での直しは消えます
- interactive では、.pptx の見た目の直しは映像に出ません（映像は場面の指定から描く）。.pptx は PowerPoint で直したい人のために残します

## Windows 以外・PowerPoint の無い PC で作ったとき

slides では、Windows 以外では .pptx まで作って止まり（終了コード 0）、書き出しの手順を表示します。Windows で同じ出力フォルダを使い、`--from export` で続けます。
PowerPoint を使わずに MP4 まで作るなら、`--render-mode interactive` で作り直します（上の節）。

## AI に任せること

- `erkit make` の表示と `run.json` を読み、失敗した段の原因と、続きから作るコマンドを人に示す
- interactive なら `checks\検証結果.md` を読み、要確認の行の原因（場面の指定・字幕）と直し方を示す
- `erkit voice review` の `review.tsv` を読み、印の付いた文から読み辞書に足す語を提案する（足すかは人が決める。耳で確かめるのは人）
- できた MP4 は人が見て確かめる
