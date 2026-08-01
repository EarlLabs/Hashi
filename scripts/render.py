#!/usr/bin/env python3
"""Render the agentkit into hashi/.claude. Mechanical substitution only —
the rulebooks are authored separately, and the per-command surgery
(no leads, no tracker service) is applied by hand afterwards."""
import os
import pathlib
import shutil
import sys

# Where the kit lives. Override with HASHI_AGENTKIT when Kaizen sits elsewhere.
KIT = pathlib.Path(
    os.environ.get("HASHI_AGENTKIT", "~/stuff/projects/Kaizen/infra/agentkit")
).expanduser()
OUT = pathlib.Path(__file__).resolve().parents[1] / ".claude"

AGENTS = [
    "architect-xavier", "security-holmes", "product-owner-ohno",
    "researcher-curie", "dev-anderson", "dev-neumann", "dev-potts",
    "reviewer-granger",
]
COMMANDS = [
    "product", "develop", "fix", "refactor", "epic",
    "brainstorm", "review", "abort", "doc", "research",
]

ZONE_TABLE = """| Zone | Label | Paths | Rulebook | Verify | Owner |
|---|---|---|---|---|---|
| `control` | Control plane: API, admin panel, subscription delivery, persistence | `control/**`, `tests/control/**`, `tests/e2e/control/**` | `.claude/projects/01-control-rulebook.md` | `make test-control` | Thomas Anderson (`dev-anderson`) |
| `edge` | Data plane: transport profiles, node bootstrap, config rendering, health | `edge/**`, `tests/edge/**`, `tests/e2e/edge/**` | `.claude/projects/02-edge-rulebook.md` | `make test-edge` | John von Neumann (`dev-neumann`) |
| `infra` | Deployment and operations: compose stacks, Caddy, CI, backups, secrets | `deploy/**`, `.github/**`, `Makefile`, `scripts/**`, `.e2e/**`, `.env.example`, `tests/infra/**`, `tests/e2e/infra/**` | `.claude/projects/04-infra-rulebook.md` | `make test-infra` | Pepper Potts (`dev-potts`) |

Everything not listed above — `docs/**`, `.claude/**`, `pyproject.toml`,
`README.md`, `CLAUDE.md`, `.gitignore` — belongs to no zone and is owner and
architect territory. `pyproject.toml` is deliberately among them: adding a
dependency is an architect decision (core invariants §5), so a developer who
needs one asks rather than edits."""

AGENT_REGISTRY = """| Agent | File | Role | Zone | Model |
|---|---|---|---|---|
| Taiichi Ohno | `product-owner-ohno.md` | Product Owner — charter, backlog, accept | — | opus |
| Charles Xavier | `architect-xavier.md` | Solution Architect — also every developer's lead | all | opus |
| Sherlock Holmes | `security-holmes.md` | Security review (design + code) | all | opus |
| Marie Curie | `researcher-curie.md` | Research | — | opus |
| Thomas Anderson | `dev-anderson.md` | Developer | `control` | opus |
| John von Neumann | `dev-neumann.md` | Developer | `edge` | opus |
| Pepper Potts | `dev-potts.md` | Developer | `infra` | opus |
| Hermione Granger | `reviewer-granger.md` | Code review | `control`, `edge`, `infra` | sonnet |

**Not installed in this project**, so nothing may wait on them: team leads
(each zone has one developer — Xavier is the escalation path), a second
reviewer, the analyst, the designer and the UI reviewer."""

CONTEXT_DOCS = (
    "`README.md`, `CLAUDE.md`, and the `AGENTS.md` of every zone in scope "
    "(`control/AGENTS.md`, `edge/AGENTS.md`, `deploy/AGENTS.md`)"
)

ALL_RULEBOOKS = (
    "`00-core-invariants.md` (everywhere), `01-control-rulebook.md` (zone `control`), "
    "`02-edge-rulebook.md` (zone `edge`), `04-infra-rulebook.md` (zone `infra`) and "
    "`03-security-checklist.md` (everywhere), all under `.claude/projects/`"
)

TEST_POLICY_TMPL = (
    "one e2e scenario per acceptance criterion, in `{e2e_dir}`, written before or "
    "alongside the code, and run with `make test-e2e` against the stack `make "
    "e2e-up` starts. Unit tests only for pure branchy logic — config rendering, "
    "credential derivation, subscription serialisation"
)
TEST_POLICY = TEST_POLICY_TMPL.format(e2e_dir="tests/e2e/<your zone>/")

CONTEXT_DOC_POLICY = """Update the `AGENTS.md` of the area you changed. Keep each
under 300 lines and put no code in them — they orient a newcomer, they do not
document the API."""

SECURITY_ZONE_NOTES = """
  - **The adversary here is a censor with network position**, not only a remote
    attacker. Fingerprintability is a security property: a new listener, a fixed
    port, a self-signed certificate, a predictable path or a distinctive packet
    rhythm is a finding.
  - **No connection, traffic or DNS logging.** A log line recording who connected
    to what is a finding, not a feature — including at debug level.
  - **Subscription URLs are bearer credentials**: unguessable, revocable, never
    logged, never in a task file.
  - **Revocation must be total** — a revoked user loses access on every node and
    every transport, not only the one they last used.
  - **Node private keys and provider credentials** live in the control plane's
    encrypted store. Never in git, never in a status file, never in a log.
  - **The admin panel is the highest-value target in the system** — it can add a
    node and read every credential. Every route authenticated, no unauthenticated
    read, no "internal only" endpoint that is merely undocumented."""

GLOBAL = {
    "PROJECT": "hashi",
    "OWNER_LANGUAGE": "English",
    "MAIN_BRANCH": "main",
    "INTEGRATION_BRANCH": "develop",
    "TRACKER_ROOT": "docs/tracker",
    "PRODUCT_ROOT": "docs/product",
    "SPEC_ROOT": "docs/specs",
    "RESEARCH_ROOT": "docs/research",
    "RULEBOOK_CORE": ".claude/projects/00-core-invariants.md",
    "RULEBOOK_SECURITY": ".claude/projects/03-security-checklist.md",
    "RULEBOOKS": ALL_RULEBOOKS,
    "NOTIFY_CMD": "scripts/notify.sh",
    "ASK_OWNER_CMD": "scripts/ask_owner.sh",
    "VERIFY_ALL_CMD": "make test",
    "ZONE_TABLE": ZONE_TABLE,
    "ZONE_KEYS": "control, edge, infra",
    "ZONE_KEY_EXAMPLE": "control",
    "CONTEXT_DOCS": CONTEXT_DOCS,
    "AGENT_REGISTRY": AGENT_REGISTRY,
    "TEST_POLICY": TEST_POLICY,
    "CONTEXT_DOC_POLICY": CONTEXT_DOC_POLICY,
    "SECURITY_ZONE_NOTES": SECURITY_ZONE_NOTES,
    "ARCHITECT_NAME": "Charles Xavier",
    "ARCHITECT_HANDLE": "xavier",
    "SECURITY_NAME": "Sherlock Holmes",
    "SECURITY_HANDLE": "holmes",
    "RESEARCHER_NAME": "Marie Curie",
    "RESEARCHER_HANDLE": "curie",
    "PO_NAME": "Taiichi Ohno",
    "PO_HANDLE": "ohno",
    "LEAD_NAME": "Charles Xavier",
    "LEAD_HANDLE": "xavier",
    "REVIEWERS": "Hermione Granger (`reviewer-granger`)",
    "DOC_CONVENTION": (
        "Python docstrings (PEP 257) on every public module, class and function, "
        "plus a WHAT / WHY / HOW header comment at the top of every module"
    ),
    "MODEL": "opus",
    "PO_PHASE_NOTE": """Ohno is reached **only** through `/product`. This project has
no tracker service and no Hub: the slash command spawns him, he reads and writes
`docs/product/`, and he exits. Nothing dispatches to him automatically, and no
development command waits on him.""",
    "LEADS_AND_DIRECT_REPORTS": """**This project has no team leads.** Each zone has
exactly one developer, so you are their lead as well as their architect — specs
go straight to them, and they escalate to you.

- Thomas Anderson — `dev-anderson` — zone `control`
- John von Neumann — `dev-neumann` — zone `edge`
- Pepper Potts — `dev-potts` — zone `infra`""",
    "CROSS_CUTTING_ROLES": """- Sherlock Holmes — `security-holmes` — security review of design and code, every zone
- Hermione Granger — `reviewer-granger` — code review, all three zones
- Marie Curie — `researcher-curie` — research, on your brief
- Taiichi Ohno — `product-owner-ohno` — Product Owner; owns `what`, reached only via `/product`

Not installed here: team leads, a second reviewer, the analyst, the designer and
the UI reviewer. Never write a spec that waits on one of them.""",
}

ZONES = {
    "control": {
        "label": "Control plane",
        "verify": "make test-control",
        "rulebook": ".claude/projects/01-control-rulebook.md",
        "owned": "- `control/**` — the API, the admin panel, subscription delivery, persistence\n- `tests/control/**` — this zone's unit tests\n- `tests/e2e/control/**` — this zone's acceptance scenarios",
        "agents_md": "control/AGENTS.md",
    },
    "edge": {
        "label": "Data plane",
        "verify": "make test-edge",
        "rulebook": ".claude/projects/02-edge-rulebook.md",
        "owned": "- `edge/**` — transport profiles, node bootstrap, config rendering, health probes\n- `tests/edge/**` — this zone's unit tests\n- `tests/e2e/edge/**` — this zone's acceptance scenarios",
        "agents_md": "edge/AGENTS.md",
    },
    "infra": {
        "label": "Deployment and operations",
        "verify": "make test-infra",
        "rulebook": ".claude/projects/04-infra-rulebook.md",
        "owned": "- `deploy/**` — compose stacks, Caddy configuration, container definitions\n- `.github/**` — CI\n- `Makefile` — the project's verbs\n- `scripts/**` — the owner-channel scripts\n- `.e2e/**` — the e2e profile\n- `.env.example` — the environment template (never `.env`)\n- `tests/infra/**` — this zone's unit tests\n- `tests/e2e/infra/**` — this zone's acceptance scenarios",
        "agents_md": "deploy/AGENTS.md",
    },
}

OTHER_ZONE_LINE = {
    "control": "- `control/**`, `tests/control/**`, `tests/e2e/control/**` — Thomas Anderson (`dev-anderson`)",
    "edge": "- `edge/**`, `tests/edge/**`, `tests/e2e/edge/**` — John von Neumann (`dev-neumann`)",
    "infra": "- `deploy/**`, `.github/**`, `Makefile`, `scripts/**`, `.e2e/**`, `.env.example`, `tests/infra/**`, `tests/e2e/infra/**` — Pepper Potts (`dev-potts`)",
}

EXTRA_SELF_CHECK = {
    "control": """- no user identifier, subscription token or node credential appears in any log line
- every new endpoint states who may reach it and enforces that in code, not in a comment
- the subscription payload is rendered from the node and transport registry — never from a hardcoded list, or a node swap will not reach users
- nothing persists connection, traffic or DNS history""",
    "edge": """- a new transport is a self-contained profile package: no edits to the core renderer, no `if transport == ...` branch anywhere
- no generated config embeds a key that was not generated for that specific node
- every rendered config passes the upstream binary's own config check before it is handed over
- nothing in the rendered config hardcodes a country, a provider or an IP that belongs in the node record""",
    "infra": """- no secret, key or real host name is committed; `.env.example` carries fake values only
- the base compose file exposes no port to the outside world; only the dev overlay opens them
- every service has a healthcheck and a restart policy
- a fresh clone can reach a running stack with the documented commands and nothing else""",
}

DEVS = {
    "dev-anderson": ("control", "Thomas Anderson"),
    "dev-neumann": ("edge", "John von Neumann"),
    "dev-potts": ("infra", "Pepper Potts"),
}


def pre_read(zone_keys, extra_tail=True):
    lines = [
        "1. `.claude/workflow.md` — the procedure and the zone boundaries",
        "2. `.claude/projects/00-core-invariants.md` — project law, everywhere",
    ]
    n = 3
    for zk in zone_keys:
        lines.append(f"{n}. `{ZONES[zk]['rulebook']}` — the `{zk}` zone's rules")
        n += 1
    lines.append(f"{n}. `.claude/projects/03-security-checklist.md`")
    n += 1
    docs = ", ".join(f"`{ZONES[zk]['agents_md']}`" for zk in zone_keys)
    lines.append(f"{n}. `README.md` and {docs}")
    return "\n".join(lines)


def teammates(zone_key):
    rows = {
        "control": "- John von Neumann — zone `edge` — `dev-neumann.md`\n- Pepper Potts — zone `infra` — `dev-potts.md`",
        "edge": "- Thomas Anderson — zone `control` — `dev-anderson.md`\n- Pepper Potts — zone `infra` — `dev-potts.md`",
        "infra": "- Thomas Anderson — zone `control` — `dev-anderson.md`\n- John von Neumann — zone `edge` — `dev-neumann.md`",
    }
    return rows[zone_key]


def render(text, slots):
    for key, value in slots.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def main():
    (OUT / "agents").mkdir(parents=True, exist_ok=True)
    (OUT / "commands").mkdir(parents=True, exist_ok=True)
    (OUT / "projects").mkdir(parents=True, exist_ok=True)

    for name in AGENTS:
        slots = dict(GLOBAL)
        if name in DEVS:
            zk, _ = DEVS[name]
            z = ZONES[zk]
            slots.update({
                "ZONE_KEY": zk,
                "ZONE_LABEL": z["label"],
                "VERIFY_CMD": z["verify"],
                "OWNED_PATHS": z["owned"],
                "OTHER_ZONES": "\n".join(
                    OTHER_ZONE_LINE[k] for k in ZONES if k != zk
                ),
                "PRE_READ": pre_read([zk]),
                "TEAMMATES": teammates(zk),
                "EXTRA_SELF_CHECK": EXTRA_SELF_CHECK[zk],
                # zone-scoped: this developer's own acceptance-scenario directory
                "TEST_POLICY": TEST_POLICY_TMPL.format(e2e_dir=f"tests/e2e/{zk}/"),
            })
        if name == "reviewer-granger":
            slots.update({
                "MODEL": "sonnet",
                "REVIEW_ZONES": "[control, edge, infra]",
                "PRE_READ": pre_read(["control", "edge", "infra"]),
                # A reviewer covering several zones gets the list, not `make test`:
                # running the whole repo on a one-zone diff is slow enough that
                # reviewers start skipping the step (MANIFEST §3, §5.11).
                "VERIFY_CMD": (
                    "make test-control   # and/or test-edge, test-infra — "
                    "whichever zones the diff actually touches"
                ),
            })
        src = (KIT / "agents" / f"{name}.md").read_text()
        (OUT / "agents" / f"{name}.md").write_text(render(src, slots))

    for name in COMMANDS:
        src = (KIT / "commands" / f"{name}.md").read_text()
        slots = dict(GLOBAL)
        slots["VERIFY_CMD"] = "make test"   # commands are project-wide
        (OUT / "commands" / f"{name}.md").write_text(render(src, slots))

    wf = (KIT / "workflow.md").read_text()
    slots = dict(GLOBAL)
    slots["VERIFY_CMD"] = "the zone's verify command (see the zone table above)"
    (OUT / "workflow.md").write_text(render(wf, slots))

    shutil.copyfile(KIT / "VERSION", OUT / "KIT_VERSION")
    print("rendered", len(AGENTS), "agents,", len(COMMANDS), "commands, workflow, KIT_VERSION")
    return 0


if __name__ == "__main__":
    sys.exit(main())
