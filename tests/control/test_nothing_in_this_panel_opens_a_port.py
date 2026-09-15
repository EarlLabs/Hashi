"""The panel picks a port and nothing opens it, so it says so — M23, round 2.

WHAT: the three places the operator meets a port number — the enable dialog, the
      Transports screen's range column, and the probe's own good-news sentence.
WHY:  measured on the owner's real leaf on 2026-09-15. ``amneziawg`` was enabled on
      ``51930``, applied, and every reading was green: the node read ``active / in sync``
      and the probe read *"is listening"*. The client sent 12 479 bytes and received none,
      and no handshake ever completed — the host's ``ufw`` allows three other numbers, and
      none of the eight commands an apply runs on a node is a firewall command.

      This is M14's shape, which the charter names as the failure that hurts most: every
      signal green, nothing carried. The product cannot close it by checking, and that is
      the decision this file records rather than a gap it leaves open:

      * **apply cannot open the port.** It logs in as a deliberately unprivileged account
        (M13), and the provider's own firewall is not on the host at all — so a control
        plane that "opened the port" would be a fifth green signal over the same silence.
      * **the panel cannot refuse one.** Nothing in this control plane knows which ports a
        host was prepared with; a node never dials us and nothing reads the host's
        firewall. A refusal built on a guess turns away a port that is open.
      * **the probe cannot see it.** ``ss`` on the node answers what is BOUND, which is
        the whole of what it may claim — a socket behind a closed firewall reads exactly
        like a working one.

      So what the product owes is the sentence, in the places the number is chosen and
      read, and a probe that does not let "is listening" be read as "a user can connect".
HOW:  the panel's own screens, rendered. No host is dialled and nothing here proves a
      packet arrives — that is the field's, and it is item 2 of this milestone's walk.
"""

from control.app.services import console

# What a port number costs beyond this panel, in the words all three surfaces share: the
# script that opens one on a host, which is the product's own and takes the same number
# the operator typed here.
THE_SCRIPT = "scripts/node-bootstrap.sh"


async def said_on(client, path: str) -> str:
    """One screen's text as running words, since every sentence here wraps in markup."""
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return " ".join(response.text.split())


async def test_the_enable_dialog_says_nothing_here_opens_a_port(client) -> None:
    """At the moment the number is chosen, which is the only moment it is actionable.

    Red against the previous commit: the dialog explains what apply does to the host and
    says nothing about the one thing it does not do.
    """
    created = await client.post(
        "/api/nodes",
        json={"name": "leaf-nl", "address": "192.0.2.60", "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text

    said = await said_on(client, f"/panel/nodes/{created.json()['id']}/transports")

    assert "Nothing here opens a port" in said, said
    assert THE_SCRIPT in said, said
    # The failure shape, named — because "open the port" is advice an operator has read
    # before, and what they have not read is that skipping it looks like success here.
    assert "looks exactly like a working transport" in said, said
    # And the layer this product cannot reach at all.
    assert "provider" in said, said


async def test_the_transports_screen_says_what_its_port_column_is_not(client) -> None:
    """The range is what a protocol accepts, not what a host will let through.

    The walk read ``udp 1024–65535`` on this screen and chose a number inside it. Both
    facts are true and the screen only carried one of them.
    """
    said = await said_on(client, "/panel/transports")

    assert "not what a host will let through" in said, said
    assert THE_SCRIPT in said, said


def test_the_probe_says_it_cannot_see_a_firewall() -> None:
    """The sentence that must not be read as "a user can connect".

    "Not dialled from outside" was already true and was read as a formality. Naming the
    two layers is the difference between a caveat and a caveat an operator acts on: a
    bound socket behind a closed firewall is exactly the reading this probe must not be
    taken to disprove.

    Asserted on the constant rather than through a probe, because it is the WORDING that
    was found wanting; ``test_a_probe_says_what_it_checked.py`` is what pins that this
    sentence reaches the healthy answer at all.
    """
    said = console.WHAT_A_PROBE_CANNOT_SEE

    assert "not dialled from outside" in said, said
    assert "firewall" in said, said
    assert "security group" in said, said
