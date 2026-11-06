"""install.ps1・erkit.ps1 の静的な検査。

- ASCII だけ・BOM なし（Windows PowerShell 5.1 は BOM の無いファイルをシステムの文字コードで読む）
- 外部ソフトを入れない（winget は案内の文字列にだけ出る）・管理者の権限を求めない
- PowerShell の構文（pwsh か powershell があるときだけ。Windows の CI で動く）
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / "install.ps1", ROOT / "erkit.ps1"]


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_ascii_only(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "BOM がある"
    bad = [(i + 1, ln) for i, ln in enumerate(data.splitlines()) if any(b > 0x7F for b in ln)]
    assert not bad, f"ASCII 以外の文字がある行: {bad[:3]}"


def test_install_does_not_install_external_software():
    text = (ROOT / "install.ps1").read_text(encoding="ascii")
    for no, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0]
        if "winget" in code:
            assert "Write-Note" in code or "Write-Warn" in code, f"{no}: winget を実行している: {line}"
    lowered = text.lower()
    assert "runas" not in lowered            # 管理者の権限で起動し直さない
    for word in ("Invoke-WebRequest", "Start-BitsTransfer", "msiexec"):
        assert word.lower() not in lowered, word


def test_install_steps_in_order():
    text = (ROOT / "install.ps1").read_text(encoding="ascii")
    order = ["1/5 Python", "2/5 Virtual environment", "3/5 Browser", "4/5 Config files", "5/5 erkit doctor"]
    pos = [text.index(s) for s in order]
    assert pos == sorted(pos)
    assert 'pip install -e ".[dev]"' in text
    assert "playwright install chromium" in text
    assert "--channel msedge" in text        # 失敗したら Edge を案内
    assert "Test-Path $dest" in text          # 設定は上書きしない


def test_erkit_ps1_passes_args_and_exit_code():
    text = (ROOT / "erkit.ps1").read_text(encoding="ascii")
    assert "& $erkit @args" in text
    assert "exit $LASTEXITCODE" in text


def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


@pytest.mark.skipif(_powershell() is None, reason="PowerShell が無い（Windows の CI で確かめる）")
@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_powershell_syntax(path):
    script = (
        "$errs = $null; $tokens = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errs); "
        "if ($errs.Count -gt 0) { $errs | ForEach-Object { Write-Output $_.ToString() }; exit 1 } else { exit 0 }"
    )
    r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(_powershell() is None, reason="PowerShell が無い（Windows の CI で確かめる）")
def test_erkit_ps1_without_venv_says_install(tmp_path):
    """.venv が無い場所では、install.ps1 を案内して終了コード 2。"""
    copy = tmp_path / "erkit.ps1"
    shutil.copy(ROOT / "erkit.ps1", copy)
    r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(copy), "doctor"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 2
    assert "install.ps1" in r.stdout
