# config

利用者が編集する設定の置き場所です。`kit.example.yaml` を `kit.yaml` に写して使います（`kit.yaml` は commit しません）。

| 項目 | 内容 |
|---|---|
| `output_root` | 出力先のルート（空ならユーザーのフォルダの `ExplainerReelKit\output`） |
| `voice.engine` / `voice.url` | 音声合成エンジン（既定 AivisSpeech、`http://127.0.0.1:10101`） |
| `voice.speaker` | 既定の声（ほのか / ノーマル） |
| `voice.dictionaries` | 読み辞書（既定は使わない） |
| `voice.credits` | クレジットの表記が必要な声 |
