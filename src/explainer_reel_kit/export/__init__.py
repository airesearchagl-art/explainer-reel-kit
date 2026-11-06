"""書き出し: PowerPoint（デスクトップ版、Windows）で .pptx を無音の MP4 にする。

書き出しの本体は PowerShell のスクリプト ``Export-PptxToVideo.ps1``（パッケージのデータ。ASCII のみ）。
PowerPoint の COM（Presentation.CreateVideo）を使い、スライドの自動切替の秒数とアニメーションの時刻で動画の長さが決まる。
スクリプトは手でも呼べる（``erkit make`` が表示する手順）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any, Callable

SCRIPT_NAME = "Export-PptxToVideo.ps1"

#: (pptx, 出力 mp4, 上書きするか) → スクリプトの結果（JSON 1 行の中身と exit_code）
Exporter = Callable[[Path, Path, bool], dict[str, Any]]

EXIT_MEANING = {
    2: "引数・入力の誤り（Windows 以外を含む）",
    3: "出力ファイルが既にある（--force で上書き）",
    4: "PowerPoint を起動できない・開けない",
    5: "PowerPoint が書き出しに失敗した",
    6: "時間切れ",
}


class ExportError(Exception):
    """書き出しに失敗した。"""


def script_path() -> Path:
    """パッケージのデータとして入っているスクリプトの実際のパス。"""
    return Path(str(resources.files(__name__).joinpath(SCRIPT_NAME)))


def is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform).startswith("win")


def parse_result(stdout: str) -> dict[str, Any]:
    """スクリプトの標準出力の最後の JSON 1 行。"""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def powershell_exporter(powershell: str = "powershell", runner=subprocess.run) -> Exporter:
    """Export-PptxToVideo.ps1 を呼ぶ書き出し（Windows）。"""

    def run(pptx: Path, out_mp4: Path, force: bool) -> dict[str, Any]:
        cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path()),
               "-InputPath", str(pptx), "-OutputPath", str(out_mp4)]
        if force:
            cmd.append("-Force")
        res = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        info = parse_result(res.stdout)
        info.setdefault("exit_code", res.returncode)
        if res.returncode != 0:
            meaning = EXIT_MEANING.get(res.returncode, "")
            detail = info.get("error") or (res.stderr or "").strip()[-500:]
            raise ExportError(f"書き出しが終了コード {res.returncode} で止まりました（{meaning}）: {detail}".rstrip(": "))
        return info

    return run


def manual_command(pptx: Path, out_mp4: Path) -> str:
    """手で書き出すときのコマンド（PowerShell）。"""
    return (f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script_path()}" '
            f'-InputPath "{pptx}" -OutputPath "{out_mp4}"')
