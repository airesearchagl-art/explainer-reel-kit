# explainer-reel-kit

題材から、AI との対話で台本を作り、ナレーション付きの説明動画（MP4）にするためのキットです。

```text
題材 → 台本（AI との対話）→ 説明図（コードで描く）・Web 画面の撮影 → ナレーション → スライド（.pptx）→ MP4
```

- 台本は Markdown 1 枚。シーンごとに見出し・画像・ナレーションを書きます
- 動画だけでなく、PowerPoint で直せる .pptx も残ります
- 手元の PC で動きます。有料のサービスや API キーは要りません（音声は AivisSpeech、書き出しは PowerPoint）
- 対話はふだん使う AI（Claude Code・Codex・Cursor・Copilot・手元の LLM など）で進めます
- 社外秘を含む台本は、AI への送信・撮影・音声合成をこの PC の中だけに限ります（台本の `confidentiality`）

## 状態

**開発中（0.1.0）**。いまできるのは、台本の検証・説明図・Web 画面の撮影・ナレーション・スライドまでです。動画の書き出しと導入の手順は後の版で入ります。

| できること | 状態 |
|---|---|
| 台本の検証 `erkit check`・JSON への変換 `erkit convert` | できる |
| ナレーション `erkit voice list / synth / kana`（[仕様](docs/design/narration.md)） | できる（AivisSpeech が要る） |
| スライド `erkit deck`（[仕様](docs/design/recipes.md)） | できる |
| 説明図 `erkit diagram`（HTML → PNG ＋ 注釈位置）| できる（[書き方](docs/design/diagram.md)） |
| Web 画面の撮影 `erkit capture`・操作の記録 `erkit record` | できる（[書き方](docs/design/capture-web.md)） |
| 書き出し・`erkit make` | これから |
| 導入スクリプト・環境の確認 `erkit doctor` | これから |
| AI との対話の手順（`AGENTS.md`）・Claude Code のプラグイン | これから |

## いま試す（開発者向け）

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

設定は `config/kit.example.yaml` を `config/kit.yaml` に写して書きます（出力先・声・読み辞書・声のクレジット）。

台本の書き方: [テンプレート](src/explainer_reel_kit/data/templates/storyboard.md)・[台本の仕様](docs/design/storyboard.md)・[注釈位置の仕様](docs/design/marks.md)

## 前提（完成時）

- Windows ＋ PowerPoint（デスクトップ版）
- Python 3.10 以上、ffmpeg、AivisSpeech

## ライセンス

MIT（[LICENSE](LICENSE)）。依存しているもののライセンスは [THIRD_PARTY.md](THIRD_PARTY.md)。
