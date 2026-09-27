"""The deployment runbook's load-bearing claims — M11.3, and M6.2's two defects.

WHAT: static checks over ``docs/deploy/runbook.md``, and over the agreement between its
      leaf section and the script that section documents.
WHY:  the runbook is the only artefact an operator follows at 3am, and prose drifts in a
      way code does not: nothing breaks when a documented flag is renamed, when a quoted
      line of output is paraphrased, or when a port literal creeps back into a firewall
      rule. Two of those had already happened here — the runbook told an operator to run
      ``ufw enable`` with no ``ufw logging off`` in front of it, which starts writing
      source addresses (docs/decisions.md, decision 5), and it opened four literal ports,
      which are four ports the fleet cannot move away from.
HOW:  the file is read, never rendered, and never followed. Same division as
      ``test_node_bootstrap_script.py``: nothing here proves the runbook works, it proves
      the runbook cannot quietly teach the harmful version of a step.
"""

import ast
import inspect
import pathlib
import re

import pytest

from control.app.api.routes import router as api_router
from control.app.services import console, relay
from control.app.services.placement import TUNNEL_TAKEN, claim
from control.app.services.transports import (
    hop_transports,
    offerable_transports,
    retired_transports,
)
from edge.bootstrap.node_stack import EXTENSION
from edge.egress import NO_RESOLVER, ResolverMissing
from edge.registry import discover, profile

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"
SCRIPT = REPO / "scripts" / "node-bootstrap.sh"
TUNNEL_SCRIPT = REPO / "scripts" / "management-tunnel.sh"
PANEL_SCRIPT = REPO / "scripts" / "panel-bootstrap.sh"
CADDYFILE = REPO / "deploy" / "caddy" / "Caddyfile"
NODES_TABLE = REPO / "control" / "app" / "templates" / "panel" / "nodes_table.html"
MIGRATIONS = REPO / "control" / "migrations" / "versions"
ENV_EXAMPLE = REPO / ".env.example"

# M16's section, by its exact title: the shapes that build a hop and the migration that
# empties the field both point at it by these words.
RESOLVER_SECTION = "A node that dials a hop needs a resolver"

# M28.4's section, by its exact title, for the same reason: ``.env.example`` sends the
# operator here for the one decision it cannot carry in a comment.
RETENTION_SECTION = "The retention this host's own key cannot reach"

# Ports that mean something to somebody, so a literal one is a value that gets copied.
# The same list the script's own test uses, for the same reason.
KNOWN_PORTS = (21, 22, 23, 25, 53, 80, 443, 1194, 3306, 5432, 6379, 8000, 8080, 8443, 51820)


@pytest.fixture(scope="module")
def runbook() -> str:
    return RUNBOOK.read_text()


@pytest.fixture(scope="module")
def leaf_section(runbook: str) -> str:
    """The section that takes an operator from a rented host to a drivable node."""
    section = re.search(r"^## Preparing a leaf\n(?:.*\n)*?(?=^## )", runbook, re.M)
    assert section, (
        "the runbook has no leaf section — every leaf is then prepared by hand, which is "
        "the thing M11 exists to end"
    )
    return section.group(0)


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


def test_logging_is_turned_off_before_any_firewall_is_enabled(runbook: str) -> None:
    """Decision 5, in the file an operator actually types from.

    ``ufw enable`` turns connection logging on by default and begins writing source
    addresses the moment the firewall comes up — the one record the charter forbids at any
    level. Afterwards is too late: the file exists by then, and rsyslog, kern.log and the
    journal already hold copies that no cleanup on the host reaches. A position check, not
    a presence check, because a ``ufw logging off`` further down the page is exactly the
    version that does not protect anybody.
    """
    enables = [m.start() for m in re.finditer(r"ufw (?:--force )?enable", runbook)]
    assert enables, "the runbook no longer brings a host firewall up at all"
    offs = [m.start() for m in re.finditer(r"ufw logging off", runbook)]
    for enable in enables:
        assert any(off < enable for off in offs), (
            "the runbook enables ufw with no `ufw logging off` in front of it, so following "
            "it creates a connection log on the host"
        )


def test_the_runbook_never_asks_for_logging_to_be_switched_on(runbook: str) -> None:
    """There is no level of it that is allowed, including "temporarily, while debugging"."""
    assert not re.search(r"ufw logging (?:on|low|medium|high|full)\b", runbook), (
        "the runbook names a ufw logging level other than off"
    )


def test_no_firewall_rule_in_the_runbook_opens_a_port_literal(runbook: str) -> None:
    """A port written into a runbook is a port the fleet cannot move away from.

    The rule that keeps a country, a provider, an address or a port out of the code applies
    here word for word: an operator opens the ports THEIR configuration uses, read off
    sshd, their Caddyfile and the node record. A literal here is also the specific defect
    M6.2 named — four of them on one line.
    """
    rules = re.findall(r"ufw allow [^\n]*", runbook)
    assert rules, "the runbook opens no ports at all, which no host firewall survives"
    for rule in rules:
        # The command only; a trailing `#` comment is where an operator is told WHERE to
        # read their own value from, and telling them that is the whole fix.
        command = rule.split("#")[0]
        assert not re.search(r"\d", command), f"a firewall rule opens a literal port: {rule!r}"
        assert "<" in command, (
            f"a firewall rule names no placeholder, so it is not clear what to substitute: "
            f"{rule!r}"
        )


def test_the_leaf_section_hardcodes_no_port_provider_or_address(leaf_section: str) -> None:
    """Same hard rule as the script's, applied to the prose that surrounds it.

    Prose is where it comes back: a worked example with a real port reads as helpful and is
    indistinguishable, three months later, from a requirement.
    """
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", leaf_section), (
        "an IP address is hardcoded in the leaf section"
    )
    for port in KNOWN_PORTS:
        assert not re.search(rf"\b{port}\b", leaf_section), (
            f"the literal port {port} appears in the leaf section — even as an example it "
            "is a value somebody will copy into a rule"
        )
    for provider in ("hetzner", "digitalocean", "vultr", "linode", "aws", "timeweb", "ovh"):
        assert provider not in leaf_section.lower(), (
            f"the leaf section names {provider}, and a runbook that names one provider is a "
            "runbook the next rental does not match"
        )
    assert not re.search(r"[a-z]+://", leaf_section), (
        "the leaf section carries a URL — a node's addresses are node-record data"
    )


def test_every_command_in_the_leaf_section_survives_being_pasted(leaf_section: str) -> None:
    """A placeholder in a runnable fence must not be a shell metacharacter.

    ``NODE=<user>@<host>`` is a redirection, not a placeholder: pasted verbatim it dies on
    ``user: No such file or directory``, which names neither the script nor the thing the
    operator forgot to fill in. This is the one command the milestone exists to make
    possible, typed by somebody rebuilding a node under time pressure — a loud, confusing
    failure spends exactly the attention the script was written to save. Prose may keep
    angle brackets; a ```bash fence may not.
    """
    fences = re.findall(r"^```bash\n((?:.*\n)*?)^```$", leaf_section, re.M)
    assert fences, "the leaf section shows no command to run"
    for fence in fences:
        assert "<" not in fence and ">" not in fence, (
            f"a runnable command carries a shell redirection where a placeholder was meant: "
            f"{fence!r}"
        )
    assert re.search(r"\b[A-Z][A-Z_]{3,}\b", "".join(fences)), (
        "no placeholder is recognisable in the commands, so it is not clear what to replace"
    )


def test_the_leaf_section_quotes_the_script_rather_than_paraphrasing_it(
    leaf_section: str, script: str
) -> None:
    """Every operator-facing string in the section must exist in the script, verbatim.

    This is the drift the section is most likely to suffer, and the most expensive: a
    paraphrased success line is one an operator compares against their terminal and cannot
    match, at which point they do not know whether the run went well. Renaming a flag or
    rewording a `say` line therefore turns this red, which is the point — the wording is a
    contract between the two files, not a description of one by the other.

    The script's lines are compared with its shell variables expanded the way the run
    expands them, because M13 gave the closing lines a path and an account name that are
    values rather than words, and M19 gave one of them the key file. The substitution is
    the runbook's own convention for a transcript of output — angle brackets — and nothing
    else here is normalised: a reworded sentence is still a reworded sentence.

    Every variable a quoted line carries has to be in that list, and the one missed cost
    exactly what this test exists to prevent: M19's new line was the only sentence in the
    sample transcript nothing held, because ``${KEYS_FILE}`` was not normalised and so the
    line could not be quoted below.
    """
    as_the_operator_sees_it = (
        script.replace("${NODE_ROOT}", "/opt/hashi")
        .replace("${TARGET_USER}", "<user>")
        .replace("${KEYS_FILE}", "<the account's ~/.ssh/authorized_keys>")
    )
    for quoted in (
        # success, and what to do next
        "key authorised, firewall up, logging off",
        "register it in the panel with ssh_user",
        # M13: the script now creates the directory, so the claim it makes about hashi
        # state is narrower and the wording moved with it. Both files moved together,
        # which is what this test is for.
        "created /opt/hashi, empty and owned by <user>",
        "no hashi code and no hashi state was installed here — /opt/hashi is an empty "
        "directory owned by <user>, and the control plane fills it on your first apply",
        # a host somebody already prepared
        "docker is already installed — left exactly as it is",
        "the control plane's key is already authorised for",
        # M26's second walk: the step says what it READ out of ufw's config file, because
        # that file is all there is to read while the firewall is inactive — and the claim
        # that the firewall is not logging is made once, after the firewall itself is
        # asked. Both lines are quoted here because an operator matches a terminal against
        # this page, and this is the run's one subject the charter forbids at any level.
        "/etc/ufw/ufw.conf already reads LOGLEVEL=off",
        "the running firewall was asked and it is not logging",
        "was already open",
        "incoming was already denied by default",
        "the firewall was already up — its existing rules were kept",
        # M18.3: the two lines about an already-prepared directory now say that its
        # CONTENTS changed hands as well. They are quoted here for the reason the whole
        # test exists — an operator matching a terminal against this page — and because
        # this is the one claim in the run that an operator would otherwise have to
        # verify by hand on a live node.
        "/opt/hashi was already here — <user> now owns it and everything an earlier "
        "apply left inside it; nothing in it was read, changed or removed",
        "/opt/hashi was already here before this run — whatever an earlier apply left in "
        "it, this run neither read, changed nor removed it; it now belongs to <user> "
        "along with the directory, so an apply as that account can replace it",
        # M19: the one line the run prints about the check that replaced reading the key
        # file back. It names the file, so the operator can see WHICH file sshd said it
        # reads — which is the whole content of the check, and a paraphrase of it on this
        # page would leave them comparing two different sentences.
        "sshd reads <the account's ~/.ssh/authorized_keys>, so a key installed there is "
        "one it will consult",
        # the boundary the run ends on
        "the provider's own firewall sits in front of this host and outside this script's "
        "reach",
    ):
        assert quoted in as_the_operator_sees_it, f"the script no longer says {quoted!r}"
        assert quoted in leaf_section, (
            f"the runbook does not quote {quoted!r}, so an operator cannot match what they "
            "see against what this section promises"
        )
    for flag in ("--authorized-key", "--authorized-key-file", "--port", "--user", "--ssh-port"):
        assert flag in script, f"the script no longer accepts {flag}"
        assert flag in leaf_section, f"the leaf section does not document {flag}"
    assert "make node-bootstrap" in leaf_section, (
        "the section documents an operation without naming its Make target"
    )
    assert "**1**" in leaf_section and "**2**" in leaf_section, (
        "the section does not give the exit codes, so a piped run's failure is unreadable"
    )


def test_the_leaf_section_says_which_accounts_work(leaf_section: str) -> None:
    """M13.3, and the question the runbook could not answer when it cost an evening.

    Shape A said "reach the box as root" and every host in this project's history was
    reached that way, so nothing in here was wrong — it was silent. Meanwhile the script
    supports a non-root account, puts it in the docker group, and ends by telling the
    operator to register it. An operator following both ended up with a node the control
    plane could not write to, and nothing on the page said which of the two they should
    have believed.

    So the section states the rule, states what makes an account work, and states the
    repair for a host that predates the script — the last one verbatim, because an
    operator pastes it.
    """
    section = re.search(
        r"^### Which accounts work\n(?:.*\n)*?(?=^### )", leaf_section, re.M
    )
    assert section, (
        "the runbook does not say which accounts can drive a node, which is how a "
        "documented non-root ssh_user became a node nothing could be written to"
    )
    accounts = section.group(0)
    assert "passwordless" in accounts, (
        "the section does not say what a non-root account needs, so 'any account' reads as "
        "true and the script refuses half of them"
    )
    for requirement in ("`docker` group", "/opt/hashi", "public key"):
        assert requirement in accounts, (
            f"the section does not say the account must have {requirement}, so an operator "
            "cannot tell whether the one they picked will work"
        )
    assert "escalat" in accounts, (
        "the section does not say the control plane never escalates on a node — without "
        "that, none of the three requirements has a reason and the next reader relaxes one"
    )
    assert "install -d -m 700 -o THE_SSH_USER /opt/hashi" in accounts, (
        "the section does not give the by-hand repair for a host prepared before the "
        "script existed, which is every host this project already has"
    )


def test_the_leaf_section_names_the_layer_the_script_cannot_see(leaf_section: str) -> None:
    """The provider's security group, and how to confirm it without lying to yourself.

    It is a separate layer, in the provider's console, invisible from inside the host — and
    when it is shut it looks EXACTLY like a broken transport, so the operator debugs the
    transport, where there is nothing to find. Naming it is not enough on its own: the
    honest check is from a machine on a different network, and the check itself has a known
    false negative that reads as a closed port.
    """
    assert "security group" in leaf_section, "the provider's own firewall is not named"
    assert "different network" in leaf_section, (
        "the section does not say where to probe from — a check run on the host, or from "
        "the same private network, answers a question nobody asked"
    )
    assert "unprivileged" in leaf_section and "false negative" in leaf_section, (
        "the section does not warn that the probe can lie: a process that cannot bind a "
        "privileged port reports a shut port that is in fact open"
    )
    assert "does not register the node" in leaf_section, (
        "a prepared host reads as a node the fleet knows about"
    )
    assert "reachability" in leaf_section, (
        "the section leaves 'ready' covering whether anyone can reach the host"
    )


def test_the_leaf_section_does_not_read_as_though_the_host_were_blank(
    leaf_section: str,
) -> None:
    """"Already done by somebody else" is the normal case, on real rented hardware.

    Both hosts of this project's field run already had docker, and one already had an
    active firewall carrying rules of its own. A section written for a blank host does not
    match what the operator is looking at, and the first thing they do about the mismatch
    is stop trusting the section.
    """
    assert re.search(r"already", leaf_section), "the section assumes a host with no past"
    assert "union of every run" in leaf_section, (
        "the section does not say the script never closes a port, so an operator reads a "
        "re-run as a rule set that shrinks to the arguments they just passed"
    )


@pytest.fixture(scope="module")
def panel_section(runbook: str) -> str:
    """The section that takes an operator to a console that is no longer public — M7."""
    section = re.search(r"^## Reaching the panel\n(?:.*\n)*?(?=^## )", runbook, re.M)
    assert section, (
        "the runbook does not say how to reach the panel now that it is off the public "
        "hostname — which leaves the operator with a 404 and no next step"
    )
    return section.group(0)


def test_the_panel_section_quotes_the_scripts_rather_than_paraphrasing_it(
    panel_section: str,
) -> None:
    """Every operator-facing string in the section exists verbatim in a script.

    The same mechanical anti-drift M11.3 established for the leaf section, and it is
    what makes changing a `say` line cost the same edit in both places. Paraphrase is
    how a runbook stops matching the thing it documents: nothing breaks, the words
    just quietly stop being the ones on the screen.
    """
    quoted = {
        TUNNEL_SCRIPT: (
            "Its configuration follows ONCE and is not stored anywhere",
            "already a peer of this tunnel",
            # Kept to what fits on one line in BOTH files: the script wraps this
            # message and so does the prose quoting it, and a fragment that spans a
            # newline in either can never match verbatim.
            "NOT done, and not yet true: the tunnel is not up",
        ),
        PANEL_SCRIPT: (
            "generating the management tunnel the panel is reached over",
        ),
    }
    for path, strings in quoted.items():
        source = path.read_text()
        for string in strings:
            assert string in source, (
                f"the runbook quotes {string!r}, which {path.name} does not print"
            )
            assert string in panel_section, (
                f"{path.name} prints {string!r} and the runbook does not quote it"
            )


def test_the_panel_section_agrees_with_the_caddyfile_about_what_each_site_serves(
    panel_section: str,
) -> None:
    """The split is the milestone, so the runbook's account of it must be the truth.

    An operator reading that the console is on the public site — or that ``/sub`` moved
    — makes exactly the wrong decision about which port to open, and a firewall opened
    on the wrong reasoning is how the panel ends up public again.
    """
    caddyfile = CADDYFILE.read_text()
    for path in ("/sub/*", "/panel/*", "/api/*", "/static/*"):
        assert path in caddyfile, f"the Caddyfile no longer mentions {path}"
        assert path in panel_section, (
            f"the Caddyfile serves {path} and the runbook's table does not say where"
        )


def test_the_panel_section_leaves_the_way_back_in_verified_rather_than_described(
    panel_section: str,
) -> None:
    """M7.3 was raised from "document" to "document and TEST" on 2026-09-09.

    A fallback that has only been written down is worth nothing on the day it is
    needed, and that day is an emergency rotation. So the section has to carry a
    command that CHECKS the route, not only one that opens it — and it has to say what
    a working answer looks like.
    """
    assert "ssh -L" in panel_section, "the section does not show how to open the forward"
    checks = re.findall(r"curl[^\n]*", panel_section)
    assert checks, "the section shows no command that checks the fallback actually works"
    assert any("panel" in check for check in checks), (
        "the section's check does not ask for the console, so it proves the forward is "
        "open rather than that the panel answers through it"
    )
    assert "200" in panel_section, (
        "the section does not say what a working answer looks like, so an operator "
        "cannot tell a checked fallback from an unchecked one"
    )


def test_the_panel_section_does_not_render_forwarding_rules_into_the_admin_tunnel(
    panel_section: str,
) -> None:
    """The quiet mistake the plan names, kept out of the prose an operator copies.

    The management tunnel carries traffic TO the panel host and never THROUGH it, so
    M14's `PostUp`/`PostDown` masquerade must not be rendered for it — doing so turns
    the admin tunnel into an exit node, which is a change of what the host is, made by
    nobody. The section says so; it must never show the rules.
    """
    for directive in ("PostUp", "PostDown", "MASQUERADE", "ip_forward"):
        assert not re.search(rf"^\s*{directive}\s*=", panel_section, re.M), (
            f"the section shows a {directive} line for the management tunnel"
        )


# --- the shapes, and the combination the product refuses — M15.3 ---------------------
#
# Everything above guards two sections; these guard the three shapes and the section
# that answers them. The drift this file exists to catch is exactly the drift that cost
# M15: the runbook mandated one transport for the hop and recommended the same one for
# the users of the box that dials it, and nothing anywhere compared the two claims
# against the product. Prose is where that recommendation lives, so prose is where the
# check has to be.
#
# ``control`` and ``edge`` are IMPORTED rather than described, the convention
# ``test_node_bootstrap_agrees_with_the_control_plane.py`` established: the answer
# compared against the page is the one the panel and the renderers really give, not a
# second copy of it in a regex here.


# The hop form's own field, as the runbook writes it. ``\s`` rather than a space because
# the instruction wraps across a line in one of the shapes, and a check that missed a
# wrapped hop would be a check that passes on the sentence it exists to read.
HOP_FIELD = r"transport =\s*`([a-z0-9-]+)`"


def _flat(text: str) -> str:
    """``text`` with its line wrapping collapsed, so a phrase can be looked for at all.

    The runbook wraps at about ninety columns and its cross-references wrap with it, so a
    substring check against the raw text asks the prose to be laid out a particular way —
    which is a test dictating typography rather than content.
    """
    return re.sub(r"\s+", " ", text)


def _prose_paragraphs(text: str) -> list[str]:
    """Every blank-line-delimited block of ``text``, with each TABLE ROW dropped first.

    The tables are dropped because a check over the whole document cannot otherwise tell
    prose from the cell it is supposed to be explaining — which is how the retirement
    check below spent its first round passing on the table row five lines above it, and
    on two pre-existing sentences about a node record's ``retired`` state that have
    nothing to do with a transport. Every row, not only the capability table's: a second
    table answering for the first is the same defect with a different address.

    Per PARAGRAPH rather than over the remainder in one piece, for the same reason: the
    claim is that some paragraph both names the transport and says what happened to it,
    and a document-wide search is satisfied by two unrelated sentences in two sections.
    """
    prose = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("|")
    )
    return [_flat(block).strip() for block in re.split(r"\n\s*\n", prose) if block.strip()]


def _numbered_steps(body: str) -> list[str]:
    """Each numbered instruction in a section, with its continuation lines.

    Per STEP rather than per line: an instruction wraps, and the transport it names is as
    likely to be on the second line as the first.
    """
    return re.findall(r"^\d+\. [^\n]*\n(?:   [^\n]*\n)*", body, re.M)


def _transport_names(text: str) -> set[str]:
    """Every installed transport named in backticks in ``text``."""
    return {name for name in re.findall(r"`([a-z0-9-]+)`", text) if name in discover()}


def _answer(cell: str) -> str:
    """The yes/no a table cell opens with, whatever qualification follows it.

    The table's own convention, and the reason the columns are worth checking at all: a
    cell may explain itself at any length, but it must commit in its first word.
    """
    words = re.sub(r"[^a-z]+", " ", cell.lower()).split()
    assert words and words[0] in ("yes", "no"), (
        f"the capability table's cell {cell!r} does not start with yes or no, so nothing "
        "can tell what it claims"
    )
    return words[0]


def _egress_expression(transport_name: str) -> str:
    """Whether this transport's data plane is routed by the kernel or re-originates.

    Read off the transport's own render module — which of ``edge.egress``'s two
    expressions it imports — rather than off its name, its family or its config format.
    That import IS the distinction the runbook's first column describes: a package that
    calls ``wg_quick_egress`` hands a user's packets to the node's routing table and is
    refused on a node whose way out is a hop, and one that calls ``exit_origin``
    terminates the connection and opens its own from the hop's near address.
    """
    tree = ast.parse(inspect.getsource(profile(transport_name).profile))
    # Parsed rather than scanned. A docstring in a render module may quote the OTHER
    # expression while explaining why it does not use it — both of these packages explain
    # themselves at length — and a regex over the source reads that as an import, then
    # reports "imports neither, or both" about something that never happened. The
    # diagnosis matters here more than usual: this is the fact the runbook's first column
    # is checked against.
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "edge.egress"
        for alias in node.names
    }
    kernel = "wg_quick_egress" in imported
    userspace = "exit_origin" in imported
    assert kernel != userspace, (
        f"{transport_name} imports neither of edge.egress's two expressions, or imports "
        f"both — from edge.egress it imports {sorted(imported)} — so there is no answer "
        "to give an operator about what it does with a hop"
    )
    return "kernel" if kernel else "userspace"


@pytest.fixture(scope="module")
def capability_table(runbook: str) -> dict[str, tuple[str, str, str]]:
    """The runbook's own table of what each installed transport may be asked to do."""
    table = re.search(
        r"^\| transport \|[^\n]*\n\|[-| ]+\|\n((?:\|[^\n]*\n)+)", runbook, re.M
    )
    assert table, (
        "the runbook no longer states which transport may serve users on a node that "
        "dials a hop — which is the question following it used to get wrong"
    )
    rows: dict[str, tuple[str, str, str]] = {}
    for line in table.group(1).splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        assert len(cells) == 4, f"the capability table's row {line!r} is not four columns"
        rows[cells[0].strip("`")] = (cells[1], cells[2], cells[3])
    return rows


def test_the_capability_table_covers_every_transport_this_image_ships(
    capability_table: dict[str, tuple[str, str, str]],
) -> None:
    """A fifth transport is a fifth row, or the table is an answer with a hole in it.

    An operator reads a table as complete. One that silently omits the protocol they just
    enabled is worse than no table, because they stop looking.
    """
    assert set(capability_table) == set(discover()), (
        "the runbook's transport table and the installed transports disagree about which "
        "protocols exist"
    )


def test_the_table_agrees_with_the_code_about_users_on_a_node_that_dials_a_hop(
    capability_table: dict[str, tuple[str, str, str]],
) -> None:
    """M15.3's whole subject, checked against ``edge`` rather than against memory.

    A user-facing transport on a node whose way out is a hop must terminate the
    connection and originate its own; one whose packets the kernel routes is accepted by
    the panel and refused by ``edge/egress.py`` at apply. The table says which is which,
    and this is what stops it saying it wrongly.
    """
    for name, (with_hop, _, _) in capability_table.items():
        expected = "no" if _egress_expression(name) == "kernel" else "yes"
        assert _answer(with_hop) == expected, (
            f"the runbook says {name} is {_answer(with_hop)!r} for the users of a node "
            f"with a hop, and its renderer says {expected!r}"
        )


def test_the_table_agrees_with_the_panel_about_which_transport_can_carry_a_hop(
    capability_table: dict[str, tuple[str, str, str]],
) -> None:
    """The other half of the same contradiction, and the half that is enforced.

    The hop form offers exactly ``transports.hop_transports()``. A runbook naming one it
    does not offer sends an operator looking for a missing option; one omitting a
    transport the form offers hides a choice.
    """
    offered = set(hop_transports())
    for name, (_, _, for_the_hop) in capability_table.items():
        expected = "yes" if name in offered else "no"
        assert _answer(for_the_hop) == expected, (
            f"the runbook says {name} is {_answer(for_the_hop)!r} for the hop, and the "
            f"panel's hop form says {expected!r}"
        )


def test_the_table_offers_users_only_a_transport_the_panel_proposes(
    capability_table: dict[str, tuple[str, str, str]],
) -> None:
    """The column for a node with no hop, against the form an operator actually meets.

    IT USED TO ASK THE DECLARED DELIVERY FORMATS — whether a user's client could
    consume this transport at all, which is what ``nodes.enable_transport`` refuses on.
    That was the whole answer until M20, when a transport measured to carry nothing on the
    hosts this runbook prepares was retired from the enable dialog. Its formats are
    unchanged and it is still installed, so the old question still answers "yes" for it
    and the runbook would have gone on recommending a protocol no form offers.

    ``offerable_transports`` is the panel's own answer and is therefore the honest one for
    a column of advice: a yes here for a transport the dialog does not list sends an
    operator hunting for a missing option, which is exactly the failure the hop column's
    sibling check exists to prevent.
    """
    offered = set(offerable_transports())
    for name, (_, without_hop, _) in capability_table.items():
        expected = "yes" if name in offered else "no"
        assert _answer(without_hop) == expected, (
            f"the runbook says {name} is {_answer(without_hop)!r} for the users of a "
            f"node with no hop, and the panel's enable dialog says {expected!r}"
        )


def test_the_table_says_why_a_transport_it_no_longer_recommends_is_not_offered(
    runbook: str, capability_table: dict[str, tuple[str, str, str]]
) -> None:
    """A "no" an operator cannot act on is a cell that will be argued with.

    The registry carries a reason for every retirement precisely so that nothing has to
    write one down twice — so the runbook has to say the transport is retired where the
    operator meets the row, and the paragraphs around the table have to say what that
    means for the node they are standing in front of. Checked as prose rather than word
    for word: the sentence on the panel is the transport's own and this file is a
    different audience.

    THE SECOND HALF OF THIS TEST COULD NOT FAIL UNTIL REVIEW FOUND IT, and the shape is
    worth keeping written down. It searched the whole document for the word "retired",
    which the cell asserted three lines above it already guarantees, and which two
    pre-existing sentences about setting a NODE RECORD to ``retired`` supply as well —
    so deleting the only paragraph that explains a retirement to an operator left the
    suite green. It now asks for the conjunction instead: one paragraph, outside every
    table, that both NAMES the transport and says it is retired. Nothing else in this
    document can satisfy that, which is the property the old assertion was missing.

    The two have to be in the SAME paragraph deliberately. An explanation whose subject
    is in one paragraph and whose verdict is in another is one an operator searching this
    file for either word does not find whole, which is the failure the cell points at
    them to avoid.
    """
    retired = set(retired_transports())
    marked = retired & set(capability_table)
    if not marked:
        pytest.skip("this image retires no transport, so no cell can mark one")

    paragraphs = _prose_paragraphs(runbook)
    for name in marked:
        _, without_hop, _ = capability_table[name]
        assert "retired" in without_hop.lower(), (
            f"the runbook tells an operator not to give {name} to users on a node with "
            "no hop and does not say it has been retired, so the only way to find out is "
            "to go looking for it on a form that no longer has it"
        )
        explained = [
            block
            for block in paragraphs
            if re.search(rf"`{re.escape(name)}`", block) and "retire" in block.lower()
        ]
        assert explained, (
            f"the capability table marks {name} retired and no paragraph outside the "
            "tables both names it and says so, so the cell is a verdict with no appeal "
            "— and the operator's only way to find out what happened to a protocol they "
            "know this image ships is to go looking for it on a form that no longer "
            "has it"
        )


@pytest.fixture(scope="module")
def shapes(runbook: str) -> dict[str, str]:
    """Each ``## Shape X`` section, by its letter."""
    sections = re.findall(r"^## Shape (\w) — [^\n]*\n((?:.*\n)*?)(?=^## )", runbook, re.M)
    assert sections, "the runbook no longer describes a deployment shape"
    return {letter: body for letter, body in sections}


def test_every_hop_the_runbook_builds_is_over_a_transport_that_can_carry_one(
    shapes: dict[str, str],
) -> None:
    """The mandate half, read out of the instructions rather than out of the prose.

    ``transport = `x`` is the hop form's own field, so every occurrence of it is a
    transport an operator will type into that form — and the form offers only
    ``hop_transports()``. Plain WireGuard is the one that matters: it is a config file
    like AmneziaWG, so the shape of the advice looks right, and the hop it would build
    crosses the border it is protocol-blocked at.
    """
    offered = set(hop_transports())
    named = {
        name for body in shapes.values() for name in re.findall(HOP_FIELD, body)
    }
    assert named, "no shape builds a hop, so the topology the charter needs is undocumented"
    assert named <= offered, (
        f"the runbook builds a hop over {sorted(named - offered)}, which the panel's hop "
        "form does not offer"
    )


def test_no_shape_tells_an_operator_to_enable_a_retired_transport(
    shapes: dict[str, str]
) -> None:
    """The steps an operator actually types from, against the panel they type them into.

    The capability table is reference and the shapes are instructions, and an operator
    following Shape A at 3am reads the second — so a retired transport named there is a
    protocol they will look for on a dialog that does not list it, and then enable over
    the API because the runbook said to. The table being right is not enough.

    Over every backticked name in the shape, rather than over one instruction's phrasing:
    the runbook writes "Enable a transport: `x`" in one shape and "Enable a
    **user-facing** transport on E — `x`" in another, and a check tied to either
    sentence would be a check that a paraphrase turns green.
    """
    retired = set(retired_transports())
    if not retired:
        pytest.skip("this image retires no transport, so no shape can recommend one")

    named = {
        (letter, name)
        for letter, body in shapes.items()
        for name in retired
        if re.search(rf"`{re.escape(name)}`", body)
    }
    assert not named, (
        f"a deployment shape tells an operator to use a retired transport: {sorted(named)}. "
        "The panel does not offer it, so following that step means going round the panel."
    )


def test_no_shape_that_builds_a_hop_offers_its_users_a_kernel_tunnel(
    shapes: dict[str, str], capability_table: dict[str, tuple[str, str, str]]
) -> None:
    """The contradiction M15 was found in the field, guarded where it was written.

    A shape that builds a hop is a shape whose entry node dials one, so the transport it
    tells an operator to enable for that node's users must be one the table above marks
    yes. Checked per shape rather than per file, because the same transport is the right
    answer in Shape A — one box, no hop — and the wrong one on the box that dials a hop,
    and a check that could not tell the two apart would have to forbid the correct advice
    to catch the incorrect one.

    Each such shape must also point at the section that explains the refusal: an operator
    who reads only their own shape has to be able to get there, since that is where the
    way out of it is written.
    """
    for letter, body in shapes.items():
        if not re.search(HOP_FIELD, body):
            continue
        steps = [step for step in _numbered_steps(body) if "user-facing" in step]
        assert steps, (
            f"Shape {letter} builds a hop and never says to enable a user-facing "
            "transport, so it produces an entry node nobody can dial"
        )
        for step in steps:
            for name in _transport_names(step):
                assert _answer(capability_table[name][0]) == "yes", (
                    f"Shape {letter} names {name} where it tells an operator what to give "
                    f"the users of a node that dials a hop: {step.strip()!r}"
                )
        assert "The one combination that will not render" in _flat(body), (
            f"Shape {letter} builds a hop and does not point at the section that says "
            "which user-facing transport such a node can actually render"
        )


def test_the_orphan_exception_covers_every_extension_a_config_is_written_with(
    runbook: str,
) -> None:
    """The rendered config an operator is told to delete, named the way it is on disk.

    A rendered config takes the TRANSPORT's extension (``node_stack.EXTENSION``), so the
    WireGuard family leaves a ``.conf`` behind and the VLESS pair leaves a ``.json``. That
    is not a detail: the section carrying this exception is the one that moves an entry
    node's users onto VLESS, so the very next orphan it creates is the one a ``.conf``
    -only exception would not name — and the standing rule above it would then read as
    "never touch it", leaving a node key and every user's id on a host that can be seized.

    Both places that state the exception are checked, because an operator reads whichever
    one they reach first.
    """
    exception = re.search(
        r"^\*\*So delete it,(?:.*\n)*?(?=^### |^## )", runbook, re.M
    )
    assert exception, (
        "the runbook no longer tells an operator to delete an orphaned config, so the "
        "standing rule reads as forbidding it and the material stays on the host"
    )
    rule = re.search(
        r"^- \*\*Never edit anything under `/opt/hashi`[^\n]*\n(?:  [^\n]*\n)*", runbook, re.M
    )
    assert rule, "the runbook no longer carries the rule this exception is an exception to"

    for extension in sorted(set(EXTENSION.values())):
        for where, text in (("the exception", exception.group(0)), ("the rule", rule.group(0))):
            assert f"`.{extension}`" in text, (
                f"{where} does not name .{extension}, which is how a rendered config for "
                "one of the installed transports is written on a node"
            )

    # The target only — a trailing ``#`` comment is where the operator is told which name
    # to substitute, the same convention as the firewall rules further up this file.
    removals = re.findall(r"^rm /opt/hashi/conf/(\S+)", exception.group(0), re.M)
    assert removals, "the exception shows no command, so what to type is left to the reader"
    for target in removals:
        assert not any(target.endswith(f".{ext}") for ext in EXTENSION.values()), (
            f"the command removes {target!r}, which fixes one transport's extension into a "
            "line an operator pastes for any of them"
        )


# --- M16: a node that dials a hop needs a resolver ------------------------------------

@pytest.fixture(scope="module")
def resolver_section(runbook: str) -> str:
    """The section that says what the upgrade makes of every existing entry node."""
    section = re.search(
        rf"^## {RESOLVER_SECTION}\n(?:.*\n)*?(?=^## |^---$)", runbook, re.M
    )
    assert section, (
        "the runbook does not say that a node dialling a hop refuses to render without a "
        "resolver — the state an upgrade to M16 puts every existing entry node into, "
        "silently, until an operator reads why their revocation did not finish"
    )
    return section.group(0)


def test_the_runbook_quotes_the_refusal_a_node_without_a_resolver_gets(
    resolver_section: str,
) -> None:
    """Quoted from ``edge``, and checked against it.

    An operator searching the runbook for the words in their banner has to find these
    words; a refusal reworded in the code turns this red instead of leaving the runbook
    describing a banner that no longer reads like this. The type name is the prefix the
    banner carries, so it is checked too.
    """
    quoted = _flat(re.sub(r"^> ?", "", resolver_section, flags=re.M))
    assert _flat(NO_RESOLVER) in quoted, (
        "the runbook's quotation of the no-resolver refusal is not what edge says"
    )
    assert f"{ResolverMissing.__name__}:" in quoted


def test_the_runbook_says_to_set_it_right_after_the_upgrade_before_anything_else(
    resolver_section: str,
) -> None:
    """The instruction the migration cannot carry itself, said where an upgrader looks.

    Before the next apply AND before a revocation: from the moment the column exists, an
    entry that dials a hop cannot be rendered, so a revoked user keeps working there.
    """
    flat = _flat(resolver_section)
    for phrase in ("right after the upgrade", "before the next apply", "before you revoke"):
        assert phrase in flat, f"the resolver section no longer says {phrase!r}"


def test_the_runbook_sends_an_operator_to_an_edit_path_that_exists(
    resolver_section: str,
) -> None:
    """An instruction is only as good as the button and the route it names.

    ``Nodes → resolver`` is checked against the Nodes table's own row button — its label
    and the dialog it opens — and the API call against the API's own routes, so neither
    can be renamed without this saying so.
    """
    flat = _flat(resolver_section)
    assert "Nodes → resolver" in flat
    assert re.search(
        r'hx-get="/panel/nodes/\{\{ node\.id \}\}/resolver"[^>]*>resolver</button>',
        NODES_TABLE.read_text(),
    ), "the Nodes table has no row button labelled resolver opening the resolver dialog"
    routes = {
        (method, route.path)
        for route in api_router.routes
        for method in getattr(route, "methods", ())
    }
    assert any(
        method == "POST" and path.endswith("/nodes/{node_id}/resolver")
        for method, path in routes
    ), "the API has no POST route that sets a node's resolver"
    assert "POST /api/nodes/<id>/resolver" in flat


def test_every_shape_that_builds_a_hop_gives_its_entry_a_resolver(
    shapes: dict[str, str],
) -> None:
    """Where an operator actually registers the entry node is where they have to hear it."""
    for letter, body in shapes.items():
        if not re.search(HOP_FIELD, body):
            continue
        assert RESOLVER_SECTION in _flat(body), (
            f"Shape {letter} builds a hop and never says its entry node needs a resolver"
        )


def test_the_migration_that_empties_the_field_points_at_this_section() -> None:
    """The thing that creates the stranded state names the page that says what to do."""
    migration = next(MIGRATIONS.glob("*_a_nodes_resolver.py")).read_text()
    assert RESOLVER_SECTION in _flat(migration)


# --- M17.1c: the third thing two rows on one node collide on --------------------------
#
# The page said, twice, that a listening port and a config name were the whole list —
# "Nothing else collides". Since M17.1c ``placement.claim`` refuses a third: two
# WireGuard-family rows on one node whose tunnel networks overlap, hop ends and withdrawn
# rows included. It fires on exactly the pair this runbook mandates — Shape A's
# user-facing `amneziawg` and the hop the same box dials — so the operator met a
# refusal the page said could not exist. Read out of ``placement`` rather than described,
# for this file's usual reason: the answer compared against the prose has to be the one
# the panel really gives.


def _claim_refusals() -> set[str]:
    """The collision checks ``placement.claim`` puts in front of a new row, by name.

    By ``ast`` over ``claim``'s own source rather than by calling it: the question is
    which refusals exist, which is a property of the code, and answering it with a
    database and three rows would make this an integration test of the thing it is only
    supposed to be counting.
    """
    calls = ast.walk(ast.parse(inspect.getsource(claim)))
    return {
        node.func.id
        for node in calls
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.endswith("_is_free")
    }


def test_a_new_collision_check_cannot_be_added_without_the_page_gaining_a_sentence() -> None:
    """The list the runbook commits to is closed, so the code's list has to be pinned.

    ``claim`` refuses on a port, on a tunnel range, on the socket a delivery host's own
    listener holds (M27.6), and — by having no name left — on the config name, which is
    the one it answers with rather than the one it checks. Four, and the page says
    "Nothing else collides". A fifth check added here is a fifth thing an operator has
    to be told about, and this is what says so.

    ``delivery_socket_is_free`` is the one that proved the guard works: it was added to
    ``claim`` and this test went red in the same run, which is how the runbook gained
    the paragraph about 443 rather than going quietly false.
    """
    assert _claim_refusals() == {
        "port_is_free",
        "tunnel_network_is_free",
        "delivery_socket_is_free",
    }, (
        "placement.claim's collision checks have changed. The runbook's *Rules that are "
        "not optional* lists them for the operator and closes the list — update the "
        "bullet, then this test"
    )


def test_no_paragraph_lists_what_two_rows_collide_on_and_leaves_the_range_out(
    runbook: str,
) -> None:
    """Both places that name the first two collisions, and any third place later.

    Per paragraph rather than per section: the claim was made twice, in two sections,
    and the one that was corrected in M17.2's docs commit was not the one an operator
    following Shape A reads first.
    """
    claims = [
        paragraph
        for paragraph in re.split(r"\n[ \t]*\n", runbook)
        if "collide" in paragraph and "listening port" in _flat(paragraph)
    ]
    assert claims, (
        "no paragraph of the runbook says what two rows on one node collide on, so the "
        "operator following Shape A and then its hop has nothing to read"
    )
    for paragraph in claims:
        flat = _flat(paragraph)
        assert "config name" in flat, f"a collision paragraph omits the config name: {flat}"
        assert "range" in flat, (
            "a collision paragraph names the port and the config name and not the tunnel "
            f"range, which placement.tunnel_network_is_free also refuses: {flat}"
        )


def test_the_runbook_quotes_the_refusal_two_overlapping_tunnels_get(runbook: str) -> None:
    """Quoted from ``control``, and checked against it.

    The placeholder-free tail of the refusal — everything after the last value it names,
    so the quotation carries no node, no transport and no range of its own. An operator
    searching the page for the words in the dialog in front of them has to find them.
    """
    prose = _flat(TUNNEL_TAKEN[TUNNEL_TAKEN.rindex("}") + 1 :].strip())
    quoted = _flat(re.sub(r"^[ \t]*> ?", "", runbook, flags=re.M))

    assert prose in quoted, (
        "the runbook's quotation of the overlapping-tunnels refusal is not what control "
        "says any more"
    )


def test_the_account_change_section_does_not_instruct_a_step_with_no_surface(
    runbook: str,
) -> None:
    """M18.3's review: the section ended on "change ``ssh_user`` on the node record".

    There is no way to do that and there was none when the sentence was written.
    ``ssh_user`` is assigned once, in ``create_node``; the node POST routes are
    ``/state``, ``/resolver`` and ``/apply``; the panel's only box for it is the
    registration dialog; ``NodeResponse`` does not expose it, so the operator cannot even
    READ the value to discover the disagreement; and there is no node DELETE. An operator
    following it handed the host to a new account, left the control plane dialling the old
    one for ever, and had no repair short of editing Postgres.

    So the section has to say what cannot be done and give the repairs that exist. Pinned
    here because prose is what this diff changed and nothing else guards it — the two
    ``==>`` quotations above are the only other thing in this file that reads it.
    """
    section = re.search(
        r"^### Changing the account a node is driven as\n(?:.*\n)*?(?=^### )",
        runbook,
        re.M,
    )
    assert section, (
        "the runbook no longer has a section on changing a node's account, which is the "
        "one operation M18.3 is about"
    )
    account = section.group(0)
    assert "cannot be changed today" in account, (
        "the section does not say that `ssh_user` cannot be changed after registration, so "
        "the operator is left to discover it on a node that no longer applies"
    )
    for repair in ("register the host a second time", "`retired`"):
        assert repair in account, (
            f"the section does not give the repair that exists ({repair}) for a host whose "
            "account was changed, so the only remedy left is editing the database by hand"
        )
    assert "new node in every user's subscription" in account, (
        "the second repair is given without its cost, which is the whole fleet's links "
        "moving to cut over one host"
    )
    # And the superseded procedure fifty lines above it, which told the operator to type a
    # recursive chown on a live node, is not standing beside it saying the opposite.
    assert "chown -R" not in runbook, (
        "the runbook still tells the operator to chown the node directory by hand — the "
        "exact act the bootstrap script now performs, and the one its own comment says it "
        "exists to remove"
    )


# --- M25's second walk: the growth path, and the page that was missing ----------------
#
# The runbook offered A, B and C as a one-time choice and described no move between them.
# The move an operator makes is Shape A and then a Russian box — and Shape B, read as a
# migration, points the existing box at the entry position, which the hop form refuses.
# Of the two ways out that refusal names, removal is the one an operator reaches for, and
# removal is what destroys every user's material on that box. So the page has to name
# the other move: the box you have becomes the LEAF, and the new box becomes the entry.
#
# Everything below asks the code the same question the section answers, for this file's
# usual reason — a page of advice about what the panel will accept is worth nothing if
# the panel has stopped accepting it.


@pytest.fixture(scope="module")
def growth_section(runbook: str) -> str:
    """The section that takes an operator from one box to the charter's topology."""
    section = re.search(
        r"^## Growing out of Shape A — [^\n]*\n(?:.*\n)*?(?=^## |^---$)", runbook, re.M
    )
    assert section, (
        "the runbook describes three shapes and no move between them — so an operator who "
        "ran Shape A and then rented a Russian box has only Shape B to read, and following "
        "it destroys every credential their users are connecting on"
    )
    return section.group(0)


def _nodes_whose_offers_the_hop_form_asks_about() -> set[str]:
    """Which of ``establish_hop``'s two nodes is checked for user-facing rows.

    By ``ast`` over the function's own source, the same reading ``_claim_refusals`` takes
    of ``placement.claim``: the question is which node that refusal is about, which is a
    property of the code rather than of a database with two rows in it.
    """
    tree = ast.parse(inspect.getsource(relay.establish_hop))
    return {
        ast.unparse(argument)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "user_facing_on"
        for argument in node.args[1:]
    }


def test_the_growth_path_sends_the_box_that_already_serves_users_to_the_leaf_end(
    growth_section: str,
) -> None:
    """The whole point of the section, and the one claim it cannot be wrong about.

    An operator's first box serves users on a kernel tunnel. It can keep doing that as
    the LEAF end of a hop and cannot as the entry end, and the asymmetry is not a
    convention — ``establish_hop`` asks only the entry node what it offers its users,
    because the leaf's users exit by the leaf's own route however many hops land on it.
    If that refusal ever grew to ask the leaf as well, this advice would start costing an
    operator the credentials it exists to save, and it would do so silently.
    """
    assert _nodes_whose_offers_the_hop_form_asks_about() == {"entry_node.id"}, (
        "relay.establish_hop no longer refuses on the ENTRY node's offers alone. The "
        "runbook's growth path tells an operator their existing user-facing transport "
        "survives on the leaf end — check that is still true before touching this test"
    )
    flat = _flat(growth_section)
    assert "becomes the **leaf**" in flat, (
        "the growth path does not say plainly which box becomes the leaf, which is the "
        "one instruction it exists to give"
    )
    assert "becomes the **entry**" in flat, (
        "the growth path does not say plainly which box becomes the entry"
    )


def test_the_growth_path_quotes_what_removing_a_transport_destroys(
    growth_section: str,
) -> None:
    """Why the other way out of the refusal is the expensive one, in the panel's words.

    The refusal an operator meets offers two remedies and this page has to say which of
    them costs what. Quoted from ``console.removal_summary`` and checked against it — the
    clause up to its first full stop, which is everything the dialog says about what
    removal took and carries no node and no transport of its own. An operator who reads
    "remove that transport" and does it has destroyed every user's material on that
    box, and this is the sentence that has to be in front of them first.
    """
    summary = _flat(
        console.removal_summary("<node>", "<transport>", nothing_left_enabled=False)
    )
    cost = summary.split("— ", 1)[1].split(". ")[0]

    assert cost in _flat(re.sub(r"^[ \t]*> ?", "", growth_section, flags=re.M)), (
        "the growth path's quotation of what removal destroys is not what the panel says "
        f"any more — the remove dialog now reads {cost!r}"
    )


def test_the_growth_path_builds_a_hop_the_panel_would_actually_accept(
    growth_section: str, capability_table: dict[str, tuple[str, str, str]]
) -> None:
    """The new entry node, against the three forms the operator types it into.

    Same three questions ``test_no_shape_that_builds_a_hop_offers_its_users_a_kernel_
    tunnel`` and its neighbours ask of a shape, asked here because this section is a
    fourth set of instructions and inherits none of them: the hop form offers only
    ``hop_transports()``, a node that dials a hop can render only a user-facing
    transport the table marks yes, and such a node does not render at all without a
    resolver. A migration that ends in a refusal is worse than no migration — the
    operator has already rented the box.
    """
    flat = _flat(growth_section)

    carriers = set(re.findall(HOP_FIELD, growth_section))
    assert carriers, "the growth path never builds a hop, so it does not reach route A"
    assert carriers <= set(hop_transports()), (
        f"the growth path builds a hop over {sorted(carriers - set(hop_transports()))}, "
        "which the panel's hop form does not offer"
    )

    steps = [step for step in _numbered_steps(growth_section) if "user-facing" in step]
    assert steps, (
        "the growth path never says to enable a user-facing transport on the new entry, "
        "so it produces an entry node nobody can dial"
    )
    for step in steps:
        for name in _transport_names(step):
            assert _answer(capability_table[name][0]) == "yes", (
                f"the growth path names {name} where it tells an operator what to give the "
                f"users of the node that dials the hop: {step.strip()!r}"
            )

    assert RESOLVER_SECTION in flat, (
        "the growth path registers a node that dials a hop and never says it needs a "
        "resolver, so the first apply refuses"
    )
    assert "The one combination that will not render" in flat, (
        "the growth path does not point at the section that says which user-facing "
        "transport the node it creates can render"
    )


def test_no_paragraph_states_the_kernel_tunnel_rule_without_naming_which_end(
    runbook: str,
) -> None:
    """The rule is true of ONE end, and *Rules that are not optional* said it absolutely.

    The bullet used to state it absolutely — a kernel tunnel for a node's own users and a
    hop still cannot share a node — and it sat two bullets below a paragraph of this same
    page explaining that on a leaf they are exactly right, where an operator goes to look a
    rule up. The product's answer is the
    narrower one — ``establish_hop`` asks only the entry node what it offers its users
    — so an operator who believes the absolute version takes a transport away from a leaf
    that could have kept it, and takes every credential on it with them.

    Per paragraph, and over the whole document rather than over that section, for the
    reason the collision check above gives: the claim is the kind that gets restated
    somewhere else, and the restatement is what an operator reads first.

    ``dial`` or ``entry`` because those are the two ways this page names the end that
    cannot: a node that DIALS a hop, or the ENTRY of one. A paragraph that says neither
    is making the absolute claim, whatever words it makes it in.

    THE VERB, WORD-BOUNDED, and that is not fussiness — ``\\bdial`` also matches
    ``dialog``, which the pool bullet four lines below this rule happens to contain. The
    check passed on the absolute sentence it was written to catch.
    """
    for paragraph in _prose_paragraphs(runbook):
        if "kernel tunnel" not in paragraph:
            continue
        assert re.search(r"\b(?:dials?|dialling|dialled|entry)\b", paragraph, re.I), (
            "a paragraph says what a user-facing kernel tunnel may not share a node "
            "with and never says which end of the hop that is true of — on a leaf it is "
            f"supported and is what the growth path depends on: {paragraph}"
        )


# --- M26's first acceptance walk: what a shape leaves out ---------------------


def test_every_shape_that_adds_a_user_applies_afterwards(shapes: dict[str, str]) -> None:
    """The step the walk had to work out for itself, in the pages it worked from.

    It added a user and fetched their configuration file: complete, correct, importable
    — the node's real public key, an address out of that row's pool — while the node held
    no peer for them and their client would have handshaked into nothing. A second apply,
    three minutes later, is what made it true.

    Both shapes that add users read *"Apply … Add users"*, in that order, which is the
    right order for a node and the wrong one for a person. So a shape whose steps add a
    user has to apply AFTER it, and this asserts the order rather than the presence of the
    word: an apply above the add-user step is the version the walk followed.

    THE ORDER CHECK SKIPS A SHAPE WHOSE ADD STEP IT CANNOT RECOGNISE, so it is bracketed
    by two assertions that can fail on their own — "a verification that cannot fail" is
    this repository's signature defect and the skip is one waiting to happen. One end
    catches the specific way it would happen (a step reverting to the retired word, which
    M29 took out of this page and which this regex no longer matches); the other catches
    the general one (no shape matched at all, so nothing below ran), and is the same
    ``assert steps`` the two ``user-facing`` filters above carry for the same reason.
    """
    covered = set()
    for letter, body in shapes.items():
        steps = _numbered_steps(body)
        retired = [
            step for step in steps if re.search(r"add (?:a )?friends?\b", step, re.I)
        ]
        assert not retired, (
            f"Shape {letter} tells an operator to add a friend. The word is `user` "
            "(docs/decisions.md, 2026-09-22) — and the order check below does not "
            f"recognise this step, so it skips the shape silently: "
            f"{[step.strip() for step in retired]!r}"
        )
        adding = [
            index
            for index, step in enumerate(steps)
            if re.search(r"add (?:a )?user", step, re.I)
        ]
        if not adding:
            continue
        covered.add(letter)
        applying = [
            index
            for index, step in enumerate(steps)
            if re.search(r"\bapply\b", step, re.I)
        ]
        assert any(index > adding[0] for index in applying), (
            f"Shape {letter} adds a user and never applies afterwards, so the user it "
            "hands a link to is on no node until the operator works that out themselves"
        )
    assert covered, (
        "no shape adds a user at all, so the order this test exists to check was not "
        "checked anywhere — either the runbook stopped telling an operator to add one, "
        "or it words it in a way this no longer matches"
    )


def test_the_leaf_section_says_the_exit_codes_do_not_survive_make(
    leaf_section: str,
) -> None:
    """The walk ran the documented invocation and got make's own code for both.

    Run directly, a refusal exits 1 and a bad argument exits 2, exactly as this page says.
    Run as ``make node-bootstrap`` — which is what the page tells the operator to type —
    both come back as 2, because GNU make exits 2 whenever a recipe fails. The codes are
    right and the sentence around them was not.
    """
    said = _flat(leaf_section)
    assert "make" in said and re.search(r"does not pass them on", said, re.I), (
        "the section gives two exit codes and does not say that the invocation it "
        "documents collapses both into make's own"
    )


def test_the_control_plane_block_says_how_many_commands_it_is(runbook: str) -> None:
    """M26's first walk, its first medium: the control plane is not brought up by one
    script.

    The claim is checked against the block itself rather than believed: the number the
    prose states must be the number of commands in the fence under it, so neither can be
    edited without the other. ``&&`` counts as two, because it is two — the walk counted
    what it typed.
    """
    section = re.search(
        r"^### Bring up the control plane\n((?:.*\n)*?)^### ", runbook, re.M
    )
    assert section, "the runbook no longer has a control-plane block to count"
    body = section.group(1)

    claimed = re.search(r"\*\*This is (\d+) commands on (\d+) lines", body)
    assert claimed, (
        "the control-plane block does not say how many commands it is, so an operator "
        "reads 'one script' and meets a dozen"
    )
    fence = re.search(r"```bash\n((?:.*\n)*?)```", body)
    assert fence, "the control-plane section no longer has a command block"
    lines = [
        line.split("#")[0].strip()
        for line in fence.group(1).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    commands = sum(len(line.split("&&")) for line in lines)

    assert (int(claimed.group(2)), int(claimed.group(1))) == (len(lines), commands), (
        f"the block is {len(lines)} lines and {commands} commands, and the page claims "
        f"{claimed.group(2)} and {claimed.group(1)}"
    )
    assert "panel-bootstrap.sh` is one of them" in _flat(body), (
        "the page does not say which of those commands the charter's second script is"
    )


def test_the_prerequisites_name_what_the_control_plane_box_needs(runbook: str) -> None:
    """A genuinely bare host had none of them, and this section listed none of them.

    The walk needed a container runtime, ``git`` and ``make`` before the first line of
    that block, and met each one as an error message instead of as a line on this page.
    """
    section = re.search(
        r"^### What every box must already have\n((?:.*\n)*?)(?=^#{2,3} )", runbook, re.M
    )
    assert section, "the runbook no longer says what a box must already have"
    said = _flat(section.group(1))
    for needed in ("git", "make"):
        assert re.search(rf"`{needed}`", said), (
            f"the prerequisites do not name {needed}, which the control-plane block needs "
            "before its first command"
        )
    assert re.search(r"control.plane box", said, re.I), (
        "the section answers for a node only, and the control-plane box is not a node"
    )


@pytest.fixture(scope="module")
def retention_section(runbook: str) -> str:
    """M28.4's section: the half of the protection that is not on this host at all."""
    section = re.search(
        rf"^### {re.escape(RETENTION_SECTION)}\n((?:.*\n)*?)(?=^#{{2,3}} )", runbook, re.M
    )
    assert section, (
        "the runbook no longer says what retention the backup bucket must have — which "
        "leaves a write-only key against a bucket that keeps one overwritable copy"
    )
    return section.group(1)


def _table_rows(section: str) -> list[list[str]]:
    """The decision table's data rows, as cells. Header and separator dropped."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|") and set(line) - set("|- ")
    ]
    assert rows, "the section carries no table"
    return rows[1:]


def test_the_retention_section_settles_the_three_rather_than_offering_them(
    retention_section: str,
) -> None:
    """The plan offered versioning, object lock and a lifecycle rule as a choice.

    They are not one: the first is the defence, the second an upgrade to it, the third the
    thing being defended against. A page that lists all three with no verdict reads as
    "pick whichever your store has", and the store that has only the third is then set up
    with a rule that deletes the history on a timer and nothing that keeps it.
    """
    rows = _table_rows(retention_section)
    verdicts = {row[0].lower(): row[1] for row in rows}
    for mechanism in ("versioning", "object lock", "lifecycle"):
        matched = [name for name in verdicts if mechanism in name]
        assert len(matched) == 1, f"the table has no single row for {mechanism}: {matched}"

    versioning = next(v for name, v in verdicts.items() if "versioning" in name)
    assert "required" in versioning.lower(), (
        f"versioning is not stated as required — it reads {versioning!r}, and every other "
        "row on this page assumes it is on"
    )
    lifecycle = next(v for name, v in verdicts.items() if "lifecycle" in name)
    assert "not a retention mechanism" in lifecycle.lower(), (
        f"the lifecycle row reads {lifecycle!r}, which lets a rule that deletes on a "
        "schedule be mistaken for one that keeps things"
    )


def test_the_retention_section_denies_that_the_object_name_is_the_defence(
    retention_section: str,
) -> None:
    """The plausible wrong answer, and it is already half true, which is what makes it bad.

    ``hashi-<timestamp>.sql.gz.age`` does stop two runs colliding. It stops nothing else:
    the uploading credential picks the name, so it can write yesterday's name, and a bucket
    with no versioning keeps whatever was written last.
    """
    said = _flat(retention_section)
    assert "hashi-<timestamp>" in said, (
        "the section does not say what the object is called, so a reader cannot tell "
        "whether the naming is doing the work"
    )
    assert "by mistake" in said and "on purpose" in said, (
        "the section does not separate what the naming defends against from what "
        "versioning defends against"
    )


def test_the_retention_section_gives_a_check_this_host_cannot_run_for_them(
    retention_section: str,
) -> None:
    """A retention that has only been described is worth nothing, and cannot be tested here.

    The credential on this host writes and does nothing else, so the check has to be run by
    the owner from somewhere else — and the page has to say that this repository will never
    run it, or ``make verify`` passing reads as the bucket being configured.
    """
    said = _flat(retention_section)
    for call in (
        "GetBucketVersioning",
        "GetObjectLockConfiguration",
        "GetBucketLifecycleConfiguration",
        "ListObjectVersions",
    ):
        assert call in said, (
            f"the section does not name {call}, so the operator is left to find the check "
            "in a console whose wording differs from every other store's"
        )
    assert "No test in this tree asserts any of the above" in said, (
        "the section does not say that nothing here proves the retention is on, which is "
        "the sentence that keeps a green `make verify` from being read as one"
    )


def test_the_retention_section_names_no_provider(retention_section: str) -> None:
    """CLAUDE.md's rule, in the one section most likely to break it.

    Retention is configured in somebody's console, and a console path is the shape a
    provider name arrives in: it reads as helpful and is indistinguishable, later, from a
    requirement. The protocol calls above are the general form and every store answers
    them.
    """
    providers = re.compile(
        r"aws|amz|amazon|google|azure|cloudflare|backblaze|wasabi|yandex|selectel|minio",
        re.IGNORECASE,
    )
    found = providers.findall(retention_section)
    assert found == [], f"the retention section names {sorted(set(found))}"
    assert not re.search(r"[a-z]+://", retention_section), (
        "the retention section carries a URL — the store is a field, not an address"
    )
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", retention_section), (
        "an IP address is hardcoded in the retention section"
    )


def test_the_env_file_sends_the_operator_to_the_section_that_decides_retention(
    runbook: str,
) -> None:
    """The comment beside the write-only key cannot carry the whole decision, so it points.

    An anchor by exact title, the same way M16's resolver section is pointed at: rename the
    heading and this fails, rather than leaving a comment that directs an operator to a
    section that is no longer there.
    """
    # The comment wraps, and a wrapped title is still a pointer: the `#` that opens each
    # continuation line is dropped before the phrase is looked for.
    env = ENV_EXAMPLE.read_text()
    said = _flat(re.sub(r"\n#", " ", env))
    assert RETENTION_SECTION in said, (
        "`.env.example` does not point at the section that decides the bucket-side "
        "retention, so the credential comment is the only account of it an operator sees"
    )
    assert f"### {RETENTION_SECTION}" in runbook, "the section it points at is gone"
    assert "VERSIONING" in said, (
        "the comment beside the write-only key does not name the mechanism that makes "
        "write-only stick, so the key reads as sufficient on its own"
    )
