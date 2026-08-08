# /analyze — Business Analysis & Specification Pipeline (hashi)

> **Solo project.** There is only one persona here — `alfred`. Ignore every "spawn `<agent>`" instruction below **except the one phase that says "Run the review-loop skill"** (do not confuse this with a phase that merely has "Review" in its title, such as a Quality Review that spawns Xavier — that one is not the exception; collapse it into your own work like every other spawn instruction): do every other phase's work yourself, in this same context, one phase after another, and skip any step that exists only to hand work between separate agents (Handoff files, cross-agent status pushes). The review-loop phase still happens — the review-loop skill (`.claude/skills/review-loop/`) spawns `reviewer-strict`, a second, independent, edit-incapable agent, for every development task, and in solo YOU (the orchestrator) apply its findings yourself, same as the skill's default rule. This is not optional and self-review is never a substitute for it — see `alfred.md`.

**You are the pipeline ORCHESTRATOR.** Do NOT analyze anything yourself.
Spawn each agent using the Agent tool. `subagent_type` = filename in `.claude/agents/` without `.md`.

All inter-agent communication happens via files only:
- `docs/tracker/{task-id}/status/`
- `docs/tracker/{task-id}/tasks/`

The output of this pipeline is one or more living specifications under `docs/specs/`,
written by **Ada Lovelace** (`analyst-lovelace`) and reviewed by **Charles Xavier** (`architect-xavier`).

---

## Before You Start

1. Derive a short `task-id` slug from the topic (e.g., `analyze-auth-otp`, `analyze-feature-b-logging`, `analyze-feature-a-setup`).
2. Create tracker and analytics output directories:
```bash
mkdir -p docs/tracker/{task-id}/status docs/tracker/{task-id}/tasks
mkdir -p docs/specs/cross-cutting   # plus one directory per zone: `control`, `edge`, `infra`
```

3. Create a brief `README.md` at the task root:
```bash
cat > docs/tracker/{task-id}/README.md <<'EOF'
# {task-id}

**Type:** analysis
**Goal:** {1-2 sentence summary of what is being documented}
EOF
```

4. Register the task in the SQLite tracker:
```bash
TASK_RECORD=$( task:create \
  "analysis: {topic}" \
  "{topic description from arguments}" \
  "analysis" \
  "Pipeline: /analyze")
TRACKER_ID=$(echo "$TASK_RECORD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
 task:status "$TRACKER_ID" in_progress
```

5. Notify the project owner:
```bash
scripts/notify.sh "Starting analysis: \"$TOPIC\"
Estimated time: 10-20 minutes.
Result: specifications in docs/specs/."
```

---

## Phase 1 — Scope Definition (Xavier)

Spawn sub-agent `architect-xavier` with:
```
Analysis request from the project owner: <full description>
task-id: <task-id>

This is an /analyze pipeline. Determine:
1. Which zone(s) are involved: `control`, `edge`, `infra`, or cross-cutting.
2. Which domain(s) are involved: auth, feature-a, feature-b, feature-c, navigation, etc.
3. Whether this is Mode A (top-down from the project owner's intent — default) or Mode B (code-driven analysis — only if the project owner explicitly asks).
4. What specific features/flows need to be documented and at what granularity (one spec per user-facing capability).
5. For UI features: list the canonical screens involved (consult docs/specs/screen-registry.md if it exists, otherwise list candidate screens from the code in mobile/iosApp/iosApp/Features and mobile/androidApp/.../features and the Figma "Mockups" page).

If the scope is clear — write the task file for Ada immediately.
If the scope is ambiguous — form clarifying questions and send them via scripts/notify.sh.

Your deliverable: docs/tracker/<task-id>/tasks/xavier-to-lovelace-<task-id>.md
The task file must include:
- Mode (A or B)
- Platform(s) and domain(s)
- Granularity decision (how many specs, which feature each covers)
- For UI features: candidate screen list with canonical ID suggestions
- Out-of-scope list

Also update: docs/tracker/<task-id>/status/architect-xavier.yml
```

**If Xavier asks clarifying questions:** STOP the pipeline.
```bash
scripts/notify.sh "Xavier needs clarification on the analysis scope. Please reply."
```
Wait for the project owner's reply, then re-spawn Xavier with answers.

**If Xavier proceeds directly:** continue to Phase 2.

---

## Phase 2 — Specification (Ada Lovelace)

Spawn sub-agent `analyst-lovelace` with:
```
task-id: <task-id>
Read your assignment: docs/tracker/<task-id>/tasks/xavier-to-lovelace-<task-id>.md
Create/update specifications in docs/specs/{platform}/{domain}/.
For UI specs: maintain docs/specs/screen-registry.md and use canonical screen IDs in every flow.
Update: docs/tracker/<task-id>/status/analyst-lovelace.yml
```

**If Ada sets status to `waiting_for_input`:** STOP the pipeline.
```bash
scripts/notify.sh "Ada needs your input to continue. Check her questions."
```
Wait for the project owner's reply, then re-spawn Ada with:
```
task-id: <task-id>
the project owner's answers: <the project owner's reply>
Continue your specification work. Your questions are at:
docs/tracker/<task-id>/tasks/lovelace-questions-<task-id>.md
```

Wait for Ada to complete.

---

## Phase 3 — Quality Review (Xavier)

Spawn sub-agent `architect-xavier` with:
```
task-id: <task-id>
This is the review phase of an /analyze pipeline.
Read Ada's specifications. Check which files she created/updated by reading:
docs/tracker/<task-id>/status/analyst-lovelace.yml

Review for:
1. Completeness — every business rule has at least one acceptance criterion; every error path has a flow.
2. Consistency — new specs do not contradict existing ones in docs/specs/.
3. Clarity — a developer could implement the feature from this spec without further questions.
4. No implementation details leaking into behavior specs.
5. Mermaid diagrams are syntactically correct (no trailing semicolons, correct arrow syntax, stateDiagram-v2 not stateDiagram).
6. For UI specs:
   - Every spec includes a Screen Inventory table mapping canonical IDs → design frame → the implementation in each zone that renders it.
   - Every navigation step in Screen Flow names source and destination canonical IDs explicitly.
   - Canonical IDs in the spec match docs/specs/screen-registry.md.
   - User flow Mermaid diagrams use canonical IDs as participant aliases.

If issues found — write feedback to docs/tracker/<task-id>/tasks/xavier-review-lovelace-<task-id>.md
Update: docs/tracker/<task-id>/status/architect-xavier.yml with verdict (approved | needs_revision).
```

If Xavier finds issues → re-spawn Ada with feedback, then re-run Phase 3. Max **2 review rounds**;
after that, deliver with documented issues.

---

## Phase 4 — Deliver Results

Update tracker:
```bash
 task:status "$TRACKER_ID" done
```

If **git workflow instructions** were provided (remote mode):
- Create branch `analyze/{slug}` from `develop`, push, create PR to `develop`.
- PR title: `docs(analytics): {feature} specification`
- PR body lists all specs created/updated with their IDs and locations.

If **no git workflow instructions** (local mode):
- Specs are saved locally; report file paths to the project owner.

Notify the project owner:
```bash
scripts/notify.sh "Analysis complete: {topic}
Specs created/updated:
- {list of spec IDs and file paths}
Screens registered: {count}
Location: docs/specs/"
```

---

## Global Rules

- Ada does the analysis, Xavier scopes and reviews. Orchestrator coordinates.
- If Ada needs the project owner's input — STOP and wait. Never fabricate business rules.
- If any agent returns `blocked` — notify the project owner immediately and stop.
- Max 2 rounds of review before delivering (even if imperfect, with noted issues).
- Default is Mode A (top-down from the project owner's intent). Mode B (code-driven) only when the project owner explicitly asks.
- UI specs MUST use canonical screen IDs from the registry and document explicit screen-to-screen transitions. Reject any UI spec that lacks a Screen Flow section.
