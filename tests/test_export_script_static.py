"""Static checks for export/windows/Export-PptxToVideo.ps1 .

Runs only when PowerShell 7 (`pwsh`) is on PATH; skipped otherwise.
PowerPoint COM itself cannot run here, so behavior on Windows is checked by
a human (the Windows steps in the PR / README).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from explainer_reel_kit.export import script_path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = script_path()
PWSH = os.environ.get("PWSH") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="pwsh not available")


def _pwsh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO,
    )


def test_script_parses_without_errors() -> None:
    cmd = (
        "$t=$null;$e=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$t,[ref]$e);"
        "$e.Count"
    )
    res = _pwsh("-Command", cmd)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "0"


def test_syntax_lists_expected_parameters() -> None:
    res = _pwsh("-Command", f"Get-Command -Syntax '{SCRIPT}'")
    assert res.returncode == 0, res.stderr
    for name in (
        "-InputPath", "-OutputPath", "-VertResolution", "-Fps", "-Quality",
        "-DefaultSlideSeconds", "-TimeoutSec", "-Force",
    ):
        assert name in res.stdout


def _call_stop_decision(exit_code: int, started_by_us: bool, owned: int, others: str) -> str:
    """Load only Get-OwnedPowerPointStopDecision from the script (via AST) and call it."""
    cmd = (
        "$t=$null;$e=$null;"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$t,[ref]$e);"
        "$fn=$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]"
        " -and $n.Name -eq 'Get-OwnedPowerPointStopDecision'}, $true) | Select-Object -First 1;"
        "if (-not $fn) { throw 'function not found' };"
        ". ([scriptblock]::Create($fn.Extent.Text));"
        f"Get-OwnedPowerPointStopDecision -ExitCode {exit_code} "
        f"-StartedByUs ${str(started_by_us).lower()} -OwnedPidCount {owned} "
        f"-OtherPresentationsOpen {others}"
    )
    res = _pwsh("-Command", cmd)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.mark.parametrize(
    ("exit_code", "started_by_us", "owned", "others", "expected"),
    [
        # Regression guard: failure + other presentations open -> do not Stop-Process
        (6, True, 1, "2", "skip-others-open"),
        # Count unknown (PowerPoint busy) is treated as "may be open"
        (6, True, 1, "$null", "skip-others-open"),
        # Failure in our own idle instance -> stop it
        (6, True, 1, "0", "stop"),
        (5, True, 1, "0", "stop"),
        # Never stop the user's PowerPoint, nor after success
        (6, False, 0, "0", "none"),
        (6, False, 1, "0", "none"),
        (0, True, 1, "0", "none"),
        (6, True, 0, "0", "none"),
    ],
)
def test_owned_powerpoint_stop_decision(
    exit_code: int, started_by_us: bool, owned: int, others: str, expected: str
) -> None:
    assert _call_stop_decision(exit_code, started_by_us, owned, others) == expected


def test_stop_process_is_gated_by_stop_decision() -> None:
    """The only Stop-Process call must sit behind the 'stop' decision."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count("Stop-Process") == 1
    gate = text.index("if ($stopDecision -eq 'stop')")
    assert gate < text.index("Stop-Process")


_PARSE = (
    "Set-StrictMode -Version 3.0;"
    "$t=$null;$e=$null;"
    f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$t,[ref]$e);"
)


def test_process_id_calls_are_always_wrapped_in_array() -> None:
    """Every Get-PowerPointProcessId call must be the sole command inside @(...).

    Regression for the Windows run: unwrapped, 0 processes -> $null and
    StrictMode 3 throws on $null.Count.
    """
    cmd = _PARSE + (
        "$calls=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]"
        " -and $n.GetCommandName() -eq 'Get-PowerPointProcessId'}, $true));"
        "$bad=@($calls | Where-Object { -not ("
        " $_.Parent -is [System.Management.Automation.Language.PipelineAst] -and"
        " $_.Parent.PipelineElements.Count -eq 1 -and"
        " $_.Parent.Parent.Parent -is [System.Management.Automation.Language.ArrayExpressionAst]) });"
        "'calls=' + $calls.Count; 'bad=' + $bad.Count; $bad | ForEach-Object { 'line ' + $_.Extent.StartLineNumber }"
    )
    res = _pwsh("-Command", cmd)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.split()
    assert "bad=0" in lines, res.stdout
    assert int(lines[0].split("=")[1]) >= 3  # $pidsBefore, $ourPids (try + finally)


def _assignment_rhs(variable: str) -> str:
    """Source text of every RHS assigned to `$variable` in the script, as pwsh code."""
    return (
        f"$rhs=@($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst]"
        f" -and $n.Left.Extent.Text -eq '${variable}'}}, $true) | ForEach-Object {{ $_.Right.Extent.Text }});"
        "if ($rhs.Count -eq 0) { throw 'no assignment found' };"
    )


@pytest.mark.parametrize("n_procs", [0, 1, 2])
def test_pid_lists_count_with_mocked_processes(n_procs: int) -> None:
    """Evaluate the script's real RHS for $pidsBefore / $ourPids with a mock."""
    ids = ",".join(str(1000 + i) for i in range(n_procs))
    mock = f"function Get-PowerPointProcessId {{ {ids if ids else ''} }};"
    cmd = _PARSE + mock + (
        _assignment_rhs("pidsBefore")
        # Dot-source the assignment itself; Invoke-Expression would unroll the result.
        + "foreach ($r in $rhs) { . ([scriptblock]::Create('$pidsBefore = ' + $r)); 'before=' + $pidsBefore.Count };"
        # Our-process lists, with nothing running before (the 'we started it' case).
        + "$pidsBefore = @();"
        + _assignment_rhs("ourPids")
        + "foreach ($r in $rhs) { if ($r -match 'Get-PowerPointProcessId') {"
        "   . ([scriptblock]::Create('$ourPids = ' + $r)); 'ours=' + $ourPids.Count } }"
    )
    res = _pwsh("-Command", cmd)
    assert res.returncode == 0, res.stderr
    out = res.stdout.split()
    befores = [x for x in out if x.startswith("before=")]
    ours = [x for x in out if x.startswith("ours=")]
    assert befores == [f"before={n_procs}"]
    assert len(ours) >= 2
    assert set(ours) == {f"ours={n_procs}"}


def test_unwrapped_call_reproduces_the_windows_failure() -> None:
    """Documents the bug: without @(), 0 processes gives $null and .Count throws."""
    cmd = (
        "Set-StrictMode -Version 3.0;"
        "function Get-PowerPointProcessId { };"
        "$x = Get-PowerPointProcessId;"
        "try { $null = $x.Count; 'no-throw' } catch { 'throws' }"
    )
    res = _pwsh("-Command", cmd)
    assert res.stdout.strip() == "throws"


def test_ownership_is_decided_before_com_and_outside_try() -> None:
    """$startedByUs must be set before New-Object -ComObject and not inside try,
    so an early exception still lets `finally` quit/stop the PowerPoint we started."""
    cmd = _PARSE + (
        "$asg=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst]"
        " -and $n.Left.Extent.Text -eq '$startedByUs'}, $true));"
        "$com=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]"
        " -and $n.GetCommandName() -eq 'New-Object'}, $true))[0];"
        "$inTry=$false; $p=$asg[0].Parent; while ($p) { if ($p -is [System.Management.Automation.Language.TryStatementAst]) { $inTry=$true }; $p=$p.Parent };"
        "'assignments=' + $asg.Count; 'before_com=' + ($asg[0].Extent.StartOffset -lt $com.Extent.StartOffset); 'in_try=' + $inTry"
    )
    res = _pwsh("-Command", cmd)
    assert res.returncode == 0, res.stderr
    out = res.stdout.split()
    assert out == ["assignments=1", "before_com=True", "in_try=False"]


@pytest.mark.skipif(os.name == "nt", reason="checks the non-Windows guard")
def test_non_windows_exits_2_with_json_line() -> None:
    res = _pwsh("-File", str(SCRIPT), "-InputPath", "in.pptx", "-OutputPath", "out.mp4")
    assert res.returncode == 2
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["status"] == "invalid_environment"
    assert {"input", "output", "seconds_elapsed", "status"} <= payload.keys()
    assert "invalid_environment" in res.stderr
