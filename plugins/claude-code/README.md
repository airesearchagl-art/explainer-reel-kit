# Claude Code のプラグイン（explainer-reel-kit）

キットを Claude Code で使うためのプラグインです。題材の聞き取りから MP4 まで、キットの手順書（`docs/guide/`）の順に Claude Code が人と対話して進め、`erkit` を呼びます。

プラグインは**キットの `erkit` を呼ぶ薄い層**です。動画を作る処理・台本の仕様・設定はすべてキットの本体にあり、プラグインは持ちません。

## 入れ方

1. キットを入れる（[docs/guide/00-setup.md](../../docs/guide/00-setup.md)。`install.ps1` と `erkit doctor`）
2. キットのフォルダで Claude Code を開く

```powershell
cd $env:USERPROFILE\explainer-reel-kit
claude
```

3. Claude Code の中で、マーケットプレイスを追加してプラグインを入れる

```text
/plugin marketplace add airesearchagl-art/explainer-reel-kit
/plugin install explainer-reel-kit@explainer-reel-kit
```

（`@` の前がプラグインの名前、後がマーケットプレイスの名前です。どちらも `explainer-reel-kit`）

4. 入ったか確かめる: `/plugin` を開いて「Installed」に `explainer-reel-kit` があること

更新するとき: キットのフォルダで `git pull` をしてから、Claude Code で `/plugin marketplace update explainer-reel-kit`。プラグインの版はキットの版と同じにしてあり、違うとスキルが知らせます。

## 使い方

| 入口 | すること |
|---|---|
| 「説明動画を作りたい」と頼む | スキル `make-explainer` が働き、手順書の順に進める（区分 → 聞き取り → 見る人 → 構成 → 台本 → 説明図・撮影 → 確認 → 書き出し） |
| `/explainer-reel-kit:explainer-new` | 区分を確かめ、`reels/` に台本のフォルダとひな形を作る（例 `/explainer-reel-kit:explainer-new glass-choice`） |
| `/explainer-reel-kit:explainer-check` | `erkit doctor` と `erkit check` を実行して読み、足りないものと台本の直す所を示す（例 `/explainer-reel-kit:explainer-check reels/glass-choice/glass-choice.storyboard.md`） |
| `/explainer-reel-kit:explainer-make` | `--dry-run` で段の順番を見せ、人がよいと言ってから MP4 まで作る。止まったら続きから作るコマンドを示す |

コマンドもスキルも、名前の前にプラグインの名前 `explainer-reel-kit:` が付きます（例 `/explainer-reel-kit:explainer-new`）。入力欄で `/explainer-reel-kit` と打つと候補に出ます。スキル（`make-explainer` など）は、頼んだ内容に合わせて Claude Code が自分で使うので、名前を打たなくてかまいません。

スキル:

| スキル | 使いどころ |
|---|---|
| `make-explainer` | 全体の進め方 |
| `storyboard` | 台本を書く・直す、`erkit check` を通す |
| `diagram` | 説明図の HTML を書く、`erkit diagram`、確認画像 |
| `web-capture` | 操作定義を書く・記録モード、`erkit capture`、確認画像 |

## 社外秘の材料

最初に、材料に社外秘（所属先の外に出せない情報）が含まれるかを聞きます。**含む・分からないときは、資料を受け取らずに止まります**。Claude Code はクラウドの AI で動くためです。
その場合は、この PC の中で動く AI（LM Studio・Ollama など）に [prompts/](../../prompts/README.md) を貼って進めてください（[confidentiality.md](../../docs/guide/confidentiality.md)）。区分を下げるのは人だけです。

## できないこと

- 動画の公開（動画サイトへのアップロード）、外部のサービスとの連携
- ソフトの導入（ffmpeg・AivisSpeech・PowerPoint・Python は人が入れる。プラグインは入れ方を伝えるだけ）
- 社外秘の材料での台本づくり（上のとおり止まる）
- 画面を見て判断すること（確認画像・スライド・MP4 は人が見る）
- フック（hooks）は使っていません。どの AI でも同じ動きにするためです

Claude Code 以外の AI は、キットの [AGENTS.md](../../AGENTS.md)（エージェント）か [prompts/](../../prompts/README.md)（チャットだけの AI）を使います。中身は同じ手順書です。
