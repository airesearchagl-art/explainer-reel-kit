# -*- coding: utf-8 -*-
"""レンダラー: 中間データ ＋ 場面コード → MP4。

1. 600 フレームごとの区間に分け、RGB の生フレームを ffmpeg に流して H.264 にする
   （``libx264 -crf 15 -preset medium -g 60 -pix_fmt yuv420p``、色は bt709・limited を明示、``-video_track_timescale 15360``）
2. 区間のファイルを concat demuxer で ``-c copy`` 連結する
3. 音声の正本（MP4 など）があれば、その音声トラックを ``-map 1:a:0 -c copy`` で結合する（再エンコードしない）。
   無ければ映像だけの MP4（erkit make はこの後 mux でナレーションを入れる）

はまりやすい点を仕組みで防ぐ:
- 1: 区間は 600 フレーム固定（30 の倍数）。場面の境界では切らない（最後の区間だけ短い）
- 2: 書き出しの scale で ``out_color_matrix=bt709:out_range=limited``、コンテナにも bt709 を書く（取り出しは verify が明示）
- 6: ``-movie_timescale`` は ffmpeg が対応しているとき（5 以降）だけ付ける（古い ffmpeg では音声の長さの表示がミリ秒に丸まる）
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import engine
from .engine import Frame, LayoutError, raster
from .scenes import SceneSet, default_scene, draw_credit, load_scenes
from .subtitles import draw_subtitle, write_srt
from .timeline import Timeline, load_pauses, load_timeline_doc

CHUNK = 600            # 1 区間のフレーム数（30 の倍数で固定。連結で時刻がずれないように）
TIMESCALE = 15360      # 映像トラックの timescale（30 fps の 512 倍）
X264 = ['-c:v', 'libx264', '-profile:v', 'high', '-preset', 'medium', '-crf', '15', '-g', '60',
        '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
        '-color_range', 'tv', '-video_track_timescale', str(TIMESCALE)]
VF = 'scale=out_color_matrix=bt709:out_range=limited,format=yuv420p'
FF = ['-nostdin', '-hide_banner', '-v', 'error']
PKG_DIR = Path(__file__).resolve().parent


class RenderError(RuntimeError):
    """描けない・ffmpeg が失敗した。"""


@dataclass
class Project:
    """描くのに要るもの。場面コードのフォルダ・静止画のフォルダは scenes.load_scenes の決まりで探す。"""

    timeline: Path
    scenes_dir: Path | None = None
    pauses: Path | None = None
    extra_asset_dirs: list[Path] = field(default_factory=list)
    #: 空でなければ、静止画はこの下のファイルだけを読む（erkit make: 台本のフォルダと出力フォルダ）
    asset_roots: list[Path] = field(default_factory=list)

    @classmethod
    def from_dir(cls, project_dir: Path, timeline: Path | None = None, scenes_dir: Path | None = None,
                 pauses: Path | None = None) -> "Project":
        """プロジェクトのフォルダの決まりの置き場: data\\render-timeline.json、scenes\\、data\\pauses.json。"""
        d = Path(project_dir)
        return cls(timeline=Path(timeline) if timeline else d / "data" / "render-timeline.json",
                   scenes_dir=Path(scenes_dir) if scenes_dir else d / "scenes",
                   pauses=Path(pauses) if pauses else d / "data" / "pauses.json")


class Renderer:
    """フレーム番号 → 表示リスト・画像。"""

    def __init__(self, project: Project):
        self.project = project
        engine.set_asset_roots(project.asset_roots)
        doc = load_timeline_doc(project.timeline)
        ids = [s["id"] for s in doc["scenes"]]
        self.scenes: SceneSet = load_scenes(project.scenes_dir, ids, extra_asset_dirs=project.extra_asset_dirs)
        self.T = Timeline(doc, base_dir=Path(project.timeline).parent, pauses=load_pauses(project.pauses),
                          weights=self.scenes.at_weights)
        self.scenes.compile(self.T)   # scenes.yaml の場面（きっかけ・はみ出しはここで確かめる）
        self.last_id = ids[-1]
        self.asset_dirs = list(engine.ASSET_DIRS)

    def activate(self) -> None:
        """この描き手の静止画の置き場に戻す（2 つの描き手を並べて使うとき。sheet --against-scenes）。"""
        if list(engine.ASSET_DIRS) != self.asset_dirs:
            engine.set_asset_dirs(self.asset_dirs)
        roots = [Path(d).resolve() for d in self.project.asset_roots]
        if list(engine.ASSET_ROOTS) != roots:
            engine.set_asset_roots(roots)

    def layers(self, frame: int) -> tuple[tuple, tuple]:
        """(場面の表示リスト, 字幕の表示リスト)。時刻はフレームの先頭（frame / fps 秒）。"""
        T = self.T
        f = Frame()
        sc = T.scene_at(frame)
        t = frame / T.fps
        try:
            fn = self.scenes.funcs.get(sc["id"])
            if fn is not None:
                fn(f, t, T)
            else:
                default_scene(f, t, T, sc)
            if sc["id"] == self.last_id:
                draw_credit(f, T)
            n = len(f.ops)
            (self.scenes.subtitle or draw_subtitle)(f, frame, T)
        except LayoutError as e:
            raise LayoutError(f"場面 {sc['id']}、{t:.2f}s（フレーム {frame}）: {e}") from e
        return tuple(f.ops[:n]), tuple(f.ops[n:])

    def build_ops(self, frame: int) -> tuple:
        a, b = self.layers(frame)
        return a + b

    def frame_image(self, frame: int):
        return raster(self.build_ops(frame))


# ---------------------------------------------------------------- ffmpeg の引数

def plan_chunks(nframes: int, chunk: int = CHUNK) -> list[tuple[int, int]]:
    """区間 [(開始, 終わり)]。場面の境界に関係なく chunk フレームごと（最後だけ短い）。"""
    if chunk % 30:
        raise ValueError("区間のフレーム数は 30 の倍数にしてください（連結で時刻がずれるため）")
    return [(a, min(nframes, a + chunk)) for a in range(0, nframes, chunk)]


def encode_command(ffmpeg: str, out: Path, fps: int = engine.FPS, width: int = engine.W,
                   height: int = engine.H) -> list[str]:
    return [ffmpeg, *FF, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps),
            '-i', '-', '-vf', VF, '-r', str(fps), *X264, str(out)]


def concat_command(ffmpeg: str, list_file: Path, out: Path) -> list[str]:
    return [ffmpeg, *FF, '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file), '-c', 'copy',
            '-video_track_timescale', str(TIMESCALE), str(out)]


def mux_command(ffmpeg: str, video: Path, audio_source: Path, out: Path, movie_timescale: int | None) -> list[str]:
    ts = ['-movie_timescale', str(movie_timescale)] if movie_timescale else []
    return [ffmpeg, *FF, '-y', '-i', str(video), '-i', str(audio_source), '-map', '0:v:0', '-map', '1:a:0',
            '-c', 'copy', *ts, '-movflags', '+faststart', str(out)]


def supports_movie_timescale(ffmpeg: str) -> bool:
    """mp4 の muxer が -movie_timescale に対応しているか（ffmpeg 5 以降）。"""
    res = subprocess.run([ffmpeg, '-hide_banner', '-h', 'muxer=mp4'], capture_output=True)
    return 'movie_timescale' in res.stdout.decode('utf-8', 'replace')


def audio_sample_rate(ffprobe: str, path: Path) -> int | None:
    res = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=sample_rate',
                          '-of', 'default=noprint_wrappers=1:nokey=1', str(path)], capture_output=True, text=True)
    try:
        return int(res.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        return None


def _need(tool: str) -> None:
    if shutil.which(tool) is None and not Path(tool).is_file():
        raise RenderError(f"{tool} が見つかりません（PATH に追加するか --ffmpeg / --ffprobe で指定）")


# ---------------------------------------------------------------- 区間を描く

def seg_path(build: Path, a: int, b: int) -> Path:
    return Path(build) / f"seg_{a:05d}_{b:05d}.mp4"


def render_segment(r: Renderer, a: int, b: int, out: Path, ffmpeg: str = 'ffmpeg') -> dict:
    """フレーム [a, b) を 1 つの区間ファイルにする。表示リストが前と同じなら描画を使い回す。"""
    out = Path(out)
    tmp = out.with_name(out.stem + '.part.mp4')
    p = subprocess.Popen(encode_command(ffmpeg, tmp, r.T.fps, r.T.width, r.T.height), stdin=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    prev, data, drawn = None, None, 0
    t0 = time.time()
    try:
        for fr in range(a, b):
            ops = r.build_ops(fr)
            if ops != prev:
                data = raster(ops).tobytes()
                prev = ops
                drawn += 1
            p.stdin.write(data)
    except BaseException:
        p.kill()
        p.wait()
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if p.stdin and not p.stdin.closed:
            try:
                p.stdin.close()
            except OSError:
                pass
    err = p.stderr.read().decode('utf-8', 'replace') if p.stderr else ''
    if p.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise RenderError(f"ffmpeg（区間 {a}-{b}）が失敗しました: {err.strip()[-800:]}")
    os.replace(tmp, out)
    return {"a": a, "b": b, "frames": b - a, "drawn": drawn, "sec": round(time.time() - t0, 2), "log": dict(r.T.log)}


_WORKER: Renderer | None = None


def _init_worker(project: Project) -> None:
    global _WORKER
    _WORKER = Renderer(project)


def _work(args: tuple[int, int, str, str]) -> dict:
    a, b, out, ffmpeg = args
    assert _WORKER is not None
    return render_segment(_WORKER, a, b, Path(out), ffmpeg)


# ---------------------------------------------------------------- 入力のハッシュ（区間を使い回してよいか）

def input_stamp(r: Renderer) -> dict:
    """描いた絵を決めるもの（中間データ・pauses・場面コード・静止画・このパッケージのコードと書体・書き出しの設定）のハッシュ。"""
    h = hashlib.sha256()

    def add(label: str, path: Path) -> None:
        h.update(label.encode('utf-8') + b'\0')
        h.update(Path(path).read_bytes() if Path(path).is_file() else b'<missing>')

    add('timeline', r.project.timeline)
    if r.project.pauses:
        add('pauses', r.project.pauses)
    for p in r.scenes.files:
        add(f'scene:{p.name}', p)
    for d in engine.ASSET_DIRS:
        if d.is_dir():
            for p in sorted(d.rglob('*')):
                if p.is_file():
                    add(f'asset:{p.relative_to(d).as_posix()}', p)
    for sc in r.T.scenes:   # 既定の場面の画像（work\assets の外にあることもある）
        if sc.get('image'):
            add(f'image:{sc["id"]}', Path(sc['image']))
    for p in sorted(PKG_DIR.rglob('*.py')):   # parts\ の部品も
        add(f'pkg:{p.relative_to(PKG_DIR).as_posix()}', p)
    for p in sorted(engine.FONT_DIR.glob('*.otf')):   # 書体が変われば絵も変わる
        add(f'font:{p.name}', p)
    h.update(json.dumps([X264, VF, CHUNK]).encode('utf-8'))
    return {"sha256": h.hexdigest()}


def render(project: Project, out: Path, *, build_dir: Path | None = None, ffmpeg: str = 'ffmpeg',
           ffprobe: str = 'ffprobe', jobs: int | None = None, audio_source: Path | None = None,
           force: bool = False, srt: Path | bool = True, log: Callable[[str], None] = print) -> dict:
    """全編を描いて MP4 にする。戻り値は記録（run.json・checks に残す形）。

    srt: 焼き込みと同じ cues から書く SRT。True なら MP4 の隣（拡張子 .srt）、False なら書かない。

    build_dir の区間ファイルは、入力のハッシュが同じなら使い回す（途中で止めても続きから）。force で描き直す。
    """
    _need(ffmpeg)
    out = Path(out)
    build = Path(build_dir) if build_dir else out.parent / 'build'
    build.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    r = Renderer(project)
    T = r.T
    stamp = input_stamp(r)
    stamp_file = build / 'stamp.json'
    old = json.loads(stamp_file.read_text(encoding='utf-8')) if stamp_file.is_file() else None
    if force or old != stamp:
        for p in build.glob('seg_*.mp4'):
            p.unlink()
    stamp_file.write_text(json.dumps(stamp) + '\n', encoding='utf-8')

    chunks = plan_chunks(T.nframes)
    todo = [(a, b) for a, b in chunks if not seg_path(build, a, b).is_file()]
    jobs = max(1, jobs or min(4, os.cpu_count() or 1))
    log(f"[interactive] {T.nframes} フレーム（{T.total:.3f}s）、区間 {len(chunks)}（描く {len(todo)}）、並列 {min(jobs, max(1, len(todo)))}")
    results: list[dict] = []
    if todo:
        if jobs > 1 and len(todo) > 1:
            args = [(a, b, str(seg_path(build, a, b)), ffmpeg) for a, b in todo]
            try:
                with ProcessPoolExecutor(max_workers=min(jobs, len(todo)), initializer=_init_worker,
                                         initargs=(project,)) as ex:
                    for res in ex.map(_work, args):
                        results.append(res)
                        log(f"[interactive] seg {res['a']:05d}-{res['b']:05d} {res['frames']} frames"
                            f"（描いた {res['drawn']}）{res['sec']}s")
            except LayoutError:
                raise
            except Exception as e:
                if isinstance(e, RenderError):
                    raise
                raise RenderError(f"区間を描けませんでした: {type(e).__name__}: {e}") from e
        else:
            for a, b in todo:
                res = render_segment(r, a, b, seg_path(build, a, b), ffmpeg)
                results.append(res)
                log(f"[interactive] seg {a:05d}-{b:05d} {res['frames']} frames（描いた {res['drawn']}）{res['sec']}s")

    lst = build / 'concat.txt'
    lst.write_text(''.join(f"file '{seg_path(build, a, b).name}'\n" for a, b in chunks), encoding='utf-8')
    video = build / 'video_only.mp4'
    _run(concat_command(ffmpeg, lst, video), '区間の連結')
    ts = None
    if audio_source is not None:
        audio_source = Path(audio_source)
        if not audio_source.is_file():
            raise RenderError(f"音声の正本がありません: {audio_source}")
        if supports_movie_timescale(ffmpeg):
            ts = audio_sample_rate(ffprobe, audio_source) if shutil.which(ffprobe) or Path(ffprobe).is_file() else None
        muxed = build / 'muxed.mp4'
        _run(mux_command(ffmpeg, video, audio_source, muxed, ts), '音声の結合')
        src = muxed
    else:
        src = video
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + '.part' + out.suffix)
    shutil.copyfile(src, tmp)   # 出来上がってから名前を付ける（途中で止まっても壊れた MP4 を残さない）
    os.replace(tmp, out)
    drawn = sum(x['drawn'] for x in results)
    srt_path = out.with_suffix('.srt') if srt is True else (Path(srt) if srt else None)
    if srt_path is not None:
        write_srt(timeline_cues(T), T.fps, srt_path)
    record = {
        "output": str(out), "frames": T.nframes, "duration_sec": round(T.total, 6), "fps": T.fps,
        "size": [T.width, T.height], "chunk": CHUNK, "segments": len(chunks), "rendered_segments": len(results),
        "drawn_frames": drawn, "jobs": jobs, "elapsed_sec": round(time.time() - t_start, 1),
        "x264": X264, "vf": VF, "movie_timescale": ts, "audio_source": str(audio_source) if audio_source else None,
        "scenes": r.scenes.record(), "stamp": stamp["sha256"], "srt": str(srt_path) if srt_path else None,
    }
    log(f"[interactive] wrote {out}（描いたフレーム {drawn}、{record['elapsed_sec']}s）")
    return record


def timeline_cues(T: Timeline) -> list[dict]:
    """Timeline の字幕を中間データの形（text・start_frame・end_frame・lines）で。"""
    return [{"text": c["text"], "start_frame": c["f0"], "end_frame": c["f1"], **({"lines": c["lines"]} if c.get("lines") else {})}
            for c in T.cues]


def _run(cmd: list[str], what: str) -> None:
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        raise RenderError(f"ffmpeg（{what}）が失敗しました: {res.stderr.decode('utf-8', 'replace').strip()[-800:]}")
