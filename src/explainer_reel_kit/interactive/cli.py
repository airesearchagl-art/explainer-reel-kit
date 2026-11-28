"""python -m explainer_reel_kit.interactive {analyze-audio,render,sheet,stills,verify,schema,gallery}

コード描画（render_mode: interactive）の道具。台本からは ``erkit make --render-mode interactive`` が
同じ部品を呼ぶ。ここのコマンドは、中間データ（render timeline）と場面コードのフォルダ（プロジェクト）を直接扱う
（中間データは erkit make が出力フォルダの work/render-timeline.json に書く）。

プロジェクトのフォルダの決まりの置き場（どれも引数で変えられる）::

    <プロジェクト>\\
      scenes\\                 場面コード（index.py か <場面 id>.py）と場面の指定 scenes.yaml。scenes\\assets\\ も静止画の置き場
      assets\\                 静止画
      data\\render-timeline.json  中間データ（erkit make が作ったものを写すか --timeline で指定）
      data\\pauses.json        文中の無音（analyze-audio で作る。無くてもよい）
      verify.yaml             画面の文字の禁止語など（verify）

  analyze-audio  音声から文中の無音を取り出す（data\\pauses.json）
  render         全編を描いて MP4 にする（--audio-source の音声トラックをそのまま結合）
  sheet          指定した秒のフレームを 2×2 に並べた一覧画像（checks\\sheets\\）。--cues で scenes.yaml のきっかけごとに 3 枚
  stills         指定した秒の静止画（checks\\stills\\）
  verify         出来上がった MP4 の検証（checks\\verify.json・検証結果.md）
  schema         scenes.yaml の JSON スキーマを書き出す（パッケージの data/schema/scenes.schema.json）。--check で同じか確かめる
  gallery        部品の見本の静止画（型ごと。ダミーの中身）

終了コード: 0 成功 / 1 検証が「要確認」・描けない / 2 引数・入力の誤り
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import LayoutError
from .timeline import TimelineError


def _project_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--project", required=True, type=Path, help="プロジェクトのフォルダ（scenes・assets・data）")
    p.add_argument("--timeline", type=Path, help=r"中間データ（既定 <project>\data\render-timeline.json）")
    p.add_argument("--scenes", type=Path, help=r"場面コードのフォルダ（既定 <project>\scenes）")
    p.add_argument("--pauses", type=Path, help=r"文中の無音（既定 <project>\data\pauses.json。無ければ使わない）")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m explainer_reel_kit.interactive",
                                 description="コード描画（interactive）の道具: 変換・描画・確かめ・検証")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze-audio", help="音声から文中の無音を取り出す")
    _project_args(a)
    a.add_argument("--audio", required=True, type=Path, help="音声（MP4・WAV）。音声は変えない")
    a.add_argument("--out", type=Path, help=r"既定 <project>\data\pauses.json")
    a.add_argument("--ffmpeg", default="ffmpeg")

    r = sub.add_parser("render", help="全編を描いて MP4 にする")
    _project_args(r)
    r.add_argument("--out", required=True, type=Path, help="出力 MP4（checks・build はこのフォルダの下）")
    r.add_argument("--audio-source", type=Path, help="音声の正本（この音声トラックを再エンコードせずに結合）")
    r.add_argument("--build", type=Path, help=r"区間ファイルの置き場（既定 <出力のフォルダ>\build）")
    r.add_argument("--jobs", type=int, help="並列の数（既定は CPU の数と 4 の小さい方）")
    r.add_argument("--force", action="store_true", help="区間ファイルを使い回さずに描き直す")
    r.add_argument("--verify", action="store_true", help="描いた後に verify を続けて行う（--audio-source を正本として比べる）")
    r.add_argument("--ffmpeg", default="ffmpeg")
    r.add_argument("--ffprobe", default="ffprobe")

    for name, help_ in (("sheet", "指定した秒のフレームを 2×2 に並べた一覧画像"), ("stills", "指定した秒の静止画")):
        s = sub.add_parser(name, help=help_)
        _project_args(s)
        s.add_argument("--out-dir", type=Path, help=rf"既定 <project>\checks\{name}s")
        if name == "sheet":
            s.add_argument("--name", default="sheet", help="一覧画像の名前（<name>_00.jpg …）")
            s.add_argument("--cues", action="store_true",
                           help="scenes.yaml の場面ごとに、きっかけの前・直後・終わりの 3 枚を並べる（<場面 id>_cues_NN.jpg）")
            s.add_argument("--against-scenes", type=Path,
                           help="--cues と一緒に: 同じ時刻の絵をこの場面コードのフォルダでも描いて次の行に並べる（見比べ）")
            s.add_argument("--scene", action="append", help="--cues で一覧にする場面 id（何度でも。既定はすべて）")
        s.add_argument("times", nargs="*", type=float, help="秒（--cues のときは要らない）")

    g = sub.add_parser("gallery", help="部品の見本の静止画（型ごと。ダミーの中身）")
    g.add_argument("--out", required=True, type=Path, help="書き出すフォルダ（リポジトリの外か checks の下。PNG は commit しない）")
    g.add_argument("--type", action="append", help="型の名前（何度でも。既定はすべて）")

    sc = sub.add_parser("schema", help="scenes.yaml の JSON スキーマを書き出す")
    sc.add_argument("--out", type=Path, help="既定 パッケージの data/schema/scenes.schema.json")
    sc.add_argument("--check", action="store_true", help="書き出さずに、ファイルが今の部品と同じか確かめる（違えば 1）")

    v = sub.add_parser("verify", help="出来上がった MP4 の検証")
    _project_args(v)
    v.add_argument("--video", required=True, type=Path)
    v.add_argument("--audio-ref", type=Path, help="音声の正本（AAC のパケット・PCM の MD5 を比べる）")
    v.add_argument("--checks", type=Path, help=r"記録の置き場（既定 <MP4 のフォルダ>\checks）")
    v.add_argument("--config", type=Path, help=r"verify.yaml（既定 <project>\verify.yaml）")
    v.add_argument("--steps", default="all", help="probe,decode,audio,subs,frames,text（既定 all）")
    v.add_argument("--ffmpeg", default="ffmpeg")
    v.add_argument("--ffprobe", default="ffprobe")
    return ap


def _project(args):
    from .render import Project

    proj = Project.from_dir(args.project, args.timeline, args.scenes, args.pauses)
    if not proj.timeline.is_file():
        raise TimelineError(f"中間データがありません: {proj.timeline}（erkit make の work/render-timeline.json を --timeline で指定）")
    return proj


def _verify(args, proj, video: Path, audio_ref: Path | None, checks: Path | None, config: Path | None,
            steps: str = "all") -> int:
    from .render import Renderer
    from .verify import STEPS, Verifier, load_config

    cfg_path = config or (args.project / "verify.yaml")
    ver = Verifier(Renderer(proj), video, checks or (video.parent / "checks"), config=load_config(cfg_path),
                   config_dir=cfg_path.parent, audio_ref=audio_ref, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe,
                   log=lambda s: print(s, file=sys.stderr))
    res = ver.run(list(STEPS) if steps == "all" else [s.strip() for s in steps.split(",") if s.strip()])
    return 0 if res.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    log = lambda s: print(s, file=sys.stderr)  # noqa: E731
    try:
        if args.cmd == "gallery":
            from .gallery import SAMPLES, make_gallery

            unknown = [t for t in (args.type or []) if t not in SAMPLES]
            if unknown:
                print(f"ERROR 知らない型: {unknown}（型: {', '.join(SAMPLES)}）", file=sys.stderr)
                return 2
            print("\n".join(str(p) for p in make_gallery(args.out, args.type)))
            return 0
        if args.cmd == "schema":
            from .spec import SCHEMA_FILE, json_schema

            out = args.out or SCHEMA_FILE
            text = json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n"
            if args.check:
                same = out.is_file() and out.read_text(encoding="utf-8") == text
                print(f"{'OK' if same else 'DIFF'} {out}")
                return 0 if same else 1
            out.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {out}")
            return 0
        proj = _project(args)
        if args.cmd == "analyze-audio":
            from .audio import analyze
            from .timeline import load_timeline_doc

            out = args.out or (args.project / "data" / "pauses.json")
            pauses = analyze(args.audio, load_timeline_doc(proj.timeline), out, ffmpeg=args.ffmpeg)
            print(f"wrote {out}（無音 {sum(len(v) for v in pauses.values())} か所）")
            return 0

        if args.cmd == "render":
            from .render import render

            rec = render(proj, args.out, build_dir=args.build, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe,
                         jobs=args.jobs, audio_source=args.audio_source, force=args.force, log=log)
            checks = args.out.parent / "checks"
            checks.mkdir(parents=True, exist_ok=True)
            (checks / "render.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"wrote {args.out}")
            if args.verify:
                return _verify(args, proj, args.out, args.audio_source, None, None)
            return 0

        if args.cmd in ("sheet", "stills"):
            from .render import Project, Renderer
            from .sheet import make_cue_sheets, make_sheets, make_stills

            out_dir = args.out_dir or (args.project / "checks" / f"{args.cmd}s")
            if args.cmd == "sheet" and args.cues:
                against = None
                if args.against_scenes:
                    against = Renderer(Project(timeline=proj.timeline, scenes_dir=args.against_scenes,
                                               pauses=proj.pauses))
                r = Renderer(proj)
                if not r.scenes.compiled:
                    print("ERROR scenes.yaml で描く場面がありません（--cues は scenes.yaml の場面のきっかけを並べる）",
                          file=sys.stderr)
                    return 2
                paths = make_cue_sheets(r, out_dir, against=against, scenes=args.scene)
                print("\n".join(str(p) for p in paths))
                return 0
            if not args.times:
                print("ERROR 秒を 1 つ以上書きます（sheet は --cues でも作れる）", file=sys.stderr)
                return 2
            r = Renderer(proj)
            paths = (make_sheets(r, args.name, args.times, out_dir) if args.cmd == "sheet"
                     else make_stills(r, args.times, out_dir))
            print("\n".join(str(p) for p in paths))
            return 0

        if args.cmd == "verify":
            return _verify(args, proj, args.video, args.audio_ref, args.checks, args.config, args.steps)
    except (TimelineError, LayoutError) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 2
    except Exception as e:  # 場面コード・ffmpeg の失敗は段の名前を添えて止める
        from .render import RenderError
        from .scenes import SceneError
        from .verify import VerifyError

        if isinstance(e, (RenderError, SceneError, VerifyError)):
            print(f"ERROR [{args.cmd}] {e}", file=sys.stderr)
            return 1
        raise
    return 2
