# よくある失敗

まず `erkit doctor` を実行して、`NG` の行と `→` の入れ方を見てください。

## PowerShell

### スクリプトを実行できない（実行ポリシー）

`.\.venv\Scripts\Activate.ps1` や `.\erkit.ps1` で「このシステムではスクリプトの実行が無効になっている」と出るとき。
このウィンドウだけ許します（管理者の権限は要りません。ウィンドウを閉じると元に戻ります）。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

導入スクリプトは `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1` で実行します。

### `<` や `>` を含むコマンドがエラーになる

手順書の `<日付>` や `<名前>` は「ここに実際の値を入れる」という意味の書き方です。PowerShell では `<` と `>` が記号（リダイレクト）として扱われるので、**そのまま打たず、実際の値に置き換えます**。
出力フォルダのように名前が分からないものは、コマンドで求めます。

```powershell
$d = Get-ChildItem "$env:USERPROFILE\ExplainerReelKit\output" -Directory -Filter "*_u-value*" | Sort-Object LastWriteTime | Select-Object -Last 1
Invoke-Item $d.FullName
```

### 失敗したのに次のコマンドが動いてしまう

前のコマンドが成功したときだけ次を実行するには、終了コードで区切ります。

```powershell
erkit check samples\u-value\u-value.storyboard.md
if ($LASTEXITCODE -eq 0) { erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app }
```

### `erkit` が見つからない

仮想環境を有効にしていません。キットのフォルダで `.\.venv\Scripts\Activate.ps1` を実行するか、`.\erkit.ps1 doctor` のように `.\erkit.ps1` から呼びます。`.venv` が無ければ `install.ps1` をもう一度実行します。

## ffmpeg

`ffmpeg / ffprobe` が `NG` のとき:

1. `winget install Gyan.FFmpeg` で入れる
2. **PowerShell を開き直す**（PATH は開いた時点のものが使われます）
3. `ffmpeg -version` が表示されるか確かめ、もう一度 `erkit doctor`

## 音声合成エンジン（AivisSpeech）

| 表示 | すること |
|---|---|
| `ENGINE_CONNECTION_FAILED`（接続できない） | AivisSpeech を起動する。起動直後は準備に少し時間がかかるので、数十秒待ってから `erkit voice list` |
| 既定の声が無い | AivisSpeech の画面で声を入れるか、`erkit voice list` で選んだ style id を `config\kit.yaml` の `voice.speaker` に書く |
| 上書きを止めた（終了コード 3） | ナレーションを書き換えた後。`--force` を付けて作り直す |
| 社外秘の台本でエンジンの URL がこの PC の外 | エンジンをこの PC で動かす（`http://127.0.0.1:10101`）。区分を下げて回避しない |

## ブラウザ（撮影・説明図）

| 症状 | すること |
|---|---|
| Chromium を起動できない・入れられない（社内のネットワークなど） | Windows 標準の Edge を使う: コマンドに `--channel msedge` を付ける（`erkit doctor --channel msedge` で確かめる） |
| 説明図のシーンが失敗し「外の URL」と出る | HTML から Web フォント・CDN・外の画像を外す（ネットワークを止めて描くため） |
| mark が見つからない・小さすぎる | 名前の書き間違い、非表示の要素、8px 未満。指す要素をカード全体などにする |
| 撮影でセレクタが 1 つに決まらない | ページに `data-testid` を付ける、または記録モード（`erkit record`）で作り直す |
| 社外秘の台本で撮影が止まる | 撮る URL がこの PC の外。`--serve` かこの PC で起動したアプリを撮る |

## PowerPoint（書き出し）

- PowerPoint のデスクトップ版が要ります（Web 版・ストア版の一部では COM が使えません）。`erkit doctor` の PowerPoint の行で確かめます
- 書き出しの間は PowerPoint を触らないでください。開いたままのダイアログ（ライセンスの確認など）があると止まります。一度 PowerPoint を手で起動して閉じてから、もう一度試します
- 時間切れで止まったら、`--from export` で続きから作り直します

## 出力先を変える

既定の出力先はユーザーのフォルダの `ExplainerReelKit\output`、撮影素材は `ExplainerReelKit\captures` です。容量の大きいドライブに移すときは、環境変数か設定で変えます。

```powershell
$env:ERKIT_OUTPUT_ROOT = "$env:USERPROFILE\Videos\ExplainerReelKit\output"
$env:ERKIT_CAPTURES_ROOT = "$env:USERPROFILE\Videos\ExplainerReelKit\captures"
erkit doctor
```

- `$env:…` はこのウィンドウの間だけ有効です。ずっと使うなら `config\kit.yaml` の `output_root`・`captures_root` に書きます
- 優先の順: コマンドの引数（`--output-root`・`--captures-root`）＞ 環境変数 ＞ `config\kit.yaml` ＞ 既定

## それでも分からないとき

`erkit doctor --json` の結果と、失敗したコマンドの表示、`run.json` を AI に貼って原因を聞きます（社外秘の台本なら、この PC の中で動く AI に）。
