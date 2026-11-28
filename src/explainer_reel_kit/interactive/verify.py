# -*- coding: utf-8 -*-
"""出来上がった MP4 の検証。記録は出力フォルダの checks\\ に置く。

| 手順 | 内容 |
|---|---|
| probe | 尺・解像度・fps・フレーム数を中間データと照合（ffprobe） |
| decode | 映像・音声を最後までデコードし、エラーの出力が無いこと |
| audio | 音声の正本（--audio-ref）と AAC のパケット・デコード後の PCM の MD5 が一致すること（正本が無ければ省く） |
| subs | 全フレームの字幕帯を走査し、字幕の表示・非表示が中間データの cues のフレームと一致すること（SRT とも照合できる） |
| frames | 字幕・場面の切替の前後のフレームを MP4 から取り出し（bt709・limited を明示）、コードの描画結果と画素で比べる |
| text | 全フレームの表示リストから画面の文字を集め、禁止語（台本のフォルダの verify.yaml）と照合する。cue_points.json も書く |
| report | checks\\検証結果.md にまとめる |

verify.yaml（場面コードのフォルダかその親。題材の固有の語はここに書き、公開のリポジトリに入れない）::

    screen_text:
      forbidden: [語, …]              # 画面のどこにも出さない語（字幕も含む。大文字・小文字を区別しない）
      forbidden_before:               # この秒より前の画面に出さない語（開示の前など）
        sec: 120.0                    # 省略すると全編
        words: [語, …]
        allow: [語, …]                # これを含む文字列は除く
        include_subtitles: false      # 字幕の文字も見るか（既定は見ない）
      numbers_reference: data/元資料の文字.txt   # 画面の数値がこの文書にあるか（無い数値を記録する）
    subtitles_reference: data/字幕.srt          # 字幕の文言・時刻を SRT とも照合する
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

import yaml
from PIL import Image, ImageChops, ImageStat

from .subtitles import parse_srt, srt_frame
from .engine import H, SUB_TOP, W, texts_of
from .render import Renderer
from .subtitles import wrap_subtitle_info

FF = ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error']
STEPS = ('probe', 'decode', 'audio', 'subs', 'frames', 'text', 'report')
MAX_MEAN_DIFF = 4.0   # 取り出したフレームと描画結果の差（平均の絶対差、0〜255）の上限


class VerifyError(RuntimeError):
    pass


def load_config(path: Path | None) -> dict:
    if path is None or not Path(path).is_file():
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise VerifyError(f'verify.yaml の形が違います: {path}')
    return data


def _md5(ffmpeg: str, args: list[str]) -> str:
    out = subprocess.check_output([ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', *args]).decode().strip()
    return out.split('=')[-1]


def _diff(a, b) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


# ffmpeg 7 以降は select の式が長いと読めない（ffmpeg 8.1 で 100 項まで。4.4 では 300 項でも通った）。
# 80 項ずつに分け、まとまりの先頭の手前へシークしてから選ぶ（-ss は入力側。正確なシークで、n は先頭のフレームから 0）
SELECT_MAX_TERMS = 80


def extract_args(video: Path, frames: list[int], fps: int) -> list[str]:
    """frames（昇順）を取り出す ffmpeg の引数（-i から）。色は bt709・limited を明示して RGB にする（色ずれを防ぐ）。"""
    f0 = frames[0]
    expr = '+'.join('eq(n\\,%d)' % (f - f0) for f in frames)
    vf = ("select='%s',setpts=N/(%d*TB),scale=in_color_matrix=bt709:in_range=limited,format=rgb24" % (expr, fps))
    ss = ['-ss', '%.6f' % ((f0 - 0.5) / fps)] if f0 > 0 else []
    return [*ss, '-i', str(video), '-map', '0:v:0', '-vf', vf, '-frames:v', str(len(frames)), '-f', 'rawvideo', '-']


def merge_runs(cues: list[dict]) -> list[list[int]]:
    """字幕の表示区間を、続いているもの（前の終わり＝次の始まり）はつないで返す（字幕帯の検出と比べる形）。"""
    runs: list[list[int]] = []
    for c in cues:
        if runs and runs[-1][1] == c['f0']:
            runs[-1][1] = c['f1']
        else:
            runs.append([c['f0'], c['f1']])
    return runs


class Verifier:
    def __init__(self, renderer: Renderer, video: Path, checks: Path, *, config: dict | None = None,
                 config_dir: Path | None = None, audio_ref: Path | None = None, ffmpeg: str = 'ffmpeg',
                 ffprobe: str = 'ffprobe', srt: Path | None = None, log: Callable[[str], None] = print):
        """srt: 出力の SRT。無ければ MP4 の隣の .srt があるときにそれを使う。"""
        self.r = renderer
        self.T = renderer.T
        self.video = Path(video)
        self.checks = Path(checks)
        self.config = config or {}
        self.config_dir = Path(config_dir) if config_dir else None
        self.audio_ref = Path(audio_ref) if audio_ref else None
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.log = log
        self.srt = Path(srt) if srt else (self.video.with_suffix('.srt') if self.video.with_suffix('.srt').is_file() else None)
        self.result_path = self.checks / 'verify.json'
        self.checks.mkdir(parents=True, exist_ok=True)
        if not self.video.is_file():
            raise VerifyError(f'MP4 がありません: {self.video}')

    # ---- 記録
    def load(self) -> dict:
        return json.loads(self.result_path.read_text(encoding='utf-8')) if self.result_path.is_file() else {}

    def save(self, key: str, value: Any) -> None:
        data = self.load()
        data[key] = value
        self.result_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        self.log(f"[verify] {key}: {'OK' if value.get('ok') else ('省略' if value.get('ok') is None else '要確認')}")

    def _path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() or self.config_dir is None else self.config_dir / q

    def _ff(self) -> list[str]:
        return [self.ffmpeg, *FF[1:]]

    # ---- 手順
    def probe(self) -> None:
        info = json.loads(subprocess.check_output([self.ffprobe, '-v', 'error', '-show_streams', '-show_format',
                                                   '-count_packets', '-of', 'json', str(self.video)]))
        (self.checks / 'ffprobe.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
        vs = [s for s in info['streams'] if s['codec_type'] == 'video']
        aus = [s for s in info['streams'] if s['codec_type'] == 'audio']
        if not vs:
            self.save('probe', dict(ok=False, error='映像のトラックがありません'))
            return
        v = vs[0]
        r = dict(duration_format=float(info['format']['duration']), video_duration=float(v.get('duration', 0)),
                 width=v['width'], height=v['height'], avg_frame_rate=v['avg_frame_rate'],
                 r_frame_rate=v['r_frame_rate'], nb_frames=int(v.get('nb_frames') or v.get('nb_read_packets') or 0),
                 video_codec=v['codec_name'], pix_fmt=v['pix_fmt'], color_space=v.get('color_space'),
                 color_range=v.get('color_range'), size_bytes=int(info['format']['size']))
        if aus:
            a = aus[0]
            r.update(audio_codec=a['codec_name'], audio_sample_rate=a['sample_rate'], audio_channels=a['channels'],
                     audio_duration=float(a.get('duration', 0)), audio_packets=int(a.get('nb_read_packets') or 0))
        want = self.T.nframes / self.T.fps
        # 音声を正本からそのまま写したときは、尺は 1.5 ms 以内。AAC に書き出したときは、音声の端数の分だけ長くなる
        tol = 0.0015 if self.audio_ref else 0.05
        r['expected_duration'] = want
        r['ok'] = (abs(r['duration_format'] - want) < tol and abs(r['video_duration'] - want) < 1e-4
                   and (r['width'], r['height']) == (self.T.width, self.T.height)
                   and r['avg_frame_rate'] == f'{self.T.fps}/1' and r['nb_frames'] == self.T.nframes)
        self.save('probe', r)

    def decode(self) -> None:
        maps = ['-map', '0:v:0', '-map', '0:a:0?']
        p = subprocess.run(self._ff() + ['-xerror', '-i', str(self.video), *maps, '-f', 'null', '-'],
                           capture_output=True)
        err = p.stderr.decode('utf-8', 'replace')
        self.save('decode', dict(returncode=p.returncode, stderr=err[-600:], ok=(p.returncode == 0 and not err.strip())))

    def audio(self) -> None:
        if self.audio_ref is None:
            self.save('audio', dict(ok=None, skipped='音声の正本（--audio-ref）が無いため省きました'))
            return
        r: dict[str, Any] = {}
        for name, path in (('reference', self.audio_ref), ('new', self.video)):
            r[name] = dict(packet_md5=_md5(self.ffmpeg, ['-i', str(path), '-map', '0:a:0', '-c', 'copy', '-f', 'md5', '-']),
                           pcm_md5=_md5(self.ffmpeg, ['-i', str(path), '-map', '0:a:0', '-f', 'md5', '-']))
            a = json.loads(subprocess.check_output([self.ffprobe, '-v', 'error', '-select_streams', 'a:0',
                                                    '-count_packets', '-show_streams', '-of', 'json', str(path)]))['streams'][0]
            r[name].update(codec=a['codec_name'], sample_rate=a['sample_rate'], channels=a['channels'],
                           duration=a.get('duration'), packets=a.get('nb_read_packets'), bit_rate=a.get('bit_rate'),
                           start_time=a.get('start_time'))
        r['reference_path'] = str(self.audio_ref)
        # bit_rate はコンテナが尺とサイズから計算する参考値なので比べない。長さの表示は、-movie_timescale の無い
        # 古い ffmpeg で結合するとミリ秒に丸まるので 1 ms 以内なら一致とみなす
        ref, new = r['reference'], r['new']
        r['ok'] = (all(ref[k] == new[k] for k in ref if k not in ('bit_rate', 'duration'))
                   and abs(float(ref['duration'] or 0) - float(new['duration'] or 0)) < 0.001)
        self.save('audio', r)

    def subs(self) -> None:
        """字幕帯に文字が出ているフレームを映像から検出し、中間データの字幕の表示フレームと照合する。"""
        T = self.T
        bw, bh = 480, 34
        crop = 'crop=%d:%d:0:%d,scale=%d:%d:flags=area,format=gray' % (W, H - SUB_TOP - 4, SUB_TOP + 4, bw, bh)
        p = subprocess.Popen(self._ff() + ['-i', str(self.video), '-map', '0:v:0', '-vf', crop, '-f', 'rawvideo', '-'],
                             stdout=subprocess.PIPE)
        on: list[bool] = []
        while True:
            buf = p.stdout.read(bw * bh)
            if len(buf) < bw * bh:
                break
            on.append(sum(1 for v in buf if v > 110) >= 6)
        p.stdout.close()
        p.wait()
        n = len(on)
        expected = [T.cue_at(f) is not None for f in range(T.nframes)]
        mism = [f for f in range(min(n, T.nframes)) if on[f] != expected[f]]
        runs, start = [], None
        for f in range(n + 1):
            cur = on[f] if f < n else False
            if cur and start is None:
                start = f
            elif not cur and start is not None:
                runs.append([start, f])
                start = None
        want = merge_runs(T.cues)
        cues = [dict(number=c['number'], sentence=c['sentence'], frames=[c['f0'], c['f1']],
                     shown_sec='%.3f-%.3f' % (c['f0'] / T.fps, c['f1'] / T.fps)) for c in T.cues]
        non_comma = []
        for c in T.cues:
            if not c.get('lines'):
                lines, at_comma = wrap_subtitle_info(c['text'])
            else:   # 改行を決めてある字幕（台本から作ったもの）も、2 行なら 1 行目の終わりを見る
                lines = c['lines']
                at_comma = len(lines) == 1 or lines[0][-1] in '、。'
            if not at_comma:
                non_comma.append(dict(number=c['number'], lines=lines))
        res = dict(frames_scanned=n, cue_count=len(T.cues), detected_runs=len(runs), mismatched_frames=len(mism),
                   first_mismatches=mism[:10], runs_equal_cue_frames=(runs == want),
                   non_comma_breaks=non_comma, cues=cues)
        ok = n == T.nframes and not mism and runs == want
        ref = self.config.get('subtitles_reference')
        if ref:
            srt = parse_srt(self._path(ref))
            # 表示フレームは SRT の時刻以降の最初のフレーム（SRT はミリ秒に丸めた値なので 1 ms の誤差は許す）
            per = 1000 / T.fps

            def near(ms, f):
                return -1 < f * per - ms < per

            srt_ok = (len(srt) == len(T.cues) and all(
                near(s['start_ms'], c['f0']) and near(s['end_ms'], c['f1']) and s['text'] == c['text']
                for s, c in zip(srt, T.cues)))
            res.update(subtitles_reference=str(self._path(ref)), srt_matches_text_and_time=srt_ok)
            ok = ok and srt_ok
        if self.srt is not None:
            # 出力の SRT（焼き込みと同じ cues から書いたもの）: 表示フレームが cues・焼き込みの検出と一致すること
            out_srt = parse_srt(self.srt) if self.srt.is_file() else []
            srt_frames = [[srt_frame(s['start_ms'], T.fps), srt_frame(s['end_ms'], T.fps)] for s in out_srt]
            cue_frames = [[c['f0'], c['f1']] for c in T.cues]
            srt_runs = merge_runs([{'f0': a, 'f1': b} for a, b in srt_frames])
            srt_res = dict(path=str(self.srt), cues=len(out_srt), frames_equal_cues=srt_frames == cue_frames,
                           text_equal_cues=[s['text'] for s in out_srt] == [c['text'] for c in T.cues],
                           runs_equal_burned=srt_runs == runs,
                           first_differences=[dict(number=i + 1, srt=a, cue=b) for i, (a, b) in
                                              enumerate(zip(srt_frames, cue_frames)) if a != b][:10])
            srt_res['ok'] = (bool(out_srt) and srt_res['frames_equal_cues'] and srt_res['text_equal_cues']
                             and srt_res['runs_equal_burned'])
            res['srt_output'] = srt_res
            ok = ok and srt_res['ok']
        res['ok'] = ok
        self.save('subtitles', res)

    def frames(self) -> None:
        """切替の前後のフレームを MP4 から取り出し、コードで描いた同じフレームと比べる（文言・時刻の確認）。

        各切替について「直前のフレームは切替前の絵に、切替フレームは切替後の絵に近い」ことを確かめる。場面の切替は
        内容がフェードインするので、境界の 12 フレーム後（新しい場面の内容が出たところ）とも比べる。
        """
        T, r = self.T, self.r
        pairs_band = []
        for c in T.cues:
            pairs_band += [(c['f0'] - 1, c['f0']), (c['f1'] - 1, c['f1'])]
        pairs_full = [(sc['f0'] - 1, sc['f0']) for sc in T.scenes[1:]]
        pairs_full += [(sc['f0'] - 1, min(sc['f1'] - 1, sc['f0'] + 12)) for sc in T.scenes[1:]]
        want = sorted(set(f for p in pairs_band + pairs_full for f in p if 0 <= f < T.nframes))
        dec, ras = {}, {}
        for k in range(0, len(want), SELECT_MAX_TERMS):
            part = want[k:k + SELECT_MAX_TERMS]
            p = subprocess.Popen(self._ff() + extract_args(self.video, part, T.fps), stdout=subprocess.PIPE)
            for f in part:
                buf = p.stdout.read(W * H * 3)
                if len(buf) < W * H * 3:
                    break
                im = Image.frombytes('RGB', (W, H), buf)
                ri = r.frame_image(f)
                dec[f] = (im.resize((640, 360), Image.BOX), im.crop((0, SUB_TOP, W, H)))
                ras[f] = (ri.resize((640, 360), Image.BOX), ri.crop((0, SUB_TOP, W, H)))
            p.stdout.close()
            p.wait()
        if not dec:
            self.save('frame_compare', dict(ok=False, error='フレームを取り出せませんでした'))
            return
        worst_full = max((round(_diff(dec[f][0], ras[f][0]), 3), f) for f in dec)
        worst_band = max((round(_diff(dec[f][1], ras[f][1]), 3), f) for f in dec)

        def check(pairs, k):
            bad, same, margin = [], [], None
            for a, b in pairs:
                if a not in dec or b not in dec:
                    continue
                if ras[a][k].tobytes() == ras[b][k].tobytes():   # 描いた絵が同じ（見た目の切替が無い）組は数えない
                    same.append([a, b])
                    continue
                for x, y in ((a, b), (b, a)):
                    own, other = _diff(dec[x][k], ras[x][k]), _diff(dec[x][k], ras[y][k])
                    if not own < other:
                        bad.append(x)
                    m = other - own
                    margin = m if margin is None else min(margin, m)
            return bad, (None if margin is None else round(margin, 3)), same

        bad_b, m_b, same_b = check(pairs_band, 1)
        bad_f, m_f, same_f = check(pairs_full, 0)
        self.save('frame_compare', dict(
            frames_compared=len(dec), frames_requested=len(want), subtitle_switches_checked=len(pairs_band),
            subtitle_switches_wrong=bad_b, subtitle_min_margin=m_b, subtitle_same_image_pairs=same_b,
            scene_switches_checked=len(pairs_full), scene_switches_wrong=bad_f, scene_min_margin=m_f,
            scene_same_image_pairs=same_f, worst_mean_abs_diff_full=worst_full,
            worst_mean_abs_diff_subtitle_band=worst_band,
            scene_boundaries=[[s['id'], s['f0'], s['f1']] for s in T.scenes],
            ok=(len(dec) == len(want) and not bad_b and not bad_f and worst_full[0] < MAX_MEAN_DIFF
                and worst_band[0] < MAX_MEAN_DIFF)))

    def text(self) -> None:
        """全フレームの画面の文字を走査する（表示リストから。字幕と場面の文字は分けて数える）。"""
        T, r = self.T, self.r
        seen: dict[str, int] = {}
        first: dict[str, int] = {}
        first_screen: dict[str, int] = {}
        subs: set[str] = set()
        for f in range(T.nframes):
            scene_ops, sub_ops = r.layers(f)
            for s in texts_of(sub_ops):
                subs.add(s)
                if s not in seen:
                    seen[s], first[s] = 0, f
                seen[s] += 1
            for s in texts_of(scene_ops):
                if s not in seen:
                    seen[s], first[s] = 0, f
                if s not in first_screen:
                    first_screen[s] = f
                seen[s] += 1
        cfg = self.config.get('screen_text') or {}
        forbidden = [str(w) for w in cfg.get('forbidden') or []]
        hits = {s: first[s] for s in seen if any(w.lower() in s.lower() for w in forbidden)}
        before = cfg.get('forbidden_before') or {}
        limit = int(round(float(before['sec']) * T.fps)) if before.get('sec') is not None else T.nframes
        words = [str(w) for w in before.get('words') or []]
        allow = [str(w) for w in before.get('allow') or []]
        pool = first if before.get('include_subtitles') else first_screen
        early = {s: f for s, f in pool.items() if f < limit and any(w in s for w in words) and not any(w in s for w in allow)}
        numbers = {}
        ref_ok = True
        if cfg.get('numbers_reference'):
            ref_path = self._path(cfg['numbers_reference'])
            ref = ref_path.read_text(encoding='utf-8') if ref_path.is_file() else ''
            ref_ok = bool(ref)
            num = re.compile(r'\d[\d,]*(?:\.\d+)?')
            ref_nums = set(num.findall(ref))
            for s in first_screen:
                for n_ in num.findall(s):
                    if n_ not in ref_nums and n_.replace(',', '') not in ref_nums:
                        numbers.setdefault(n_, []).append(s)
        listing = sorted((f, s) for s, f in first.items())
        (self.checks / 'screen_text.json').write_text(json.dumps(
            [dict(first_frame=f, first_sec=round(f / T.fps, 2), text=s, subtitle=(s in subs and s not in first_screen))
             for f, s in listing], ensure_ascii=False, indent=1), encoding='utf-8')
        (self.checks / 'cue_points.json').write_text(json.dumps(T.log, ensure_ascii=False, indent=1), encoding='utf-8')
        self.save('screen_text', dict(distinct_strings=len(seen), screen_strings=len(first_screen),
                                      subtitle_strings=len(subs), forbidden_hits=hits,
                                      forbidden_before_sec=(None if before.get('sec') is None else float(before['sec'])),
                                      forbidden_before_hits=early, numbers_not_in_reference=numbers,
                                      cue_points=len(T.log), ok=(not hits and not early and ref_ok)))

    def hashes(self) -> dict:
        h = {'video': hashlib.sha256(self.video.read_bytes()).hexdigest(),
             'timeline': hashlib.sha256(Path(self.r.project.timeline).read_bytes()).hexdigest()}
        if self.r.project.pauses and Path(self.r.project.pauses).is_file():
            h['pauses'] = hashlib.sha256(Path(self.r.project.pauses).read_bytes()).hexdigest()
        return h

    def report(self) -> dict:
        d = self.load()
        d['sha256'] = self.hashes()
        keys = ('probe', 'decode', 'audio', 'subtitles', 'frame_compare', 'screen_text')
        state = {k: (d.get(k) or {}).get('ok', False) for k in keys}
        d['ok'] = all(v is not False for v in state.values()) and all(k in d for k in keys)
        self.result_path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
        fps = self.T.fps

        def ok(k):
            v = state.get(k)
            return '省略' if v is None else ('OK' if v else '要確認')

        mmss = lambda fr: '%d:%04.1f' % (fr // fps // 60, fr / fps % 60)
        rows = []
        p = d.get('probe') or {}
        if 'duration_format' in p:
            rows.append(('尺', ok('probe'), '%.6f 秒（映像 %.6f 秒%s）' % (
                p['duration_format'], p['video_duration'],
                f"／音声 {p['audio_duration']:.6f} 秒" if 'audio_duration' in p else '')))
            rows.append(('解像度・フレームレート', ok('probe'), '%d×%d、%s fps、%d フレーム（中間データ %d）' % (
                p['width'], p['height'], p['avg_frame_rate'], p['nb_frames'], self.T.nframes)))
        rows.append(('全区間のデコード', ok('decode'), '映像・音声を最後までデコード、エラー出力 %s' % (
            'なし' if (d.get('decode') or {}).get('ok') else 'あり')))
        a = d.get('audio') or {}
        if a.get('ok') is None:
            rows.append(('音声トラックの一致', '省略', a.get('skipped', '')))
        else:
            rows.append(('音声トラックの一致', ok('audio'), 'AAC パケットの MD5（%s）、デコード後 PCM の MD5（%s）、%s パケット' % (
                a['new']['packet_md5'], a['new']['pcm_md5'], a['new']['packets'])))
        s = d.get('subtitles') or {}
        if s:
            extra = '。SRT の文言・時刻とも一致' if s.get('srt_matches_text_and_time') else ''
            so = s.get('srt_output')
            if so:
                extra += '。出力の SRT（%s）は %s' % (Path(so['path']).name, '表示フレームが字幕・焼き込みと一致' if so.get('ok')
                                                     else '字幕・焼き込みと不一致（verify.json の srt_output）')
            nc = len(s.get('non_comma_breaks') or [])
            rows.append(('字幕の表示時刻', ok('subtitles'), '全 %d フレームを走査。%d キュー、不一致 %d フレーム%s。読点以外で折った字幕 %d' % (
                s['frames_scanned'], s['cue_count'], s['mismatched_frames'], extra, nc)))
        fc = d.get('frame_compare') or {}
        if 'scene_boundaries' in fc:
            rows.append(('字幕の文言・場面の切替', ok('frame_compare'),
                         '字幕の切替 %d か所と場面の切替 %d か所の前後フレームを描画結果と画素比較。取り違え %d' % (
                             fc['subtitle_switches_checked'], fc['scene_switches_checked'],
                             len(fc['subtitle_switches_wrong']) + len(fc['scene_switches_wrong']))))
            rows.append(('場面の境界', ok('frame_compare'), ' / '.join(
                '%s %s' % (b[0], mmss(b[1])) for b in fc['scene_boundaries']) + ' / 終了 ' + mmss(fc['scene_boundaries'][-1][2])))
        tx = d.get('screen_text') or {}
        if tx:
            rows.append(('画面の文字', ok('screen_text'), '禁止語 %d 件、指定の秒より前に出さない語 %d 件、元資料に無い数値: %s（%d 種類の文字列を走査）' % (
                len(tx['forbidden_hits']), len(tx['forbidden_before_hits']),
                ('なし' if not tx['numbers_not_in_reference'] else '、'.join(sorted(tx['numbers_not_in_reference']))),
                tx['distinct_strings'])))
        lines = ['# 検証結果', '', f'対象: `{self.video.name}`', '', f"総合: {'OK' if d['ok'] else '要確認'}", '',
                 '| 項目 | 判定 | 内容 |', '| --- | --- | --- |']
        lines += ['| %s | %s | %s |' % row for row in rows]
        lines += ['', '数値の詳細は `verify.json`、画面に出る文字の一覧は `screen_text.json`、強調の切替時刻は `cue_points.json`。',
                  '強調の時刻（T.at）は推定で、耳で聞いての確認ではない。読みやすさは sheet の一覧画像で目で確かめる。', '']
        (self.checks / '検証結果.md').write_text('\n'.join(lines), encoding='utf-8')
        self.log(f"[verify] 総合 {'OK' if d['ok'] else '要確認'}（{self.checks / '検証結果.md'}）")
        return d

    def run(self, steps: list[str] | None = None) -> dict:
        steps = list(steps or STEPS)
        unknown = [s for s in steps if s not in STEPS]
        if unknown:
            raise VerifyError(f'知らない手順: {unknown}（{", ".join(STEPS)}）')
        for s in steps:
            if s == 'report':
                continue
            getattr(self, s)()
        return self.report()
