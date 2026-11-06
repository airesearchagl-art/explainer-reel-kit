# prompts — チャットだけの AI に貼る指示文

ファイルを読めない・コマンドを実行できない AI（ブラウザのチャット、手元の LLM のチャット画面など）で台本まで進めるための指示文です。
エージェント（Claude Code・Codex・Cursor など）を使うなら、これは要りません。リポジトリの [AGENTS.md](../AGENTS.md) を読ませてください。

## 使い方

| 順 | 指示文 | 貼るもの | AI が返すもの | 人がすること |
|---|---|---|---|---|
| 1 | [01-intake.md](01-intake.md) | 指示文だけ（資料は区分を決めた後） | 聞き取りのまとめと、見る人（A・B・C）の提案 | 区分を決めて答える。資料を貼る |
| 2 | [02-outline.md](02-outline.md) | 指示文 | 構成の表 | 表を確かめ、直してほしい所を伝える |
| 3 | [03-storyboard.md](03-storyboard.md) | 指示文＋テンプレート＋見本の台本 | 台本（Markdown 1 枚） | ファイルに保存して `erkit check`。エラーが出たら表示を貼る |
| 4 | [04-diagram-html.md](04-diagram-html.md) | 指示文＋共通の CSS のクラス表 | 説明図の HTML（シーンごと） | ファイルに保存して `erkit diagram`。確認画像を見る |

**まとめて進める**（1〜4 の代わり）: [05-batch.md](05-batch.md) に、埋めた答えのひな形（[batch.md](../docs/guide/batch.md)）を続けて貼ると、1 回の返事で台本・説明図の HTML・報告（構成・決めたこと・未確認の数値と事実）が返ります。区分が general でなければ AI は止まります。MP4 は人が報告を見てから作ります。

- 1 つの会話で 1 から順に貼ってください（前の答えを覚えているため）
- AI が書いたものは、必ず人が読んで確かめます。数値・事実は根拠の資料と突き合わせます
- **社外秘を含む・分からない材料は、クラウドの AI に貼らないでください**。この PC の中で動く AI（LM Studio・Ollama など）か、所属先が認めた AI だけに貼ります（[confidentiality.md](../docs/guide/confidentiality.md)）
- 手元の LLM で文脈が足りないときは、3 の「見本の台本」を省き、テンプレートだけ貼ります

## 保存する場所

台本は `reels\<id>\<id>.storyboard.md`、説明図は `reels\<id>\diagrams\s01_….html` のように保存します（[04-storyboard.md](../docs/guide/04-storyboard.md)）。
保存するときの文字コードは UTF-8 です（メモ帳なら「UTF-8」を選ぶ）。
