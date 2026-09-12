param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Target
)

$ErrorActionPreference = "Stop"

# This launcher lives at:
# scripts/opencode/frontend/Start-WiseWayTask.ps1
#
# Therefore the repository root is three directories above $PSScriptRoot.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

$RepoName = Split-Path $RepoRoot -Leaf
$RepoParent = Split-Path $RepoRoot -Parent
$WorktreesRoot = Join-Path $RepoParent "$RepoName-worktrees"

$BacklogPath = Join-Path $RepoRoot "docs\progress\FRONTEND_BACKLOG.md"

function Fail {
    param([string] $Message)

    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Require-LastExitCode {
    param([string] $Description)

    if ($LASTEXITCODE -ne 0) {
        Fail "$Description failed with exit code $LASTEXITCODE."
    }
}

# ---------------------------------------------------------------------------
# Normalize target
# ---------------------------------------------------------------------------

$NormalizedInput = $Target.Trim().ToUpperInvariant()

if ($NormalizedInput -notmatch '^(E|WP)-?(\d+)$') {
    Fail "Target must look like E-01, E01, WP-01, or WP01."
}

$TargetKind = $Matches[1]
$TargetNumber = [int] $Matches[2]

if ($TargetNumber -lt 1) {
    Fail "Target number must be greater than zero."
}

$TargetId = "{0}-{1:D2}" -f $TargetKind, $TargetNumber
$TargetSlug = $TargetId.ToLowerInvariant()

$BranchName = "feat/$TargetSlug"
$WorktreePath = Join-Path $WorktreesRoot $TargetSlug

# ---------------------------------------------------------------------------
# Basic prerequisites
# ---------------------------------------------------------------------------

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git is not available in PATH."
}

if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
    Fail "opencode is not available in PATH."
}

if (-not (Test-Path $BacklogPath)) {
    Fail "Frontend backlog was not found: $BacklogPath"
}

# Validate that the requested target actually exists in the frontend backlog.
if ($TargetKind -eq "E") {
    $TargetPattern = "^##\s+EPIC\s+$([regex]::Escape($TargetId))\b"
}
else {
    $TargetPattern = "^###\s+$([regex]::Escape($TargetId))\b"
}

$TargetExists = Select-String `
    -Path $BacklogPath `
    -Pattern $TargetPattern `
    -Quiet

if (-not $TargetExists) {
    Fail "Target $TargetId was not found in FRONTEND_BACKLOG.md."
}

# ---------------------------------------------------------------------------
# Prepare main checkout
# ---------------------------------------------------------------------------

Push-Location $RepoRoot

try {
    $InsideWorktree = (& git rev-parse --is-inside-work-tree 2>$null)

    if ($LASTEXITCODE -ne 0 -or $InsideWorktree.Trim() -ne "true") {
        Fail "$RepoRoot is not a Git worktree."
    }

    $CurrentBranch = (& git branch --show-current).Trim()
    Require-LastExitCode "Reading current branch"

    if ($CurrentBranch -ne "main") {
        Fail @"
This launcher must be run from the clean main checkout.

Current checkout:
  $RepoRoot

Current branch:
  $CurrentBranch

Expected branch:
  main

After E-01 is merged, run the launcher from the normal repository checkout,
for example:

  cd C:\dev\WiseWay
  .\scripts\opencode\frontend\Start-WiseWayTask.ps1 E-02
"@
    }

    $DirtyState = & git status --porcelain
    Require-LastExitCode "Inspecting main working tree"

    if ($DirtyState) {
        Fail @"
The main checkout is not clean.

Commit, stash, or otherwise resolve its changes before creating a new
Execution Unit.

git status --porcelain:
$($DirtyState -join "`n")
"@
    }

    Write-Host ""
    Write-Host "Updating origin/main..." -ForegroundColor Cyan

    & git fetch --prune origin
    Require-LastExitCode "git fetch"

    & git pull --ff-only origin main
    Require-LastExitCode "git pull --ff-only"

    # -----------------------------------------------------------------------
    # Refuse accidental duplicate Execution Units
    # -----------------------------------------------------------------------

    & git show-ref --verify --quiet "refs/heads/$BranchName"
    $LocalBranchExists = ($LASTEXITCODE -eq 0)

    & git ls-remote --exit-code --heads origin $BranchName *> $null
    $RemoteBranchExists = ($LASTEXITCODE -eq 0)

    $WorktreeExists = Test-Path $WorktreePath

    if ($WorktreeExists -or $LocalBranchExists -or $RemoteBranchExists) {
        Write-Host ""
        Write-Host "Execution Unit already appears to exist." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Target:      $TargetId"
        Write-Host "Branch:      $BranchName"
        Write-Host "Worktree:    $WorktreePath"
        Write-Host "Local branch exists:  $LocalBranchExists"
        Write-Host "Remote branch exists: $RemoteBranchExists"
        Write-Host "Worktree exists:      $WorktreeExists"

        if ($WorktreeExists) {
            Write-Host ""
            Write-Host "To continue the existing worktree:" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  cd `"$WorktreePath`""
            Write-Host "  opencode -c"
        }

        Write-Host ""
        exit 1
    }

    # -----------------------------------------------------------------------
    # Create Execution Unit branch/worktree
    # -----------------------------------------------------------------------

    if (-not (Test-Path $WorktreesRoot)) {
        New-Item `
            -ItemType Directory `
            -Path $WorktreesRoot `
            -Force | Out-Null
    }

    Write-Host ""
    Write-Host "Creating Execution Unit..." -ForegroundColor Cyan
    Write-Host "Target:   $TargetId"
    Write-Host "Branch:   $BranchName"
    Write-Host "Worktree: $WorktreePath"
    Write-Host ""

    & git worktree add `
        --no-track `
        -b $BranchName `
        $WorktreePath `
        origin/main

    Require-LastExitCode "git worktree add"
}
finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# Launch frontend orchestrator
# ---------------------------------------------------------------------------

Set-Location $WorktreePath

$Prompt = @"
Start frontend Execution Unit $TargetId.

This feature branch/worktree has already been created by the launcher for the selected Execution Unit.

First read:
1. AGENTS.md
2. .opencode/rules/frontend.md
3. docs/progress/FRONTEND_BACKLOG.md
4. Only the docs/team documents and public OpenAPI sections relevant to the selected target.

Reconcile the backlog with the actual repository and Git state.

Execute the entire selected frontend Execution Unit $TargetId according to the current frontend execution workflow.

Autonomously process all dependency-ready Work Packages and executable leaf tasks inside the selected target.

For every new leaf, use a fresh frontend/worker child session.
Every frontend/reviewer invocation must use a fresh child session.

Do not stop between leaves or Work Packages unless there is a real blocker or a required human decision.

Do not perform a second full semantic review after reviewer PASS merely for reassurance.

After all internal Work Package reviews, perform the final Execution Unit review and all applicable full verification.

Bring the selected target to READY_FOR_HUMAN_REVIEW, or precisely record a real blocker if no further dependency-safe progress is possible.
"@

Write-Host ""
Write-Host "Launching frontend/orchestrator for $TargetId..." -ForegroundColor Green
Write-Host ""

& opencode `
    --agent "frontend/orchestrator" `
    --prompt $Prompt

if ($LASTEXITCODE -ne 0) {
    Fail "OpenCode exited with code $LASTEXITCODE."
}