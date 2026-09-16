"""The charter's deployment claims, checked against the two scripts — M26.

WHAT: static checks over ``docs/product/charter.md``'s *one script per host* section and
      the two scripts it describes.
WHY:  the charter said node bootstrap brings a host *"from a bare host to serving
      traffic"* and that a run *"ends by checking the daemon accepts its own config and
      the node answers a health probe"*. An independent acceptance walk measured both on
      bare hosts on 2026-09-16: the node script ends at a prepared host and says so, at
      which point ``/opt/hashi`` is empty — no daemon, no config, nothing to probe — and
      serving traffic is three panel actions further on. The health-probe promise was
      true of the OTHER script all along.

      Nothing held the charter to the product, so the sentence outlived the walk that
      disproved it by a whole milestone. This is what holds it: the page's own quotations
      must exist in the scripts, and the promise it makes about verification must belong
      to the script that makes it.
HOW:  the files are read, never run. Same division as ``test_deploy_runbook.py``: nothing
      here proves a script works, it proves the charter cannot quietly claim something no
      script does.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CHARTER = REPO / "docs" / "product" / "charter.md"
NODE_SCRIPT = REPO / "scripts" / "node-bootstrap.sh"
PANEL_SCRIPT = REPO / "scripts" / "panel-bootstrap.sh"


@pytest.fixture(scope="module")
def charter() -> str:
    return CHARTER.read_text()


@pytest.fixture(scope="module")
def deployment(charter: str) -> str:
    """The section that says what the two scripts deliver, and nothing else."""
    section = re.search(
        r"^\*\*One script per host\.\*\*(?:.*\n)*?(?=^## )", charter, re.M
    )
    assert section, (
        "the charter no longer states what its deployment scripts deliver, so nothing "
        "here can be checked against them"
    )
    return section.group(0)


def flat(text: str) -> str:
    """``text`` with its line wrapping collapsed, so a phrase can be looked for at all."""
    return " ".join(text.split())


def test_the_node_script_row_does_not_promise_a_serving_host(deployment: str) -> None:
    """The measured sentence, and the one this milestone exists to retire.

    A bare host reaches *serving traffic* after one command and THREE panel actions —
    register the node, offer it a transport, apply — and a friend's packets move after
    five. The script is honest about this; the page was not.
    """
    row = re.search(r"^\| node bootstrap \|[^\n]*$", deployment, re.M)
    assert row, "the charter's script table no longer has a row for the node script"
    said = flat(row.group(0))
    assert "serving traffic" not in said, (
        "the charter again promises that the node script brings a host to serving "
        "traffic, which is one command and three panel actions apart"
    )
    assert "a host the control plane can drive" in said, (
        "the charter no longer says what the node script does deliver"
    )
    # The retired sentence may still be QUOTED in the prose below, which is how the page
    # explains what it narrowed — the row is where the claim is made.


def test_the_charter_quotes_the_line_the_node_script_actually_ends_on(
    deployment: str,
) -> None:
    """The script's closing seam, extended to a third file.

    ``docs/deploy/runbook.md`` already quotes these two lines and ``test_deploy_runbook``
    holds it to them, so the page and the terminal cannot drift. The charter now makes a
    claim about the same moment — that the run ends by printing what to type into the
    panel — and it is held the same way: by the script's own words.
    """
    script = NODE_SCRIPT.read_text()
    quoted = "register it in the panel"
    assert quoted in script, "the script no longer tells the operator to register the node"
    assert quoted in flat(deployment), (
        "the charter claims the run ends by printing what to type into the panel without "
        "quoting the line it prints, so a rewording of either would go unnoticed"
    )


def test_the_health_probe_promise_belongs_to_the_script_that_makes_it(
    deployment: str,
) -> None:
    """The promise is kept — by ``panel-bootstrap.sh``, and the charter now says so.

    That script asks the control plane it has just installed for ``/healthz`` and for a
    delivery route, from inside the compose network, and refuses if neither answers within
    its window. The walk proved it by breaking the stack: exit 1, and a sentence naming
    the timeout. So the bullet is narrowed rather than deleted — it was never wrong about
    this script.
    """
    panel = PANEL_SCRIPT.read_text()
    assert "/healthz" in panel and re.search(r"^until probe; do", panel, re.M), (
        "the panel script no longer waits for the control plane before reporting success, "
        "which is the charter's verification promise"
    )

    said = flat(deployment)
    probe = re.search(r"The panel script ends by[^.]*\.", said)
    assert probe, "the charter does not say which script makes the health check it claims"
    assert "/healthz" in probe.group(0), probe.group(0)


def test_the_charter_says_the_node_script_has_nothing_to_probe(deployment: str) -> None:
    """The reason the promise was never true of the node script, stated rather than dropped.

    When the run finishes, ``/opt/hashi`` is empty: the script installs no hashi code and
    no hashi state, and everything that ever lands there is rendered by the control plane
    and pushed on the first apply. There is no daemon to accept a config and nothing to
    answer a probe — which is a fact about the ORDER of this product, not a gap in the
    script.
    """
    script = NODE_SCRIPT.read_text()
    assert "no hashi code and no hashi state was installed here" in script, (
        "the node script no longer says it installs nothing, so the charter's reason for "
        "expecting no daemon on that host is gone"
    )
    said = flat(deployment)
    assert re.search(r"no daemon to ask", said) or re.search(
        r"has no daemon to ask", said
    ), "the charter does not say why the node script probes nothing"
    assert "`/opt/hashi` is empty" in said, (
        "the charter states the consequence without the fact it rests on"
    )


def test_the_charter_counts_what_the_walk_counted(deployment: str) -> None:
    """The narrowing is a measurement, not a hedge — so the numbers are on the page.

    Each row of that table is a count the walk took on bare hosts, and the one that
    matters most is the fifth: a friend's packets move after FIVE panel actions, because
    adding a user is a change no node has been told about until the next apply.
    """
    said = flat(deployment)
    assert "| bare host → a node **serving** | 1 | 3 —" in said, (
        "the charter no longer counts what it takes to get a node serving"
    )
    assert "apply again" in said, (
        "the charter's count omits the second apply, which is the step a friend's traffic "
        "does not move without"
    )
    assert "is not brought up by one script" in said, (
        "the charter still reads as though the control plane were one script; it is 13 "
        "commands, of which the script is one"
    )


def test_no_success_criterion_says_the_panel_bootstraps_a_node(charter: str) -> None:
    """M26's SECOND acceptance walk, one screen above the section written to fix this.

    Criterion 2 read *"when I destroy it and bootstrap a replacement FROM THE PANEL"*.
    The panel bootstraps nothing: ``scripts/node-bootstrap.sh`` is run over SSH from the
    machine holding the fleet's key pair, and it ends by printing what the operator then
    types into the panel. Round 1 narrowed the deployment section and left the criterion
    that section references standing, so the page corrected itself and went on
    overstating the product two hundred lines higher up.

    Asserted over the SUCCESS CRITERIA, not the whole file, because the rest of the page
    may quote the old wording to say it was wrong — which is exactly what the criterion
    does now.
    """
    criteria = re.search(r"^## Success criteria$(?:.*\n)*?(?=^## )", charter, re.M)
    assert criteria, "the charter no longer has a success-criteria section"

    for line in criteria.group(0).splitlines():
        if line.lstrip().startswith(("This used to read", ">")):
            # The correction's own account of what it corrected. It has to be able to
            # quote the sentence it retired, or the page cannot say what changed.
            continue
        assert "bootstrap a replacement from the panel" not in line, (
            f"a success criterion says the panel bootstraps a node, and it does not: "
            f"{line.strip()!r}"
        )


def test_the_criterion_names_the_script_that_does_the_bootstrapping(charter: str) -> None:
    """The accept direction: replacing the false claim with nothing would be worse.

    An operator reading criterion 2 has to be able to find out what to actually run, and
    the answer is a file in this repository — so the criterion names it, and this test
    fails if that file is ever renamed without the charter following.
    """
    criteria = re.search(r"^## Success criteria$(?:.*\n)*?(?=^## )", charter, re.M)
    assert criteria
    replaceable = re.search(
        r"^2\. \*\*A node is replaceable in ten minutes\.\*\*(?:.*\n)*?(?=^\d\. )",
        criteria.group(0),
        re.M,
    )
    assert replaceable, "the charter no longer states criterion 2 in the expected shape"

    named = flat(replaceable.group(0))
    assert "scripts/node-bootstrap.sh" in named, (
        "criterion 2 no longer says what an operator runs to replace a node"
    )
    assert NODE_SCRIPT.exists(), (
        "the charter names a bootstrap script this repository does not ship"
    )
