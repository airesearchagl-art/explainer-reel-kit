"""無音 MP4 ＋ シーン別 WAV → ナレーション付き MP4。

- 各スライドの開始時刻は .pptx の自動切替（p:transition advTm）と切替効果の長さから計算する
- 各 WAV は「スライド開始 ＋（切替効果の長さ）＋ pre_pause_sec」に置く（余白は WAV に含まれない）
- 音声トラックは ffmpeg の filter_complex で「無音 → WAV → 無音 → …」を連結して作り、映像はコピー（再エンコードしない）
- 映像と（計算上の）スライド合計時間、最終 MP4 の映像と音声の長さの差が 0.2 秒を超えたら警告
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from lxml import etree

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
NS = {"p": P_NS, "mc": MC_NS}
SLIDE_NAME_PREFIX = "er:"  # deck が付けるスライド名（er:<シーン id> / er:<シーン id>#<n>）
TOLERANCE_SEC = 0.2
MAX_MORPH_EXTRA_SEC = 0.5  # Morph 1 か所あたりの追加時間の上限（これを超える差は補正しない）
SAMPLE_RATE = 44100
# PowerPoint の切替速度（spd）の長さ（ms）
TRANSITION_SPEED_MS = {"fast": 500, "med": 750, "slow": 1000}
DURATIONS_FORMAT = "explainer-reel/narration-durations"

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class MuxError(Exception):
    """合成できない（入力の不足・不整合、ffmpeg の失敗）。"""


@dataclass
class SlideTiming:
    """シーン 1 つ分の表示時間。zoom: per_mark で分けたスライドは 1 つにまとめる（parts に枚数）。"""

    index: int
    id: str
    start_ms: int  # 映像内でのシーン（最初のスライド）の開始時刻
    adv_ms: int  # 自動切替秒数（advTm）。分けたスライドは、後ろのスライドの advTm と変形の長さも含む
    transition_ms: int  # シーンに入るときの切替効果の長さ（無ければ 0）
    parts: int = 1
    morphs_before: int = 0  # このシーンが表示されるまでに通る Morph の数（入るときの Morph を含む）
    morphs_inside: int = 0  # zoom: per_mark で分けたスライドの間の Morph の数


@dataclass
class Segment:
    id: str
    wav: Path
    start_sec: float
    length_sec: float


@dataclass
class MuxResult:
    output: Path
    expected_sec: float
    video_sec: float | None = None
    output_audio_sec: float | None = None
    output_video_sec: float | None = None
    command: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    morph_count: int = 0
    morph_extra_sec: float = 0.0  # Morph 1 か所あたりの追加時間（補正に使った値。補正しないときは 0）
    drift_corrected: bool = False


# ---------------------------------------------------------------- timings

def _slide_names(zf: zipfile.ZipFile) -> list[str]:
    """プレゼンテーションの表示順にスライドの XML パスを返す。"""
    rels = etree.fromstring(zf.read("ppt/_rels/presentation.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    pres = etree.fromstring(zf.read("ppt/presentation.xml"))
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    names = []
    for sld in pres.findall("p:sldIdLst/p:sldId", NS):
        target = targets[sld.get(rid_attr)]
        names.append("ppt/" + target.lstrip("/").removeprefix("ppt/"))
    return names


def _transition_info(root) -> tuple[int, int, bool]:
    """(advTm, 切替効果の長さ ms, Morph か)。Morph は mc:AlternateContent の Choice（p14:dur）を読む。"""
    morph = False
    tr = root.find("p:transition", NS)
    if tr is None:
        ac = root.find("mc:AlternateContent", NS)
        tr = ac.find("mc:Choice/p:transition", NS) if ac is not None else None
        morph = tr is not None
    if tr is None or tr.get("advTm") is None:
        raise KeyError("advTm")
    adv = int(tr.get("advTm"))
    if len(tr) == 0:
        return adv, 0, False
    dur = tr.get(f"{{{P14_NS}}}dur")
    return adv, (int(dur) if dur is not None else TRANSITION_SPEED_MS.get(tr.get("spd", "fast"), 500)), morph


def _transition(root) -> tuple[int, int]:
    adv, trans, _ = _transition_info(root)
    return adv, trans


def read_slide_timings(pptx: Path, ids: Sequence[str], transition_before_timer: bool = True) -> list[SlideTiming]:
    """.pptx からシーンごとの開始時刻を計算する。

    スライドに deck の名前（er:<id>、分けたスライドは er:<id>#<n>）があれば、それでシーンにまとめる。
    名前が無い .pptx は、スライドの順と ids を 1 対 1 で対応させる（従来どおり）。
    transition_before_timer=True: 切替効果が終わってから自動切替のタイマーが始まる前提
    （スライドの表示時間 = 切替効果 + advTm）。False なら切替効果は advTm に含まれる前提。
    """
    with zipfile.ZipFile(pptx) as zf:
        names = _slide_names(zf)
        roots = [etree.fromstring(zf.read(n)) for n in names]
    slide_names = []
    for r in roots:
        c = r.find("p:cSld", NS)
        slide_names.append(c.get("name", "") if c is not None else "")
    if roots and all(n.startswith(SLIDE_NAME_PREFIX) for n in slide_names):
        scene_of = [n[len(SLIDE_NAME_PREFIX):].split("#")[0] for n in slide_names]
        order = list(dict.fromkeys(scene_of))
        if order != list(ids):
            raise MuxError(f".pptx のシーン {order} が台本の id {list(ids)} と一致しません")
    else:
        if len(roots) != len(ids):
            raise MuxError(f".pptx のスライド数 {len(roots)} と台本の id 数 {len(ids)} が一致しません")
        scene_of = list(ids)

    out: list[SlideTiming] = []
    t = 0
    morphs = 0
    for i, (root, sid) in enumerate(zip(roots, scene_of)):
        try:
            adv, trans, is_morph = _transition_info(root)
        except KeyError:
            raise MuxError(f"スライド {i + 1}（{sid}）に自動切替（advTm）がありません") from None
        morphs += int(is_morph)
        shown = adv + (trans if transition_before_timer else 0)
        if out and out[-1].id == sid:  # 分けたスライドの続き: 変形の長さも含めてシーンにまとめる
            out[-1].adv_ms += shown
            out[-1].parts += 1
            out[-1].morphs_inside += int(is_morph)
        else:
            out.append(SlideTiming(len(out), sid, t, adv, trans, morphs_before=morphs))
        t += shown
    return out


def count_morphs(timings: Sequence[SlideTiming]) -> int:
    """動画の中の Morph の切替の数。"""
    if not timings:
        return 0
    last = timings[-1]
    return last.morphs_before + last.morphs_inside


def morph_drift(video_sec: float | None, expected_sec: float, morph_count: int) -> tuple[float, bool, str | None]:
    """Morph のずれの補正量。

    PowerPoint の Morph は p14:dur より少し長く再生される（Windows 実測で 1 か所あたり約 0.13〜0.14 秒）。
    PC ごとの定数を持たず、無音 MP4 の実際の長さとスライド秒数の合計との差を Morph の数で割って求める。
    戻り値 (1 か所あたりの追加秒, 補正するか, 補正しない理由)。Morph が無ければ (0, False, None)。
    """
    if morph_count <= 0 or video_sec is None:
        return 0.0, False, None
    diff = video_sec - expected_sec
    if diff < 0:
        return 0.0, False, f"無音 MP4 がスライド秒数の合計より {diff:+.2f}s 短いため、Morph のずれは補正しません"
    per = diff / morph_count
    if per > MAX_MORPH_EXTRA_SEC:
        return 0.0, False, (f"無音 MP4 とスライド秒数の合計の差 {diff:+.2f}s が、Morph {morph_count} か所に対して大きすぎる"
                            f"（1 か所あたり {per:.2f}s ＞ {MAX_MORPH_EXTRA_SEC}s）ため、補正しません")
    return per, True, None


def pptx_total_sec(pptx: Path, transition_before_timer: bool = True) -> float:
    """.pptx の全スライドの表示時間の合計（台本の id と突き合わせない）。"""
    with zipfile.ZipFile(pptx) as zf:
        roots = [etree.fromstring(zf.read(n)) for n in _slide_names(zf)]
    total = 0
    for r in roots:
        adv, trans = _transition(r)
        total += adv + (trans if transition_before_timer else 0)
    return total / 1000


def expected_total_sec(timings: Sequence[SlideTiming], transition_before_timer: bool = True) -> float:
    return sum(s.adv_ms + (s.transition_ms if transition_before_timer else 0) for s in timings) / 1000


# ---------------------------------------------------------------- durations / wav

def load_durations(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise MuxError(f"durations.json を読めません: {e}") from e
    if data.get("format") != DURATIONS_FORMAT:
        raise MuxError(f"durations.json の format が '{DURATIONS_FORMAT}' ではありません")
    return data


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def plan_segments(timings: Sequence[SlideTiming], durations: dict[str, Any], wav_dir: Path,
                  transition_before_timer: bool = True, morph_extra_sec: float = 0.0) -> tuple[list[Segment], list[str]]:
    """各 WAV をどこに置くか。戻り値 (区間, 警告)。

    morph_extra_sec: Morph 1 か所あたりの追加時間。シーンより前にある Morph の数だけ後ろへずらす。
    """
    warnings: list[str] = []
    if durations.get("complete") is False:
        warnings.append("durations.json が complete=false です（ナレーション生成が途中で失敗した記録）")
    pre = float(durations.get("pre_pause_sec", 0.3))
    items = {it["id"]: it for it in durations.get("items") or [] if isinstance(it, dict) and "id" in it}
    segs: list[Segment] = []
    for st in timings:
        item = items.get(st.id)
        if item is None:
            warnings.append(f"{st.id}: durations.json に記録がないため、このスライドは無音です")
            continue
        wav = Path(wav_dir) / item.get("wav", f"{st.id}.wav")
        if not wav.is_file():
            raise MuxError(f"{st.id}: WAV がありません: {wav}")
        offset = st.transition_ms if transition_before_timer else 0
        start = (st.start_ms + offset) / 1000 + pre + st.morphs_before * morph_extra_sec
        length = wav_seconds(wav)
        slot_end = (st.start_ms + offset + st.adv_ms) / 1000 + (st.morphs_before + st.morphs_inside) * morph_extra_sec
        if start + length > slot_end + 0.001:
            warnings.append(
                f"{st.id}: ナレーション（{length:.2f}s）がスライドの表示時間を {start + length - slot_end:.2f}s 超えます。"
                "deck を --durations 付きで作り直してください"
            )
        segs.append(Segment(st.id, wav, round(start, 3), round(length, 3)))
    return segs, warnings


# ---------------------------------------------------------------- ffmpeg

_AFMT = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=mono"


def build_ffmpeg_command(ffmpeg: str, video: Path, segments: Sequence[Segment], total_sec: float, out: Path,
                         overwrite: bool = False) -> tuple[list[str], list[str]]:
    """合成コマンドを組み立てる。戻り値 (コマンド, 警告)。

    音声 = [無音 gap0][wav0][無音 gap1][wav1]…[無音 tail]（concat）。重なる場合は後ろへずらし警告。
    """
    warnings: list[str] = []
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y" if overwrite else "-n", "-i", str(video)]
    for s in segments:
        cmd += ["-i", str(s.wav)]
    parts: list[str] = []
    labels: list[str] = []
    cursor = 0.0

    def gap(sec: float) -> None:
        if sec <= 0.0005:
            return
        lab = f"g{len(labels)}"
        parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=mono,atrim=duration={sec:.3f},{_AFMT}[{lab}]")
        labels.append(lab)

    order = sorted(range(len(segments)), key=lambda i: segments[i].start_sec)
    for k, i in enumerate(order):
        s = segments[i]
        if s.start_sec < cursor - 0.0005:
            warnings.append(f"{s.id}: 前のナレーションと {cursor - s.start_sec:.2f}s 重なるため後ろへずらしました")
        gap(s.start_sec - cursor)
        lab = f"w{k}"
        parts.append(f"[{i + 1}:a]aresample={SAMPLE_RATE},{_AFMT}[{lab}]")
        labels.append(lab)
        cursor = max(cursor, s.start_sec) + s.length_sec
    if cursor > total_sec + 0.0005:
        warnings.append(f"音声（{cursor:.2f}s）が映像（{total_sec:.2f}s）より長くなります")
    gap(total_sec - cursor)
    if not labels:
        gap(total_sec)
    parts.append("".join(f"[{lab}]" for lab in labels) + f"concat=n={len(labels)}:v=0:a=1[aout]")
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]
    return cmd, warnings


def _run(cmd: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe_duration(ffprobe: str, path: Path, stream: str | None = None, runner: Runner = _run) -> float | None:
    """ffprobe で長さ（秒）を得る。stream は 'v:0' / 'a:0'。取れなければ None。"""
    if shutil.which(ffprobe) is None and not Path(ffprobe).is_file():
        return None
    if stream:
        cmd = [ffprobe, "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    else:
        cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    res = runner(cmd)
    if res.returncode != 0:
        return None
    m = re.search(r"\d+(?:\.\d+)?", res.stdout or "")
    return float(m.group(0)) if m else None


def mux(video: Path, pptx: Path, ids: Sequence[str], durations_path: Path, out: Path, *,
        wav_dir: Path | None = None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", overwrite: bool = False,
        transition_before_timer: bool = True, runner: Runner = _run) -> MuxResult:
    video, pptx, out = Path(video), Path(pptx), Path(out)
    if not video.is_file():
        raise MuxError(f"無音 MP4 がありません: {video}")
    if not pptx.is_file():
        raise MuxError(f".pptx がありません: {pptx}")
    if out.exists() and not overwrite:
        raise MuxError(f"出力が既にあります（--force で上書き）: {out}")
    if shutil.which(ffmpeg) is None and not Path(ffmpeg).is_file():
        raise MuxError(f"ffmpeg が見つかりません: {ffmpeg}（PATH に追加するか --ffmpeg で指定）")

    durations = load_durations(Path(durations_path))
    timings = read_slide_timings(pptx, ids, transition_before_timer)
    expected = expected_total_sec(timings, transition_before_timer)
    morphs = count_morphs(timings)

    video_sec = probe_duration(ffprobe, video, "v:0", runner) or probe_duration(ffprobe, video, None, runner)
    total = video_sec if video_sec else expected
    warnings: list[str] = []
    info: list[str] = []
    extra, corrected, why_not = morph_drift(video_sec, expected, morphs)
    if video_sec is None:
        warnings.append("ffprobe で無音 MP4 の長さを取得できないため、スライド秒数の合計を映像の長さとみなしました")
    elif corrected:
        info.append(f"Morph の切替 {morphs} か所で、無音 MP4 がスライド秒数の合計より {video_sec - expected:+.2f}s 長いため、"
                    f"1 か所あたり {extra:.3f}s としてナレーションの位置を補正しました")
    else:
        if why_not:
            warnings.append(why_not)
        if abs(video_sec - expected) > TOLERANCE_SEC:
            warnings.append(
                f"無音 MP4 の長さ {video_sec:.2f}s がスライド秒数の合計 {expected:.2f}s と {video_sec - expected:+.2f}s ずれています。"
                "ナレーションの位置がずれる可能性があります（切替効果の扱いを変えるなら --transition-in-timer）"
            )
    segments, w = plan_segments(timings, durations, Path(wav_dir or Path(durations_path).parent),
                                transition_before_timer, morph_extra_sec=extra)
    warnings = w + warnings

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd, w = build_ffmpeg_command(ffmpeg, video, segments, total, out, overwrite)
    warnings += w
    res = runner(cmd)
    if res.returncode != 0:
        raise MuxError(f"ffmpeg が失敗しました（終了コード {res.returncode}）: {(res.stderr or '').strip()[-800:]}")

    result = MuxResult(out, expected, video_sec, command=cmd, warnings=warnings, info=info, morph_count=morphs,
                       morph_extra_sec=round(extra, 4), drift_corrected=corrected)
    result.output_video_sec = probe_duration(ffprobe, out, "v:0", runner)
    result.output_audio_sec = probe_duration(ffprobe, out, "a:0", runner)
    if result.output_video_sec is not None and result.output_audio_sec is not None:
        diff = result.output_audio_sec - result.output_video_sec
        if abs(diff) > TOLERANCE_SEC:
            warnings.append(f"出力 MP4 の音声と映像の長さが {diff:+.2f}s ずれています")
    return result
