# explainer-reel-kit

題材から、AI との対話で台本を作り、ナレーション付きの説明動画（MP4）にするためのキットです。

```text
題材 → 台本（AI との対話）→ 説明図（コードで描く）・Web 画面の撮影 → ナレーション → スライド（.pptx）→ MP4
```

- 台本は Markdown 1 枚。シーンごとに見出し・画像・ナレーションを書きます
- 動画だけでなく、PowerPoint で直せる .pptx も残ります
- 手元の PC で動きます。有料のサービスや API キーは要りません（音声は AivisSpeech、書き出しは PowerPoint）
- 対話はふだん使う AI（Claude Code・Codex・Cursor・Copilot・手元の LLM など）で進めます
- 社外秘を含む台本は、撮影・音声合成をこの PC の中だけに限ります（台本の `confidentiality`）

## 5 分で試す（Windows）

要るもの: Windows ＋ PowerPoint（デスクトップ版）、Python 3.10 以上、ffmpeg、AivisSpeech（起動しておく）。

```powershell
cd $env:USERPROFILE
git clone https://github.com/airesearchagl-art/explainer-reel-kit.git
cd explainer-reel-kit
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` は仮想環境（`.venv`）・キット・撮影用のブラウザを入れ、最後に `erkit doctor` で足りないものを表示します。
**ffmpeg・AivisSpeech・PowerPoint は自動では入れません**（入れ方を表示するだけ。管理者の権限も要りません）。

足りないものを入れたら、サンプル題材で MP4 を作ります。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
erkit doctor
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app
if ($LASTEXITCODE -eq 0) { Invoke-Item "$env:USERPROFILE\ExplainerReelKit\output" }
```

出力先のフォルダ（`<日付>_u-value`）に `u_value.mp4` と、PowerPoint で直せる `u_value.pptx` ができます。
詰まったら [よくある失敗](docs/guide/troubleshooting.md) を見てください。

## 自分の題材で作る（AI と対話する）

ふだん使う AI で進めます。

| 使う AI | 始め方 |
|---|---|
| エージェント（Claude Code・Codex・Cursor・Copilot など） | このフォルダを開いて「`AGENTS.md` を読んで、説明動画を作りたい」と頼む |
| チャットだけの AI・手元の LLM のチャット | [prompts/](prompts/README.md) の指示文を順に貼る。コマンドは人が打つ |

手順の全体は [手順書](docs/guide/README.md)（聞き取り → 見る人 → 構成 → 台本 → 説明図・撮影 → 確認 → 書き出し）にあります。

**最初に区分を決めます。** 材料に社外秘（所属先の外に出せない情報）が含まれるか・分からないなら、台本の `confidentiality` は `confidential` です。
このときキットは撮影・音声合成をこの PC の中だけに限りますが、**対話に使う AI まではキットでは止められません**。
この PC の中で動く AI か、所属先が認めた AI だけを使ってください（[区分の考え方](docs/guide/confidentiality.md)）。

## 何ができて、何をしないか

| できること | コマンド |
|---|---|
| 台本の検証・JSON への変換 | `erkit check`・`erkit convert`（[仕様](docs/design/storyboard.md)） |
| 説明図（HTML → PNG ＋ 注釈位置） | `erkit diagram`（[書き方](docs/design/diagram.md)） |
| Web 画面の撮影・操作の記録 | `erkit capture`・`erkit record`（[書き方](docs/design/capture-web.md)） |
| ナレーション（AivisSpeech） | `erkit voice list`・`erkit voice synth`・`erkit voice kana`（[仕様](docs/design/narration.md)） |
| スライド（アニメーション付きの .pptx） | `erkit deck`（[仕様](docs/design/recipes.md)） |
| 通し生成（撮影 → 説明図 → ナレーション → スライド → 書き出し → 音声の合成） | `erkit make`（[仕様](docs/design/make.md)。書き出しは Windows ＋ PowerPoint） |
| 環境の確認 | `erkit doctor` |

しないこと:

- 動画の公開（動画サイトへのアップロード）や、外部のサービスとの連携
- クラウドの AI の呼び出し（台本づくりの対話は、利用者の AI が受け持ちます。API キーは要りません）
- ffmpeg・AivisSpeech・PowerPoint・声のモデルの同梱や自動の導入
- Claude Code のプラグインは後の版で入ります（`plugins/claude-code/`）

## 段ごとに試す（開発者向け）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   / それ以外: source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium      # 説明図・撮影のブラウザ（Windows なら代わりに --channel msedge でも可）
erkit check examples/hello-kit.storyboard.md
erkit diagram examples/hello-kit.storyboard.md --out output --overlay output/check-diagram.png
erkit capture examples/hello-kit.storyboard.md --serve examples/hello-page --out output --overlay output/check-capture.png
pytest

# AivisSpeech を起動しておく（既定 http://127.0.0.1:10101）
erkit voice list
erkit voice synth examples/hello-kit.storyboard.md --out-dir out/voice
erkit deck examples/hello-kit.storyboard.md --out out/hello_kit.pptx --durations out/voice/durations.json
```

設定は `config/kit.example.yaml` を `config/kit.yaml` に写して書きます（出力先・撮影素材の置き場所・声・読み辞書・声のクレジット）。

台本の書き方: [テンプレート](src/explainer_reel_kit/data/templates/storyboard.md)・[台本の仕様](docs/design/storyboard.md)・[注釈位置の仕様](docs/design/marks.md)

## サンプル題材

[`samples/u-value/`](samples/u-value/) — **窓の断熱性能（U 値）の見方**（建築の一般的な知識、`confidentiality: general`）。
説明図（熱の逃げ方・U 値の意味）と、キットの中の計算ページの撮影（ガラスの種類を選んで熱の損失を比べる）の両方を、1 本の台本で見せます。
計算ページはこの PC だけで配信して撮るので、ネットワークなしで動きます。数値は一般的な目安を範囲で示し、根拠は [SOURCES.md](samples/u-value/SOURCES.md) にあります。

作り方の順番（詳しくは [samples/u-value/README.md](samples/u-value/README.md)）:

```bash
erkit check   samples/u-value/u-value.storyboard.md
erkit diagram samples/u-value/u-value.storyboard.md --out output/u-value
erkit capture samples/u-value/u-value.storyboard.md --serve samples/u-value/app --out output/u-value
erkit deck    samples/u-value/u-value.storyboard.md --assets-root output/u-value --out output/u-value/u_value.pptx
```

## ライセンス

MIT（[LICENSE](LICENSE)）。依存しているもののライセンスは [THIRD_PARTY.md](THIRD_PARTY.md)。
