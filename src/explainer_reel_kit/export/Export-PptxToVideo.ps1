<#
.SYNOPSIS
    Export a PowerPoint deck (.pptx) to a silent MP4 via PowerPoint COM (CreateVideo).

.DESCRIPTION
    explainer-reel-kit export runner (erkit make calls it; it can also be run by hand).

    1. Starts PowerPoint through COM (or attaches to the running instance).
    2. Opens the deck read-only and without a window (unless -ShowWindow).
    3. Calls Presentation.CreateVideo with UseTimingsAndNarrations = true, so
       per-slide auto-advance times (p:transition advTm) and animation timings
       in the deck decide the video length. Slides without a timing use
       -DefaultSlideSeconds.
    4. Polls Presentation.CreateVideoStatus until Done / Failed / timeout.
    5. Closes the deck and quits PowerPoint only if this script started it.

    The video is first written to a temporary "*.partial-<id>.mp4" file next to
    the output and renamed on success, so an existing output file is never left
    half-written. An existing output is only replaced with -Force.

    On exit one JSON line is written to stdout:
      {"input":..., "output":..., "seconds_elapsed":..., "status":..., "duration_sec":...}
    duration_sec is present only when ffprobe is on PATH and the export succeeded.
    On failure an "error" field is added and the reason is written to stderr.

    Exit codes:
      0  done
      2  invalid arguments / input file not found / output folder missing / not Windows
      3  output file exists (use -Force)
      4  COM failure (PowerPoint could not be started, deck could not be opened, CreateVideo threw)
      5  PowerPoint reported CreateVideoStatus = Failed
      6  timeout (-TimeoutSec elapsed)

.PARAMETER InputPath
    Path of the deck to export (.pptx; .pptm / .ppsx are also accepted).

.PARAMETER OutputPath
    Path of the MP4 to write. The parent folder must already exist; this script
    never chooses or creates an output location by itself.

.PARAMETER VertResolution
    Vertical resolution in pixels (default 1080).

.PARAMETER Fps
    Frames per second (default 30).

.PARAMETER Quality
    Encoder quality 1-100 (default 85).

.PARAMETER DefaultSlideSeconds
    Seconds for slides that have no timing of their own (default 5).

.PARAMETER TimeoutSec
    Give up after this many seconds (default 1800).

.PARAMETER PollIntervalSec
    Seconds between CreateVideoStatus polls (default 1).

.PARAMETER Force
    Replace an existing output file (only after the new video succeeded).

.PARAMETER ShowWindow
    Open the deck with a document window. Use this if your PowerPoint build
    refuses to export a windowless presentation.

.EXAMPLE
    .\Export-PptxToVideo.ps1 -InputPath .\timing_fixture.pptx -OutputPath .\timing_fixture.mp4
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $InputPath,

    [Parameter(Mandatory = $true)]
    [string] $OutputPath,

    [ValidateRange(144, 4320)]
    [int] $VertResolution = 1080,

    [ValidateRange(1, 60)]
    [int] $Fps = 30,

    [ValidateRange(1, 100)]
    [int] $Quality = 85,

    [ValidateRange(1, 86400)]
    [int] $DefaultSlideSeconds = 5,

    [ValidateRange(1, 86400)]
    [int] $TimeoutSec = 1800,

    [ValidateRange(0.2, 60)]
    [double] $PollIntervalSec = 1,

    [switch] $Force,

    [switch] $ShowWindow
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# --- constants ---------------------------------------------------------------
# MsoTriState
$msoTrue = -1
$msoFalse = 0
# PpAlertLevel
$ppAlertsNone = 1
# PpMediaTaskStatus
$StatusNames = @{
    0 = 'None'
    1 = 'InProgress'
    2 = 'Queued'
    3 = 'Done'
    4 = 'Failed'
}

$ExitOk = 0
$ExitBadInput = 2
$ExitOutputExists = 3
$ExitCom = 4
$ExitFailed = 5
$ExitTimeout = 6

# --- state shared with Finish ------------------------------------------------
$script:Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$script:InputFull = $InputPath
$script:OutputFull = $OutputPath

function Write-Result {
    param(
        [string] $Status,
        [string] $ErrorMessage,
        [Nullable[double]] $DurationSec
    )
    $result = [ordered]@{
        input           = $script:InputFull
        output          = $script:OutputFull
        seconds_elapsed = [math]::Round($script:Stopwatch.Elapsed.TotalSeconds, 1)
        status          = $Status
    }
    if ($null -ne $DurationSec) {
        $result['duration_sec'] = [math]::Round([double]$DurationSec, 3)
    }
    if ($ErrorMessage) {
        $result['error'] = $ErrorMessage
    }
    [Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
}

function Exit-WithError {
    param([int] $Code, [string] $Status, [string] $Message)
    [Console]::Error.WriteLine("Export-PptxToVideo: $Status - $Message")
    Write-Result -Status $Status -ErrorMessage $Message
    exit $Code
}

function Get-FfprobeDuration {
    param([string] $Path)
    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if (-not $ffprobe) { return $null }
    try {
        $out = & $ffprobe.Source -v error -show_entries format=duration `
            -of default=noprint_wrappers=1:nokey=1 -- $Path 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $text = ([string]($out | Select-Object -First 1)).Trim()
        $value = 0.0
        if ([double]::TryParse($text, [System.Globalization.NumberStyles]::Float,
                [System.Globalization.CultureInfo]::InvariantCulture, [ref]$value)) {
            return $value
        }
    }
    catch {
        [Console]::Error.WriteLine("Export-PptxToVideo: warning - ffprobe failed: $($_.Exception.Message)")
    }
    return $null
}

function Get-OwnedPowerPointStopDecision {
    <#
        Decide whether the PowerPoint process(es) this script started may be
        force-stopped after a failure. Pure function (no side effects) so the
        rule can be tested without PowerPoint.

        Returns:
          'none'              - success, not started by us, or no owned process
          'skip-others-open'  - failure, but other presentations are open or the
                                count is unknown ($null): never risk unsaved work
          'stop'              - failure and our instance holds no other presentation
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [int] $ExitCode,
        [bool] $StartedByUs,
        [int] $OwnedPidCount,
        [Nullable[int]] $OtherPresentationsOpen
    )
    if ($ExitCode -eq 0 -or -not $StartedByUs -or $OwnedPidCount -le 0) { return 'none' }
    if ($null -eq $OtherPresentationsOpen -or $OtherPresentationsOpen -gt 0) { return 'skip-others-open' }
    return 'stop'
}

function Get-PowerPointProcessId {
    # NOTE: PowerShell unrolls a function's array output, so with 0 processes the
    # caller receives $null and with 1 process a scalar int. Always call this as
    # @(Get-PowerPointProcessId) before using .Count (Set-StrictMode 3 throws on
    # $null.Count). Checked by tests/export/test_export_script_static.py.
    Get-Process -Name POWERPNT -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }
}

function Clear-TemporaryFile {
    param([string] $Path)
    if ($Path -and (Test-Path -LiteralPath $Path)) {
        try { Remove-Item -LiteralPath $Path -Force -ErrorAction Stop }
        catch {
            [Console]::Error.WriteLine("Export-PptxToVideo: warning - could not remove temporary file '$Path': $($_.Exception.Message)")
        }
    }
}

function Invoke-ComRelease {
    param($Object)
    if ($null -ne $Object) {
        try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Object) } catch { Write-Verbose "ReleaseComObject: $($_.Exception.Message)" }
    }
}

# --- validate arguments --------------------------------------------------------
$onWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
if (-not $onWindows) {
    Exit-WithError -Code $ExitBadInput -Status 'invalid_environment' -Message 'PowerPoint COM export requires Windows with desktop PowerPoint.'
}

try {
    $script:InputFull = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($InputPath)
    $script:OutputFull = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
}
catch {
    Exit-WithError -Code $ExitBadInput -Status 'invalid_argument' -Message "Could not resolve paths: $($_.Exception.Message)"
}

if (-not (Test-Path -LiteralPath $script:InputFull -PathType Leaf)) {
    Exit-WithError -Code $ExitBadInput -Status 'input_not_found' -Message "Input file not found: $($script:InputFull)"
}
$inExt = [System.IO.Path]::GetExtension($script:InputFull).ToLowerInvariant()
if ($inExt -notin @('.pptx', '.pptm', '.ppsx')) {
    Exit-WithError -Code $ExitBadInput -Status 'invalid_argument' -Message "Input must be .pptx / .pptm / .ppsx, got '$inExt'."
}
if ([System.IO.Path]::GetExtension($script:OutputFull).ToLowerInvariant() -ne '.mp4') {
    Exit-WithError -Code $ExitBadInput -Status 'invalid_argument' -Message 'OutputPath must end with .mp4.'
}
$outDir = [System.IO.Path]::GetDirectoryName($script:OutputFull)
if (-not $outDir -or -not (Test-Path -LiteralPath $outDir -PathType Container)) {
    Exit-WithError -Code $ExitBadInput -Status 'output_dir_not_found' -Message "Output folder does not exist: $outDir (create it first; this script does not choose output locations)."
}
if ((Test-Path -LiteralPath $script:OutputFull) -and -not $Force) {
    Exit-WithError -Code $ExitOutputExists -Status 'output_exists' -Message "Output file already exists: $($script:OutputFull) (use -Force to overwrite)."
}
if ([string]::Equals($script:InputFull, $script:OutputFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    Exit-WithError -Code $ExitBadInput -Status 'invalid_argument' -Message 'InputPath and OutputPath must differ.'
}

$outName = [System.IO.Path]::GetFileNameWithoutExtension($script:OutputFull)
$partialPath = Join-Path $outDir ("{0}.partial-{1}.mp4" -f $outName, ([guid]::NewGuid().ToString('N').Substring(0, 8)))

# --- export ------------------------------------------------------------------------
$app = $null
$presentations = $null
$pres = $null
$ourPids = @()
$savedAlerts = $null
$exitCode = $ExitOk
$status = 'done'
$errorMessage = $null

# PowerPoint is single-instance: New-Object attaches to a running instance if
# there is one. Decide ownership BEFORE touching COM, so that an exception at any
# later point still leaves $startedByUs correct for the cleanup in `finally`.
$pidsBefore = @(Get-PowerPointProcessId)
$startedByUs = ($pidsBefore.Count -eq 0)

try {
    try {
        $app = New-Object -ComObject PowerPoint.Application
    }
    catch {
        $exitCode = $ExitCom; $status = 'com_error'
        $errorMessage = "Could not start PowerPoint via COM (is desktop PowerPoint installed?): $($_.Exception.Message)"
        throw
    }
    $ourPids = @(@(Get-PowerPointProcessId) | Where-Object { $pidsBefore -notcontains $_ })

    if ($startedByUs) {
        # Suppress dialogs only in an instance we own; never touch the user's settings.
        try { $savedAlerts = $app.DisplayAlerts; $app.DisplayAlerts = $ppAlertsNone } catch { Write-Verbose "DisplayAlerts: $($_.Exception.Message)" }
    }

    $withWindow = if ($ShowWindow) { $msoTrue } else { $msoFalse }
    try {
        $presentations = $app.Presentations
        # Open(FileName, ReadOnly, Untitled, WithWindow)
        $pres = $presentations.Open($script:InputFull, $msoTrue, $msoFalse, $withWindow)
    }
    catch {
        $exitCode = $ExitCom; $status = 'com_error'
        $errorMessage = "Could not open the presentation: $($_.Exception.Message)"
        throw
    }

    try {
        # CreateVideo(FileName, UseTimingsAndNarrations, DefaultSlideDuration, VertResolution, FramesPerSecond, Quality)
        $pres.CreateVideo($partialPath, $true, $DefaultSlideSeconds, $VertResolution, $Fps, $Quality)
    }
    catch {
        $exitCode = $ExitCom; $status = 'com_error'
        $errorMessage = "CreateVideo failed: $($_.Exception.Message)"
        throw
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    $lastStatus = -1
    while ($true) {
        try {
            $code = [int]$pres.CreateVideoStatus
        }
        catch {
            # PowerPoint can be briefly busy (RPC_E_CALL_REJECTED) while encoding.
            $code = $lastStatus
        }
        if ($code -ne $lastStatus -and $StatusNames.ContainsKey($code)) {
            Write-Verbose ("CreateVideoStatus = {0} ({1:N1} s)" -f $StatusNames[$code], $script:Stopwatch.Elapsed.TotalSeconds)
        }
        $lastStatus = $code

        if ($code -eq 3) { break }
        if ($code -eq 4) {
            $exitCode = $ExitFailed; $status = 'failed'
            $errorMessage = 'PowerPoint reported CreateVideoStatus = Failed.'
            throw $errorMessage
        }
        if ([DateTime]::UtcNow -ge $deadline) {
            $exitCode = $ExitTimeout; $status = 'timeout'
            $errorMessage = "Export did not finish within $TimeoutSec s (last status: $($StatusNames[$code]))."
            throw $errorMessage
        }
        Start-Sleep -Milliseconds ([int]($PollIntervalSec * 1000))
    }

    if (-not (Test-Path -LiteralPath $partialPath -PathType Leaf)) {
        $exitCode = $ExitFailed; $status = 'failed'
        $errorMessage = 'CreateVideoStatus reported Done but no video file was written.'
        throw $errorMessage
    }
}
catch {
    if ($exitCode -eq $ExitOk) {
        $exitCode = $ExitCom; $status = 'com_error'
        $errorMessage = "Unexpected error: $($_.Exception.Message)"
    }
}
finally {
    # Close the deck (read-only; nothing to save).
    if ($null -ne $pres) {
        try { $pres.Close() }
        catch {
            [Console]::Error.WriteLine("Export-PptxToVideo: warning - could not close the presentation: $($_.Exception.Message)")
        }
    }

    # Other presentations open in the instance after closing ours: $null = unknown.
    $othersOpen = $null
    if ($null -ne $app) {
        if ($startedByUs) {
            try { $othersOpen = [int]$app.Presentations.Count } catch { Write-Verbose "Presentations.Count: $($_.Exception.Message)" }
            if ($null -eq $othersOpen -or $othersOpen -gt 0) {
                # Someone may have opened a deck in our instance meanwhile; leave PowerPoint running.
                $countText = if ($null -eq $othersOpen) { 'an unknown number of' } else { "$othersOpen" }
                [Console]::Error.WriteLine("Export-PptxToVideo: warning - PowerPoint was left running because $countText other presentation(s) may be open.")
                if ($null -ne $savedAlerts) { try { $app.DisplayAlerts = $savedAlerts } catch { Write-Verbose "DisplayAlerts restore: $($_.Exception.Message)" } }
            }
            else {
                try { $app.Quit() }
                catch {
                    [Console]::Error.WriteLine("Export-PptxToVideo: warning - PowerPoint.Quit failed: $($_.Exception.Message)")
                }
            }
        }
    }

    Invoke-ComRelease $pres
    Invoke-ComRelease $presentations
    Invoke-ComRelease $app
    $pres = $null; $presentations = $null; $app = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()

    # The POWERPNT process may appear late, or COM may have failed after spawning
    # it; look again so a process we started is not missed.
    if ($startedByUs -and $ourPids.Count -eq 0) {
        $ourPids = @(@(Get-PowerPointProcessId) | Where-Object { $pidsBefore -notcontains $_ })
    }

    # After a timeout an export may still be running in an instance we own.
    # Stop only the processes this script started; never the user's PowerPoint,
    # and never an instance where other presentations are (or may be) open.
    $stopDecision = Get-OwnedPowerPointStopDecision -ExitCode $exitCode -StartedByUs $startedByUs `
        -OwnedPidCount $ourPids.Count -OtherPresentationsOpen $othersOpen
    if ($stopDecision -eq 'skip-others-open') {
        [Console]::Error.WriteLine("Export-PptxToVideo: warning - PowerPoint process(es) $($ourPids -join ', ') started by this script were NOT stopped because other presentations are (or may be) open; the export may still be running. Close PowerPoint manually after saving your work.")
    }
    if ($stopDecision -eq 'stop') {
        Start-Sleep -Seconds 2
        foreach ($procId in $ourPids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -eq 'POWERPNT') {
                [Console]::Error.WriteLine("Export-PptxToVideo: warning - stopping PowerPoint process $procId started by this script.")
                try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch { [Console]::Error.WriteLine("Export-PptxToVideo: warning - could not stop process ${procId}: $($_.Exception.Message)") }
            }
        }
    }
}

if ($exitCode -ne $ExitOk) {
    Clear-TemporaryFile $partialPath
    Exit-WithError -Code $exitCode -Status $status -Message $errorMessage
}

# --- move into place -----------------------------------------------------------
try {
    if (Test-Path -LiteralPath $script:OutputFull) {
        if (-not $Force) {
            # Appeared while we were exporting; keep both and fail.
            Exit-WithError -Code $ExitOutputExists -Status 'output_exists' -Message "Output file appeared during export: $($script:OutputFull). New video kept at $partialPath."
        }
        Move-Item -LiteralPath $partialPath -Destination $script:OutputFull -Force
    }
    else {
        Move-Item -LiteralPath $partialPath -Destination $script:OutputFull
    }
}
catch {
    Exit-WithError -Code $ExitCom -Status 'io_error' -Message "Video was written to '$partialPath' but could not be moved to the output path: $($_.Exception.Message)"
}

$duration = Get-FfprobeDuration $script:OutputFull
Write-Result -Status 'done' -DurationSec $duration
exit $ExitOk
