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
from control.app.services.placement import TUNNEL_TAKEN, claim
from control.app.services.transports import hop_transports
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

# M16's section, by its exact title: the shapes that build a hop and the migration that
# empties the field both point at it by these words.
RESOLVER_SECTION = "A node that dials a hop needs a resolver"

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

    The script's lines are compared with its two shell variables expanded the way the run
    expands them, because M13 gave the closing lines a path and an account name that are
    values rather than words. The substitution is the runbook's own convention for a
    transcript of output — angle brackets — and nothing else here is normalised: a
    reworded sentence is still a reworded sentence.
    """
    as_the_operator_sees_it = script.replace("${NODE_ROOT}", "/opt/hashi").replace(
        "${TARGET_USER}", "<user>"
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
        "ufw logging was already off",
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
# the friends of the box that dials it, and nothing anywhere compared the two claims
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
    calls ``wg_quick_egress`` hands a friend's packets to the node's routing table and is
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
        "the runbook no longer states which transport may serve friends on a node that "
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


def test_the_table_agrees_with_the_code_about_friends_on_a_node_that_dials_a_hop(
    capability_table: dict[str, tuple[str, str, str]],
) -> None:
    """M15.3's whole subject, checked against ``edge`` rather than against memory.

    A friend-facing transport on a node whose way out is a hop must terminate the
    connection and originate its own; one whose packets the kernel routes is accepted by
    the panel and refused by ``edge/egress.py`` at apply. The table says which is which,
    and this is what stops it saying it wrongly.
    """
    for name, (with_hop, _, _) in capability_table.items():
        expected = "no" if _egress_expression(name) == "kernel" else "yes"
        assert _answer(with_hop) == expected, (
            f"the runbook says {name} is {_answer(with_hop)!r} for the friends of a node "
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


def test_the_table_offers_friends_only_a_transport_they_could_receive(
    capability_table: dict[str, tuple[str, str, str]],
) -> None:
    """The column for a node with no hop, against the rule that governs it.

    ``nodes.enable_transport`` refuses a transport that declares no format a friend's
    client can consume, so a yes here for such a transport is advice the panel rejects.
    """
    installed = discover()
    for name, (_, without_hop, _) in capability_table.items():
        expected = "yes" if installed[name].subscription_formats else "no"
        assert _answer(without_hop) == expected, (
            f"the runbook says {name} is {_answer(without_hop)!r} for the friends of a "
            f"node with no hop, and its declared delivery formats say {expected!r}"
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


def test_no_shape_that_builds_a_hop_offers_its_friends_a_kernel_tunnel(
    shapes: dict[str, str], capability_table: dict[str, tuple[str, str, str]]
) -> None:
    """The contradiction M15 was found in the field, guarded where it was written.

    A shape that builds a hop is a shape whose entry node dials one, so the transport it
    tells an operator to enable for that node's friends must be one the table above marks
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
        steps = [step for step in _numbered_steps(body) if "friend-facing" in step]
        assert steps, (
            f"Shape {letter} builds a hop and never says to enable a friend-facing "
            "transport, so it produces an entry node nobody can dial"
        )
        for step in steps:
            for name in _transport_names(step):
                assert _answer(capability_table[name][0]) == "yes", (
                    f"Shape {letter} names {name} where it tells an operator what to give "
                    f"the friends of a node that dials a hop: {step.strip()!r}"
                )
        assert "The one combination that will not render" in _flat(body), (
            f"Shape {letter} builds a hop and does not point at the section that says "
            "which friend-facing transport such a node can actually render"
        )


def test_the_orphan_exception_covers_every_extension_a_config_is_written_with(
    runbook: str,
) -> None:
    """The rendered config an operator is told to delete, named the way it is on disk.

    A rendered config takes the TRANSPORT's extension (``node_stack.EXTENSION``), so the
    WireGuard family leaves a ``.conf`` behind and the VLESS pair leaves a ``.json``. That
    is not a detail: the section carrying this exception is the one that moves an entry
    node's friends onto VLESS, so the very next orphan it creates is the one a ``.conf``
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
# friend-facing `amneziawg` and the hop the same box dials — so the operator met a
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

    ``claim`` refuses on a port, on a tunnel range and — by having no name left — on the
    config name, which is the one it answers with rather than the one it checks. Three,
    and the page says "Nothing else collides". A fourth check added here is a fourth
    thing an operator has to be told about, and this is what says so.
    """
    assert _claim_refusals() == {"port_is_free", "tunnel_network_is_free"}, (
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
