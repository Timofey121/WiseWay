param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Target
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & git -C $script:RepoRoot @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
}

# ------------------------------------------------------------
# Resolve and normalize target
# ------------------------------------------------------------

$NormalizedTarget = $Target.Trim().ToUpperInvariant()

if ($NormalizedTarget -match '^E-?(\d{2})$') {
    $TargetId = "E-$($Matches[1])"
    $TargetKind = 'EPIC'
}
elseif ($NormalizedTarget -match '^WP-?(\d{2})$') {
    $TargetId = "WP-$($Matches[1])"
    $TargetKind = 'WORK_PACKAGE'
}
else {
    throw "Invalid target '$Target'. Use E-01 / E01 or WP-01 / WP01."
}

# ------------------------------------------------------------
# Resolve repository
# ------------------------------------------------------------

$RepoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()

if ($LASTEXITCODE -ne 0 -or -not $RepoRoot) {
    throw "Cannot determine WiseWay repository root."
}

$BacklogPath = Join-Path $RepoRoot 'docs\progress\FRONTEND_BACKLOG.md'

if (-not (Test-Path $BacklogPath)) {
    throw "Frontend backlog not found: $BacklogPath"
}

# ------------------------------------------------------------
# Protect base checkout
# ------------------------------------------------------------

$CurrentChanges = @(
    & git -C $RepoRoot status --porcelain
)

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect repository status."
}

if ($CurrentChanges.Count -gt 0) {
    Write-Host ""
    Write-Host "Base checkout contains uncommitted changes:"
    $CurrentChanges | ForEach-Object { Write-Host $_ }
    Write-Host ""

    throw "Commit, stash, or intentionally resolve base-checkout changes before starting a new Execution Unit."
}

# ------------------------------------------------------------
# Update main
# ------------------------------------------------------------

Write-Host ""
Write-Host "Updating origin/main..."

Invoke-Git @('fetch', 'origin')
Invoke-Git @('switch', 'main')
Invoke-Git @('pull', '--ff-only')

# ------------------------------------------------------------
# Validate target against the updated backlog
# ------------------------------------------------------------

if ($TargetKind -eq 'EPIC') {
    $TargetPattern = "^## EPIC $([regex]::Escape($TargetId))\b"
}
else {
    $TargetPattern = "^### $([regex]::Escape($TargetId))\b"
}

$TargetExists = Select-String `
    -Path $BacklogPath `
    -Pattern $TargetPattern `
    -Quiet

if (-not $TargetExists) {
    throw "Target $TargetId was not found in FRONTEND_BACKLOG.md."
}

# ------------------------------------------------------------
# Define branch/worktree
# ------------------------------------------------------------

$Slug = $TargetId.ToLowerInvariant()
$Branch = "feat/$Slug"

$RepoParent = Split-Path $RepoRoot -Parent
$WorktreesRoot = Join-Path $RepoParent 'WiseWay-worktrees'
$WorktreePath = Join-Path $WorktreesRoot $Slug

New-Item `
    -ItemType Directory `
    -Force `
    -Path $WorktreesRoot | Out-Null

# ------------------------------------------------------------
# Refuse accidental duplicate start
# ------------------------------------------------------------

$ExistingLocalBranch = @(
    & git -C $RepoRoot branch --list $Branch
)

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect local branches."
}

if ($ExistingLocalBranch.Count -gt 0) {
    throw @"
Local branch already exists: $Branch

If this is an interrupted Execution Unit, resume it instead:

cd "$WorktreePath"
opencode -c --auto
"@
}

$ExistingRemoteBranch = @(
    & git -C $RepoRoot branch --remotes --list "origin/$Branch"
)

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect remote branches."
}

if ($ExistingRemoteBranch.Count -gt 0) {
    throw "Remote branch already exists: origin/$Branch. Do not create a second Execution Unit over it."
}

if (Test-Path $WorktreePath) {
    throw @"
Worktree path already exists:

$WorktreePath

If this is an interrupted Execution Unit, resume OpenCode from that worktree.
"@
}

# ------------------------------------------------------------
# Create isolated Execution Unit
# ------------------------------------------------------------

Write-Host ""
Write-Host "Creating WiseWay Execution Unit"
Write-Host "--------------------------------"
Write-Host "Target:   $TargetId"
Write-Host "Kind:     $TargetKind"
Write-Host "Branch:   $Branch"
Write-Host "Worktree: $WorktreePath"
Write-Host ""

Invoke-Git @(
    'worktree',
    'add',
    $WorktreePath,
    '-b',
    $Branch,
    'origin/main'
)

# ------------------------------------------------------------
# Build orchestrator startup prompt
# ------------------------------------------------------------

if ($TargetKind -eq 'EPIC') {
    $ExecutionInstruction = @"
The selected Execution Unit is the complete Epic $TargetId.

Identify all Work Packages belonging to $TargetId and execute all
dependency-ready work inside this Epic.

Continue autonomously across Work Package boundaries.

Do not stop merely because one Work Package is complete.

If one item is blocked, continue other dependency-ready work inside $TargetId
when possible.

Only stop when the complete Epic is READY_FOR_HUMAN_REVIEW, no further useful
progress is possible, or a genuine human decision is required.
"@
}
else {
    $ExecutionInstruction = @"
The selected Execution Unit is the single Work Package $TargetId.

Execute all required leaves of $TargetId, recursively decomposing oversized
leaves when necessary.

Do not execute another Work Package after $TargetId is complete.

Stop when this Work Package as an Execution Unit is READY_FOR_HUMAN_REVIEW,
no further useful progress is possible, or a genuine human decision is
required.
"@
}

$Prompt = @"
Start WiseWay Execution Unit $TargetId.

Read AGENTS.md first.

Then read:
- docs/progress/FRONTEND_BACKLOG.md;
- all relevant docs/team sources;
- the public OpenAPI contract when applicable;
- actual repository state.

$ExecutionInstruction

For implementation work use the autonomous cycle defined in AGENTS.md:

frontend-worker
-> reviewer
-> repair when required
-> reviewer PASS
-> verification
-> backlog update
-> checkpoint commit
-> push current feature branch
-> next leaf

At the end of each Work Package perform the required Work Package review.

At the end of the selected Execution Unit perform a complete integrated
Execution Unit review.

Do not create another branch, worktree, or ordinary PR.
The branch and worktree for $TargetId have already been created.

Do not ask the human for routine engineering/tool decisions.

Use ordinary engineering judgment autonomously.

Communicate with the human in Russian.

Finish according to the final reporting contract in AGENTS.md.
"@

# ------------------------------------------------------------
# Launch OpenCode
# ------------------------------------------------------------

Write-Host "Starting OpenCode in autonomous mode..."
Write-Host ""

Push-Location $WorktreePath

try {
    opencode `
        --auto `
        --agent orchestrator `
        --title "WiseWay $TargetId" `
        --prompt $Prompt
}
finally {
    Pop-Location
}