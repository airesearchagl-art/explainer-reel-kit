# 7. 書き出し

## MP4 まで作る

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

## 途中で止まったとき（続きから）

段が失敗すると、「直したら、そこから」のコマンドが表示され、`run.json` の `resume` にも残ります。
原因を直したら、その段から作り直します。`--out-dir` を省くと、この台本の最後の実行を続けます。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --from voice
```

`--from` に書ける段: `capture` / `diagram` / `assets` / `voice` / `deck` / `export` / `mux`（それより前の段が前回うまく終わっているときだけ）。

ナレーションを書き換えた後は、変わったシーンの WAV を作り直すため `--force` を付けます（付けないと、上書きせずに止まります）。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --from voice --force
```

## PowerPoint で直してから書き出し直す

キットが作った .pptx を PowerPoint で直し、同じ名前で保存してから、書き出しの段から作り直せます。

```powershell
erkit make samples\u-value\u-value.storyboard.md --from export
```

- 直してよいもの: 文字の言い回し・位置・大きさ、図形の色
- **スライドの枚数・順番・自動切替の秒数・アニメーションの時刻は変えない**でください。ナレーションとの合わせ（mux）がずれます。変えたいときは台本を直して `--from deck` から作り直します
- 台本から作り直すと、PowerPoint での直しは消えます

## Windows 以外で作ったとき

Windows 以外では .pptx まで作って止まり（終了コード 0）、書き出しの手順を表示します。Windows で同じ出力フォルダを使い、`--from export` で続けます。

## AI に任せること

- `erkit make` の表示と `run.json` を読み、失敗した段の原因と、続きから作るコマンドを人に示す
- できた MP4 は人が見て確かめる
