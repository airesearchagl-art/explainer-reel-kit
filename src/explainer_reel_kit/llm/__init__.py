"""手元の LLM（任意の段）: 台本の下書き（``erkit draft``）・読みの候補（``erkit voice suggest``）・接続の確認（``erkit llm check``）。

OpenAI 互換の API（LM Studio・Ollama など）を標準ライブラリだけで呼ぶ。社外秘の区分（未記入も）は、
この PC（127.0.0.1 / ::1 / localhost）の LLM にだけ送る。設計は docs/design/llm.md。
"""
