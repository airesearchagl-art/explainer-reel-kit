# explainer-reel-kit — GitHub Copilot（エージェント）への決まり

このリポジトリで説明動画の台本・説明図を書くときの、GitHub Copilot 向けの入口です。
決まりの本体は [`AGENTS.md`](../AGENTS.md) です。**最初に `AGENTS.md` を読み**、その手順（[docs/guide/](../docs/guide/README.md)）に従ってください。
会社の PC での準備と進め方は [docs/guide/copilot.md](../docs/guide/copilot.md) にあります。

## あなたの id

**あなたの id は `github-copilot`** です。社内で認められた AI の許可リスト（`config/approved_ai.yaml`）で、この id を探します。

## 社外秘（confidential）の台本・資料

- 台本の区分は `confidentiality`。書いていない・読めない台本、区分がまだ決まっていない題材は `confidential` として扱います
- 区分が決まるまで、資料を読まない・開かない
- `confidential` のとき、`config/approved_ai.yaml` を読み、次の項目があるかを確かめます

  ```yaml
  - id: github-copilot
    kind: agent
    allows: [confidential]
  ```

  - **無い**（ファイルが無い・`approved: []` のまま・`kind` が `agent` でない・`allows` に `confidential` が無い）とき:
    **confidential の台本・資料を開かず、読まず、止まって**人に伝えます（「許可リストに github-copilot が無いので、社外秘の資料は扱えません。所属先の規程を確かめて、人が config/approved_ai.yaml に書いてください」）
  - **ある**とき: 進めてかまいません。最初に、項目の `name`・`approved_on`・`basis` を人に伝えます
  - ファイルを開けないとき（`.gitignore` で外してあるため見えないなど）は、人に `erkit doctor` を実行してもらい、「社内で認められた AI（許可リスト）」の行で確かめます。確かめられないあいだは、無いものとして止まります
- 載っていても、守ること:
  - **許可リストを書き換えない**（足す・直す・消す・コメントを外す、のどれもしない。書くのは人だけ）
  - **区分を下げない**（`confidential` → `general` に変えるのは人だけ。上げるのはよい）
  - **confidential の台本・資料を、公開のリポジトリへ push しない**。キットを取り込んだ元（公開の `airesearchagl-art/explainer-reel-kit`、`upstream` などの名前のリモート）へは push しない。push してよいのは、人が決めた会社の非公開リポジトリ（`origin`）だけで、それも人が頼んだときだけ
  - キットの区分の確かめ（撮影・説明図・ナレーション・通し生成は、confidential ならこの PC の中だけ）を緩める変更をしない。`src/` は変えない
  - 資料の中身をそのまま台本のコメントやファイルに写さない（必要な数値・事実だけを、出典と一緒に書く）

## 作業の決まり（AGENTS.md と同じ）

- 区分を決める → 聞き取り → 見る人 → 構成（台本を書く前に人に見せる）→ 台本 → `erkit check` が通るまで直す
- 台本は `reels/<台本の id>/` に置く（`reels/` は `.gitignore` で外してある）
- 画面を捏造しない（説明図は `説明用再構成図`）。赤枠・矢印は座標ではなく mark の名前で指す
- 数値・事実には出典を付ける。分からないことは人に聞き、作らない
- MP4・WAV・.pptx・撮影画像・説明図の PNG を commit しない。パスワード・トークン・個人の情報を書かない
- コマンドは VS Code のターミナル（PowerShell）で、仮想環境を有効にしてから `erkit …` を実行する。結果を読んで直す
