# -*- coding: utf-8 -*-
"""``erkit make`` から呼ぶ入口（render_mode: interactive）。

interactive は、ナレーション（voice）・スライド（deck、python-pptx で .pptx を作るだけ）・音声の合成（mux、音量そろえ）を
slides と共通に使い、**書き出しの段だけ**を差し替える。PowerPoint のアプリは使わない。

場面の境界と音声の位置は .pptx のスライドの時刻（``reel.mux.read_slide_timings``。p:transition の advTm と切替効果の長さ）
から出す。ナレーションの WAV は「スライドの開始 ＋ 切替効果 ＋ pre_pause_sec」に置かれる（mux と同じ）ので、
同じナレーションなら slides と同じ位置に音声が入る。スライドの秒（advTm）は deck がナレーションの WAV の実尺
（durations.json の slide_sec）から決めている。

make の流れ（make 側がすること）::

    1. 台本を読んだ後、出力フォルダを作る前:   mode, source = resolve_render_mode(--render-mode, doc)
       interactive なら                      info = precheck_scenes(storyboard, doc)   # 誤り → InteractiveError（exit_code 2/1）
    2. voice・deck は slides と同じ
    3. 書き出しの段の代わり:                  info = render_storyboard(storyboard, doc, out_dir, stem, ...)
                                              → work/<stem>.silent.mp4・work/render-timeline.json・<stem>.srt など
    4. mux は slides と同じ（無音 MP4 は work/<stem>.silent.mp4）
    5. mux の後:                              info = verify_storyboard(out_dir, stem, scenes_dir)  # 要確認でも止めない

区分の関所: interactive の描画はこの PC の中だけで行い、ネットワークを使わない。静止画は台本のフォルダと出力フォルダの
中のファイルだけ（URL・その外のファイルは LayoutError）。場面コード（Python）・scenes.yaml は台本のフォルダの
``scenes/`` の下のものだけを読み込む（それ以外の場所を指定すると InteractiveError）。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import DEFAULT_RENDER_MODE, RENDER_MODES

Log = Callable[[str], None]


class InteractiveError(Exception):
    """interactive の段で止める。exit_code 2: 引数・台本・scenes.yaml の誤り、1: 描けない・ffmpeg の失敗など。"""

    def __init__(self, stage: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code


# ---------------------------------------------------------------- 映像の作り方

def resolve_render_mode(command: str | None, doc: Mapping[str, Any]) -> tuple[str, str]:
    """映像の作り方: コマンドの ``--render-mode`` ＞ 台本の ``reel.render_mode`` ＞ slides。

    戻り値 (mode, 出どころ: command / storyboard / default)。知らない値は InteractiveError（exit_code 2）。
    """
    if command is not None:
        if command not in RENDER_MODES:
            raise InteractiveError("render_mode", f"--render-mode は {' / '.join(RENDER_MODES)} のどれかです: {command}", 2)
        return command, "command"
    value = (doc.get("reel") or {}).get("render_mode")
    if value is not None:
        if value not in RENDER_MODES:
            raise InteractiveError("render_mode", f"台本の render_mode は {' / '.join(RENDER_MODES)} のどれかです: {value}", 2)
        return value, "storyboard"
    return DEFAULT_RENDER_MODE, "default"


# ---------------------------------------------------------------- 置き場

@dataclass(frozen=True)
class InteractivePaths:
    """interactive が読み書きするファイル（出力フォルダの決まりは erkit make と同じ）。"""

    out_dir: Path
    stem: str  # reel.output_name

    @property
    def work(self) -> Path:
        return self.out_dir / "work"

    @property
    def pptx(self) -> Path:
        return self.out_dir / f"{self.stem}.pptx"

    @property
    def narration_dir(self) -> Path:
        return self.work / "narration"

    @property
    def durations(self) -> Path:
        return self.narration_dir / "durations.json"

    @property
    def narration_input(self) -> Path:
        return self.work / "narration-input.json"

    @property
    def assets(self) -> Path:
        return self.work / "assets"

    @property
    def render_timeline(self) -> Path:
        return self.work / "render-timeline.json"

    @property
    def pauses(self) -> Path:
        return self.work / "pauses.json"

    @property
    def interactive(self) -> Path:
        return self.work / "interactive"

    @property
    def build(self) -> Path:
        return self.interactive / "build"

    @property
    def silent_mp4(self) -> Path:
        return self.work / f"{self.stem}.silent.mp4"

    @property
    def final_mp4(self) -> Path:
        return self.out_dir / f"{self.stem}.mp4"

    @property
    def srt(self) -> Path:
        return self.out_dir / f"{self.stem}.srt"

    @property
    def checks(self) -> Path:
        return self.out_dir / "checks"


def find_scenes_dir(storyboard: Path, reel_id: str) -> Path | None:
    """場面コードのフォルダ: 台本のフォルダの ``scenes/<reel id>/``、無ければ ``scenes/``（直下に .py か scenes.yaml が
    あるとき）。どちらも無ければ None（すべて既定の場面）。"""
    base = Path(storyboard).resolve().parent / "scenes"
    if (base / reel_id).is_dir():
        return base / reel_id
    if base.is_dir() and (any(base.glob("*.py")) or (base / "scenes.yaml").is_file()):
        return base
    return None


def scenes_dir_for(storyboard: Path, doc: Mapping[str, Any], scenes_dir: Path | None = None) -> Path | None:
    """使う場面コードのフォルダ。指定があっても、台本のフォルダの ``scenes/`` の下だけを認める。"""
    if scenes_dir is None:
        return find_scenes_dir(storyboard, doc["reel"]["id"])
    d = Path(scenes_dir).resolve()
    base = Path(storyboard).resolve().parent / "scenes"
    try:
        d.relative_to(base)
    except ValueError:
        raise InteractiveError("scenes", f"場面コードは台本のフォルダの scenes/ の下だけを読み込みます: {d}"
                                         f"（置き場: {base}）", 2) from None
    if not d.is_dir():
        raise InteractiveError("scenes", f"場面コードのフォルダがありません: {d}", 2)
    return d


def asset_roots(storyboard: Path, out_dir: Path | None = None) -> list[Path]:
    """静止画を読んでよいフォルダ: 台本のフォルダと出力フォルダ（work/assets の複製）。"""
    roots = [Path(storyboard).resolve().parent]
    if out_dir is not None:
        roots.append(Path(out_dir).resolve())
    return roots


# ---------------------------------------------------------------- 1. 合成の前の確かめ

def narration_texts(doc: Mapping[str, Any]) -> dict[str, str]:
    """{場面 id: ナレーションの原稿}（intro → scenes → outro。narration-input と同じ）。"""
    from ..narration.adapter import slide_ids

    texts = [(doc.get("intro") or {}).get("narration", ""), *[s.get("narration", "") for s in doc["scenes"]],
             (doc.get("outro") or {}).get("narration", "")]
    return dict(zip(slide_ids(doc), texts))


def precheck_scenes(storyboard: Path, doc: Mapping[str, Any], scenes_dir: Path | None = None,
                    log: Log = print) -> dict[str, Any]:
    """scenes.yaml を、ナレーションの合成の前（出力フォルダを作る前）に確かめる。

    台本の原稿から文の時刻を仮に置いた中間データで部品を組み立て、試し描きする（precheck.check_before_synthesis）。
    scenes.yaml の誤り → InteractiveError（exit_code 2）、場面コードを読み込めない → InteractiveError（exit_code 1）。
    戻り値は run.json の ``stages`` に残す記録（status: ok / skipped、scenes_dir、scenes、parts など）。
    """
    from ..narration.adapter import slide_ids
    from . import precheck
    from .engine import LayoutError
    from .scenes import SceneError
    from .spec import SpecError

    d = scenes_dir_for(storyboard, doc, scenes_dir)
    try:
        info = precheck.check_before_synthesis(dict(doc), slide_ids(doc), narration_texts(doc), d,
                                               asset_roots=asset_roots(storyboard))
    except SpecError as e:
        raise InteractiveError("scenes", f"scenes.yaml の誤り（合成の前に止めました）: {e}", 2) from e
    except LayoutError as e:
        raise InteractiveError("scenes", f"場面の組み立ての誤り（合成の前に止めました）: {e}", 2) from e
    except SceneError as e:
        raise InteractiveError("scenes", f"場面コードを読み込めません（合成の前に止めました）: {e}", 1) from e
    info["scenes_dir"] = str(d) if d else None
    if info["status"] == "ok":
        shadow = f"、Python が先の場面 {', '.join(info['shadowed_by_python'])}" if info["shadowed_by_python"] else ""
        log(f"[scenes] scenes.yaml を合成の前に確かめました（場面 {len(info['scenes'])}、部品 {info['parts']}{shadow}）")
    return info


# ---------------------------------------------------------------- 3. 描く（書き出しの段の代わり）

def _load_narration_items(paths: InteractivePaths) -> dict[str, str]:
    try:
        data = json.loads(paths.narration_input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InteractiveError("interactive", f"ナレーションの入力を読めません: {paths.narration_input}: {e}") from e
    return {it["id"]: it["text"] for it in data.get("items") or [] if isinstance(it, dict)}


def _previous_timeline(paths: InteractivePaths, reuse_run: Path | None) -> dict | None:
    """前の中間データ（作り直しの比較）: 同じフォルダなら上書きする前の work の、reuse_run なら前の出力フォルダの。"""
    cands = [paths.render_timeline]
    if reuse_run is not None:
        cands.append(Path(reuse_run) / "work" / "render-timeline.json")
    for cand in cands:
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def render_storyboard(storyboard: Path, doc: Mapping[str, Any], out_dir: Path, stem: str | None = None, *,
                      scenes_dir: Path | None = None, credit: str | None = None,
                      narration_items: Mapping[str, str] | None = None,
                      readings: Mapping[str, str] | None = None,
                      timings: Sequence[Any] | None = None,
                      reuse_run: Path | None = None,
                      ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", jobs: int | None = None,
                      force: bool = False, log: Log = print) -> dict[str, Any]:
    """台本（ナレーションと .pptx を作った後）→ 無音 MP4。戻り値は run.json の ``stages`` に残す記録。

    読むもの（out_dir の下。erkit make の決まりの置き場）:
      - ``<stem>.pptx``: スライドの時刻（場面の境界と音声の位置。timings を渡せば読まない）
      - ``work/narration/durations.json`` と ``work/narration/<id>.wav``: 文の時刻を WAV の実尺から測る
      - ``work/narration-input.json``: 原稿（narration_items を渡せば読まない）
      - ``work/assets/``: 既定の場面で全面に出す画像（assets の段の複製）
      - 場面コード: 台本のフォルダの ``scenes/<reel id>/`` か ``scenes/``（scenes_dir で指定するときもその下だけ）
      - reuse_run: 前の出力フォルダ（``work/render-timeline.json`` を作り直しの比較に使う）
    書くもの:
      - ``work/render-timeline.json``: 中間データ（場面・文・字幕）
      - ``<stem>.srt``: 字幕（焼き込みと同じ cues から。最終の MP4 の隣）
      - ``checks/resync.json``・``checks/resync.md``: 作り直した前後の比較
      - ``work/pauses.json``: 文中の無音（mux と同じ位置に WAV を並べたトラックから。トラックは消す）
      - ``work/interactive/build/``: 600 フレームごとの区間（入力のハッシュが同じなら使い回す）
      - ``work/<stem>.silent.mp4``: 描いた無音 MP4（この後 mux でナレーションを入れる）

    readings: {場面 id: 合成入力（読みの辞書の後）}。中間データの reading に記録だけ残す。
    無音 MP4 が既にあれば、force でなければ InteractiveError（exit_code 1）。
    """
    from ..narration.errors import NarrationError
    from ..reel.mux import (MuxError, build_track_command, expected_total_sec, load_durations, plan_segments,
                            read_slide_timings)
    from ..narration.adapter import slide_ids
    from . import audio as iaudio
    from . import convert as iconv
    from . import render as irender
    from . import sync as isync
    from .engine import LayoutError
    from .scenes import SceneError
    from .spec import SpecError
    from .subtitles import write_srt
    from .timeline import TimelineError, write_timeline

    out_dir = Path(out_dir)
    paths = InteractivePaths(out_dir, stem or doc["reel"]["output_name"])
    if paths.silent_mp4.exists() and not force:
        raise InteractiveError("interactive", f"無音 MP4 が既にあります（--force で描き直す）: {paths.silent_mp4}")
    sdir = scenes_dir_for(storyboard, doc, scenes_dir)
    ids = slide_ids(doc)
    try:
        if timings is None:
            timings = read_slide_timings(paths.pptx, ids)
        durations = load_durations(paths.durations)
        narration = dict(narration_items) if narration_items is not None else _load_narration_items(paths)
        total = expected_total_sec(timings)
        images = iconv.storyboard_images(dict(doc), paths.assets, rel_to=paths.work)
        source = {"kind": "storyboard", "path": str(Path(storyboard).resolve()),
                  "sha256": _sha256(Path(storyboard)), "pptx": str(paths.pptx), "durations": str(paths.durations)}
        tl, warns = iconv.from_storyboard(dict(doc), timings, durations, narration, images=images, credit=credit,
                                          total_ms=int(round(total * 1000)), source=source,
                                          wav_dir=paths.narration_dir, readings=dict(readings) if readings else None,
                                          image_dir=paths.work)
        old_tl = _previous_timeline(paths, reuse_run)
        write_timeline(tl, paths.render_timeline)
        resync = isync.resync_report(old_tl, tl, durations, paths.checks)
        write_srt(tl["cues"], tl["fps"], paths.srt)
        measured = sum(1 for e in tl["sentences"] if e.get("timing") == "measured")
        log(f"[interactive] 文の時刻: 測った {measured} / {len(tl['sentences'])}。字幕 {paths.srt}。"
            + (f"初めての合成（前の出力なし）。記録 {paths.checks / 'resync.md'}" if resync.get("first") else
               f"作り直しの比較 {paths.checks / 'resync.md'}（変わった文と前後 {len(resync['sentences'])}）"))
        log(f"[interactive] 中間データ {paths.render_timeline}（場面 {len(tl['scenes'])}、文 {len(tl['sentences'])}、"
            f"字幕 {len(tl['cues'])}、{tl['total_frames']} フレーム）")

        # 文中の無音: mux と同じ位置に WAV を並べたトラックから（音声は変えない。解析用の一時ファイル）
        paths.interactive.mkdir(parents=True, exist_ok=True)
        segments, _ = plan_segments(timings, durations, paths.narration_dir)
        track = paths.interactive / "narration-track.wav"
        cmd, _ = build_track_command(ffmpeg, segments, total, track)
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise InteractiveError("interactive", "ナレーションのトラック（無音の解析用）を作れません: "
                                                  f"{(res.stderr or '').strip()[-500:]}")
        pauses = iaudio.find_pauses(iaudio.envelope(track, ffmpeg), tl["sentences"])
        paths.pauses.write_text(json.dumps(pauses, ensure_ascii=False, indent=1), encoding="utf-8")
        track.unlink(missing_ok=True)

        project = irender.Project(timeline=paths.render_timeline, scenes_dir=sdir, pauses=paths.pauses,
                                  asset_roots=asset_roots(storyboard, out_dir))
        rec = irender.render(project, paths.silent_mp4, build_dir=paths.build, ffmpeg=ffmpeg, ffprobe=ffprobe,
                             jobs=jobs, force=force, srt=False, log=log)
    except SpecError as e:   # 合成の前に確かめているので、ふつうは来ない（合成の間に scenes.yaml を直したときなど）
        raise InteractiveError("scenes", f"scenes.yaml の誤り: {e}", 2) from e
    except (TimelineError, LayoutError, SceneError, irender.RenderError, MuxError, NarrationError, OSError,
            subprocess.SubprocessError) as e:
        raise InteractiveError("interactive", str(e)) from e
    finally:
        from . import engine

        engine.set_asset_roots([])
    rec["srt"] = str(paths.srt)
    return {"timeline": str(paths.render_timeline), "pauses": str(paths.pauses), "srt": str(paths.srt),
            "silent_mp4": str(paths.silent_mp4), "scenes_dir": str(sdir) if sdir else None,
            "network": "使わない（描画はこの PC の中だけ）", "warnings": warns,
            "sentences": len(tl["sentences"]), "measured_sentences": measured, "cues": len(tl["cues"]),
            "resync": {"compared": resync["compared"], "first": resync.get("first", False),
                       "synthesized_paragraphs": resync["synthesized_paragraphs"],
                       "report": str(paths.checks / "resync.md")}, "render": rec}


# ---------------------------------------------------------------- 5. 検証（mux の後）

VERIFY_KEYS = ("probe", "decode", "audio", "subtitles", "frame_compare", "screen_text")


def verify_storyboard(out_dir: Path, stem: str, scenes_dir: Path | None = None, *, storyboard: Path | None = None,
                      ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", log: Log = print) -> dict[str, Any]:
    """出来上がった MP4（``<stem>.mp4``）を検証する。音声の正本は無いので audio は省く。止めない（例外を投げない）。

    読むもの: ``<stem>.mp4``・``<stem>.srt``（あれば照合）・``work/render-timeline.json``・``work/pauses.json``・場面コード、
    verify.yaml（場面コードのフォルダか、その親。題材の禁止語など。無くてもよい）。
    書くもの: ``checks/verify.json``・``checks/検証結果.md``・``checks/screen_text.json``・``checks/cue_points.json``・
    ``checks/ffprobe.json``。
    戻り値（run.json の ``stages`` に残す）: status（ok / needs_review / failed）・ok・failed（要確認の手順）・
    config・result・report。make は ok でなければ警告にする（MP4 は残す）。
    """
    from . import engine
    from . import render as irender
    from .engine import LayoutError
    from .scenes import SceneError
    from .timeline import TimelineError
    from .verify import Verifier, VerifyError, load_config

    paths = InteractivePaths(Path(out_dir), stem)
    cfg_path = None
    if scenes_dir is not None:
        cfg_path = next((p for p in (Path(scenes_dir) / "verify.yaml", Path(scenes_dir).parent / "verify.yaml")
                         if p.is_file()), None)
    roots = asset_roots(storyboard, out_dir) if storyboard is not None else [Path(out_dir).resolve()]
    try:
        project = irender.Project(timeline=paths.render_timeline, scenes_dir=scenes_dir, pauses=paths.pauses,
                                  asset_roots=roots)
        ver = Verifier(irender.Renderer(project), paths.final_mp4, paths.checks, config=load_config(cfg_path),
                       config_dir=cfg_path.parent if cfg_path else None, ffmpeg=ffmpeg, ffprobe=ffprobe, log=log)
        d = ver.run()
    except (VerifyError, SceneError, TimelineError, LayoutError, irender.RenderError, OSError,
            subprocess.SubprocessError, ValueError) as e:
        return {"status": "failed", "ok": False, "error": str(e), "failed": ["verify"]}
    finally:
        engine.set_asset_roots([])
    failed = [k for k in VERIFY_KEYS if (d.get(k) or {}).get("ok") is False]
    return {"status": "ok" if d.get("ok") else "needs_review", "ok": bool(d.get("ok")), "failed": failed,
            "config": str(cfg_path) if cfg_path else None, "result": str(paths.checks / "verify.json"),
            "report": str(paths.checks / "検証結果.md")}


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


__all__ = ["InteractiveError", "InteractivePaths", "VERIFY_KEYS", "asset_roots", "find_scenes_dir", "narration_texts",
           "precheck_scenes", "render_storyboard", "resolve_render_mode", "scenes_dir_for", "verify_storyboard"]
