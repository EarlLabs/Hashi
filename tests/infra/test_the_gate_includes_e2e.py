"""Something has to run tests/e2e — M6.6.

WHAT: that a named gate exists which boots a stack and runs the acceptance scenarios,
      that CI runs it, and that ``make test`` still does not.
WHY:  nothing ran ``tests/e2e`` at all. ``make test`` excludes it deliberately — a gate
      that silently needs Docker is a gate agents skip — and CI ran the same three zone
      targets, so the exclusion was total. ``tests/e2e/infra/test_panel_bootstrap.py``
      failed for as long as it had existed and was found by accident, eleven milestones
      later, by somebody running it for an unrelated reason.
HOW:  reads the Makefile and the workflow. Nothing here runs either: whether the gate
      passes is what the gate is for, and asserting it here would mean this file booting a
      stack every time somebody ran ``make test-infra``.

The property being protected is narrow and worth stating exactly: **the absence of the
e2e tier must not be able to look like success.** Both halves of that matter — a gate that
skips when Docker is missing fails it just as badly as no gate at all.
"""

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
CLAUDE_MD = REPO / "CLAUDE.md"


@pytest.fixture(scope="module")
def makefile() -> str:
    return MAKEFILE.read_text()


def recipe(makefile: str, target: str) -> str:
    """The lines of one target: its dependencies plus every tab-indented line under it."""
    match = re.search(
        rf"^{re.escape(target)}:([^\n]*)\n((?:(?:\t|#)[^\n]*\n|\n(?=\t))*)", makefile, re.M
    )
    assert match, f"there is no `make {target}`"
    return match.group(1) + "\n" + match.group(2)


def test_there_is_one_target_that_answers_is_this_green(makefile: str) -> None:
    """A single verb that includes the acceptance tier, so "green" has one meaning."""
    gate = recipe(makefile, "verify")
    assert "test" in gate, "the gate does not include the static zones"
    assert "e2e" in gate, (
        "`make verify` does not reach the acceptance tier, which leaves the gate exactly "
        "where it was: three static zones and nothing that boots anything"
    )


def test_the_e2e_half_fails_loudly_when_there_is_no_engine(makefile: str) -> None:
    """The failure mode that dug the hole: an absent engine must not read as a pass.

    A ``pytest.skip`` or a silent ``|| true`` here would be worse than no gate, because a
    skipped tier reports green and nobody looks again.
    """
    half = recipe(makefile, "e2e-verify")
    assert "docker info" in half, (
        "the e2e gate does not check for a running engine, so on a machine without one it "
        "fails somewhere further in with a message about something else"
    )
    assert "exit 1" in half, "a missing docker engine does not fail the gate"
    assert "e2e-up" in half and "test-e2e" in half, (
        "the gate does not boot a stack and run the scenarios against it"
    )
    assert "e2e-down" in half, (
        "the gate leaves the stand and its volumes behind, so the next run inherits state "
        "from the last failure"
    )


def test_make_test_still_needs_no_docker(makefile: str) -> None:
    """The constraint this fix must not trample, stated as a test.

    Folding e2e into ``make test`` was the obvious repair and is the wrong one: a `make
    test` that fails on a laptop with the daemon stopped is a `make test` people route
    around, which is how the hole was dug in the first place. ``test`` keeps its meaning;
    ``verify`` is the bigger claim, under its own name.
    """
    static = recipe(makefile, "test")
    assert "e2e" not in static, (
        "`make test` now needs a docker engine — it is the target every zone job and every "
        "agent runs, and it has to keep meaning 'the part that needs nothing'"
    )


def test_ci_runs_the_acceptance_tier() -> None:
    """And visibly: an advisory job is a green tick with an annotation nobody opens."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    jobs = workflow["jobs"]

    runners = [
        (name, job) for name, job in jobs.items()
        if any(
            "e2e" in str(step.get("run", "")) for step in job.get("steps", [])
        )
    ]
    assert runners, (
        "no CI job runs the acceptance scenarios, so tests/e2e is again a suite nothing "
        "executes — which is the entire finding this test exists for"
    )
    for name, job in runners:
        assert not job.get("continue-on-error"), (
            f"the {name} job cannot fail the build, so a red scenario reports green"
        )
        for step in job.get("steps", []):
            assert not step.get("continue-on-error"), (
                f"a step of the {name} job swallows its own failure"
            )


def test_the_gate_is_written_down_where_a_reader_finds_it(makefile: str) -> None:
    """A verb nobody is told about is a verb nobody runs, which is this bug again."""
    assert "make verify" in CLAUDE_MD.read_text(), (
        "CLAUDE.md's Commands section does not name the gate, so the next reader learns "
        "it from an incident instead"
    )
