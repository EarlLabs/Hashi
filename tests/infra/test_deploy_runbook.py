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

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"
SCRIPT = REPO / "scripts" / "node-bootstrap.sh"
TUNNEL_SCRIPT = REPO / "scripts" / "management-tunnel.sh"
PANEL_SCRIPT = REPO / "scripts" / "panel-bootstrap.sh"
CADDYFILE = REPO / "deploy" / "caddy" / "Caddyfile"

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
        "/opt/hashi was already here — its contents were left alone, and <user> owns the "
        "directory",
        "/opt/hashi was already here before this run — whatever an earlier apply left in "
        "it, this run neither changed nor removed it, only re-asserted that <user> owns "
        "the directory",
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
