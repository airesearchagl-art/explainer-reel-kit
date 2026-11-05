from __future__ import annotations

import json
from decimal import Decimal

import pytest

from explainer_reel_kit.narration.errors import (
    EngineError,
    EngineErrorKind,
    InputError,
    OverwriteRefusedError,
)
from explainer_reel_kit.narration.synth import (
    audio_seconds,
    parse_input,
    run_synth,
    slide_seconds,
)
from explainer_reel_kit.narration.textproc import PronunciationDictionary
from explainer_reel_kit.narration.wavutil import read_info

SPEAKER = 888753760
DICT = PronunciationDictionary({"躯体": "クタイ", "天端": "テンバ", "見付け": "ミツケ", "笠木": "カサギ"})


def run(narration, out_dir, client, **kwargs):
    kwargs.setdefault("dictionary", DICT)
    kwargs.setdefault("log", lambda message: None)
    return run_synth(narration, out_dir, client, **kwargs)


def durations(out_dir):
    return json.loads((out_dir / "durations.json").read_text(encoding="utf-8"))


# -- seconds ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "audio, pre, post, expected",
    [
        (Decimal("1"), 0.3, 0.5, 1.8),
        (Decimal("1.001"), 0.3, 0.5, 1.81),  # any remainder rounds UP
        (Decimal("1.0001"), 0, 0, 1.01),
        (Decimal("2.2"), 0.1, 0.2, 2.5),  # no binary-float drift (2.2+0.1+0.2 = 2.5000000000000004 in float)
        (Decimal(44101) / Decimal(44100), 0.3, 0.5, 1.81),
        (Decimal("0"), 0.3, 0.5, 0.8),
    ],
)
def test_slide_seconds_rounds_up_to_centiseconds(audio, pre, post, expected):
    assert slide_seconds(audio, pre, post) == expected


def test_audio_seconds_rounds_to_milliseconds():
    assert audio_seconds(Decimal("1.0004")) == 1.0
    assert audio_seconds(Decimal("1.0005")) == 1.001


# -- input validation ---------------------------------------------------------------


def test_parse_input_defaults(make_input):
    narration = parse_input(make_input())
    assert narration.engine_url is None
    assert (narration.speed, narration.volume) == (1.0, 1.0)
    assert (narration.pre_pause_sec, narration.post_pause_sec) == (0.3, 0.5)
    assert [i.id for i in narration.items] == ["scene-01", "scene-02"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"speaker": "1"},
        {"speaker": -1},
        {"speed": 0.49},
        {"speed": 2.01},
        {"volume": 2.5},
        {"pre_pause_sec": -0.1},
        {"engine_url": "127.0.0.1:10101"},
        {"items": []},
        {"items": [{"id": "../evil", "text": "あ。"}]},
        {"items": [{"id": "a b", "text": "あ。"}]},
        {"items": [{"id": "s1", "text": "   "}]},
        {"items": [{"id": "s1"}]},
        {"items": [{"id": "s1", "text": "あ。", "extra": 1}]},
        {"unknown_key": True},
        {"version": 2},
    ],
)
def test_parse_input_rejects(make_input, overrides):
    with pytest.raises(InputError):
        parse_input(make_input(**overrides))


def test_parse_input_rejects_case_insensitive_duplicate_ids(make_input):
    data = make_input(items=[{"id": "Scene1", "text": "あ。"}, {"id": "scene1", "text": "い。"}])
    with pytest.raises(InputError, match="重複"):
        parse_input(data)


def test_schema_accepts_all_documented_fields(make_input):
    narration = parse_input(
        make_input(
            **{
                "$schema": "../schema/narration-input.schema.json",
                "version": 1,
                "engine_url": "http://192.168.0.10:10101",
                "speed": 1.1,
                "volume": 0.9,
                "pre_pause_sec": 0,
                "post_pause_sec": 1.0,
            }
        )
    )
    assert narration.engine_url == "http://192.168.0.10:10101"
    assert narration.post_pause_sec == 1.0


# -- synth: normal path ---------------------------------------------------------------


def test_generates_wavs_and_durations(tmp_path, client, engine, make_input):
    narration = parse_input(make_input(speed=1.25, volume=0.75))
    doc = run(narration, tmp_path, client)

    assert doc == durations(tmp_path)
    assert doc["complete"] is True
    assert doc["format"] == "explainer-reel/narration-durations"
    assert doc["engine_url"] == "http://engine.test:10101"
    assert doc["speaker"] == SPEAKER

    # dictionary applied before synthesis
    assert engine.synthesized_texts() == ["クタイのテンバを確認します。", "カサギのミツケは三十ミリです。"]

    first, second = doc["items"]
    assert first["id"] == "scene-01" and first["wav"] == "scene-01.wav"
    # 14 chars × 10 ms = 0.14 s; slide = 0.14 + 0.3 + 0.5
    assert first["audio_sec"] == 0.14
    assert first["slide_sec"] == 0.94
    assert first["chunks"] == 1
    assert (first["sample_rate"], first["channels"]) == (44100, 1)
    assert len(first["text_hash"]) == 64 and len(first["synth_hash"]) == 64
    assert second["audio_sec"] == 0.15  # 15 chars

    info = read_info(tmp_path / "scene-01.wav")
    assert (info.sample_rate, info.channels, info.frames) == (44100, 1, round(0.14 * 44100))

    sent = [json.loads(c.body) for c in engine.calls if c.path == "/synthesis"]
    assert all(q["speedScale"] == 1.25 and q["volumeScale"] == 0.75 for q in sent)


def test_long_item_is_split_and_joined_without_silence(tmp_path, client, engine, make_input):
    text = "あいう。かきく。さしす。たち。"
    narration = parse_input(make_input(items=[{"id": "long", "text": text}]))
    doc = run(narration, tmp_path, client, max_chars=8)

    assert engine.synthesized_texts() == ["あいう。かきく。", "さしす。たち。"]
    record = doc["items"][0]
    assert record["chunks"] == 2
    # 8 + 7 chars → frames of both chunks exactly, nothing inserted between them
    expected_frames = round(0.08 * 44100) + round(0.07 * 44100)
    assert read_info(tmp_path / "long.wav").frames == expected_frames
    assert record["audio_sec"] == 0.15


# -- synth: regeneration rules ------------------------------------------------------------


def test_rerun_with_same_text_skips_engine(tmp_path, client, engine, make_input):
    narration = parse_input(make_input())
    first = run(narration, tmp_path, client)
    engine.calls.clear()

    second = run(narration, tmp_path, client)
    assert engine.calls == []  # not even /speakers
    assert [r["synth_hash"] for r in second["items"]] == [r["synth_hash"] for r in first["items"]]
    assert [r["audio_sec"] for r in second["items"]] == [r["audio_sec"] for r in first["items"]]


def test_pause_change_updates_slide_sec_without_regeneration(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    engine.calls.clear()

    doc = run(parse_input(make_input(pre_pause_sec=1.0, post_pause_sec=1.0)), tmp_path, client)
    assert engine.calls == []
    assert doc["items"][0]["slide_sec"] == 2.14


def test_changed_text_is_not_overwritten_without_force(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    before = (tmp_path / "scene-02.wav").read_bytes()
    engine.calls.clear()

    changed = make_input(
        items=[
            {"id": "scene-01", "text": "躯体の天端を確認します。"},
            {"id": "scene-02", "text": "笠木を変更しました。"},
            {"id": "scene-03", "text": "新しいシーンです。"},
        ]
    )
    with pytest.raises(OverwriteRefusedError) as info:
        run(parse_input(changed), tmp_path, client)
    assert info.value.item_ids == ["scene-02"]
    assert info.value.exit_code == 3
    # nothing happened: no engine calls, no new files, old WAV intact
    assert engine.calls == []
    assert not (tmp_path / "scene-03.wav").exists()
    assert (tmp_path / "scene-02.wav").read_bytes() == before

    doc = run(parse_input(changed), tmp_path, client, force=True)
    # only the changed and the new item are synthesized; the identical one is still skipped
    assert engine.synthesized_texts() == ["カサギを変更しました。", "新しいシーンです。"]
    assert [r["id"] for r in doc["items"]] == ["scene-01", "scene-02", "scene-03"]


def test_settings_change_counts_as_change(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    with pytest.raises(OverwriteRefusedError):
        run(parse_input(make_input(speaker=7)), tmp_path, client)
    with pytest.raises(OverwriteRefusedError):
        run(parse_input(make_input(speed=1.1)), tmp_path, client)
    with pytest.raises(OverwriteRefusedError):
        run(parse_input(make_input()), tmp_path, client, dictionary=PronunciationDictionary.empty())


def test_existing_wav_without_record_is_protected(tmp_path, client, engine, make_input):
    (tmp_path / "scene-01.wav").write_bytes(b"user's own file")
    with pytest.raises(OverwriteRefusedError) as info:
        run(parse_input(make_input()), tmp_path, client)
    assert info.value.item_ids == ["scene-01"]
    assert (tmp_path / "scene-01.wav").read_bytes() == b"user's own file"


def test_missing_wav_is_regenerated_even_with_record(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    (tmp_path / "scene-01.wav").unlink()
    engine.calls.clear()
    run(parse_input(make_input()), tmp_path, client)
    assert engine.synthesized_texts() == ["クタイのテンバを確認します。"]


def test_removed_items_drop_out_of_durations(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    doc = run(parse_input(make_input(items=[{"id": "scene-02", "text": "笠木の見付けは三十ミリです。"}])), tmp_path, client)
    assert [r["id"] for r in doc["items"]] == ["scene-02"]


def test_corrupt_durations_is_treated_as_no_record(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    (tmp_path / "durations.json").write_text("{broken", encoding="utf-8")
    messages = []
    with pytest.raises(OverwriteRefusedError):
        run(parse_input(make_input()), tmp_path, client, log=messages.append)
    assert any("durations.json" in m for m in messages)


# -- synth: failures --------------------------------------------------------------------


def test_unknown_speaker_is_input_error(tmp_path, client, engine, make_input):
    with pytest.raises(InputError, match="12345"):
        run(parse_input(make_input(speaker=12345)), tmp_path, client)
    assert "/audio_query" not in engine.paths()


def test_interrupted_run_keeps_records_of_finished_items(tmp_path, client, engine, make_input, make_response):
    def fail_second(call):
        if "ミツケ" in call.query["text"]:
            return make_response(500, "engine crashed")(call)
        return engine._default(call)

    engine.overrides["/audio_query"] = fail_second
    with pytest.raises(EngineError) as info:
        run(parse_input(make_input()), tmp_path, client)
    assert info.value.kind is EngineErrorKind.AUDIO_QUERY_FAILED

    partial = durations(tmp_path)
    assert partial["complete"] is False
    assert [r["id"] for r in partial["items"]] == ["scene-01"]
    assert not (tmp_path / "scene-02.wav").exists()

    engine.overrides.clear()
    engine.calls.clear()
    doc = run(parse_input(make_input()), tmp_path, client)
    assert engine.synthesized_texts() == ["カサギのミツケは三十ミリです。"]  # scene-01 skipped
    assert doc["complete"] is True


def test_mismatched_chunk_formats_are_reported(tmp_path, client, engine, make_input):
    from explainer_reel_kit.narration.tts.aivisspeech import HttpResponse
    from explainer_reel_kit.narration.wavutil import silent_wav

    rates = iter([44100, 22050])
    engine.overrides["/synthesis"] = lambda call: HttpResponse(200, silent_wav(0.02, sample_rate=next(rates)))
    narration = parse_input(make_input(items=[{"id": "x", "text": "あいう。かきく。"}]))
    with pytest.raises(EngineError) as info:
        run(narration, tmp_path, client, max_chars=4)
    assert info.value.kind is EngineErrorKind.MALFORMED_RESPONSE
    assert not (tmp_path / "x.wav").exists()


def test_no_temp_files_left_behind(tmp_path, client, make_input):
    run(parse_input(make_input()), tmp_path, client)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["durations.json", "scene-01.wav", "scene-02.wav"]


# -- Windows-oriented robustness ----------------------------------------------------------


@pytest.mark.parametrize("item_id", ["CON", "nul", "Com1", "LPT9", "aux"])
def test_windows_reserved_ids_are_rejected(make_input, item_id):
    with pytest.raises(InputError, match="予約名"):
        parse_input(make_input(items=[{"id": item_id, "text": "あ。"}]))


def test_non_utf8_input_is_input_error(tmp_path, make_input):
    from explainer_reel_kit.narration.synth import load_input

    path = tmp_path / "in.json"
    path.write_text(json.dumps(make_input(), ensure_ascii=False), encoding="utf-16")  # PowerShell 5 Out-File
    with pytest.raises(InputError, match="UTF-8"):
        load_input(path)
    path.write_text(json.dumps(make_input(), ensure_ascii=False), encoding="utf-8-sig")  # BOM is fine
    assert load_input(path).speaker == SPEAKER


def test_non_utf8_dictionary_is_input_error(tmp_path):
    path = tmp_path / "dict.yaml"
    path.write_bytes("entries:\n  躯体: クタイ\n".encode("cp932"))
    with pytest.raises(InputError, match="UTF-8"):
        PronunciationDictionary.load(path)


def test_locked_wav_is_output_error(tmp_path, client, make_input, monkeypatch):
    from explainer_reel_kit.narration import synth as synth_module
    from explainer_reel_kit.narration.errors import OutputError

    def locked(src, dst):
        raise PermissionError(13, "The process cannot access the file", str(dst))

    monkeypatch.setattr(synth_module.os, "replace", locked)
    with pytest.raises(OutputError) as info:
        run(parse_input(make_input()), tmp_path, client)
    assert "scene-01.wav" in str(info.value)
    assert info.value.exit_code == 4
    assert [p.name for p in tmp_path.iterdir()] == []  # temp file cleaned up


def test_out_dir_that_is_a_file_is_output_error(tmp_path, client, make_input):
    from explainer_reel_kit.narration.errors import OutputError

    blocker = tmp_path / "out"
    blocker.write_text("not a folder")
    with pytest.raises(OutputError):
        run(parse_input(make_input()), blocker / "sub", client)


# -- paragraphs  -----------------------------------------------------------------


def test_paragraph_starts_sec(tmp_path, client, engine, make_input):
    # paragraph 1 → 2 chunks (4 + 4 chars), paragraph 2 → 1 chunk (5 chars); 10 ms per char
    text = "あいう。かきく。\nさしすせ。"
    doc = run(parse_input(make_input(items=[{"id": "p", "text": text}])), tmp_path, client, max_chars=4)
    record = doc["items"][0]
    assert engine.synthesized_texts() == ["あいう。", "かきく。", "さしすせ。"]
    assert record["chunks"] == 3
    assert record["paragraph_starts_sec"] == [0.0, 0.08]
    assert record["audio_sec"] == 0.13
    assert doc["version"] == 2


def test_paragraphs_are_not_packed_together(tmp_path, client, engine, make_input):
    text = "躯体を確認します。\n\n天端を確認します。\n笠木を確認します。"
    doc = run(parse_input(make_input(items=[{"id": "p", "text": text}])), tmp_path, client)
    assert engine.synthesized_texts() == ["クタイを確認します。", "テンバを確認します。", "カサギを確認します。"]
    assert doc["items"][0]["paragraph_starts_sec"] == [0.0, 0.1, 0.2]


def test_single_paragraph_starts_at_zero(tmp_path, client, make_input):
    doc = run(parse_input(make_input()), tmp_path, client)
    assert [r["paragraph_starts_sec"] for r in doc["items"]] == [[0.0], [0.0]]


def test_paragraph_starts_use_exact_frames(tmp_path, client, engine, make_input):
    from explainer_reel_kit.narration.tts.aivisspeech import HttpResponse
    from explainer_reel_kit.narration.wavutil import silent_wav

    lengths = iter([1.23456, 0.5])
    engine.overrides["/synthesis"] = lambda call: HttpResponse(200, silent_wav(next(lengths)))
    doc = run(parse_input(make_input(items=[{"id": "p", "text": "一。\n二。"}])), tmp_path, client)
    first_frames = round(1.23456 * 44100)  # 54444 frames → 1.234558... s
    assert doc["items"][0]["paragraph_starts_sec"] == [0.0, round(first_frames / 44100, 3)]


def test_v1_fields_are_kept_in_v2_records(tmp_path, client, make_input):
    doc = run(parse_input(make_input()), tmp_path, client)
    v1_keys = {"id", "wav", "audio_sec", "slide_sec", "chunks", "sample_rate", "channels", "text_hash", "synth_hash"}
    assert set(doc["items"][0]) == v1_keys | {"paragraph_starts_sec"}
    assert {"format", "version", "complete", "speaker", "pre_pause_sec", "post_pause_sec"} <= set(doc)


def test_skip_keeps_paragraph_starts(tmp_path, client, engine, make_input):
    data = make_input(items=[{"id": "p", "text": "一つ目。\n二つ目。"}])
    first = run(parse_input(data), tmp_path, client)
    engine.calls.clear()
    second = run(parse_input(data), tmp_path, client)
    assert engine.calls == []
    assert second["items"][0]["paragraph_starts_sec"] == first["items"][0]["paragraph_starts_sec"] == [0.0, 0.04]


def test_moving_a_line_break_counts_as_change(tmp_path, client, make_input):
    run(parse_input(make_input(items=[{"id": "p", "text": "一つ目。二つ目。"}])), tmp_path, client)
    with pytest.raises(OverwriteRefusedError):
        run(parse_input(make_input(items=[{"id": "p", "text": "一つ目。\n二つ目。"}])), tmp_path, client)


def test_v1_durations_requires_force(tmp_path, client, engine, make_input):
    run(parse_input(make_input()), tmp_path, client)
    path = tmp_path / "durations.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    old["version"] = 1
    for rec in old["items"]:
        del rec["paragraph_starts_sec"]
    path.write_text(json.dumps(old), encoding="utf-8")
    engine.calls.clear()

    messages = []
    with pytest.raises(OverwriteRefusedError):
        run(parse_input(make_input()), tmp_path, client, log=messages.append)
    assert engine.calls == []
    assert any("version 1" in m and "--force" in m for m in messages)

    doc = run(parse_input(make_input()), tmp_path, client, force=True)
    assert doc["version"] == 2
    assert all(r["paragraph_starts_sec"] == [0.0] for r in doc["items"])
