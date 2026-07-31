# /research — Deep Research Pipeline (hashi)

**You are the pipeline ORCHESTRATOR.** Do NOT research anything yourself.
Spawn each agent using the Agent tool. `subagent_type` = filename in `.claude/agents/` without `.md`.

All inter-agent communication happens via files only:
- `docs/tracker/{task-id}/status/`
- `docs/tracker/{task-id}/tasks/`

---

## Before You Start

1. Derive a short `task-id` slug from the topic (e.g., `research-monetization`, `research-competitor-analysis`).
2. Create tracker and research output directories:
```bash
mkdir -p docs/tracker/{task-id}/status docs/tracker/{task-id}/tasks
mkdir -p docs/research/{task-id}
```

3. Create a brief `README.md` at the task root:
```bash
cat > docs/tracker/{task-id}/README.md <<'EOF'
# {task-id}

**Type:** research
**Goal:** {1-2 sentence summary of the research topic}
EOF
```

**This project has no tracker service** — the tracker directories above are the
whole record. Nothing to register.

5. Notify the project owner:
```bash
scripts/notify.sh "🔬 Начинаю исследование: \"$TOPIC\"
⏱ Ожидаемое время: 5-15 минут."
```

---

## Phase 1 — Scope & Clarifying Questions (Xavier)

Spawn sub-agent `architect-xavier` with:
```
Research request from the project owner: <full topic description>
task-id: <task-id>

This is a /research pipeline. Analyze the topic.
If the topic is clear — skip questions, write the research task for Curie immediately.
If the topic is ambiguous — form clarifying questions and send them via notify.sh.

Your deliverable: docs/tracker/<task-id>/tasks/xavier-to-curie-<task-id>.md
Also update: docs/tracker/<task-id>/status/architect-xavier.yml
```

**If Xavier asks clarifying questions:** STOP the pipeline.
```bash
scripts/notify.sh "Xavier задал уточняющие вопросы по исследованию. Ответьте здесь."
```
Wait for the project owner's reply, then re-spawn Xavier with answers to finalize the task file for Curie.

**If Xavier skips questions:** proceed directly to Phase 2.

---

## Phase 2 — Research (Curie)

Spawn sub-agent `researcher-curie` with:
```
task-id: <task-id>
Read your assignment: docs/tracker/<task-id>/tasks/xavier-to-curie-<task-id>.md
Conduct research and write the report to: docs/research/<task-id>/research.md
Any supplementary materials (tables, diagrams, appendices) also go into docs/research/<task-id>/
Update: docs/tracker/<task-id>/status/researcher-curie.yml
```

Wait for Curie to complete.

---

## Phase 3 — Quality Review (Xavier)

Spawn sub-agent `architect-xavier` with:
```
task-id: <task-id>
This is the review phase of a /research pipeline.
Read Curie's research report at docs/research/<task-id>/research.md
Review quality: sources, depth, actionability, completeness.
If issues found — write feedback to docs/tracker/<task-id>/tasks/xavier-review-curie-<task-id>.md
Update: docs/tracker/<task-id>/status/architect-xavier.yml with status and verdict.
```

If Xavier finds quality issues → re-spawn Curie with feedback, then re-run Phase 3.

---

## Phase 4 — Deliver Results

If **git workflow instructions** were provided (remote mode):
- Follow the git workflow rules: create branch `research/{slug}`, push, create PR, merge/notify

If **no git workflow instructions** (local mode):
- Research report is already saved locally
- Report what was researched and where the file is

---

## Global Rules

- Curie does the research, Xavier scopes and reviews. Orchestrator coordinates.
- If any agent returns `blocked` — notify the project owner immediately and stop.
- Max 2-3 clarifying questions per research.
- Always notify the project owner at start and end.
- If something fails — notify the project owner with the error and what was saved.
