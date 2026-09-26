"""Retiring a transport, and everything retiring one must NOT do — M20.

WHAT: the ``Retirement`` declaration: that a transport carrying one is still
      discovered, still loadable, still renders, and still holds every other
      declaration it had; that a retirement with no reason is refused at discovery;
      and that this image ships one, whose measured defect is the reason it exists.
WHY:  a protocol that cannot carry a user's traffic must stop being suggested, and the
      only other way to do that is a name compared in the panel — which is the branch
      the registry exists to prevent. The declaration is the alternative, so what it
      does and what it deliberately leaves alone both have to be pinned: a retirement
      that quietly removed the package would turn every test parametrised over the
      WireGuard family into a single-case test, and lose the guard against `control`
      learning a protocol's name.
HOW:  pure calls over ``discover()`` and ``profile()``. No Docker, no database, no
      network. The reason itself is prose and is not asserted word for word — what is
      asserted is that there IS one, because a package the panel never offers with no
      explanation on disk is the reader this field exists for.
"""

from dataclasses import replace

import pytest

from edge.registry import (
    ConfigFormat,
    ContractViolation,
    Retirement,
    _check_declaration,
    discover,
    profile,
)

INSTALLED = discover()

RETIRED = sorted(name for name, meta in INSTALLED.items() if meta.retired is not None)

# The two members of the wg-quick family, derived from the config format for the same
# reason every other list here is: the property is about the data plane, not about a
# protocol's name.
KERNEL_TUNNELS = sorted(
    name
    for name, meta in INSTALLED.items()
    if meta.config_format in {ConfigFormat.WG_QUICK, ConfigFormat.WG_QUICK_PLAIN}
)


def test_this_image_ships_a_retired_transport() -> None:
    """Non-vacuity for every parametrised test below, stated once and out loud.

    An image with nothing retired would pass the whole of this file by having nothing
    to check, which is the shape the plan calls a verification that cannot fail.
    """
    assert RETIRED, (
        "no transport in this image declares itself retired, so every assertion here "
        "about what retirement does is vacuous"
    )


def test_the_family_member_measured_unusable_is_the_one_retired() -> None:
    """The declaration itself, pinned by name — the one place a name belongs.

    Everything else in this repository asks the registry rather than naming a protocol;
    this test is the opposite on purpose, because the thing being pinned is a fact about
    ONE package, measured on a live node twice. Without it the declaration could be
    deleted and nothing at all would go red: every other test here derives its subject
    from ``discover()`` and would simply check nothing.

    The sibling half matters as much: retiring one member of a family must not retire
    the family, or the fleet has no kernel tunnel to offer at all.
    """
    assert "wireguard" in RETIRED, (
        "plain WireGuard is offered again. Its pinned data plane writes forwarding "
        "rules on a netfilter backend the host firewall's default-deny policy does not "
        "share, so a user handshakes and carries nothing — measured twice on a live "
        "node. If that has been fixed, the fix is an image pin or backend-aware rules, "
        "and this test is the record of what has to be true first."
    )
    assert INSTALLED["amneziawg"].retired is None, (
        "the obfuscated member of the family is retired too, which leaves the fleet "
        "with no kernel tunnel it may offer anybody"
    )


def test_retiring_one_member_does_not_reduce_the_family_to_one_case() -> None:
    """Done-when 4, as arithmetic — the reason the package stays in the tree.

    ``AmbiguousPeerRoute`` is asserted in each package, and the contract tests iterate
    every installed transport. Both are parametrised, so deleting the retired package
    would not fail anything: the same files would keep passing over one member and the
    guard against a hardcoded protocol name would be gone with no test to say so.
    """
    assert len(KERNEL_TUNNELS) >= 2, (
        f"the wg-quick family is down to {KERNEL_TUNNELS}, so every test parametrised "
        "over it now proves one implementation rather than a contract"
    )
    assert any(INSTALLED[name].retired is not None for name in KERNEL_TUNNELS)
    assert any(INSTALLED[name].retired is None for name in KERNEL_TUNNELS)


@pytest.mark.parametrize("name", RETIRED)
def test_a_retired_transport_states_a_reason(name: str) -> None:
    """A package the panel never offers, explained where it is declared.

    Asserted as prose rather than word for word: what must not happen is a reason that
    is a label — "retired", "broken" — because the reader this field exists for is
    someone who has just found a package in the tree that nothing proposes, and a label
    sends them to ``git log`` exactly as an empty field would.
    """
    reason = INSTALLED[name].retired.reason
    assert reason == reason.strip() and len(reason.split()) >= 10, (
        f"{name} is retired with {reason!r}, which is a label rather than an answer"
    )


@pytest.mark.parametrize("name", RETIRED)
def test_a_retired_transport_is_still_discovered_and_still_renders(
    name: str, node, transport_fixture
) -> None:
    """The half of this milestone that is about NOT breaking anything.

    The owner's leaf runs a row of one of these today. Retirement removes the transport
    from what the panel proposes and from nothing else, so discovery, ``profile()``, the
    renderers and the bytes they produce are all untouched — the golden files in
    ``tests/edge/golden/`` are the byte-for-byte half of this claim and did not move.
    """
    transport = profile(name)
    assert transport.meta.retired is not None

    validated = transport.validate(transport_fixture(name, "params"))
    config = transport.profile.render_server(
        node, validated, transport_fixture(name, "credentials")[:1]
    )
    assert config.strip(), f"{name} is retired and now renders nothing"
    assert transport.meta.subscription_formats, (
        f"{name} lost its user-facing format when it was retired, so the user who "
        "already holds one could not be handed a replacement"
    )


def test_a_retirement_with_no_reason_is_refused_at_discovery() -> None:
    """The refusal provoked rather than assumed — the only shape this field can take
    that says less than saying nothing.

    ``Retirement("")`` is the accident a plain ``str | None`` could not tell from the
    ordinary case, and it is why this declaration is a type: a transport would vanish
    from every chooser in the panel and leave no sentence anywhere saying why.
    """
    meta = replace(INSTALLED[sorted(INSTALLED)[0]], retired=Retirement(reason="   "))
    with pytest.raises(ContractViolation) as refused:
        _check_declaration("any-package", meta)
    assert "reason" in str(refused.value)


def test_a_retirement_that_states_a_reason_is_accepted() -> None:
    """The other side of the same check, so it cannot refuse everything and pass."""
    meta = replace(
        INSTALLED[sorted(INSTALLED)[0]],
        retired=Retirement(reason="measured on a live node: it carries nothing"),
    )
    assert _check_declaration("any-package", meta) is meta
