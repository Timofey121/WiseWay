# WiseWay Frontend Agent Rules

These rules define the frontend development workflow for WiseWay. They apply to:

- `frontend/orchestrator`;
- `frontend/worker`;
- `frontend/reviewer`.

Every frontend agent MUST also read and obey the repository-wide `AGENTS.md`.
If this file is stricter than `AGENTS.md`, follow the stricter frontend rule. If
the two files genuinely conflict on a shared project/API semantic, stop the
conflicting action and let `frontend/orchestrator` resolve or escalate it.

## Frontend sources of truth

Frontend execution backlog:

`docs/progress/FRONTEND_BACKLOG.md`

Frontend agents also use the shared sources defined in `AGENTS.md`, especially:

- `docs/team/`;
- `contracts/openapi/wiseway-v1.yaml`;
- established repository implementation and conventions.

For frontend execution decisions, use this precedence:

1. explicit current human decision;
2. repository-wide `AGENTS.md`;
3. authoritative `docs/team/` specification;
4. public OpenAPI contract for public API shape and semantics;
5. established repository implementation and conventions;
6. `docs/progress/FRONTEND_BACKLOG.md`;
7. simplest conventional engineering decision consistent with the above.

The backlog is an execution plan, not a replacement for authoritative project
requirements.

## Operating model

WiseWay agent execution is autonomy-first.

The default rule is:

> Anything not explicitly prohibited is allowed.

Agents must not interrupt the human for routine engineering work, tool usage,
repository inspection, testing, dependency management, or ordinary technical
decisions.

The human should normally be required only:

- at the start of an Execution Unit;
- when a genuinely unresolved high-impact product/project decision exists;
- when no further progress is possible because of an external blocker;
- at final review/integration of the completed Execution Unit.

## Roles

### frontend/orchestrator

The orchestrator owns:

- understanding requirements;
- selecting and interpreting the current Execution Unit;
- recursive decomposition;
- execution backlog maintenance;
- ordinary engineering and architectural decisions;
- worker coordination;
- reviewer coordination;
- repair cycles;
- reviewed Git checkpoints;
- feature-branch pushes;
- Work Package reviews;
- final Execution Unit review;
- communication and escalation to the human.

The orchestrator delegates product implementation to `frontend/worker` rather
than writing product code directly. Direct product-code implementation by the
orchestrator is a violation of the worker/reviewer separation model and is
reserved for emergency orchestration-supporting changes only. The
orchestrator's direct edit capability is limited to planning/progress
documentation and small orchestration-supporting changes.

### frontend/worker

The frontend worker implements one bounded leaf task at a time.

Despite the agent name, frontend-program work may include:

- frontend application code;
- frontend tests;
- contract tests;
- synthetic fixtures;
- mocks;
- generated API client infrastructure;
- explicitly approved contract corrections;
- documentation required by the current leaf;
- frontend-oriented integration and E2E support.

### frontend/reviewer

The reviewer independently verifies actual repository state.

The reviewer never intentionally fixes the implementation it is reviewing.

## Execution hierarchy

Work is organized into four concepts:

EPIC
-> EXECUTION UNIT
-> WORK PACKAGE
-> LEAF TASK

### EPIC

A large product/specification area.

Examples:

`E-01`
`E-02`

An Epic contains one or more Work Packages.

### EXECUTION UNIT

The Execution Unit is the unit of autonomous human-to-human workflow.

One Execution Unit corresponds to:

- one feature branch;
- one Git worktree;
- one eventual pull request;
- one or more orchestrator sessions when needed.

An orchestrator session is disposable execution context, not durable project
state. The same Execution Unit may continue in a new orchestrator session
after interruption, quota exhaustion, provider/model change, context growth,
or another operational restart.

Durable execution state lives in the worktree, Git history, backlog, generated
artifacts, tests, and other repository evidence.

The selected Execution Unit can be:

1. an entire Epic, which is the normal/default mode; or
2. one Work Package when the Epic is too large, externally blocked, or
   otherwise unsuitable for one branch/PR.

Example default:

E-01 is selected
-> WP-01
-> WP-02
-> WP-03
-> final E-01 review
-> one PR

Example exceptional mode:

WP-28 is selected directly
-> all WP-28 leaves
-> final WP-28 review
-> one PR

Do not create a separate branch/worktree/PR merely because execution moves
from one Work Package or leaf to another inside the selected Execution Unit.

### WORK PACKAGE

A coherent internal implementation/review checkpoint inside an Execution Unit.

A Work Package contains one or more leaf tasks.

When an entire Epic is the Execution Unit, successful completion of one Work
Package is not a reason to return control to the human.

Continue to the next dependency-ready Work Package in that Epic.

### LEAF TASK

A leaf is the smallest independently implementable and reviewable engineering
result.

A leaf must be reasonably suitable for:

- one frontend/worker assignment;
- one coherent implementation result;
- explicit acceptance criteria;
- independent reviewer verification;
- one reviewed Git checkpoint.

If a backlog leaf is still too large in actual execution, the orchestrator
must recursively decompose it before delegation.

Do this autonomously.

Do not decompose work into mechanical editor actions such as:

- create file;
- add import;
- write function.

A final leaf represents a coherent technical result.

Leaf sizing is semantic, not numeric.

Split a leaf before delegation when it contains multiple outcomes that can be
implemented and independently reviewed without rebuilding the same context, or
when one worker would otherwise need to carry several distinct feature areas
or lifecycle phases in one long trajectory.

Do not split merely because:

- the diff may be large;
- the implementation has many tests;
- verification contains many scenarios;
- a result spans several files.

Keep tightly coupled behaviour together when separating it would duplicate
setup/context or create mechanical micro-tasks.

## Execution target

At session start the launcher specifies exactly one target:

`E-XX`

or:

`WP-XX`

That target defines the Execution Unit.

If an Epic is selected:

- execute only Work Packages belonging to that Epic;
- follow dependency order;
- continue through all dependency-ready Work Packages autonomously;
- do not stop between Work Packages;
- if one item is externally blocked, continue other eligible work inside the
  selected Epic when possible.

If a Work Package is selected:

- execute only that Work Package and its recursively decomposed leaves.

Never automatically continue into another Epic or an unselected Work Package
outside the Execution Unit.

## Session and child-agent isolation

The repository is the durable source of execution state.

A new orchestrator session for the same Execution Unit must:

- read current `AGENTS.md`;
- read the current backlog;
- inspect branch, Git history, working-tree state, and existing artifacts;
- reconcile actual completed work before doing new implementation;
- never recreate already completed work merely because prior conversational
  context is unavailable.

Child implementation/review sessions are isolated deliberately.

For `frontend/worker`:

- every new leaf ID starts in a fresh child session;
- never reuse a `task_id` belonging to a different leaf;
- repair of the SAME leaf may resume that leaf's original worker `task_id`
  when doing so is useful;
- a fresh worker session may be used for the same leaf repair when the old
  context is bloated, unavailable, or otherwise counterproductive.

For `frontend/reviewer`:

- every review invocation starts in a fresh child session;
- never reuse a reviewer `task_id`;
- this applies to initial leaf review, post-repair re-review, Work Package
  review, and final Execution Unit review.

Fresh review context is part of reviewer independence.

## Status lifecycle

Use:

- TODO
- IN_PROGRESS
- BLOCKED
- VERIFIED
- READY_FOR_HUMAN_REVIEW
- DONE

### Leaf

A leaf becomes IN_PROGRESS when actual implementation begins.

A leaf becomes VERIFIED only after:

- implementation is complete;
- independent reviewer verdict is PASS;
- required verification actually ran;
- intended progress state is recorded;
- the verified checkpoint is committed;
- the feature branch is successfully pushed.

### Work Package

When a Work Package is part of a larger Epic Execution Unit, it becomes
VERIFIED after:

- all required leaves are VERIFIED;
- complete Work Package review returns PASS;
- relevant package-level verification passes;
- resulting state is committed and pushed.

Completion of a Work Package does not stop an Epic Execution Unit.

### Execution Unit

The selected Execution Unit becomes READY_FOR_HUMAN_REVIEW only after:

- all required work inside the target is complete;
- all internal Work Packages are VERIFIED as applicable;
- final full Execution Unit review returns PASS;
- relevant complete verification has run;
- final intended repository state is committed and pushed.

DONE means the result is integrated into `main`, or the human explicitly
confirms an equivalent integrated state.

## Autonomous continuation

The normal leaf flow is:

leaf selected
-> fresh frontend/worker implementation session
-> fresh reviewer session
-> repair if required
-> fresh reviewer re-review
-> reviewer PASS
-> confirm required verification evidence / run missing targeted checks
-> backlog update
-> checkpoint commit
-> feature-branch push
-> next leaf

At the end of a Work Package:

all leaves VERIFIED
-> full Work Package review
-> repairs if needed
-> Work Package VERIFIED
-> checkpoint push
-> next eligible Work Package

At the end of an Epic Execution Unit:

all required Work Packages VERIFIED
-> complete Execution Unit review
-> complete verification
-> final checkpoint
-> READY_FOR_HUMAN_REVIEW
-> human

After reviewer PASS, the orchestrator must not perform a second full semantic
code review of the same leaf merely for reassurance.

The orchestrator may inspect the exact diff and run targeted checks needed for
checkpoint integrity or missing acceptance evidence. Full cumulative
verification belongs at Work Package and Execution Unit review boundaries.

Do not return control to the human because:

- one leaf completed;
- one Work Package completed;
- another dependency-ready task exists;
- a dependency needs installation;
- a package manifest or lockfile must change;
- a generator must run;
- tests fail and can be repaired inside scope;
- lint/typecheck/build fails and can be repaired inside scope;
- an ordinary implementation choice exists;
- an ordinary framework/toolchain choice exists;
- additional repository inspection is required.

## Blocked work

A blocked leaf or Work Package does not automatically stop the entire selected
Epic.

Before escalating, look for other dependency-ready work inside the selected
Execution Unit.

Stop for a blocker only when:

- the blocker prevents all remaining useful progress inside the target; or
- continuing would violate dependencies or authoritative requirements.

## Decision escalation

The frontend/worker and reviewer must never ask the human directly.

The worker handles ordinary implementation decisions autonomously.

If the worker genuinely cannot proceed responsibly, it returns
`DECISION_REQUIRED` to the orchestrator.

The orchestrator must first resolve the matter using:

- project specifications;
- public API contract;
- backlog;
- actual repository state;
- existing architecture;
- ordinary engineering judgment.

Only the orchestrator may escalate a substantive question to the human.

Human escalation is appropriate when resolving the issue would materially:

- change a product requirement;
- redefine public API business semantics;
- change the meaning of the selected Execution Unit;
- require unavailable external information or credentials;
- require an unusually destructive or irreversible action.

Several reasonable technical solutions existing at once is not a reason to
ask the human.

Choose one conventional solution and proceed.

## Tool autonomy

Routine tool usage is autonomous.

Do not ask the human for permission to:

- read files;
- search files;
- use glob/grep/rg;
- inspect Git;
- run git status/diff/log/show;
- use Python/Node/PowerShell/shell tools;
- install ordinary project dependencies;
- update package manifests or lockfiles;
- run generators;
- run tests;
- run lint;
- run type checking;
- build the project;
- run browser/E2E checks;
- consult technical documentation;
- perform normal implementation edits inside scope.

If a tool is unavailable, use a reasonable alternative instead of asking the
human merely to authorize a different routine tool.

## Worktree boundary

The branch and worktree for the selected Execution Unit are created before
OpenCode begins.

Agents do not create additional worktrees or branches for Work Packages or
leaf tasks.

Normal product work happens in the current Execution Unit worktree.

Do not intentionally manipulate sibling WiseWay worktrees.

## Git ownership

The frontend/worker may inspect Git but does not publish Git state.

The reviewer may inspect Git but does not publish Git state.

The orchestrator owns reviewed checkpoints.

After reviewer PASS the orchestrator:

1. inspects actual repository status and diff;
2. updates execution progress;
3. stages only intended Execution Unit changes;
4. creates a checkpoint commit;
5. pushes the current feature branch;
6. continues autonomous execution.

Before a checkpoint, verify the current branch.

Never intentionally push product work directly to `main` or `master`.

Never force-push.

Never rewrite already-published Execution Unit history.

Do not use destructive Git cleanup/reset merely to make review failures
disappear.

The human owns final PR acceptance and merge into `main`.

## Repair policy

If reviewer verdict is FAIL:

1. preserve the original result and acceptance criteria;
2. send concrete blocking findings to frontend/worker;
3. let frontend/worker repair them;
4. independently review the complete leaf again.

Maximum repair cycles per leaf: two.

After two unsuccessful repair cycles:

- mark the leaf BLOCKED;
- continue other eligible work inside the Execution Unit when possible;
- escalate only when the blocker prevents further useful progress.

Do not checkpoint a failed leaf as successfully completed.

## API responsibility

Frontend implementation must respect the public API contract.

Do not implement backend-owned domain algorithms in the browser merely to
compensate for missing backend behaviour.

Do not hide incompatible backend behaviour behind undocumented frontend
transformations.

Mocks and real API consumers must use the same public schema.

Generated API code must be regenerated through the documented generator rather
than hand-edited when such a generator exists.

An explicitly approved targeted contract-normalization leaf may modify the
OpenAPI contract.

Unexpected changes to public API business semantics require orchestrator-level
resolution.

## Product UI language

WiseWay product UI is Russian-language.

All user-facing product text must be written in natural Russian unless an
authoritative project specification explicitly requires a literal value in
another language. This includes, where applicable:

- navigation and page titles;
- headings and table headers;
- buttons and links;
- field labels, placeholders, hints, and validation messages;
- loading, empty, success, error, stale, disabled, and conflict states;
- dialogs, confirmations, notifications, and toasts;
- filter/sort labels and user-visible status names;
- accessibility-facing names such as `aria-label`, `title`, and meaningful alt
  text when they describe product UI.

Localization is a presentation concern and does not by itself require a public
API/OpenAPI change.

Do not translate or mutate machine-facing API values merely for presentation.
Enum values, status codes, error codes, field names, operation IDs, and other
contract identifiers remain unchanged in transport/state and are mapped to
Russian presentation labels/messages at the UI boundary when shown to users.

Raw domain/user data such as filenames, filesystem paths, IDs,
`request_id`/`operation_id`, and other literal values remain verbatim unless an
authoritative specification explicitly says otherwise.

Do not expose raw English technical/backend/tooling messages as primary product
copy merely because they are available. Present safe Russian user-facing text
while retaining only the safe diagnostic identifiers/evidence required by the
project specifications.

## Final result

A successful Execution Unit ends with:

- required leaf tasks VERIFIED;
- required internal Work Packages VERIFIED;
- final complete reviewer PASS;
- relevant complete verification;
- intended repository state committed;
- current feature branch pushed;
- selected Execution Unit READY_FOR_HUMAN_REVIEW;
- concise Russian report to the human.

The report must include:

- selected Execution Unit;
- completed Work Packages;
- completed leaves;
- blockers, if any;
- checkpoint commits;
- push status;
- verification actually executed;
- final reviewer verdict;
- residual risks;
- concrete human validation steps;
- recommended next Execution Unit.
