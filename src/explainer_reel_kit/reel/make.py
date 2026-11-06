"""通し生成（``erkit make``）: 台本 → 撮影 → 説明図 → 素材 → ナレーション → スライド → 書き出し → 音声の合成。

出力::

    <出力先のルート>/<YYYYMMDD>_<reel id>[_<一言>]/       同じ名前があれば -2, -3 …
        <output_name>.mp4        完成した動画
        <output_name>.pptx       直すための PowerPoint
        run.json                 実行の記録（区分・段ごとの結果・再開のコマンド）
        work/
            diagram/             この実行で描いた説明図（<image.ref> と marks.json）
            assets/              この実行で使った画像の複製
            narration-input.json
            narration/           <id>.wav と durations.json
            <output_name>.silent.mp4
            check/overlay.png    確認用の一覧画像（赤枠・矢印を画像に描いたもの）
    <撮影素材のルート>/web/<reel id>/   Web の撮影（日付なし。撮り直すと上書き）

実行の前に、残りの段に要るもの（ブラウザ・操作定義・音声合成エンジンと声・PowerPoint・ffmpeg）を一度に確かめ、
足りなければ何も作らずに止める。社外秘の台本（未記入も）と ``--offline`` では、ネットワークの外へ出る設定
（音声合成エンジン・撮影の URL・LLM）がこの PC だけかを先に確かめ、違えば何も作らずに止める。
"""
from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .. import __version__
from .. import config as kit_config
from .. import storyboard as sb
from ..capture.web.serve import is_local_url
from ..deck import marks as deck_marks
from ..deck.builder import BuildError, build_deck
from ..export import Exporter, ExportError, is_windows, manual_command, powershell_exporter
from ..narration.adapter import AdapterError, slide_ids, storyboard_to_narration_input
from ..narration.dictionaries import load_dictionaries
from ..narration.errors import NarrationError
from ..narration.synth import parse_input, run_synth
from ..narration.textproc import PronunciationDictionary
from ..narration.tts import TTSEngine, get_engine
from .assets import AssetsError, resolve_assets, stage_assets
from .mux import MuxError, mux

RUN_FORMAT = "explainer-reel-kit/run@1"
STAGES = ("capture", "diagram", "assets", "voice", "deck", "export", "mux")
STAGE_TITLES = {
    "capture": "Web 画面の撮影",
    "diagram": "説明図を描く",
    "assets": "素材をまとめる",
    "voice": "ナレーション",
    "deck": "スライド",
    "export": "書き出し（PowerPoint）",
    "mux": "音声の合成",
}
JST = timezone(timedelta(hours=9))


class MakeError(Exception):
    """引数・台本の誤りで始められない（終了コード 2）。"""

    exit_code = 2


class MakeStop(MakeError):
    """前提が足りない・社外秘の確かめで止めた・段が失敗した（終了コード 1）。"""

    exit_code = 1


class StageFailed(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


@dataclass
class MakeOptions:
    storyboard: Path
    label: str | None = None
    output_root: Path | None = None
    out_dir: Path | None = None  # 新しく作る出力フォルダ、または --from で再開するフォルダ
    captures_root: Path | None = None
    assets_root: Path | None = None
    actions: Path | None = None
    serve: Path | None = None
    url_map: list[tuple[str, str]] = field(default_factory=list)
    channel: str | None = None
    executable: str | None = None
    engine: str | None = None
    engine_url: str | None = None
    speaker: int | None = None
    dictionaries: list[str] | None = None  # None なら設定の voice.dictionaries
    allow_placeholders: bool = False
    no_capture: bool = False  # 撮影せず、撮影素材のフォルダにある画像を使う
    from_stage: str | None = None
    dry_run: bool = False
    offline: bool = False
    force: bool = False
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    platform: str | None = None


@dataclass
class Hooks:
    """外の仕組みを差し替える口（テスト用。既定は本物）。"""

    capture: Callable[..., dict[str, Any]] | None = None
    diagram: Callable[..., dict[str, Any]] | None = None
    engine: TTSEngine | None = None
    transport: Any = None
    exporter: Exporter | None = None
    checks: Callable[["Maker", list[str]], list[tuple[str, str | None]]] | None = None
    now: Callable[[], datetime] | None = None


@dataclass
class MakeResult:
    status: str  # done / needs_export / dry_run
    out_dir: Path | None
    run: dict[str, Any] = field(default_factory=dict)
    next_steps: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _folder_part(text: str) -> str:
    import re

    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text).strip()
    return re.sub(r"\s+", "-", s)


def unique_dir(root: Path, name: str) -> Path:
    p = root / name
    n = 2
    while p.exists():
        p = root / f"{name}-{n}"
        n += 1
    return p


def web_scenes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in doc["scenes"] if (s.get("image") or {}).get("source") == "web"]


def diagram_scenes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in doc["scenes"] if (s.get("image") or {}).get("source") == "generated"
            and (s.get("capture") or {}).get("tool") == "html"]


class Maker:
    def __init__(self, opts: MakeOptions, cfg: kit_config.KitConfig | None = None, hooks: Hooks | None = None,
                 log: Callable[[str], None] = print):
        self.o = opts
        self.cfg = cfg or kit_config.KitConfig()
        self.h = hooks or Hooks()
        self.log = log
        self.storyboard = Path(opts.storyboard)
        if opts.from_stage is not None and opts.from_stage not in STAGES:
            raise MakeError(f"--from には {' / '.join(STAGES)} のどれかを指定してください")
        if not self.storyboard.is_file():
            raise MakeError(f"台本がありません: {self.storyboard}")
        try:
            self.doc = sb.load_storyboard(self.storyboard)
        except (sb.ConversionError, OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise MakeError(f"台本を読めません: {self.storyboard}: {e}") from e
        rep = sb.validate_storyboard(self.doc, base_dir=self.storyboard.parent)
        errors = [e for e in rep.errors if not e.startswith("[image]")]  # manual の画像は素材の段で確かめる
        if errors:
            raise MakeError("台本が検証を通りません（erkit check で確かめてください）:\n  " + "\n  ".join(errors))
        self.reel = self.doc["reel"]
        self.reel_id = self.reel["id"]
        self.stem = self.reel["output_name"]
        self.confidentiality = sb.confidentiality(self.doc)
        self.output_root = kit_config.output_root(self.cfg, opts.output_root)
        self.captures_root = kit_config.captures_root(self.cfg, opts.captures_root)
        self.captures_dir = self.captures_root / "web" / _folder_part(self.reel_id)
        self.actions_path = Path(opts.actions) if opts.actions else \
            self.storyboard.resolve().parent / f"{self.reel_id}.actions.yaml"
        try:
            self.narration_input = storyboard_to_narration_input(
                self.doc, default_speaker=self.cfg.voice_speaker, default_engine=self.cfg.voice_engine)
        except AdapterError as e:
            raise MakeError(str(e)) from e
        if opts.speaker is not None:
            self.narration_input["speaker"] = opts.speaker
        self.speaker = self.narration_input["speaker"]
        self.engine_name = opts.engine or self.narration_input.get("engine") or self.cfg.voice_engine
        self.credit = self.cfg.credit_for(self.speaker)
        self.out_dir: Path | None = None
        self.run: dict[str, Any] = {}
        self._engine: TTSEngine | None = self.h.engine

    # ------------------------------------------------------------ 名前・段

    def now(self) -> datetime:
        return (self.h.now or (lambda: datetime.now(JST)))()

    def iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def new_dir_name(self) -> str:
        parts = [self.now().strftime("%Y%m%d"), _folder_part(self.reel_id)]
        if self.o.label:
            parts.append(_folder_part(self.o.label))
        return "_".join(p for p in parts if p)

    def stage_needed(self, name: str) -> tuple[bool, str]:
        """(実行するか, しない理由)。"""
        if name == "capture" and not web_scenes(self.doc):
            return False, "Web の撮影をするシーンがない"
        if name == "capture" and self.o.assets_root is not None:
            return False, "--assets-root の画像を使う"
        if name == "capture" and self.o.no_capture:
            return False, f"--no-capture（{self.captures_dir} にある画像を使う）"
        if name == "diagram" and not diagram_scenes(self.doc):
            return False, "HTML の説明図のシーンがない"
        if name in ("export", "mux") and self.h.exporter is None and not is_windows(self.o.platform):
            return False, "Windows 以外（書き出しは PowerPoint のデスクトップ版で行う）"
        return True, ""

    def stages_to_run(self) -> list[str]:
        start = STAGES.index(self.o.from_stage) if self.o.from_stage else 0
        return list(STAGES[start:])

    def command(self, from_stage: str | None = None) -> str:
        parts = ["erkit", "make", str(self.storyboard)]
        if from_stage:
            parts += ["--from", from_stage]
            if self.out_dir is not None:
                parts += ["--out-dir", str(self.out_dir)]
        for flag, val in (("--serve", self.o.serve), ("--label", self.o.label if not from_stage else None),
                          ("--assets-root", self.o.assets_root), ("--actions", self.o.actions),
                          ("--channel", self.o.channel)):
            if val:
                parts += [flag, str(val)]
        if self.o.offline:
            parts.append("--offline")
        if self.o.allow_placeholders:
            parts.append("--allow-placeholders")
        if self.o.no_capture:
            parts.append("--no-capture")
        return " ".join(f'"{p}"' if " " in p else p for p in parts)

    # ------------------------------------------------------------ ネットワークの確かめ

    def engine_url(self) -> str:
        url = self.o.engine_url or self.narration_input.get("engine_url") or self.cfg.voice_url
        if url:
            return url
        from ..narration.tts import default_url

        return default_url(self.engine_name) or ""

    def capture_urls(self) -> dict[str, str]:
        """撮影する URL（--url-map と --serve で置き換えた後）。"""
        from ..capture.web.capture import map_url

        base = "http://127.0.0.1:1/" if self.o.serve is not None else None
        out = {}
        for sc in web_scenes(self.doc):
            url = (sc.get("capture") or {}).get("url")
            if isinstance(url, str):
                out[sc["id"]] = map_url(url, self.o.url_map, base)
        return out

    def network_checks(self, stages: Sequence[str]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        if "voice" in stages:
            url = self.engine_url()
            checks.append({"item": f"音声合成エンジン（{self.engine_name}）", "value": url, "ok": is_local_url(url)})
        run_capture = "capture" in stages and self.stage_needed("capture")[0]
        if run_capture:
            for sid, url in self.capture_urls().items():
                checks.append({"item": f"撮影の URL（{sid}）", "value": url, "ok": is_local_url(url)})
        if "diagram" in stages and self.stage_needed("diagram")[0]:
            checks.append({"item": "説明図", "value": "ネットワークを止めて描く", "ok": True})
        checks.append({"item": "LLM", "value": "使わない（erkit make は台本を読むだけ）", "ok": True})
        return checks

    @property
    def network_reasons(self) -> list[str]:
        return (["--offline"] if self.o.offline else []) + \
            (["社外秘（confidential）の台本"] if self.confidentiality != sb.GENERAL else [])

    def guard_network(self, stages: Sequence[str]) -> list[dict[str, Any]] | None:
        """社外秘・--offline の確かめ。外へ出る設定があれば理由を表示して MakeStop。"""
        if not self.network_reasons:
            return None
        checks = self.network_checks(stages)
        bad = [c for c in checks if not c["ok"]]
        why = "・".join(self.network_reasons)
        if bad:
            self.log(f"[make] {why}のため、この PC の外へ出る設定では作りません（何も作っていません）:")
            for c in bad:
                self.log(f"  - {c['item']}: {c['value']}")
            self.log("  音声合成エンジンはこの PC で動かし（127.0.0.1）、撮影する Web ツールはこの PC で配信してください"
                     "（--serve か、capture.url を 127.0.0.1 に）。")
            if self.confidentiality != sb.GENERAL:
                self.log("  公開済みの情報・一般的な知識だけの台本なら、台本の reel.confidentiality を general にしてください")
            raise MakeStop(f"{why}: この PC の外へ出る設定があります: " + ", ".join(f"{c['item']}={c['value']}" for c in bad))
        self.log(f"[make] {why}: " + "、".join(f"{c['item']}={c['value']}" for c in checks) + " — ok")
        return checks

    # ------------------------------------------------------------ 前提の確かめ

    def engine(self) -> TTSEngine:
        if self._engine is None:
            kwargs: dict[str, Any] = {}
            if self.h.transport is not None:
                kwargs["transport"] = self.h.transport
            self._engine = get_engine(self.engine_name, self.engine_url(), **kwargs)
        return self._engine

    def default_checks(self, stages: list[str]) -> list[tuple[str, str | None]]:
        from .. import doctor

        out: list[tuple[str, str | None]] = []
        browser = ("capture" in stages and self.stage_needed("capture")[0]) or \
                  ("diagram" in stages and self.stage_needed("diagram")[0])
        if browser and (self.h.capture is None or self.h.diagram is None):
            r = doctor.check_browser(self.o.channel, self.o.executable)
            out.append((r.name, None if r.ok else f"{r.detail}。{r.hint}"))
        if "capture" in stages and self.stage_needed("capture")[0]:
            out.append(("Web の操作定義", None if self.actions_path.is_file() else
                        f"{self.actions_path} がありません（erkit record で作るか、--actions で指定）"))
        if "voice" in stages:
            try:
                eng = self.engine()
                eng.check()
                voices = eng.voices()
                msg = None if any(v.style_id == self.speaker for v in voices) else (
                    f"声 {self.speaker} がエンジンにありません（erkit voice list で確かめ、--speaker か config/kit.yaml の voice.speaker で指定）")
            except NarrationError as e:
                msg = f"{e}。{doctor.HINTS['engine']}"
            out.append((f"音声合成エンジン（{self.engine_url()}）と声 {self.speaker}", msg))
        if "export" in stages and self.stage_needed("export")[0] and self.h.exporter is None:
            r = doctor.check_powerpoint(self.o.platform)
            out.append((r.name, None if r.ok else f"{r.detail}。{r.hint}"))
        if "mux" in stages and self.stage_needed("mux")[0]:
            r = doctor.check_ffmpeg(self.o.ffmpeg, self.o.ffprobe)
            out.append((r.name, None if r.ok else f"{r.detail}。{r.hint}"))
        return out

    def checks(self, stages: list[str]) -> list[tuple[str, str | None]]:
        return (self.h.checks or Maker.default_checks)(self, stages)

    # ------------------------------------------------------------ 計画（--dry-run）

    def plan_lines(self, stages: list[str]) -> list[str]:
        out = self.o.out_dir or (self.output_root / "<日付>_" f"{self.reel_id}")
        work = Path(out) / "work"
        io = {
            "capture": (str(self.actions_path), str(self.captures_dir)),
            "diagram": (", ".join((s.get("capture") or {}).get("src", "") for s in diagram_scenes(self.doc)), str(work / "diagram")),
            "assets": ("撮影・説明図・台本のフォルダ", str(work / "assets")),
            "voice": (f"{self.engine_name} {self.engine_url()}・声 {self.speaker}", str(work / "narration" / "durations.json")),
            "deck": ("台本・素材・durations.json", str(Path(out) / f"{self.stem}.pptx")),
            "export": ("PowerPoint（COM）", str(work / f"{self.stem}.silent.mp4")),
            "mux": ("ffmpeg", str(Path(out) / f"{self.stem}.mp4")),
        }
        lines = []
        for i, name in enumerate(stages, 1):
            need, why = self.stage_needed(name)
            lines.append(f"  {i}. {name}（{STAGE_TITLES[name]}）" + ("" if need else f" — 省略: {why}"))
            if need:
                lines.append(f"       入力: {io[name][0]}")
                lines.append(f"       出力: {io[name][1]}")
        return lines

    # ------------------------------------------------------------ 記録

    def write_run(self) -> None:
        assert self.out_dir is not None
        (self.out_dir / "run.json").write_text(json.dumps(self.run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def stage_record(self, name: str, **info: Any) -> None:
        self.run["stages"][name] = {"title": STAGE_TITLES[name], **info}
        self.write_run()

    def _previous_run(self) -> Path:
        """--from: 再開する出力フォルダ（--out-dir、無ければ出力先のルートで、この台本の最後の実行）。"""
        if self.o.out_dir is not None:
            d = Path(self.o.out_dir)
            if not (d / "run.json").is_file():
                raise MakeError(f"再開する実行の記録がありません: {d / 'run.json'}")
            return d
        hits = []
        if self.output_root.is_dir():
            for rj in self.output_root.glob(f"*_{_folder_part(self.reel_id)}*/run.json"):
                try:
                    data = json.loads(rj.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if data.get("format") == RUN_FORMAT and data.get("reel_id") == self.reel_id:
                    hits.append((data.get("started_at") or "", rj.parent))
        if not hits:
            raise MakeError(f"再開できる前回の実行がありません（{self.output_root} に {self.reel_id} の run.json が無い）。"
                            "--from を付けずに実行するか、--out-dir で前回の出力フォルダを指定してください")
        return sorted(hits)[-1][1]

    def _start_record(self, stages: list[str], network: list[dict[str, Any]] | None,
                      prereq: dict[str, str]) -> None:
        if self.o.from_stage:
            self.out_dir = self._previous_run()
            self.run = json.loads((self.out_dir / "run.json").read_text(encoding="utf-8"))
            if self.run.get("reel_id") != self.reel_id:
                raise MakeError(f"{self.out_dir} は別の台本（{self.run.get('reel_id')}）の実行です")
            done = self.run.get("stages", {})
            for name in STAGES[:STAGES.index(self.o.from_stage)]:
                if (done.get(name) or {}).get("status") not in ("ok", "skipped"):
                    raise MakeError(f"前回の実行で {name} が終わっていないため、--from {self.o.from_stage} からは再開できません"
                                    f"（--from {name} を使ってください）")
            self.run["stages"] = {k: v for k, v in done.items() if k in STAGES[:STAGES.index(self.o.from_stage)]}
            self.run.setdefault("resumed", []).append({"from": self.o.from_stage, "at": self.iso()})
            self.run.update(status="running", finished_at=None, error=None, resume=None)
        else:
            root = Path(self.o.out_dir) if self.o.out_dir else unique_dir(self.output_root, self.new_dir_name())
            if root.exists() and any(root.iterdir()):
                raise MakeError(f"--out-dir のフォルダが空ではありません: {root}（再開なら --from を付ける）")
            self.out_dir = root
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.run = {
                "format": RUN_FORMAT, "erkit": __version__,
                "reel_id": self.reel_id, "title": self.reel["title"], "kind": self.reel["kind"],
                "label": self.o.label,
                "storyboard": {"path": str(self.storyboard.resolve()), "sha256": _sha256(self.storyboard)},
                "output_dir": str(self.out_dir.resolve()),
                "captures_dir": str(self.captures_dir),
                "started_at": self.iso(), "finished_at": None, "status": "running", "error": None, "resume": None,
                "stages": {}, "files": {}, "warnings": [],
            }
        self.run.update(
            confidentiality=self.confidentiality,
            offline=self.o.offline,
            network_checks=network,
            engine={"name": self.engine_name, "url": self.engine_url()},
            speaker=self.speaker, credit=self.credit,
            prereq=prereq, command=self.command(),
        )
        (self.out_dir / "work").mkdir(parents=True, exist_ok=True)
        self.write_run()

    # ------------------------------------------------------------ 実行

    def execute(self) -> MakeResult:
        stages = self.stages_to_run()
        self.log(f"[make] {self.storyboard}（{self.reel_id}、区分: {self.confidentiality}）")
        network = self.guard_network(stages)

        if self.o.dry_run:
            self.log("[dry-run] 何も実行しません")
            self.log(f"  出力先のルート: {self.output_root}　撮影素材: {self.captures_dir}")
            self.log(f"  声: {self.speaker}（{self.engine_name} {self.engine_url()}）"
                     + (f"　クレジット: {self.credit}" if self.credit else ""))
            names = [label for label, _ in self.checks(stages)] if self.h.checks else None
            self.log("  実行の前に確かめるもの: " + ("、".join(names) if names else
                     "ブラウザ・操作定義・音声合成エンジンと声・PowerPoint・ffmpeg のうち、残りの段に要るもの"))
            for line in self.plan_lines(stages):
                self.log(line)
            return MakeResult("dry_run", None)

        missing, prereq = [], {}
        for label, msg in self.checks(stages):
            prereq[label] = "ok" if msg is None else msg
            if msg is not None:
                missing.append(f"{label}: {msg}")
        if missing:
            self.log("[make] 足りないものがあるため、何も作らずに止めました:")
            for m in missing:
                self.log(f"  - {m}")
            self.log("  そろえたら、もう一度: " + self.command(self.o.from_stage))
            self.log("  まとめて確かめる: erkit doctor")
            raise MakeStop("前提が足りません: " + " / ".join(missing))
        if prereq:
            self.log("[make] 前提: " + "、".join(prereq) + " — ok")

        self._start_record(stages, network, prereq)
        assert self.out_dir is not None
        self.log(f"[make] 出力: {self.out_dir}")
        steps: list[str] = []
        try:
            for name in stages:
                need, why = self.stage_needed(name)
                if not need:
                    self.stage_record(name, status="skipped", reason=why)
                    self.log(f"[{name}] 省略: {why}")
                    continue
                self.log(f"[{name}] {STAGE_TITLES[name]}")
                self.run["stages"][name] = {"title": STAGE_TITLES[name], "status": "running", "started_at": self.iso()}
                self.write_run()
                try:
                    info = getattr(self, f"_stage_{name}")() or {}
                except StageFailed:
                    raise
                except (AssetsError, BuildError, NarrationError, ExportError, MuxError) as e:
                    raise StageFailed(name, str(e)) from e
                self.stage_record(name, status="ok", started_at=self.run["stages"][name]["started_at"],
                                  finished_at=self.iso(), **info)
            if self.stage_needed("export")[0]:
                self.run["status"] = "done"
                self.log(f"[make] できました: {self.out_dir / (self.stem + '.mp4')}")
            else:
                self.run["status"] = "needs_export"
                steps = self.manual_steps()
                self.run["next_steps"] = steps
                self.log("[make] .pptx まで作りました。Windows で次を実行すると MP4 になります:")
                for s in steps:
                    self.log("  " + s)
            return MakeResult(self.run["status"], self.out_dir, self.run, steps)
        except StageFailed as e:
            self.run["stages"][e.stage].update(status="failed", error=str(e), finished_at=self.iso())
            self.run.update(status="failed", error=f"{e.stage}: {e}", resume=self.command(e.stage))
            self.log(f"[make] 失敗した段: {e.stage}（{STAGE_TITLES[e.stage]}）")
            self.log(f"  理由: {e}")
            self.log(f"  直したら、そこから: {self.run['resume']}")
            raise MakeStop(f"{e.stage}: {e}") from e
        except Exception as e:  # 想定外の失敗も記録してから上へ
            self.run.update(status="failed", error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc(limit=5))
            raise
        finally:
            self.run["finished_at"] = self.iso()
            self.write_run()

    def manual_steps(self) -> list[str]:
        assert self.out_dir is not None
        pptx, silent = self.out_dir / f"{self.stem}.pptx", self.out_dir / "work" / f"{self.stem}.silent.mp4"
        return [f"# 1) PowerPoint で無音の MP4 に書き出す\n{manual_command(pptx, silent)}",
                f"# 2) 続きを作る（書き出しから）\n{self.command('export')}"]

    # ------------------------------------------------------------ 段

    @property
    def work(self) -> Path:
        assert self.out_dir is not None
        return self.out_dir / "work"

    def _stage_capture(self) -> dict[str, Any]:
        from ..capture.web import capture as wc

        fn = self.h.capture or wc.run_capture
        try:
            res = fn(self.storyboard, self.captures_dir, self.actions_path, None, self.o.url_map,
                     self.o.channel, self.o.executable, False, serve=self.o.serve, log=self.log)
        except wc.CaptureError as e:
            raise StageFailed("capture", str(e)) from e
        if res.get("failed"):
            bad = [f"{s.get('id')}: {s.get('error')}" for s in res.get("scenes", []) if s.get("status") == "failed"]
            raise StageFailed("capture", f"撮影に失敗したシーンが {res['failed']} 件あります: " + " / ".join(bad))
        return {"ok": res.get("ok"), "out": str(self.captures_dir)}

    def _stage_diagram(self) -> dict[str, Any]:
        from .. import diagram as dg

        fn = self.h.diagram or dg.run_diagram
        out = self.work / "diagram"
        try:
            res = fn(self.storyboard, out, None, self.o.channel, self.o.executable, log=self.log)
        except dg.DiagramError as e:
            raise StageFailed("diagram", str(e)) from e
        if res.get("failed"):
            bad = [f"{s.get('id')}: {s.get('error')}" for s in res.get("scenes", []) if s.get("status") == "failed"]
            raise StageFailed("diagram", f"描けなかった説明図が {res['failed']} 件あります: " + " / ".join(bad))
        return {"ok": res.get("ok"), "out": str(out)}

    def _stage_assets(self) -> dict[str, Any]:
        diagram_dir = self.work / "diagram"
        plan = resolve_assets(self.doc, self.storyboard.parent, captures_dir=self.captures_dir,
                              diagram_dir=diagram_dir if diagram_dir.is_dir() else None,
                              assets_root=self.o.assets_root)
        if plan.missing_manual:
            raise StageFailed("assets", "manual の画像が見つかりません: "
                              + ", ".join(f"{i.id}: {i.ref}（探した場所: {', '.join(i.searched)}）" for i in plan.missing_manual))
        if plan.placeholders and not self.o.allow_placeholders:
            raise StageFailed("assets", f"画像の無いシーンが {len(plan.placeholders)} 件あります: {plan.placeholder_text()}。"
                              "撮影・説明図の段を確かめるか、試作なら --allow-placeholders（灰色の枠で作る）")
        image_of = {e.id: e.path for e in plan.images}
        unresolved = []
        for sc in self.doc["scenes"]:
            unresolved += deck_marks.resolve_scene(sc, image_of.get(sc["id"])).unresolved
        if unresolved and not self.o.allow_placeholders:
            raise StageFailed("assets", f"位置の決まらない注釈が {len(unresolved)} 件あります: "
                              + ", ".join(u.text() for u in unresolved)
                              + "。撮影・説明図で marks.json を出すか、試作なら --allow-placeholders（既定の位置に置く）")
        warns = []
        if plan.placeholders:
            warns.append(f"画像の無いシーン（灰色の枠）: {plan.placeholder_text()}")
        if unresolved:
            warns.append(f"位置の決まらない注釈（既定の位置）: {', '.join(u.text() for u in unresolved)}")
        self.run["warnings"] += warns
        for w in warns:
            self.log(f"[assets] 注意: {w}")
        stage_assets(plan, self.work / "assets")
        self.run["assets"] = plan.record()
        self.log(f"[assets] 画像 {len(plan.found)} 件 → {self.work / 'assets'}")
        return {"found": len(plan.found), "placeholders": len(plan.placeholders), "unresolved_marks": len(unresolved)}

    def _dictionary(self) -> tuple[PronunciationDictionary, list[str]]:
        specs = self.o.dictionaries if self.o.dictionaries is not None else self.cfg.dictionaries
        if not specs:
            return PronunciationDictionary.empty(), []
        d, paths = load_dictionaries(specs)
        return d, [str(p) for p in paths]

    def _stage_voice(self) -> dict[str, Any]:
        path = self.work / "narration-input.json"
        path.write_text(json.dumps(self.narration_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        dictionary, dict_paths = self._dictionary()
        narration = parse_input(self.narration_input)
        out = self.work / "narration"
        durations = run_synth(narration, out, self.engine(), dictionary=dictionary, force=self.o.force,
                              log=lambda m: self.log(f"[voice] {m}"))
        total = sum(i["slide_sec"] for i in durations["items"])
        return {"durations": str(out / "durations.json"), "dictionaries": dict_paths, "slides_sec": round(total, 2)}

    def _stage_deck(self) -> dict[str, Any]:
        assert self.out_dir is not None
        pptx = self.out_dir / f"{self.stem}.pptx"
        res = build_deck(self.storyboard, pptx, durations=self.work / "narration" / "durations.json",
                         assets_root=self.work / "assets", credit=self.credit,
                         overlay=self.work / "check" / "overlay.png")
        self.run["warnings"] += res.warnings
        self.run["files"]["pptx"] = str(pptx)
        secs = f"、{res.video_sec:.2f} 秒" if res.video_sec is not None else ""
        self.log(f"[deck] {pptx}（{res.slide_count} 枚{secs}）"
                 + (f"、クレジット: {self.credit}" if self.credit else ""))
        return {"slides": res.slide_count, "video_sec": res.video_sec, "credit": self.credit,
                "overlay": str(res.overlay) if res.overlay else None, "slide_ids": res.slide_ids,
                "unresolved_marks": len(res.unresolved),
                # zoom: per_mark で 1 シーンを複数のスライドに分けた数と、その中身
                "split_slides": {sid: len(parts) for sid, parts in res.split.items()}, "split": res.split}

    def _stage_export(self) -> dict[str, Any]:
        assert self.out_dir is not None
        exporter = self.h.exporter or powershell_exporter()
        silent = self.work / f"{self.stem}.silent.mp4"
        info = exporter(self.out_dir / f"{self.stem}.pptx", silent, True)
        self.log(f"[export] {silent} {info.get('status', '')}")
        return {"silent_mp4": str(silent), "result": info}

    def _stage_mux(self) -> dict[str, Any]:
        assert self.out_dir is not None
        final = self.out_dir / f"{self.stem}.mp4"
        res = mux(self.work / f"{self.stem}.silent.mp4", self.out_dir / f"{self.stem}.pptx", slide_ids(self.doc),
                  self.work / "narration" / "durations.json", final, ffmpeg=self.o.ffmpeg, ffprobe=self.o.ffprobe,
                  overwrite=True)
        self.run["warnings"] += res.warnings
        for line in res.info:
            self.log(f"[mux] {line}")
        self.run["files"]["mp4"] = str(final)
        return {"mp4": str(final), "expected_sec": res.expected_sec, "video_sec": res.output_video_sec,
                "audio_sec": res.output_audio_sec, "morph_count": res.morph_count,
                "morph_extra_sec": res.morph_extra_sec, "drift_corrected": res.drift_corrected,
                "silent_video_sec": res.video_sec, "info": res.info}


def make(opts: MakeOptions, cfg: kit_config.KitConfig | None = None, hooks: Hooks | None = None,
         log: Callable[[str], None] = print) -> MakeResult:
    return Maker(opts, cfg, hooks, log).execute()
