"""思考するモデル: 思考と答えを分ける（答えだけを使う）。"""
from __future__ import annotations

import json
import random

import pytest

from explainer_reel_kit.llm.client import LLMClient, ThinkSplitter, split_think
from explainer_reel_kit.llm.config import Endpoint
from explainer_reel_kit.llm.readings import ReadingCheck, ask_readings

THOUGHT = "まず要件を整理する。冒頭、操作4つ、まとめ。事実だけを書く。" * 3
ANSWER = "冒頭: サンプルは窓の熱の逃げ方を計算する Web ページです。" * 3
GOOD_JSON = json.dumps({"title": "t", "scenes": [{"heading": f"h{i}", "narration": "ナレーションです。"} for i in range(3)]},
                       ensure_ascii=False)


def client_for(fake, timeout=5.0, model="m"):
    return LLMClient(Endpoint("fake", fake.url, model, timeout))


def thinking_server(fake, field="reasoning_content", answer=ANSWER, json_answer=GOOD_JSON):
    fake.think = lambda body: THOUGHT
    fake.reasoning_field = field
    fake.reply = lambda body: answer if body.get("stream") else json_answer


# -- splitting ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, reasoning, body",
    [
        ("<think>考える</think>答え", "考える", "答え"),
        ("  <think>\n考える\n</think>\n\n答え  ", "考える", "答え"),
        ("考えている…</think>答え", "考えている…", "答え"),  # template opened <think> in the prompt
        ("<think>途中で切れた", "途中で切れた", ""),  # cut off by max_tokens
        ("答えだけ", "", "答えだけ"),
        ("前置き<think>考え</think>答え", "考え", "前置き答え"),
    ],
)
def test_split_think(text, reasoning, body):
    assert split_think(text) == (reasoning, body)


@pytest.mark.parametrize("text", ["<think>考える</think>答え", "考えている…</think>答え", "<think>途中で切れた",
                                  "答えだけ<think>a</think>b<think>c</think>d"])
def test_think_splitter_any_chunking_matches_whole(text):
    rng = random.Random(7)
    for _ in range(30):
        splitter = ThinkSplitter()
        i = 0
        while i < len(text):
            step = rng.randint(1, 5)
            splitter.feed(text[i : i + step])
            i += step
        splitter.close()
        assert (splitter.reasoning.strip(), splitter.content.strip()) == split_think(text)


# -- client --------------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning", "inline"])
def test_stream_separates_thinking(fake_llm, field):
    thinking_server(fake_llm, field)
    fake_llm.chunk_delay = 0.005
    result = client_for(fake_llm).chat_stream([{"role": "user", "content": "x"}], model="m")
    assert result.content == ANSWER and result.reasoning == THOUGHT
    assert result.reasoning_source == ("<think>" if field == "inline" else field)
    assert result.first_reasoning_sec is not None and result.first_content_sec is not None
    assert result.first_reasoning_sec < result.first_content_sec <= result.total_sec
    assert result.first_token_sec == result.first_reasoning_sec
    assert result.content_chunks > 0 and result.reasoning_chunks > 0
    assert result.ttft_sec == result.first_content_sec  # 答えまでの時間


def test_stream_without_thinking(fake_llm):
    fake_llm.reply = lambda body: ANSWER
    result = client_for(fake_llm).chat_stream([{"role": "user", "content": "x"}], model="m")
    assert result.reasoning == "" and result.first_reasoning_sec is None and result.reasoning_source is None
    assert result.first_token_sec == result.first_content_sec


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning", "inline"])
def test_chat_separates_thinking(fake_llm, field):
    thinking_server(fake_llm, field)
    answer = client_for(fake_llm).chat([{"role": "user", "content": "x"}], model="m")
    assert answer.content == GOOD_JSON and answer.reasoning == THOUGHT


def test_chat_null_content_is_empty_answer(fake_llm):
    fake_llm.raw_body = json.dumps({"choices": [{"message": {"content": None, "reasoning_content": "考え"},
                                                 "finish_reason": "length"}]}).encode()
    answer = client_for(fake_llm).chat([{"role": "user", "content": "x"}], model="m")
    assert answer.content == "" and answer.reasoning == "考え" and answer.finish_reason == "length"


# -- readings with thinking models ------------------------------------------------------------------------


def test_readings_ignore_thinking_and_report_empty_answers(fake_llm):
    checks = [ReadingCheck("建具", "タテグ")]
    fake_llm.think = lambda body: "建具はタテグと読む。"
    fake_llm.reply = lambda body: json.dumps({"readings": [{"term": "建具", "reading": "タテグ"}]}, ensure_ascii=False)
    readings, warnings = ask_readings(client_for(fake_llm), checks, model="m")
    assert readings == {"建具": "タテグ"} and warnings == []
    assert fake_llm.requests[-1]["body"]["max_tokens"] >= 2048
    fake_llm.reply = lambda body: ""
    fake_llm.finish_reason = "length"
    readings, warnings = ask_readings(client_for(fake_llm), checks, model="m")
    assert readings == {} and "本文が空" in warnings[0] and "上限" in warnings[0]
