# 0. 準備（導入と環境の確認）

## 要るもの

| もの | 用途 | 入れ方 |
|---|---|---|
| Windows 10 / 11 | — | — |
| PowerPoint（デスクトップ版） | スライドを MP4 に書き出す | 利用者のライセンスで |
| Python 3.10 以上 | キットの本体 | `winget install Python.Python.3.12` か python.org |
| Git（任意） | キットを取ってくる | `winget install Git.Git`（ZIP でダウンロードしてもよい） |
| ffmpeg | ナレーションを動画に重ねる | `winget install Gyan.FFmpeg`（入れたら PowerShell を開き直す） |
| AivisSpeech | ナレーションの声 | 配布元のページから入れて起動する |

キットの導入スクリプトは、Python のライブラリとブラウザ（撮影・説明図用）だけを入れます。**ffmpeg・AivisSpeech・PowerPoint は自動では入れません**（入れるかどうかは利用者が決めます）。管理者の権限は要りません。

## 人が打つコマンド

```powershell
cd $env:USERPROFILE
git clone https://github.com/airesearchagl-art/explainer-reel-kit.git
cd explainer-reel-kit
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` がすること:

1. Python 3.10 以上を探す（`py -3`・`python`）。無ければ入れ方を表示して止まる
2. `.venv`（仮想環境）を作り、キットとライブラリを入れる
3. 撮影・説明図のブラウザ（Chromium）を入れる。失敗しても、Windows 標準の Edge を使う方法を表示して続ける
4. `config\*.example.yaml` を `config\*.yaml` に写す（もうあれば上書きしない）
5. `erkit doctor` を実行して、足りないものを表示する

オプション: `-SkipBrowser`（ブラウザを入れない）、`-SkipDoctor`（最後の確認をしない）、`-Python`（使う python.exe のパスを続けて書く）。

## 環境の確認（erkit doctor）

導入の後や、何かが動かないときに実行します。

```powershell
cd $env:USERPROFILE\explainer-reel-kit
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
erkit doctor
```

`NG` の行の下に `→` で入れ方が出ます。全部 `OK`（または `--` の対象外）になれば、MP4 まで作れます。
Chromium を入れていないときは `erkit doctor --channel msedge` で Edge を確かめます。

## 5 分で試す（サンプルで MP4）

AivisSpeech を起動しておいてから:

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app
if ($LASTEXITCODE -eq 0) { Invoke-Item "$env:USERPROFILE\ExplainerReelKit\output" }
```

出力先のフォルダ（`<日付>_u-value`）の中に `u_value.mp4` と `u_value.pptx` ができます。

## 声のライセンスを確かめる

既定の声は AivisSpeech の「ほのか / ノーマル」（style id `808373280`）です。入っていなければ `erkit doctor` が入っている声の一覧を出して止まります。

1. 使う声のモデルのページで、ライセンスを確かめます（例: ACML 1.0 は商用も可・クレジットの表記は任意、ACML-NC 1.0 は非営利だけ。独自の規約ならその条件）
2. どのライセンスでも、本人や公式と誤認させる使い方・誹謗中傷などは禁止です
3. 別の声を使うときは `erkit voice list` で style id を調べ、`config\kit.yaml` の `voice.speaker` を変えます
4. クレジットの表記が要る声なら、`config\kit.yaml` の `voice.credits` に書きます。最後のスライドに「ナレーション音声: …」と出ます。動画を公開するなら、公開先の説明にも書きます

## Claude Code のプラグイン（任意）

Claude Code を使うなら、プラグインを入れると、手順書の順に進めるスキルと `/explainer-reel-kit:explainer-new`・`/explainer-reel-kit:explainer-check`・`/explainer-reel-kit:explainer-make` が使えます。キットのフォルダで Claude Code を開き（`cd $env:USERPROFILE\explainer-reel-kit` の後に `claude`）、Claude Code の中で `/plugin marketplace add airesearchagl-art/explainer-reel-kit` → `/plugin install explainer-reel-kit@explainer-reel-kit` と打ちます。詳しくは [プラグインの説明](../../plugins/claude-code/README.md)。

## AI に任せること

この段は人が行います。エージェントを使う場合は、`erkit doctor` を実行させて結果を読ませ、足りないものの入れ方を説明させるところまでにします（ソフトを入れるかは人が決めます）。
