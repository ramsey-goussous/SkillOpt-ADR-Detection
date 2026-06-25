# Run ADR extraction/scoring on de-identified real notes without training.

$ErrorActionPreference = "Stop"

$ORIG = Get-Location
$ROOT = $PSScriptRoot
$skillopt = Join-Path $ROOT "external\SkillOpt"
$resultsRoot = Join-Path $ROOT "results\real_data"
$SkillOptCommit = "6940e46f4e0e537a1d7ca8432f24248d0d3550f5"

$TargetModel = if ($env:TARGET_MODEL) { $env:TARGET_MODEL } else { "claude-sonnet-4-6" }
$RealDataFile = if ($env:REAL_DATA_FILE) { $env:REAL_DATA_FILE } else { Join-Path $ROOT "real_data\real_notes.json" }
$RealSplitDir = Join-Path $ROOT "real_data_split"
$Workers = if ($env:WORKERS) { [int]$env:WORKERS } else { 1 }

function Section($Number, $Title) {
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host ("{0}/6  {1}" -f $Number, $Title)
    Write-Host ("=" * 72)
}

function Info($Text) { Write-Host ("  - " + $Text) }
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
    $candidates += @("py", "python3", "python")
    $candidates += @(
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

try {
    Section 0 "Prerequisites"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail "Git was not found. Install Git for Windows, then rerun."
    }
    $basePython = Find-Python
    if (-not $basePython) {
        Fail "No working Python found. Install Python 3.10+ or set PYTHON to python.exe."
    }
    $venvPy = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Info "creating local virtual environment at .venv"
        & $basePython -m venv (Join-Path $ROOT ".venv")
        if ($LASTEXITCODE -ne 0) { Fail "Python venv creation failed." }
    }
    $PY = $venvPy
    Info "python: $PY"

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

    Section 1 "SkillOpt source"
    if (-not (Test-Path $skillopt)) {
        Info "cloning Microsoft SkillOpt into external\SkillOpt"
        git clone https://github.com/microsoft/SkillOpt.git $skillopt
        if ($LASTEXITCODE -ne 0) { Fail "git clone failed." }
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
    }

    Section 2 "Install"
    Set-Location $skillopt
    $pyExe = (& $PY -X utf8 -c "import sys; print(sys.executable)" 2>$null)
    $stamp = Join-Path $skillopt ".skillopt_install.ok"
    $stampMatches = ((Test-Path $stamp) -and ((Get-Content $stamp -Raw) -match [regex]::Escape($pyExe)))
    if ($env:FORCE_INSTALL -eq "1" -or -not $stampMatches) {
        & $PY -X utf8 -m pip install --upgrade pip | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed." }
        & $PY -X utf8 -m pip install -e . | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "pip install -e . failed." }
        "python=$pyExe`ninstalled=$(Get-Date -Format o)" | Set-Content -Encoding UTF8 $stamp
    }

    Section 3 "ADR task package"
    $envDir = Join-Path $skillopt "skillopt\envs\adr"
    Remove-TreeInside $envDir $skillopt
    Copy-Item -Recurse -Force (Join-Path $ROOT "skillopt_adr") $envDir
    Copy-Item -Force (Join-Path $ROOT "scorer\scorer.py") (Join-Path $envDir "scorer.py")
    $cfgDir = Join-Path $skillopt "configs\adr"
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    Copy-Item -Force (Join-Path $ROOT "config\adr_skillopt.yaml") (Join-Path $cfgDir "default.yaml")
    & $PY -X utf8 (Join-Path $ROOT "scripts\patch_skillopt.py") $skillopt
    if ($LASTEXITCODE -ne 0) { Fail "SkillOpt patching failed." }

    Section 4 "Real data"
    $RealDataFile = Resolve-RepoPath $RealDataFile
    if (-not (Test-Path $RealDataFile)) {
        Fail "Real data file not found: $RealDataFile. Put de-identified notes in real_data\real_notes.json."
    }
    New-Item -ItemType Directory -Force -Path $RealSplitDir | Out-Null
    foreach ($child in @("train", "val", "test", "manifest.json")) {
        Remove-TreeInside (Join-Path $RealSplitDir $child) $ROOT
    }
    & $PY -X utf8 (Join-Path $ROOT "scripts\prepare_real_data.py") --input $RealDataFile --out $RealSplitDir
    if ($LASTEXITCODE -ne 0) { Fail "prepare_real_data.py failed." }

    Section 5 "Skill"
    if ($env:REAL_SKILL_SOURCE) {
        $skillSource = Resolve-RepoPath $env:REAL_SKILL_SOURCE
    } elseif (Test-Path (Join-Path $ROOT "results\best_skill.md")) {
        $skillSource = Join-Path $ROOT "results\best_skill.md"
    } else {
        $skillSource = Join-Path $ROOT "skills\base_skill.md"
    }
    if (-not (Test-Path $skillSource)) { Fail "Skill source not found: $skillSource" }
    Info "skill: $skillSource"

    Section 6 "Real-data evaluation"
    $runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $outRun = Join-Path $resultsRoot $runStamp
    New-Item -ItemType Directory -Force -Path $outRun | Out-Null
    & $PY -X utf8 (Join-Path $ROOT "scripts\run_real_data_eval.py") `
        --skill $skillSource `
        --split-dir $RealSplitDir `
        --out-root $outRun `
        --target-model $TargetModel `
        --workers $Workers
    if ($LASTEXITCODE -ne 0) { Fail "real-data evaluation failed." }

    Copy-Item -Force (Join-Path $outRun "REAL_DATA_SUMMARY.md") (Join-Path $resultsRoot "LATEST_REAL_DATA_SUMMARY.md")
    Write-Host ""
    Info "real-data outputs: $outRun"
    Info "latest summary: $(Join-Path $resultsRoot 'LATEST_REAL_DATA_SUMMARY.md')"
} finally {
    Set-Location $ORIG
}
