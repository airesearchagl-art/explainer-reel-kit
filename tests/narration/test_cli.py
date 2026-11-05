"""erkit voice list / synth（kana は test_kana.py）。HTTP はすべて偽のエンジン。"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.narration.cli import main
from conftest import EXAMPLE, FIXTURES

ENGINE_URL = ["--engine-url", "http://127.0.0.1:10101"]


@pytest.fixture
def input_file(tmp_path, make_input):
    path = tmp_path / "narration-input.json"
    path.write_text(json.dumps(make_input(), ensure_ascii=False), encoding="utf-8")
    return path


# -- list ---------------------------------------------------------------------------


def test_list_voices(engine, capsys):
    assert main(["list", "--engine-url", "http://engine.test:10101"], transport=engine) == 0
    cap = capsys.readouterr()
    assert "version 1.1.0" in cap.out
    assert "888753760  Test Speaker / ノーマル" in cap.out
    assert "Test Model" in cap.out
    assert engine.paths() == ["/version", "/aivm_models", "/speakers"]
    assert "既定の声 808373280" in cap.err  # 偽のエンジンには既定の声（ほのか / ノーマル）が無い


def test_list_json_and_default_voice(engine, isolated_config, capsys):
    isolated_config.write_text("voice:\n  speaker: 7\n", encoding="utf-8")
    assert main(["list", "--json"], transport=engine) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["engine"] == "aivisspeech" and data["engine_url"] == "http://127.0.0.1:10101"
    assert [v["style_id"] for v in data["voices"]] == [888753760, 7]
    assert data["default_speaker"] == 7 and data["default_speaker_found"] is True


def test_list_marks_default_voice(engine, isolated_config, capsys):
    isolated_config.write_text("voice:\n  speaker: 888753760\n", encoding="utf-8")
    assert main(["list"], transport=engine) == 0
    cap = capsys.readouterr()
    assert "Test Speaker / ノーマル  ← 既定の声" in cap.out and cap.err == ""


def test_list_models_failure_is_not_fatal(engine, make_response, capsys):
    engine.overrides["/aivm_models"] = make_response(404, "not found")
    assert main(["list"], transport=engine) == 0
    assert "models" not in capsys.readouterr().out


@pytest.mark.parametrize("path, status, kind", [("/speakers", 500, "SPEAKERS_FAILED")])
def test_list_failures(engine, make_response, capsys, path, status, kind):
    engine.overrides[path] = make_response(status, "x")
    assert main(["list"], transport=engine) == 1
    assert kind in capsys.readouterr().err


def test_list_connection_failure(engine, capsys):
    engine.connection_down = True
    assert main(["list"], transport=engine) == 1
    assert "ENGINE_CONNECTION_FAILED" in capsys.readouterr().err


def test_list_no_voices(engine, make_response, capsys):
    engine.overrides["/speakers"] = make_response(200, "[]")
    assert main(["list"], transport=engine) == 1


def test_unknown_engine(engine, capsys):
    assert main(["list", "--engine", "nothing"], transport=engine) == 2
    assert "aivisspeech" in capsys.readouterr().err


def test_bad_config(isolated_config, engine, capsys):
    isolated_config.write_text("voice: [1]\n", encoding="utf-8")
    assert main(["list"], transport=engine) == 2
    assert "voice" in capsys.readouterr().err


# -- synth（ナレーションの入力 JSON）------------------------------------------------------


def test_synth_input_end_to_end(engine, input_file, tmp_path, capsys):
    out_dir = tmp_path / "out"
    assert main(["synth", str(input_file), "--out-dir", str(out_dir)], transport=engine) == 0
    assert (out_dir / "scene-01.wav").exists() and (out_dir / "scene-02.wav").exists()
    doc = json.loads((out_dir / "durations.json").read_text(encoding="utf-8"))
    assert doc["format"] == "explainer-reel/narration-durations" and doc["version"] == 2
    assert [r["id"] for r in doc["items"]] == ["scene-01", "scene-02"]
    assert doc["engine"] == "aivisspeech"
    # 既定では読み辞書を使わない
    assert engine.synthesized_texts()[0] == "躯体の天端を確認します。"
    assert "generated scene-01" in capsys.readouterr().out
    # 2 回目: 同じ内容なのでエンジンを呼ばない
    engine.calls.clear()
    assert main(["synth", str(input_file), "--out-dir", str(out_dir)], transport=engine) == 0
    assert engine.calls == []


def test_synth_with_dictionary_and_engine_url(engine, input_file, tmp_path):
    out = tmp_path / "out"
    args = ["synth", str(input_file), "--out-dir", str(out), "--dictionary", "architecture",
            "--engine-url", "http://other.test:10101"]
    assert main(args, transport=engine) == 0
    assert engine.synthesized_texts()[0] == "クタイのテンバを確認します。"
    doc = json.loads((out / "durations.json").read_text(encoding="utf-8"))
    assert doc["engine_url"] == "http://other.test:10101"


def test_synth_dictionary_from_config(engine, input_file, tmp_path, isolated_config):
    isolated_config.write_text("voice:\n  dictionaries: [architecture]\n", encoding="utf-8")
    assert main(["synth", str(input_file), "--out-dir", str(tmp_path / "a")], transport=engine) == 0
    assert engine.synthesized_texts()[0] == "クタイのテンバを確認します。"
    engine.calls.clear()
    assert main(["synth", str(input_file), "--out-dir", str(tmp_path / "b"), "--no-dictionary"], transport=engine) == 0
    assert engine.synthesized_texts()[0] == "躯体の天端を確認します。"


def test_synth_exit_codes(engine, input_file, tmp_path, make_input, capsys):
    out_dir = tmp_path / "out"
    base = ["synth", str(input_file), "--out-dir", str(out_dir)]
    assert main(base, transport=engine) == 0

    input_file.write_text(json.dumps(make_input(items=[{"id": "scene-01", "text": "変更。"}]), ensure_ascii=False),
                          encoding="utf-8")
    assert main(base, transport=engine) == 3
    assert "--force" in capsys.readouterr().err
    assert main(base + ["--force"], transport=engine) == 0

    input_file.write_text('{"speaker": 1}', encoding="utf-8")
    assert main(base, transport=engine) == 2
    assert main(["synth", str(tmp_path / "missing.json"), "--out-dir", str(out_dir)], transport=engine) == 2
    assert main(base + ["--max-chars", "0"], transport=engine) == 2


def test_synth_engine_error_exit_code(engine, input_file, tmp_path, make_response, capsys):
    engine.overrides["/synthesis"] = make_response(500, "boom")
    assert main(["synth", str(input_file), "--out-dir", str(tmp_path / "o")], transport=engine) == 1
    assert "SYNTHESIS_FAILED" in capsys.readouterr().err


def test_synth_unknown_speaker_lists_voices(engine, input_file, tmp_path, capsys):
    assert main(["synth", str(input_file), "--out-dir", str(tmp_path / "o"), "--speaker", "123"], transport=engine) == 2
    err = capsys.readouterr().err
    assert "123" in err and "888753760  Test Speaker / ノーマル" in err


# -- synth（台本から）----------------------------------------------------------------------


def test_synth_from_storyboard(engine, tmp_path, capsys):
    out = tmp_path / "voice"
    assert main(["synth", str(EXAMPLE), "--out-dir", str(out), "--speaker", "7", *ENGINE_URL], transport=engine) == 0
    data = json.loads((out / "narration-input.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in data["items"]] == ["intro", "s01", "s02", "s03", "s04", "s05", "outro"]
    assert data["speaker"] == 7 and data["engine"] == "aivisspeech"
    doc = json.loads((out / "durations.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in doc["items"]] == [i["id"] for i in data["items"]]
    assert all(r["paragraph_starts_sec"][0] == 0 for r in doc["items"])


def test_synth_from_storyboard_uses_default_voice(engine, tmp_path, capsys):
    """台本・設定に声が無ければ、既定の声（ほのか / ノーマル 808373280）。無いエンジンでは一覧を出して止まる。"""
    assert main(["synth", str(EXAMPLE), "--out-dir", str(tmp_path / "v")], transport=engine) == 2
    err = capsys.readouterr().err
    assert "808373280" in err and "Test Speaker / Alt" in err
    assert json.loads((tmp_path / "v" / "narration-input.json").read_text(encoding="utf-8"))["speaker"] == 808373280


def test_synth_default_out_dir(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("ERKIT_OUTPUT_ROOT", str(tmp_path / "root"))
    assert main(["synth", str(EXAMPLE), "--speaker", "7"], transport=engine) == 0
    assert (tmp_path / "root" / "voice" / "hello-kit" / "durations.json").is_file()


def test_synth_confidential_storyboard_needs_this_pc(engine, tmp_path, capsys):
    doc = json.loads((FIXTURES / "narration_terms.storyboard.json").read_text(encoding="utf-8"))
    doc["reel"]["confidentiality"] = "confidential"
    sb = tmp_path / "secret.storyboard.json"
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    args = ["synth", str(sb), "--out-dir", str(tmp_path / "o"), "--speaker", "7"]
    assert main(args + ["--engine-url", "http://192.168.1.20:10101"], transport=engine) == 2
    assert "社外秘" in capsys.readouterr().err and engine.calls == []
    assert main(args + ["--engine-url", "http://localhost:10101"], transport=engine) == 0


def test_synth_invalid_storyboard(engine, tmp_path, capsys):
    bad = tmp_path / "bad.storyboard.md"
    bad.write_text(EXAMPLE.read_text(encoding="utf-8").replace("recipe: fade_sequence", "recipe: spin", 1),
                   encoding="utf-8")
    assert main(["synth", str(bad), "--out-dir", str(tmp_path / "o")], transport=engine) == 2
    assert "[recipe]" in capsys.readouterr().err


def test_synth_reports_credit(engine, tmp_path, isolated_config, capsys):
    isolated_config.write_text(
        "voice:\n  credits:\n    - name: テストの声\n      credit: テストの声のクレジット\n      style_ids: [7]\n", encoding="utf-8")
    assert main(["synth", str(EXAMPLE), "--out-dir", str(tmp_path / "o"), "--speaker", "7"], transport=engine) == 0
    assert '--credit "テストの声のクレジット"' in capsys.readouterr().out


# -- erkit の入口 ---------------------------------------------------------------------------


def test_erkit_voice_is_registered(capsys):
    assert erkit(["voice", "--help"]) == 0
    assert "synth" in capsys.readouterr().out
    assert erkit(["voice"]) == 2


def test_module_entry_point_help():
    result = subprocess.run([sys.executable, "-m", "explainer_reel_kit", "voice", "synth", "--help"],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0 and "--out-dir" in result.stdout
