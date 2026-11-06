# 手順書

題材から説明動画（MP4）までを、AI と対話しながら進める手順です。サンプル題材 [samples/u-value/](../../samples/u-value/README.md)（窓の断熱性能の見方）を例に使います。

| # | 手順書 | すること |
|---|---|---|
| 0 | [00-setup.md](00-setup.md) | 導入（`install.ps1`・`erkit doctor`）、声のライセンスの確認 |
| 1 | [01-intake.md](01-intake.md) | 題材の聞き取り（**最初に区分を決める**） |
| 2 | [02-audience.md](02-audience.md) | 見る人（A・B・C）に合わせた言葉と深さ |
| 3 | [03-outline.md](03-outline.md) | 構成（intro・シーン・outro）を決めて人に見せる |
| 4 | [04-storyboard.md](04-storyboard.md) | 台本を書き、`erkit check` を通す |
| 5 | [05-visuals.md](05-visuals.md) | 説明図（HTML）と Web 画面の撮影 |
| 6 | [06-review.md](06-review.md) | 試作・スライドの確認・読みの確認 |
| 7 | [07-export.md](07-export.md) | MP4 に書き出す・続きから作り直す |
| — | [batch.md](batch.md) | **まとめて進める**: 答えのひな形を先に渡し、1 回で台本と説明図まで（報告で確かめる） |
| — | [confidentiality.md](confidentiality.md) | 社外秘の区分と、AI の使い分け |
| — | [troubleshooting.md](troubleshooting.md) | よくある失敗 |
| — | [../../prompts/](../../prompts/README.md) | チャットだけの AI に貼る指示文 |

## AI の種類による進め方の違い

| 使う AI | 進め方 |
|---|---|
| ファイルを読み書きでき、コマンドを実行できるエージェント（Claude Code・Codex・Cursor など） | リポジトリを開いて「`AGENTS.md` を読んで、説明動画を作りたい」と頼みます。エージェントが手順書を読み、台本を書き、`erkit` を呼びます |
| チャットだけの AI（ブラウザのチャット・手元の LLM のチャット画面） | [prompts/](../../prompts/README.md) の指示文を順に貼ります。AI が書いた台本・HTML を人がファイルに保存し、`erkit` も人が打ちます。エラーが出たら、その表示を AI に貼って直してもらいます |

各手順書は「**AI に任せること**」と「**人が打つコマンド**」を分けて書いています。

## 2 つの進め方

- **段ごと**: 0〜7 の順に、各段の終わりで人が確かめます。初めて使うとき・題材が固まっていないときに
- **まとめて**: 聞き取りの答えをひな形に埋めて先に渡し、AI が 1 回で台本と説明図まで進めて報告します（[batch.md](batch.md)）。区分の約束と、MP4 の前の人の確認は同じです

## コマンドの前に（毎回）

PowerShell を開いたら、まずキットのフォルダに移り、このウィンドウだけスクリプトの実行を許して、仮想環境を有効にします。

```powershell
cd $env:USERPROFILE\explainer-reel-kit
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

この後は `erkit doctor` のように `erkit` から打てます（有効にしない場合は、`.\erkit.ps1 doctor` のように `.\erkit.ps1` を前に付けても同じです）。
キットを別の場所に置いたときは、1 行目をその場所に変えてください。

## 自分の題材のフォルダ

サンプルのフォルダを写して、中身を置き換えるのがいちばん早い方法です（[04-storyboard.md](04-storyboard.md)）。
台本・説明図の HTML・撮るページ・操作定義を 1 つのフォルダにまとめます。

台本の仕様は [docs/design/](../design/) にあります（[台本](../design/storyboard.md)・[レシピ](../design/recipes.md)・[説明図](../design/diagram.md)・[撮影](../design/capture-web.md)・[注釈位置](../design/marks.md)・[ナレーション](../design/narration.md)・[通し生成](../design/make.md)）。
