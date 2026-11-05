# 依存しているもののライセンス

このキット（explainer-reel-kit）は MIT ライセンスです（[LICENSE](LICENSE)）。
下の表のものは**キットに同梱していません**。Python のライブラリは pip で入り、外部ソフトは利用者が入れます。
それぞれのライセンス・利用条件は、配布元で確かめてください。

## Python のライブラリ（pip で入る）

| ライブラリ | 用途 | ライセンス | 入る時期 |
|---|---|---|---|
| jsonschema | 台本の検証 | MIT | いまから |
| PyYAML | 台本・設定の読み込み | MIT | いまから |
| python-pptx | .pptx の生成 | MIT | いまから |
| lxml | スライドのアニメーションの XML | BSD-3-Clause | いまから |
| Pillow | 画像の大きさ・確認用の画像 | MIT-CMU（HPND） | いまから |
| Playwright（Python） | Web 画面の撮影・説明図の描画 | Apache-2.0 | 撮影・説明図の段から（必須） |
| pytest | テスト（開発用） | MIT | いまから（`.[dev]`） |

Playwright のブラウザは `python -m playwright install chromium`（Chromium の各ライセンス）で入れるか、Windows の Microsoft Edge を使います。

## 外部ソフト（利用者が入れる）

| ソフト | 用途 | ライセンス・条件 | キットとの関係 |
|---|---|---|---|
| Microsoft PowerPoint（デスクトップ版） | .pptx → 無音の MP4 | 商用ソフト（利用者のライセンス） | 前提。PowerShell から COM で呼ぶ |
| ffmpeg / ffprobe | 音声と映像の合成・長さの測定 | ビルドにより LGPL-2.1 以降 または GPL-2.0 以降 | 別のプロセスとして呼ぶだけ（リンクしない） |
| AivisSpeech Engine（AivisSpeech に同梱） | ナレーションの音声合成 | LGPL-3.0 | 手元の HTTP（既定 `127.0.0.1:10101`）で呼ぶだけ |
| 声のモデル（AIVMX） | ナレーションの声 | モデルごと（ACML 1.0、ACML-NC 1.0、独自の規約など） | 同梱しない。利用者が AivisSpeech の画面から入れる |
| LM Studio / Ollama（任意） | 手元の LLM（社外秘の資料のたたき台など） | それぞれの規約、モデルごとのライセンス | OpenAI 互換の HTTP で呼ぶだけ |

## 声のクレジット表記

- 声のモデルを選んだら、そのモデルのページでライセンスを確かめてください
  - ACML 1.0: 商用も可、クレジット表記は任意
  - ACML-NC 1.0: 非営利の利用だけ
  - 独自の規約: その条件（クレジット必須のものもあります）
- どのライセンスでも、声の本人・公式と誤認させる使い方などは禁止されています
- クレジットが必要な声を使うときは、`config/kit.yaml` の `voice.credits` に声と文言を書き、`erkit deck --credit <文言>` で動画の最後のスライドに「ナレーション音声: <文言>」を出します（通し生成では自動にする予定）。動画の公開先の説明欄にも書いてください
