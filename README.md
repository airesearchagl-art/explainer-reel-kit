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

**開発中（0.1.0）**。いまできるのは台本の検証だけです。導入の手順・通し生成は後の版で入ります。

| できること | 状態 |
|---|---|
| 台本の検証 `erkit check`・JSON への変換 `erkit convert` | できる |
| 説明図・撮影・ナレーション・スライド・書き出し・`erkit make` | これから |
| 導入スクリプト・環境の確認 `erkit doctor` | これから |
| AI との対話の手順（`AGENTS.md`）・Claude Code のプラグイン | これから |

## いま試す（開発者向け）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   / それ以外: source .venv/bin/activate
pip install -e ".[dev]"
erkit check examples/hello-kit.storyboard.md
pytest
```

台本の書き方: [テンプレート](src/explainer_reel_kit/data/templates/storyboard.md)・[台本の仕様](docs/design/storyboard.md)

## 前提（完成時）

- Windows ＋ PowerPoint（デスクトップ版）
- Python 3.10 以上、ffmpeg、AivisSpeech

## ライセンス

MIT（[LICENSE](LICENSE)）。依存しているもののライセンスは [THIRD_PARTY.md](THIRD_PARTY.md)。
