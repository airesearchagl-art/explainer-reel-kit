"""``erkit doctor``: 動画を作るのに要るものがそろっているかを確かめ、無いものの入れ方を表示する（入れはしない）。

同じ確認を ``erkit make`` が実行の前に使う（残りの段に要るものだけ）。

終了コード: 0 そろっている（Windows 以外で PowerPoint が無いのは対象外として数えない） / 1 足りないものがある / 2 設定の誤り
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from . import config as kit_config

OK, FAIL, SKIP, WARN = "ok", "fail", "skip", "warn"
MIN_PYTHON = (3, 10)
PACKAGES = {"jsonschema": "jsonschema", "yaml": "PyYAML", "pptx": "python-pptx", "lxml": "lxml", "PIL": "Pillow",
            "playwright": "playwright"}

HINTS = {
    "python": "Python 3.10 以上を入れる（例: winget install Python.Python.3.12）。入れたらターミナルを開き直す",
    "packages": 'キットのフォルダで python -m pip install -e ".[dev]" をやり直す',
    "browser": "python -m playwright install chromium で入れるか、Windows の Edge を使う（--channel msedge）",
    "ffmpeg": "ffmpeg を入れる（例: winget install Gyan.FFmpeg）。入れたらターミナルを開き直し、ffmpeg -version で確かめる",
    "powerpoint": "PowerPoint のデスクトップ版（Microsoft 365 / Office）が要る。Web 版・ストア版の閲覧用では書き出せない",
    "engine": "AivisSpeech（https://aivis-project.com/）を入れて起動する。起動していれば http://127.0.0.1:10101 で待ち受ける",
    "voice": "AivisSpeech の画面で既定の声（ほのか）を入れるか、erkit voice list の一覧から選んで config/kit.yaml の voice.speaker に書く",
    "output": "config/kit.yaml の output_root か環境変数 ERKIT_OUTPUT_ROOT で、書き込めるフォルダを指定する",
}


@dataclass
class CheckResult:
    key: str
    name: str
    status: str  # ok / fail / skip / warn
    detail: str = ""
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.status != FAIL


def _first_line(text: str) -> str:
    text = (text or "").strip()
    return text.splitlines()[0] if text else ""


# ---------------------------------------------------------------- 個々の確認（失敗なら理由、そろっていれば None）

def check_python() -> CheckResult:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < MIN_PYTHON:
        return CheckResult("python", "Python", FAIL, f"{ver}（3.10 以上が要る）", HINTS["python"])
    return CheckResult("python", "Python", OK, f"{ver}（{sys.executable}）")


def check_packages(importer: Callable[[str], Any] = importlib.import_module) -> CheckResult:
    missing = []
    for mod, dist in PACKAGES.items():
        try:
            importer(mod)
        except ImportError:
            missing.append(dist)
    if missing:
        return CheckResult("packages", "Python のライブラリ", FAIL, "入っていない: " + ", ".join(missing), HINTS["packages"])
    return CheckResult("packages", "Python のライブラリ", OK, ", ".join(PACKAGES.values()))


def check_browser(channel: str | None = None, executable: str | None = None) -> CheckResult:
    """Playwright のブラウザを実際に起動して閉じる（撮影・説明図の段で使う）。"""
    from . import browser as br

    label = executable or (f"channel={channel}" if channel else "Playwright の Chromium")
    try:
        with br.sync_playwright() as pw:
            b = br.launch(pw, channel, executable)
            version = b.version
            b.close()
    except br.BrowserError as e:
        return CheckResult("browser", "ブラウザ（撮影・説明図）", FAIL, f"{label}: {e}", HINTS["browser"])
    except Exception as e:  # noqa: BLE001 - Playwright の内部の失敗もトレースバックにしない
        return CheckResult("browser", "ブラウザ（撮影・説明図）", FAIL, f"{label}: {_first_line(str(e))}", HINTS["browser"])
    return CheckResult("browser", "ブラウザ（撮影・説明図）", OK, f"{label} {version}")


def check_ffmpeg(ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", run=subprocess.run) -> CheckResult:
    found = []
    for exe in (ffmpeg, ffprobe):
        path = shutil.which(exe)
        if path is None:
            return CheckResult("ffmpeg", "ffmpeg / ffprobe", FAIL, f"{exe} が見つからない（PATH）", HINTS["ffmpeg"])
        try:
            r = run([path, "-hide_banner", "-version"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            return CheckResult("ffmpeg", "ffmpeg / ffprobe", FAIL, f"{exe} を実行できない: {e}", HINTS["ffmpeg"])
        if r.returncode != 0:
            return CheckResult("ffmpeg", "ffmpeg / ffprobe", FAIL, f"{exe} -version が終了コード {r.returncode}", HINTS["ffmpeg"])
        found.append(_first_line(r.stdout).replace(" Copyright", "").split(" (c)")[0])
    return CheckResult("ffmpeg", "ffmpeg / ffprobe", OK, found[0] if found else "")


def _powerpoint_registered() -> bool:  # pragma: no cover - Windows だけ
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CLSID"):
            return True
    except OSError:
        return False


def check_powerpoint(platform: str | None = None, registered: Callable[[], bool] | None = None) -> CheckResult:
    from .export import is_windows

    if not is_windows(platform):
        return CheckResult("powerpoint", "PowerPoint（書き出し）", SKIP,
                           "Windows でだけ使う（この PC では .pptx まで作り、書き出しの手順を表示する）")
    if not (registered or _powerpoint_registered)():
        return CheckResult("powerpoint", "PowerPoint（書き出し）", FAIL,
                           "PowerPoint.Application が登録されていない", HINTS["powerpoint"])
    return CheckResult("powerpoint", "PowerPoint（書き出し）", OK, "PowerPoint.Application（COM）が登録されている")


def check_engine(engine_name: str | None, url: str | None, speaker: int, *, transport=None,
                 timeout: float = 5.0) -> tuple[CheckResult, CheckResult]:
    """(エンジンへの接続, 既定の声)。"""
    from .narration.errors import NarrationError
    from .narration.tts import get_engine

    kwargs: dict[str, Any] = {"timeout_sec": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    try:
        engine = get_engine(engine_name, url, **kwargs)
        info = engine.check()
        voices = engine.voices()
    except NarrationError as e:
        name = engine_name or "aivisspeech"
        return (CheckResult("engine", "音声合成エンジン", FAIL, f"{name} {url or ''}: {_first_line(str(e))}".strip(), HINTS["engine"]),
                CheckResult("voice", "既定の声", SKIP, "エンジンにつながらないため確かめていない"))
    eng = CheckResult("engine", "音声合成エンジン", OK, f"{info.name} {info.url}（version {info.version}、声 {len(voices)}）")
    hit = next((v for v in voices if v.style_id == speaker), None)
    if hit is None:
        label = kit_config.DEFAULT_SPEAKER_LABEL if speaker == kit_config.DEFAULT_SPEAKER else ""
        listed = "、".join(f"{v.style_id} {v.label}" for v in voices[:6]) or "声がない"
        return eng, CheckResult("voice", "既定の声", FAIL, f"{speaker} {label}がない（入っている声: {listed}）", HINTS["voice"])
    return eng, CheckResult("voice", "既定の声", OK, f"{speaker} {hit.label}")


def check_output_root(root: Path) -> CheckResult:
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".erkit-doctor-", delete=True):
            pass
    except OSError as e:
        return CheckResult("output", "出力先", FAIL, f"{root}: 書き込めない（{e}）", HINTS["output"])
    free = shutil.disk_usage(root).free / 1024 ** 3
    status = WARN if free < 2 else OK
    return CheckResult("output", "出力先", status, f"{root}（空き {free:.1f} GB）",
                       "動画 1 本の作業に 1〜2 GB ほど使う。空きを作るか出力先を変える" if status == WARN else "")


# ---------------------------------------------------------------- まとめ

def run_checks(cfg: kit_config.KitConfig, *, engine_url: str | None = None, channel: str | None = None,
               executable: str | None = None, output_root: Path | None = None, platform: str | None = None,
               transport=None, skip_browser: bool = False) -> list[CheckResult]:
    results = [check_python(), check_packages()]
    results.append(CheckResult("browser", "ブラウザ（撮影・説明図）", SKIP, "--skip-browser") if skip_browser
                   else check_browser(channel, executable))
    results.append(check_ffmpeg())
    results.append(check_powerpoint(platform))
    results += check_engine(cfg.voice_engine, engine_url or cfg.voice_url, cfg.voice_speaker, transport=transport)
    results.append(check_output_root(kit_config.output_root(cfg, output_root)))
    return results


MARK = {OK: "OK  ", FAIL: "NG  ", SKIP: "--  ", WARN: "注意"}


def print_results(results: list[CheckResult], cfg: kit_config.KitConfig, out=print) -> None:
    out(f"設定: {cfg.path or '（無し。既定値で確かめる）'}")
    for r in results:
        out(f"{MARK[r.status]} {r.name}: {r.detail}")
        if r.status in (FAIL, WARN) and r.hint:
            out(f"      → {r.hint}")
    bad = [r for r in results if r.status == FAIL]
    out("そろっています" if not bad else f"足りないもの {len(bad)} 件（上の → の手順で入れてください。キットは自動では入れません）")


def configure(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--config", type=Path, help="設定ファイル（既定: config/kit.yaml を探す）")
    p.add_argument("--engine-url", help="音声合成エンジンの URL（既定: 設定、無ければ http://127.0.0.1:10101）")
    p.add_argument("--channel", help="撮影に使うブラウザ（msedge / chrome）。既定は Playwright の Chromium")
    p.add_argument("--executable", help="ブラウザの実行ファイルのパス")
    p.add_argument("--output-root", type=Path, help="出力先のルート")
    p.add_argument("--skip-browser", action="store_true", help="ブラウザの起動を確かめない")
    p.add_argument("--json", action="store_true", help="結果を JSON で出す")
    p.set_defaults(func=run)
    return p


def register(sub) -> None:
    configure(sub.add_parser("doctor", help="動画を作るのに要るものがそろっているか確かめる",
                             description="Python・ライブラリ・ブラウザ・ffmpeg・PowerPoint・AivisSpeech（既定の声）・出力先を確かめる"))


def run(args, *, transport=None, platform: str | None = None) -> int:
    try:
        cfg = kit_config.load_config(args.config)
    except kit_config.ConfigError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    results = run_checks(cfg, engine_url=args.engine_url, channel=args.channel, executable=args.executable,
                         output_root=args.output_root, platform=platform, transport=transport,
                         skip_browser=args.skip_browser)
    if args.json:
        print(json.dumps({"config": str(cfg.path) if cfg.path else None,
                          "ok": all(r.ok for r in results), "checks": [asdict(r) for r in results]},
                         ensure_ascii=False, indent=2))
    else:
        print_results(results, cfg)
    return 0 if all(r.ok for r in results) else 1


def main(argv: list[str] | None = None, **kw) -> int:
    parser = configure(argparse.ArgumentParser(prog="erkit doctor"))
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return run(args, **kw)


__all__ = ["CheckResult", "run_checks", "check_engine", "check_ffmpeg", "check_powerpoint", "check_browser",
           "check_packages", "check_python", "check_output_root", "main"]
