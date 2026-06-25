# Run the ADR SkillOpt pipeline on Windows / PowerShell.
#
# This repo starts from skills/base_skill.md. It does not include any optimized
# skill from earlier local experiments.

$ErrorActionPreference = "Stop"

$ORIG = Get-Location
$ROOT = $PSScriptRoot
$skillopt = Join-Path $ROOT "external\SkillOpt"
$resultsDir = Join-Path $ROOT "results"
$logDir = Join-Path $resultsDir "run_logs"
$SkillOptCommit = "6940e46f4e0e537a1d7ca8432f24248d0d3550f5"
$script:RunStart = Get-Date

$TargetModel = if ($env:TARGET_MODEL) { $env:TARGET_MODEL } else { "claude-sonnet-4-6" }
$OptimizerModel = if ($env:OPTIMIZER_MODEL) { $env:OPTIMIZER_MODEL } else { "claude-sonnet-4-6" }
$Epochs = if ($env:NUM_EPOCHS) { [int]$env:NUM_EPOCHS } else { 1 }
$RunTestEval = if ($env:RUN_TEST_EVAL -eq "1") { "true" } else { "false" }
$LaunchMode = if ($env:ADR_RUN_MODE) { $env:ADR_RUN_MODE } else { "manual" }

function Section($Number, $Title) {
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host ("{0}/7  {1}" -f $Number, $Title)
    Write-Host ("=" * 72)
}

function Info($Text) { Write-Host ("  - " + $Text) }
function Warn($Text) { Write-Host ("  ! " + $Text) -ForegroundColor Yellow }
function Fail($Text) { Write-Host ("  X " + $Text) -ForegroundColor Red; exit 1 }

function Test-Python($Candidate) {
    if (-not $Candidate) { return $false }
    try {
        $v = & $Candidate --version 2>&1
        return ($LASTEXITCODE -eq 0 -and "$v" -match "Python\s+\d")
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @()
    if ($env:PYTHON) { $candidates += $env:PYTHON }
    $candidates += @(
        "py",
        "python3",
        "python",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )
    foreach ($cand in $candidates) {
        if (($cand -match "\\") -and -not (Test-Path $cand)) { continue }
        if (Test-Python $cand) { return $cand }
    }
    return $null
}

function Resolve-RepoPath($PathText) {
    if ([System.IO.Path]::IsPathRooted($PathText)) { return $PathText }
    return (Join-Path $ROOT $PathText)
}

function Remove-TreeInside($Path, $AllowedRoot) {
    if (-not (Test-Path $Path)) { return }
    $resolvedPath = (Resolve-Path $Path).Path
    $resolvedRoot = (Resolve-Path $AllowedRoot).Path
    if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete outside expected root: $resolvedPath"
    }
    Remove-Item -LiteralPath $resolvedPath -Recurse -Force
}

function Write-RunStatus($ExitCode, $IsValid, $ErrorMessage) {
    $now = Get-Date
    $elapsed = [math]::Round(($now - $script:RunStart).TotalSeconds, 1)
    $status = [ordered]@{
        ran = $true
        train_exit_code = $ExitCode
        valid = $IsValid
        train_log = $script:trainLog
        model_target = $TargetModel
        model_optimizer = $OptimizerModel
        num_epochs = $Epochs
        skill_source = $script:skillSource
        run_test_eval = $RunTestEval
        launch_mode = $LaunchMode
        run_start_iso = $script:RunStart.ToString("o")
        run_status_updated_iso = $now.ToString("o")
        runner_elapsed_seconds = $elapsed
        error_message = $ErrorMessage
    }
    $status | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $script:statusPath
}

New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$script:trainLog = Join-Path $logDir "train-$runStamp.log"
$script:statusPath = Join-Path $resultsDir "run_status.json"

try {
    Section 0 "Prerequisites"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail "Git was not found. Install Git for Windows, then rerun."
    }
    Info "git found"

    $basePython = Find-Python
    if (-not $basePython) {
        Fail "No working Python found. Install Python 3.10+ or set PYTHON to python.exe."
    }
    Info "python bootstrap: $basePython"

    $venvPy = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Info "creating local virtual environment at .venv"
        & $basePython -m venv (Join-Path $ROOT ".venv")
        if ($LASTEXITCODE -ne 0) { Fail "Python venv creation failed." }
    }
    $PY = $venvPy
    $pyVersion = & $PY --version 2>&1
    Info "python: $PY ($pyVersion)"

    $claudeBin = $null
    if ($env:CLAUDE_CLI_BIN -and (Test-Path $env:CLAUDE_CLI_BIN)) {
        $claudeBin = $env:CLAUDE_CLI_BIN
    } elseif (Get-Command claude -ErrorAction SilentlyContinue) {
        $claudeBin = (Get-Command claude).Source
    } else {
        foreach ($p in @("$env:USERPROFILE\.local\bin\claude.exe", "$env:APPDATA\npm\claude.cmd")) {
            if (Test-Path $p) { $claudeBin = $p; break }
        }
    }
    if (-not $claudeBin) {
        Fail "Claude Code CLI was not found. Install it and log in with claude before running."
    }
    $env:CLAUDE_CLI_BIN = $claudeBin
    Info "claude CLI: $claudeBin"
    Info "target model: $TargetModel"
    Info "optimizer model: $OptimizerModel"
    Info "epochs: $Epochs"
    Info "test evaluation during training: $RunTestEval"
    Info "launch mode: $LaunchMode"
    if ($env:ADR_EXEC_TIMEOUT) { Info "per-note model timeout: $env:ADR_EXEC_TIMEOUT seconds" }
    if ($env:ADR_MODEL_RETRIES) { Info "per-note model retries: $env:ADR_MODEL_RETRIES" }

    Section 1 "SkillOpt source"
    if (-not (Test-Path $skillopt)) {
        Info "cloning Microsoft SkillOpt into external\SkillOpt"
        git clone https://github.com/microsoft/SkillOpt.git $skillopt
        if ($LASTEXITCODE -ne 0) { Fail "git clone failed." }
    } else {
        Info "reusing existing clone: $skillopt"
    }
    $currentSkillOptCommit = (git -C $skillopt rev-parse HEAD 2>$null)
    if ($currentSkillOptCommit -ne $SkillOptCommit) {
        Info "checking out known working SkillOpt commit $SkillOptCommit"
        git -C $skillopt cat-file -e "$SkillOptCommit^{commit}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            git -C $skillopt fetch origin main
            if ($LASTEXITCODE -ne 0) { Fail "git fetch for pinned SkillOpt commit failed." }
        }
        git -C $skillopt checkout --detach $SkillOptCommit
        if ($LASTEXITCODE -ne 0) { Fail "git checkout of pinned SkillOpt commit failed." }
    } else {
        Info "SkillOpt commit: $SkillOptCommit"
    }

    Section 2 "Install"
    Set-Location $skillopt
    $pyExe = (& $PY -X utf8 -c "import sys; print(sys.executable)" 2>$null)
    $stamp = Join-Path $skillopt ".skillopt_install.ok"
    $stampMatches = ((Test-Path $stamp) -and ((Get-Content $stamp -Raw) -match [regex]::Escape($pyExe)))
    if ($env:FORCE_INSTALL -eq "1" -or -not $stampMatches) {
        Info "installing SkillOpt editable package into .venv"
        & $PY -X utf8 -m pip install --upgrade pip | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed." }
        & $PY -X utf8 -m pip install -e . | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "pip install -e . failed." }
        "python=$pyExe`ninstalled=$(Get-Date -Format o)" | Set-Content -Encoding UTF8 $stamp
    } else {
        Info "editable install already present for this .venv"
    }

    Section 3 "ADR task package"
    if ($env:SKILL_SOURCE) {
        $skillSource = Resolve-RepoPath $env:SKILL_SOURCE
    } else {
        $skillSource = Join-Path $ROOT "skills\base_skill.md"
    }
    if (-not (Test-Path $skillSource)) { Fail "Skill source not found: $skillSource" }
    $script:skillSource = $skillSource
    Info "starting skill: $skillSource"

    $envDir = Join-Path $skillopt "skillopt\envs\adr"
    Remove-TreeInside $envDir $skillopt
    Copy-Item -Recurse -Force (Join-Path $ROOT "skillopt_adr") $envDir
    Copy-Item -Force (Join-Path $ROOT "scorer\scorer.py") (Join-Path $envDir "scorer.py")
    Copy-Item -Force $skillSource (Join-Path $envDir "skills\initial.md")

    $cfgDir = Join-Path $skillopt "configs\adr"
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    Copy-Item -Force (Join-Path $ROOT "config\adr_skillopt.yaml") (Join-Path $cfgDir "default.yaml")

    Section 4 "Data split"
    & $PY -X utf8 (Join-Path $ROOT "scripts\make_splits.py")
    if ($LASTEXITCODE -ne 0) { Fail "make_splits.py failed." }
    $dataDir = Join-Path $skillopt "data\adr_split"
    Remove-TreeInside $dataDir $skillopt
    New-Item -ItemType Directory -Force -Path (Join-Path $skillopt "data") | Out-Null
    Copy-Item -Recurse -Force (Join-Path $ROOT "data_split") $dataDir
    Info "copied split data into SkillOpt"

    Section 5 "Compatibility patches"
    & $PY -X utf8 (Join-Path $ROOT "scripts\patch_skillopt.py") $skillopt
    if ($LASTEXITCODE -ne 0) { Fail "SkillOpt patching failed." }

    Section 6 "Optimization"
    $outRun = Join-Path $skillopt "outputs\adr_run"
    Remove-TreeInside $outRun $skillopt
    Info "full train log: $script:trainLog"

    $trainArgs = @(
        "scripts\train.py",
        "--config", "configs\adr\default.yaml",
        "--backend", "claude",
        "--split_dir", "data\adr_split",
        "--optimizer_model", $OptimizerModel,
        "--target_model", $TargetModel,
        "--num_epochs", "$Epochs",
        "--eval_test", $RunTestEval,
        "--out_root", "outputs\adr_run"
    )

    Write-RunStatus $null $false "training started but did not finish"
    $trainRc = 1
    $trainError = ""
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PY -X utf8 @trainArgs 2>&1 | Tee-Object -FilePath $script:trainLog
        $trainRc = $LASTEXITCODE
    } catch {
        $trainError = $_.Exception.Message
        if (-not $trainError) { $trainError = "training interrupted or failed" }
        $trainRc = if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 130 }
        Add-Content -Path $script:trainLog -Encoding UTF8 -Value ""
        Add-Content -Path $script:trainLog -Encoding UTF8 -Value "[runner] training interrupted or failed: $trainError"
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    Write-RunStatus $trainRc ($trainRc -eq 0) $trainError

    Section 7 "Collect results"
    $best = Join-Path $outRun "best_skill.md"
    $hist = Join-Path $outRun "history.json"
    if (Test-Path $best) {
        Copy-Item -Force $best (Join-Path $resultsDir "best_skill.md")
        Info "saved results\best_skill.md"
    } else {
        Warn "best_skill.md was not produced"
    }
    if (Test-Path $hist) {
        Copy-Item -Force $hist (Join-Path $resultsDir "history.json")
        Info "saved results\history.json"
    } else {
        Warn "history.json was not produced"
    }

    & $PY -X utf8 (Join-Path $ROOT "scripts\summarize_results.py")

    $sessDir = Join-Path $resultsDir "sessions"
    New-Item -ItemType Directory -Force -Path $sessDir | Out-Null
    $sessionNum = ([int](Get-ChildItem $sessDir -Directory -ErrorAction SilentlyContinue | Measure-Object).Count) + 1
    $snapDir = Join-Path $sessDir ("s{0:D3}_{1}" -f $sessionNum, $runStamp)
    New-Item -ItemType Directory -Force -Path $snapDir | Out-Null
    Copy-Item -Force $script:skillSource (Join-Path $snapDir "starting_skill.md")
    Copy-Item -Force (Join-Path $ROOT "skills\base_skill.md") (Join-Path $snapDir "base_skill.md")
    if (Test-Path $best) { Copy-Item -Force $best (Join-Path $snapDir "best_skill.md") }
    $stateFile = Join-Path $outRun "runtime_state.json"
    if (Test-Path $stateFile) { Copy-Item -Force $stateFile (Join-Path $snapDir "runtime_state.json") }
    $snap = [ordered]@{
        session = $sessionNum
        timestamp = $runStamp
        starting_skill = $script:skillSource
        best_skill = if (Test-Path $best) { "best_skill.md" } else { $null }
        valid = ($trainRc -eq 0)
    }
    $snap | ConvertTo-Json -Depth 2 | Set-Content -Encoding UTF8 (Join-Path $snapDir "session_info.json")
    Info ("session snapshot -> results\sessions\s{0:D3}_{1}" -f $sessionNum, $runStamp)

    Write-Host ""
    if ($trainRc -ne 0) {
        Warn "Optimization exited with code $trainRc. See results\RESULTS_SUMMARY.md."
    } else {
        Info "Optimization finished successfully."
    }
    Write-Host ""
    Write-Host "Outputs:"
    Write-Host "  results\RESULTS_SUMMARY.md"
    Write-Host "  results\results.json"
    Write-Host "  results\best_skill.md"
    Write-Host "  results\run_logs\"
    Write-Host "  results\sessions\"
    Write-Host ""
    Write-Host "To continue from this repo's latest best skill after usage resets:"
    Write-Host "  `$env:SKILL_SOURCE = (Resolve-Path .\results\best_skill.md).Path"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\run_adr_skillopt.ps1"
    Write-Host ""
    Write-Host "To start over from the base skill:"
    Write-Host "  Remove-Item Env:\SKILL_SOURCE -ErrorAction SilentlyContinue"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\run_adr_skillopt.ps1"
} finally {
    Set-Location $ORIG
}
