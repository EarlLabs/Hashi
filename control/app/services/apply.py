"""Rendering a node's configuration and pushing it — backlog item 14.

WHAT: ``apply_node`` (render every enabled transport, validate, push, restart,
      verify) and ``apply_many`` (do that for a set of node-transports).
WHY:  this is the half of criterion 6 that the database cannot do. Deleting a
      user's credential rows changes what we WOULD render; until the new config
      reaches every node, the running daemon still authorises them. It is also the
      half of criterion 2 that makes a replacement node real rather than recorded.
HOW:  the order is the contract, and every step exists because skipping it produces
      a specific failure:

      1. render from the database (pure, deterministic);
      2. validate with the upstream checker — never push a config the daemon will
         reject, because it restarts into a crash loop and the node is down;
      3. place the config and the compose file;
      4. restart;
      5. verify the daemon came back ON THIS CONFIG and STAYED up — not merely that a
         container exists, which is what M1 proved says nothing, and not one sample of
         it either, which is what M26's second acceptance walk proved says nothing (see
         ``services/serving``);
      6. record the digest, so drift is detectable afterwards.

      Any failure from step 3 onward marks the node DEGRADED, never active — core
      invariants §4. A node that is half-configured and reported as fine gets
      users routed onto it, and the bug report is about their client.
"""

import datetime
import enum
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.crypto import SecretUnreadable
from control.app.errors import (
    ConfigNotServing,
    ConfigRefused,
    Conflict,
    DomainError,
    NodeCannotServe,
    NodeNotInService,
    NodeOperationFailed,
    NothingToApply,
)
from control.app.models import (
    AuditAction,
    Credential,
    Node,
    NodeState,
    NodeTransport,
    TransportPurpose,
)
from control.app.services import addresses, audit, delivery, nodes, placement, relay, serving
from control.app.settings import Settings
from edge import checker
from edge.bootstrap import NodeConnection, NodeTarget, NodeUnreachable, node_stack

# Aliased because both halves of M27.2 are called ``delivery`` and both are read in this
# file: ``services.delivery`` renders what a host is given, and this one places it.
from edge.bootstrap import delivery as node_delivery
from edge.egress import ResolverMissing
from edge.health import Listener
from edge.registry import discover, profile

logger = logging.getLogger(__name__)

# Where an operator finishes a push that did not land. A SCREEN, named in words, and
# never a page or a URL — that is the whole point of this constant existing rather than
# the sentence being written three times.
#
# It exists because the sentence it replaced outlived the surface it named. "Retry from
# the node's page" was true until M9.6 deleted that page, and it was still being drawn
# on the console afterwards: on an INCOMPLETE REVOCATION, which is the moment somebody
# who should be cut off is still connected, the operator was sent to a URL that 404s.
# A docstring naming a dead template is a nuisance; a live sentence naming one is the
# operator standing still at the only moment that matters.
#
# Every service sentence that tells an operator where to go uses this. A screen that
# moves moves here, and nothing composed in ``services/`` may name a page again.
#
# EXCEPT THE THREE REFUSALS BELOW, since M18's acceptance: they are answered to an API
# consumer as well as to the console, and naming a screen is the one thing an API message
# must not do. Their directions are written in the clauses under this and become the
# console's own words at ``panel/wording.for_the_page`` — the one seam where a sentence
# written for any caller becomes page copy. This constant stays because the sentences that
# are ONLY ever read on the console still use it (``services/console.py``, the incomplete
# revocation and rotation reports).
WHERE_TO_RETRY = "the Nodes screen"

# THE ONE CLAUSE PER REFUSAL THAT IS WRITTEN FOR A SCREEN — M18's acceptance, round 2.
#
# ``POST /api/nodes/{id}/apply`` was answering a script with "Enable a transport on it
# from the Nodes screen, then apply it" and "Nothing else in this panel stops a node
# serving what it was last given": right for the operator reading a banner, wrong in a
# JSON error body, where there is no panel and the caller is not looking at one.
#
# So the service says what is true of this control plane however it is driven, and the
# panel says it in its own words. Full sentences rather than fragments, because the
# translation is keyed on the whole of one: a clause that has to be spliced into another
# sentence is a mapping that goes stale silently the first time the sentence around it is
# rewritten, and these are keyed BY THE CONSTANT — the page's version is looked up with
# the value below, not with a copy of it (``panel/wording.py``).
#
# Nothing else in a refusal changes across the boundary. The substance — what was pushed,
# what the host is still running, what an apply can and cannot do — is the same fact for
# both readers and is written once.
ENABLE_ONE_HERE = "Enable a transport on this node, then apply it."
OFFER_ONE_AGAIN = (
    "Offer one of its transports again — which puts that transport back in every user's "
    "link — and apply."
)
NOTHING_STOPS_A_SERVING_HOST = (
    "Nothing else in this control plane stops a node serving what it was last given."
)

# The fourth clause written for any caller, and the fourth refusal that has a different
# direction on the console — M23. ``target_for`` refuses a node whose record carries no
# SSH key at all, and an API caller has no row to press anything on.
#
# IT NAMES NO BUTTON, since M23's round 2. It said "then apply it", and ``target_for`` is
# reached by the PROBE as well — so an operator who pressed probe on a keyless node was
# answered about the other button, on a screen where the two sit side by side and one of
# them rewrites a live node's configuration. "Try again" is the same instruction for both
# callers and for an API caller who pressed nothing at all.
GIVE_IT_A_KEY = "Give it one, then try again."

# What an operator is told when a node's record holds no SSH key — M23, found on the real
# hosts. It used to be ``edge``'s ``PermissionDenied`` sentence, *"the node refused the
# key this control plane holds for it"*, which sent the operator to debug a host's
# ``authorized_keys`` over a control plane that had offered the host nothing. That
# sentence is right where it fires; reaching it with an empty key was the defect, and the
# fix is on this side because this is the side that knows what is on the record.
#
# It says what did NOT happen as well as what did, because the two failures look the same
# from the node's row: nothing was dialled, so nothing on the host changed, and the node
# is still running whatever it was last given.
NO_SSH_KEY = (
    "this node has no SSH key on its record, so no connection was attempted and nothing "
    "on the node was changed — the host refused nothing, because nothing was offered to "
    f"it. {GIVE_IT_A_KEY}"
)

# What an operator is told when they press apply on a node that offers nothing — M18.1.
#
# This is the first button a new node's row invites, and until this sentence existed the
# answer to pressing it was a 502 quoting `services must be a mapping` from the node's
# own docker compose, with the node left degraded. Every part of that was working as
# designed: no enabled transport renders no config, no config makes an empty `services:`
# block, and M4 surfaces a node's real stderr verbatim rather than swallowing it. The
# situation is simply not a failure — a node with nothing enabled has nothing to serve —
# and the operator needed a sentence about transports, not about YAML.
#
# Refusal rather than a silent no-op, and the deciding case is not the console: the
# revocation fan-out re-pushes every node a withdrawn user held a credential on, and a
# withdrawn row KEEPS its minted credentials, so a node whose last row was withdrawn
# arrives here with nothing to render while its container is still running the config
# that authorises that person. A no-op would report such a node as updated. It is
# reported as not updated instead, and ``why_not_updated`` calls it REFUSED.
#
# Where they send an operator is the clause above, translated into the console's own
# words at the panel boundary, so a screen that moves moves in one place and a caller
# that has no screen is not sent to one.
#
# Both named for the ACT rather than for the state, because ``console.NOTHING_ENABLED`` is
# the drift cell's two words for the same node and the two must not be mistaken for one
# another: that one is a table cell, these are refusals. What separates the pair is YET
# against LEFT — a node on its way to serving something, and a node that served something
# and was switched off.
#
# TWO SENTENCES, NOT ONE — M18.1's review. There was one, written for the deciding case
# above and delivered almost always in the other, and each half was wrong in the other's
# case:
#
#   * it said OFFER, which on the Nodes screen is a narrower control than it sounds: it
#     appears only on a row that was enabled and then withdrawn. A node with nothing on it
#     has no such row, and the console's word there is ENABLE — the select in the
#     transports dialog, the primary button beside it, and the Nodes empty state all say
#     so. A first-run operator sent to look for "offer" finds nothing named that.
#   * and on the withdrawn-row path it named the remedy without its cost. Offering the
#     row again grants every active user material on it and puts it back in every
#     subscription — a change to everyone's link, made to cut one person off — and it is
#     the only in-product way out: removing the row does not push, a state change does
#     not reach the host, and this apply refuses again.
#
# Which one an operator gets is decided by whether the node has any transport row at all,
# not by how many are enabled — an empty node and a node with every row withdrawn are two
# different situations with two different next actions.
#
# THREE SENTENCES, NOT TWO — M18's acceptance, and the second axis is whether a config
# this panel holds has ever actually REACHED the host (``NodeTransport.applied_at``, which
# a withdrawal leaves alone). Two of the three claims above turned out to be said in
# places they are not true:
#
#   * the withdrawn one asserts the host is still serving everyone who holds a credential
#     — read on a node whose own drift cell says `never applied`, which contradicts the
#     Users screen's "No node is serving yet" and is simply false. A node nothing was ever
#     pushed to is serving nobody.
#   * and the empty one said nothing about the host at all, which is the same defect from
#     the other side: REMOVING a node's last transport leaves it with no rows, so the
#     operator who removed it to cut everybody off lands here and reads "nothing on the
#     node was changed" as "there was nothing there". The row is gone from this panel and
#     the daemon on the host is not — and because the apply is refused, no apply is ever
#     going to stop it.
#
# So the two that cannot know say what is true either way — WHATEVER this host was last
# given, it keeps running — and only the one that does know (a surviving row carries an
# ``applied_at``) makes the stronger claim. A removed row takes its ``applied_at`` with
# it, which is why the empty case can never be certain and must not pretend to be.
#
# AND THE EMPTY ONE STOPS SAYING WHAT IT CANNOT KNOW — M18's acceptance, round 2. It
# opened "Whatever this host was last given it keeps running" on a node nothing had ever
# been pushed to, which reads as a report about a config that was delivered; the walk
# read it on a host whose address does not even resolve. The evidence that would settle
# it is ``applied_at`` and it is on the row that was removed — so this sentence says that
# it cannot tell, and why, rather than picking the half that is wrong on the node the
# operator is looking at. Both halves of what it is FOR survive that: an operator with
# nothing enabled is still told to enable something, and an operator who removed a
# transport to cut people off is still told that removing it did not stop the host.
NOTHING_TO_APPLY_YET = (
    "this node has no transports enabled, so there is nothing to apply — nothing was "
    f"pushed and nothing on the node was changed. {ENABLE_ONE_HERE} Whether anything was "
    "ever pushed to this host cannot be answered from here: a removed transport takes "
    "the record of its own apply away with it. What holds either way is that an apply "
    "with nothing to push cannot change what the host is running — so if a transport was "
    "removed here to cut people off, removing it did not stop the host serving it. "
    f"{NOTHING_STOPS_A_SERVING_HOST}"
)
NOTHING_LEFT_TO_APPLY = (
    "every transport on this node is withdrawn, so there is nothing to apply — nothing "
    "was pushed and nothing on the node was changed. The node is still running the "
    "config it was last given and still serving everyone who holds a credential on it: "
    "an apply cannot stop that, because there is nothing to push. "
    f"{OFFER_ONE_AGAIN} {NOTHING_STOPS_A_SERVING_HOST}"
)
NOTHING_LEFT_TO_APPLY_UNPUSHED = (
    "every transport on this node is withdrawn, so there is nothing to apply — nothing "
    "was pushed and nothing on the node was changed. No transport on this node has ever "
    "been applied: whatever this host was last given it keeps running, and an apply "
    "cannot change that while there is nothing to push. "
    f"{OFFER_ONE_AGAIN} {NOTHING_STOPS_A_SERVING_HOST}"
)

# The clause each of the three refusals above ends its first sentence with, named here
# because M27.4 made it conditional — and the sentence that replaces it when it is not
# true any more.
#
# A refused apply now REMOVES this host's delivery material before it refuses (see
# ``apply_node``), so on a host that was holding some, "nothing on the node was changed"
# is false. It is a replacement rather than an addition on purpose: an operator cannot be
# told in one paragraph both that nothing changed and that something was taken away, and
# the clause it replaces is the one making the false half of that claim.
#
# The substitution is the same mechanism ``panel/wording`` already uses on these
# sentences — a named clause swapped for another named clause — rather than a second set
# of three constants, which would have to be kept in step with these by hand.
NOTHING_CHANGED_ON_THE_NODE = "nothing was pushed and nothing on the node was changed"
DELIVERY_TAKEN_BACK = (
    "nothing was pushed, and the one thing that did change on the node is that the "
    "pre-rendered subscriptions an earlier apply left there have been removed — a host "
    "this control plane no longer hands anybody's material to does not keep it"
)

# And when the host could not be reached to do that. Appended rather than substituted,
# because here "nothing on the node was changed" is exactly true: nothing was, including
# the removal. What the operator would otherwise not learn is that the material is still
# sitting there — which on a host nobody is pushing to any more is other people's
# configurations with no end date.
#
# ON ONE OF THE THREE REFUSALS ONLY, and it is the one that already claims to know what
# this host is running: a surviving row carries an ``applied_at``, so this control plane
# has pushed here and may have left material. The other two say in their own words that
# they cannot tell what was ever pushed to this host — a removed row takes the record of
# its own apply with it — and a hedge added to them would be a second sentence saying
# "something might be there" on the refusal an operator reads on a node they created a
# minute ago. The removal is still ATTEMPTED on all three: what is conditional is the
# claim, not the reach.
DELIVERY_MAY_STILL_BE_THERE = (
    " This control plane could not reach the node to take back the pre-rendered "
    "subscriptions an earlier apply may have left on it, so whatever is there is still "
    "there."
)

# What an apply is refused with when the node it would put into service has a pool that
# cannot hold the fleet — M23, round 3. The walk pressed apply on a degraded node with a
# two-address pool and three users: the push went out, the host's config changed, the
# daemon was restarted, and only THEN did the fan-out below refuse and roll the record
# back. The API said "Nothing has been changed", which was true of the database and false
# of the node, and every repeat press pushed and restarted again.
#
# So the measurement moved above the render, where ``nodes.set_transport_enabled`` and
# the state dialog already take it: ``addresses.shortfalls_among`` over this node's own
# enabled rows, which are exactly the ones that become serving with it. Nothing is
# dialled, so the sentence is true about the host as well as about the record.
#
# The pools are named in ``addresses.named``'s words, like every other refusal about a
# pool, and it ends where the size is actually changed — there is no resize action on the
# Nodes screen, and an operator sent to "make the pool bigger" with no screen named has
# nowhere to go.
#
# The direction is its own clause for the reason the four above it are: this sentence is
# also the body of a 409 from ``POST /api/nodes/{id}/apply``, where naming a screen is
# the one thing a message must not do. The console says where the size is changed
# (``panel/wording.py``); the service says what has to happen.
MAKE_THE_POOL_BIGGER = (
    "Make the pool bigger on that transport first, or take somebody off the fleet."
)
POOL_SHORT_TO_APPLY = (
    "applying this node is what puts it into service, and a node that serves gives every "
    "active user an address on each transport it offers — {pools}. Nothing was pushed "
    f"and nothing on the node was changed. {MAKE_THE_POOL_BIGGER}"
)

# What an apply is refused with on a node the state machine will not let serve again —
# and today that is exactly one state, ``retired``.
#
# It exists because ``apply_node`` writes ``node.state`` itself instead of going through
# ``nodes.set_node_state``, so the machine that has refused ``retired -> active`` since
# backlog item 17 was never asked on this door: apply on a retired node answered 200 and
# left it active. Round 5 made that worse rather than created it — the fan-out above now
# mints material for every active user on the way in, so the button re-activated a
# host the operator had recorded as gone AND granted the whole fleet on it, and its
# address was back in every subscription at the next fetch.
#
# WRITTEN FOR ``retired``, which is the only state that can reach it while
# ``allowed_from`` says what it says. The guard asks the machine rather than comparing to
# a literal, so a state added later that cannot become active would be refused here too —
# and would be handed a sentence about a host that was destroyed or seized, which may not
# be what that state means. Whoever adds one rewrites this.
#
# The direction is its own clause for the reason the five above it are: this sentence is
# the body of a 409 from ``POST /api/nodes/{id}/apply`` as well as a line on the console,
# and naming a screen is the one thing an API message must not do.
#
# It says what did NOT happen in the same breath, because the fan-out is the part an
# operator cannot see: nothing was dialled, nobody was granted anything, and the node is
# still exactly as they left it. What it does not claim is anything about the HOST — a
# retired node's daemon may well still be running the last file it was given, and this
# control plane has no way to know from here.
REGISTER_IT_AGAIN = (
    "If that host is genuinely back, register it again as a new node and apply that one."
)
CANNOT_SERVE_AGAIN = (
    "this node is {state}, and applying a node is what puts it into service — which is "
    "the one move a {state} node is refused. That state is where an operator records "
    "that a host is gone, so bringing the record back would put an address that may now "
    "answer for somebody else into every user's subscription and hand every active "
    "user key material on it. Nothing was pushed, nobody was granted anything and "
    f"nothing about this node was changed. {REGISTER_IT_AGAIN}"
)

# And what a PROBE is refused with on the same node — M23, round 12, which found the two
# buttons disagreeing about one address.
#
# The refusal above turns apply away because the address "may now answer for somebody
# else". The probe, sitting beside it on the same row, then opened an SSH session to that
# exact address: measured, on a retired node, ``GET /api/nodes/{id}/health`` answered 200
# having dialled it. A read is still a connection — it offers this control plane's key to
# whoever is there and asks them what they are running — and the one address this product
# refuses to push to was the one address it went on dialling.
#
# SO THE PROBE YIELDS AND THE APPLY DOES NOT, which is the way round that costs least.
# Apply's refusal closes a hole nothing else closes: it is what stops a written-off host
# reappearing in every user's subscription with key material minted for the whole fleet.
# The probe's answer, by contrast, is not lost — it is behind the step the operator has to
# take anyway. If that host is genuinely theirs again they register it as a new node, and
# they can probe THAT node freely; if it is not theirs, the probe was a connection to a
# stranger.
#
# What it costs, named rather than discovered: the probe is this console's only oracle for
# "is that host still running the file it was last given", and a retired node is exactly
# where that question is most uncomfortable — a withdrawn user may still be authorised
# there. This says so instead of answering it, because the answer would not change what
# the operator can do about it: nothing this control plane pushes reaches a node it will
# not put into service.
#
# Asked through ``cannot_serve_again`` so the two doors cannot drift, and the same type is
# raised for the same reason: what refuses is the machine, and the operator's next move
# after either is the same one. The SENTENCE differs because the two buttons do.
CANNOT_BE_DIALLED = (
    "this node is {state}, and a node in that state is not dialled by this control "
    "plane. That state is where an operator records that a host is gone, so its address "
    "may now answer for somebody else — and a probe is a connection like any other: it "
    "would offer this control plane's key to whoever is there and ask them what they are "
    "running. Nothing was dialled. What its host is still running cannot be read from "
    f"here, and nothing this control plane pushes reaches it either. {REGISTER_IT_AGAIN}"
)


def cannot_serve_again(state: NodeState) -> bool:
    """Whether the machine refuses to put a node in this state back into service.

    One predicate, two doors — the apply below and the probe in ``services/health.py`` —
    because a safety rule with two copies is a safety rule with one copy and a bug. It
    names no state: what may serve again is ``NodeState.allowed_from``'s to say, so
    widening the machine widens both doors and neither has to be found and edited.

    ``!=`` first, for the no-op ``set_node_state`` allows and for the same reason: a node
    that is ALREADY active is re-applied constantly — that is what an ordinary push is —
    and ``allowed_from`` lists no self-transition.
    """
    return state != NodeState.ACTIVE and NodeState.ACTIVE not in NodeState.allowed_from(state)

# What a FAN-OUT is refused with on a node that is not serving — M23, round 4, and it is
# the same defect class as the refusal above, one state over and one door over.
#
# Round 7 closed ``retired`` on this path by asking the state machine. ``draft`` is not
# the machine's to refuse and must not be: ``draft -> active`` is the first apply every
# node has, and it is exactly what the operator presses. What the walk measured is that
# NOBODY PRESSED IT. A node was parked in ``draft`` to rebuild its host; a new user was
# added while it was parked and granted nothing on it, correctly; and then one unrelated
# user was revoked. The revocation's fan-out applied the parked node — which took it into
# service, minted material on it for the user who had never been near it, and ran
# ``docker compose up`` on the host being rebuilt. The whole of what the operator saw was
# ``olga revoked — link is dead``.
#
# So the line is drawn at the DOOR rather than at the state. A revocation and a rotation
# reach ``apply_many`` as a consequence of an operation whose subject is somebody's
# access or one transport's material — never this node's place in the fleet, which is
# the thing being decided. An apply aimed at a node is the operator's own button and
# still takes a draft or a degraded node into service, which is the retry every failed
# apply depends on. ``apply_node`` takes the flag; the fan-out is the only caller that
# sets it.
#
# THE COST IS REAL AND IS SAID OUT LOUD, in this sentence and in the fan-out's own report:
# a node that is not serving is NOT re-pushed, so its host goes on running whatever file
# it was last given — which for a revocation may still authorise the person just
# withdrawn. Pushing anyway was weighed and refused: it restarts a daemon on a host the
# operator has taken out of service, and it is a change to a machine nobody aimed at. The
# containing fact is that nobody is routed onto a node that is not serving, so what is
# there stops growing; ending it is an apply the operator makes themselves.
#
# The direction is its own clause for the reason the six above it are: this sentence
# travels in a ``RevocationOutcome`` and a ``RotationOutcome``, both of which are answered
# to an API caller, and naming a screen is the one thing those must not do.
APPLY_IT_YOURSELF = (
    "Apply that node itself once its host is ready — that is what puts it back into "
    "service, and what replaces the file on it."
)
NOT_IN_SERVICE_TO_PUSH = (
    "this node is {state}, so it serves nobody and nothing was pushed to it: applying a "
    "node is what puts it into service, and only an apply of this node itself may decide "
    "that. Nothing was dialled, nobody was granted anything and nothing about this node "
    "was changed — and whatever its host was last given is still running there, "
    "untouched by this and now out of step with what this control plane holds. "
    f"{APPLY_IT_YOURSELF}"
)

# What the operator is told about the HOST when a push lands and the daemon does not come
# back on it — M23, round 4, and it is a sentence rather than a redesign on purpose.
#
# ``_record_failure`` deletes the credentials an apply minted on its way into service,
# because a failed apply must grant nobody. On the one failure where the bytes actually
# reached the host, that leaves the file on it authorising peers this database no longer
# holds: the walk counted two ``[Peer]`` blocks on the node against zero credential rows
# here. Round 6 named that cost when it wrote the deletion, and round 4's walk checked the
# bounds and found them to hold — a successful retry overwrites the file, each further
# failure replaces one orphan generation with the next so at most one is ever on disk, and
# an apply that minted nothing leaves nothing.
#
# So what is missing is not a mechanism, it is a sentence. The operator is already being
# told the daemon did not come up; they are not being told what is on that host meanwhile,
# and the exposure is the window in which that daemon later starts on its own — by a
# reboot, by somebody on the host — and serves peers the panel cannot list or revoke.
#
# ONLY WHEN THIS APPLY ACTUALLY MINTED SOMETHING. A re-apply of a node that was already
# serving grants nobody, deletes nothing and leaves no orphan, and saying this over it
# would be a warning about a state that is not there — which is how a real warning stops
# being read.
#
# It names no user and no host. What it says is what this control plane knows: a grant
# happened, it was undone, and the file that landed is older than the database again.
ORPHANED_ON_THE_HOST = (
    "This apply was also what put the node into service, so it granted every active "
    "user an address on it before rendering — and that grant was undone when this "
    "failed, because an apply that fails must grant nobody. The file that DID land still "
    "carries them. Nobody is routed onto a degraded node and the next successful apply "
    "rewrites that file whole, but until one does, a daemon that comes up on that host "
    "serves peers this control plane can no longer list or withdraw."
)


# The boundary between "this node failed" and "stop the whole operation".
#
# Everything ``apply_node`` does is work for ONE node — read its record, render its
# config, dial it, push, record what was pushed — so a failure of any kind there is a
# fact about that node, and the operator must be told it per node rather than losing
# the outcome for every other node to a 500 (criterion 6). The exceptions below are the
# ones that are NOT a fact about one node: they would be raised identically for every
# remaining node, and reporting them per node would say "3 nodes could not be updated"
# when the truth is "this control plane cannot read its own secrets". Worse, the one
# message that says so is written by a dedicated handler further out — catching it here
# would destroy the diagnosis while handling it, which is the exact fault M4 exists to
# fix, one level up.
#
# ``SecretUnreadable`` means HASHI_SECRET_KEY does not match the data. It is answered
# outward as a 409 with an explanation (see errors.SecretsUnreadable), not as a 500, so
# letting it through does not put an internal error in front of the operator.
#
# Note what is deliberately NOT listed: a programming error. A bug in one transport's
# renderer is still a fact about the node that uses it, and the other nodes' outcomes
# are worth more than an abort. It is logged with its traceback wherever it is caught,
# so it stays as visible as it is today.
#
# ``BaseException`` — ``asyncio.CancelledError`` above all — is excluded by using
# ``except Exception`` at the call sites and must stay excluded: a cancelled request or
# a shutting-down worker is not a per-node failure, and swallowing it hangs the loop.
_NOT_PER_NODE: tuple[type[BaseException], ...] = (SecretUnreadable,)

# The upstream image pins used to live here. They are now in
# ``edge/bootstrap/node_stack.py`` (``DATA_PLANES``), keyed by config FORMAT — naming a
# daemon is naming a protocol, and `control` is not allowed to do either.
async def render_for_node(session: AsyncSession, node: Node) -> dict[str, str]:
    """Every enabled transport's config for one node, keyed by the name it is placed under.

    Pure with respect to the node: it reads the database, then renders. Each
    transport gets exactly the users who hold a live credential on it, which is
    what makes the rendered file the authoritative answer to "who can use this node".

    THE KEY IS ``config_name``, not the transport's name, and since M15 those can
    differ: a node may run a user-facing AmneziaWG and the entry end of a hop over the
    same transport, and they are two files, two compose services and two interfaces. For
    every row written before M15 — and for every first instance since — the two strings
    are equal, which is why every caller indexing this by a transport's name still finds
    what it is looking for. A caller that needs the TRANSPORT behind a key (to resolve a
    config format, or to name it in a message) asks ``placed_transports``.
    """
    rendered: dict[str, str] = {}
    view = nodes.node_view(node)

    # This node's own way out, if it has one — M3. Read once per node rather than per
    # transport, because it is a property of the NODE: an entry node has a hop and its
    # users leave through it; a leaf has none and its users leave from it. What comes
    # back is an address and nothing else, so nothing below learns what carries the hop.
    hop_exit = await relay.exit_through_hop(session, node)

    # Queried rather than read off ``node.transports``. The relationship loads eagerly
    # when the node is freshly selected, but this function is also called right after a
    # revocation has deleted rows in the same session — at which point touching the
    # collection can trigger a lazy refresh, and lazy I/O on an async session raises
    # MissingGreenlet rather than quietly issuing a query.
    listed = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.enabled.is_(True))
        .order_by(NodeTransport.transport_name)
    )

    for node_transport in listed.scalars().unique():
        # A hop end is rendered as a PAIR with its far end, not as a server with a list
        # of users — see services/relay.py. Dispatched on the stored purpose, which
        # is topology, never on the transport's name.
        if node_transport.purpose in TransportPurpose.relays():
            peer = await relay.peer_of(session, node_transport)
            rendered[node_transport.config_name] = relay.render_end(
                node_transport, peer
            )
            continue

        result = await session.execute(
            select(Credential).where(Credential.node_transport_id == node_transport.id)
        )
        # What this transport says about giving each consumer an address of its own,
        # resolved once per row rather than per credential — M17.
        spec = addresses.spec_for(node_transport.transport_name)
        credentials = [
            # The user's own client-scoped material travels with the subject, and it
            # has to. A VLESS server config needs only the subject, so this looked
            # unnecessary until a WireGuard-family transport became user-facing (item
            # 27): its server config authorises each peer by the peer's PUBLIC key,
            # which lives here. Without it, applying such a node raised KeyError deep
            # in a renderer — and the first place that showed up was a revocation
            # returning 500, because revocation re-pushes every node the user was on.
            #
            # Handed over whole rather than filtered: which parts of its own client
            # material belong in a server config is the transport's business, and
            # picking them here would mean `control` recognising field names. That a
            # user's PRIVATE half never reaches a server config is asserted instead —
            # see tests/control/test_second_subscription_format.py.
            #
            # Built through ``addresses.edge_credential``, which is also what the user's
            # own config file is built through: this config's ``AllowedIPs`` and that
            # file's ``Address`` are two renders of one allocation, and a second builder
            # here is how they would come to disagree.
            addresses.edge_credential(row, spec)
            for row in result.scalars().unique()
            # A revoked user's rows are deleted rather than flagged, so this is a
            # belt-and-braces filter rather than the mechanism — see
            # services/users.py:revoke for why deletion is the real guarantee.
            if row.user.is_active
        ]
        # Sorted so the rendered config is byte-stable regardless of row order,
        # which is what makes the applied digest a drift signal rather than noise.
        credentials.sort(key=lambda credential: credential.subject)

        transport = profile(node_transport.transport_name)
        try:
            rendered[node_transport.config_name] = transport.profile.render_server(
                view,
                nodes.render_params(node_transport),
                credentials,
                # Which way out this tunnel's traffic takes, from the purpose the row
                # already carries and from whether this node has a hop — M14.3 and M3,
                # and see ``nodes.egress_for``. Both are passed for every transport,
                # including those whose data plane forwards nothing in the kernel and
                # renders nothing for either, so this call stays blind to which is which.
                egress=nodes.egress_for(node_transport, hop_exit),
                exit_via=hop_exit,
            )
        except NodeOperationFailed:
            raise
        except Exception as exc:
            # A renderer that refuses is a NODE-level failure, not a crash. Renderers
            # refuse on purpose — the WireGuard family, for one, refuses to write two
            # peers onto one tunnel address rather than emit a file where the second
            # silently takes over the first's route — and the operator has to read that
            # sentence, on the node's page, with the node left degraded.
            #
            # Before this, such a refusal escaped as a 500. The path it escaped through
            # was the worst available: revocation re-pushes every node the user was
            # on, so an unrelated node's rendering problem made "remove this person's
            # access" answer "internal error" — and the operator has no way to tell
            # whether the removal happened.
            #
            # Logged with its traceback before it is converted, because the conversion
            # is deliberately broad: transport exceptions share no base class (giving
            # them one in `control` would mean importing a protocol's own module here),
            # so this arm also catches a genuine bug in a renderer. A domain error is
            # reported to the operator without a stack trace, so without this line a
            # typo in a template would leave no trace anywhere. No key material can
            # reach the log: the exception message is the transport's, and the rendered
            # config is not passed.
            logger.exception(
                "rendering %s for node %s failed", node_transport.transport_name, node.id
            )
            # The message is the transport's own; nothing here interprets it. Note the
            # rendered text is NOT included: it holds key material. ``ConfigRefused``
            # rather than its parent, so a fan-out can tell "nothing was pushed and a
            # retry changes nothing" from "unreachable" by type (``why_not_updated``).
            raise ConfigRefused(
                f"{node_transport.transport_name} could not be rendered for this node "
                f"— {type(exc).__name__}: {exc}"
            ) from exc

    return rendered


async def enabled_transports(session: AsyncSession, node: Node) -> list[NodeTransport]:
    """Every row on this node that is currently offered, as rows.

    THE FILTER, in one place — M23, round 3. It is the same one ``render_for_node`` runs,
    and since this milestone three things in this module need it rather than one: which
    configs get rendered, which transport each placed config came from, and whether the
    pools on the rows about to become serving can hold the fleet. Written out a third
    time it would be the drift ``fleet_size`` and ``sized_pool`` already exist to prevent,
    one module over.

    Rows rather than columns, because the pool question is asked of the row itself
    (``addresses.shortfalls_among``). Queried rather than read off ``node.transports``
    for the reason ``render_for_node`` gives: this is reached straight after a revocation
    deleted rows in the same session, where touching the collection is lazy IO on an
    async session.
    """
    listed = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.enabled.is_(True))
        .order_by(NodeTransport.transport_name)
    )
    return list(listed.scalars().unique())


async def placed_transports(session: AsyncSession, node: Node) -> dict[str, str]:
    """Which transport each of this node's placed configs came from, by config name.

    The other half of ``render_for_node``'s key, and it exists because two of the three
    things done with a rendered config are the TRANSPORT's business rather than the
    file's: which upstream checker validates it, and which extension and data plane it
    gets (``edge.bootstrap.node_stack``). Before M15 the key was the transport's name and
    both were free.

    Its own function rather than a second return value, so no caller that indexes a config
    by name had to change. It reads ``enabled_transports`` — the same filter
    ``render_for_node`` runs, in the same transaction, against a database only the
    operator writes to — and the two are used together within one request.
    """
    return {
        row.config_name: row.transport_name
        for row in await enabled_transports(session, node)
    }


async def placed_listeners(session: AsyncSession, node: Node) -> dict[str, Listener]:
    """Where each of this node's placed configs is expected to answer — M22.

    The third member of ``render_for_node``'s family, and it exists for the same reason
    ``placed_transports`` does: the probe needs a fact about each placed config that the
    config itself does not carry. Here it is the socket — the port the OPERATOR chose,
    which lives in the row's own parameters, and the transport-layer protocols the
    TRANSPORT declared it binds, which live in its package. `edge` resolves neither: it
    has no database and no business reading a registry to answer a question about a row.

    Both halves are read through ``services.placement``, which is where this codebase
    already asks them for the port-collision rule — ``port_of`` for the value, under the
    one parameter name the hop contract knows, and ``binds_of`` for the declaration.
    Nothing here compares a transport's name to a literal, and no branch anywhere asks
    which transport it is looking at.

    A ROW THIS CANNOT ANSWER FOR IS LEFT OUT, never guessed at, and the probe reports such
    a config as unchecked rather than as silent. Four ways that happens, and they are not
    equally reachable — which is worth saying, because a reader who takes all four for
    ordinary will delete the ones nothing seems to exercise. TWO ARE ORDINARY and arrive
    through ``health.check_node``: a row that declares no port at all, and one that
    declares it in a shape that is not a port number (a value out of a future migration,
    a transport that names its port something else). The other two cannot arrive that
    way. A transport this image no longer ships is refused by ``render_for_node`` before
    the probe gets here, so the guard below holds only for a direct call — without it the
    missing package is a ``KeyError`` out of ``profile()``. And a package declaring it
    binds nothing cannot exist at all: ``edge.registry`` refuses an empty ``listens_on``
    when it loads a transport, so that guard is the second line behind a rule held in the
    other zone, and it is tested by fabricating the declaration. Inventing an answer for
    any of the four would report a working node as broken, which is the same defect as
    reporting a broken one as working — M22's own subject, pointed the other way.

    NO RANGE IS CHECKED HERE, and that is deliberate rather than an omission — but not
    because a ceiling would be a hardcoded port. It would not be: ``edge.registry``
    already writes ``1 <= low <= high <= 65535`` for this same concept, and 65535 is a
    property of the protocol rather than a node anyone could rotate away from. The reason
    is that a ceiling would make this answer WEAKER. Which ports exist belongs to the
    transport's declaration and to the kernel; a row holding a number no socket can be
    bound on is a row whose container bound nothing, so "nothing is listening for it" is
    true — and it is what the operator needs to hear. Refusing the row instead would
    report the same node as one whose port was not checked, which is the vaguer of two
    honest answers.
    """
    listed = await session.execute(
        select(
            NodeTransport.config_name, NodeTransport.transport_name, NodeTransport.params
        )
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.enabled.is_(True))
    )
    installed = discover()
    listeners: dict[str, Listener] = {}
    for config_name, transport_name, params in listed.all():
        if transport_name not in installed:
            continue
        port = placement.port_of(params or {})
        # As text, because that is what ``port_of`` promises for every transport whatever
        # shape it stores its port in. A value that is not a port number is a row nothing
        # can be checked about — and ``isdigit`` rather than ``try: int()`` because the
        # latter accepts a leading sign and unicode digits, neither of which is a port.
        if port is None or not port.isdigit():
            continue
        protocols = placement.binds_of(transport_name)
        if not protocols:
            continue
        listeners[config_name] = Listener(port=int(port), protocols=protocols)
    return listeners


def target_for(node: Node, node_settings: Settings) -> NodeTarget:
    """How to reach a node over SSH, from its record.

    The three ways a node's record cannot produce a session at all are refused here, in
    the one function both the push and the probe build their target with, so neither has
    to recognise them separately.

    THE THIRD IS "NO KEY AT ALL", and it is M23's. A record with an empty key produced a
    target the SSH layer dialled with no credential, the host answered ``PermissionDenied``,
    and both the apply banner and the probe banner said *"the node refused the key this
    control plane holds for it"* — about a control plane that holds none. That sentence is
    ``edge``'s and it is right where it fires; what was wrong is reaching it. The fact
    belongs here, because this is the side that knows what is on the record, and the
    operator's next action is a paste into this panel rather than an edit to a host's
    ``authorized_keys``.

    The key is the second of them and it was an internal error until this line existed:
    the SSH layer loads it OUTSIDE the block that turns a connection failure into
    ``NodeUnreachable``, so an unusable one escaped as an exception class — a 500 on the
    probe, and on the push a sentence saying "what reached the node is unknown", which
    is untrue when nothing was ever dialled. Refused before the connection is attempted,
    so both surfaces can say what is actually true: no session, nothing sent.

    Nodes registered before the panel started refusing such a key still hold one, which
    is why this is a check on the record and not only on the form.
    """
    if not node.ssh_host:
        raise NodeOperationFailed(
            "this node has no SSH address, so its configuration cannot be pushed"
        )
    if not node.ssh_private_key:
        raise NodeOperationFailed(NO_SSH_KEY)
    if not nodes.ssh_key_is_usable(node.ssh_private_key):
        raise NodeOperationFailed(
            "the SSH private key stored for this node cannot be read, so no connection "
            "was attempted and nothing on the node was changed"
        )
    return NodeTarget(
        host=node.ssh_host,
        port=node.ssh_port,
        username=node.ssh_user,
        private_key=node.ssh_private_key,
        host_key=node.ssh_host_key,
        connect_timeout=node_settings.node_connect_timeout,
        timeout=node_settings.node_ssh_timeout,
    )


def validate_before_push(transport_name: str, config: str, config_format) -> None:
    """Refuse to push a config the daemon would reject.

    Treats "no checker installed" and "checker cannot open a referenced file" as
    NOT-CHECKABLE rather than as a rejection, and proceeds. That is a deliberate,
    narrow allowance, and the reasoning is in ``edge/checker.py``: ``xray -test``
    builds the TLS context, so a config naming a certificate file fails locally even
    when it is perfectly valid on the node where that file exists. Failing closed
    here would make the WS+TLS transport unpushable forever.

    What is never allowed through is a config the checker actually understood and
    rejected — a syntax or schema error, which would restart the node into a crash
    loop.
    """
    result = checker.validate(config, config_format=config_format)

    if not result.available:
        logger.warning(
            "pushing %s without upstream validation — no checker installed. Install it "
            "with scripts/fetch-upstream-checkers.sh",
            transport_name,
        )
        return

    if result.ok:
        return

    # A missing local file is the known not-checkable case, not a bad config.
    if "no such file or directory" in result.output.lower():
        logger.info(
            "%s references a file that exists only on the node; local validation "
            "skipped, node-side verification still applies",
            transport_name,
        )
        return

    # ``ConfigRefused``: nothing was pushed and a retry changes nothing — and this is the
    # message known to be able to carry key material, which is why a fan-out learns the
    # kind from the type rather than from these words (``NotUpdated``).
    raise ConfigRefused(
        f"the rendered configuration for {transport_name!r} was rejected by the "
        f"upstream checker, so it was NOT pushed: {result.output[:300]}"
    )


async def _nothing_to_apply(
    session: AsyncSession, node: Node, *, delivery_material: bool | None = False
) -> str:
    """Which of the three refusals this node gets, and what it says about the host.

    ``delivery_material`` is what the removal below the refusal found: ``True`` when this
    host was holding delivery material and no longer is, ``False`` when it was holding
    none, and ``None`` when the host could not be reached to ask. The first makes the
    refusal's "nothing on the node was changed" false and replaces that clause; the third
    is said only where this node's own rows show it was ever applied, which is the same
    axis the three refusals are already chosen on — see ``DELIVERY_MAY_STILL_BE_THERE``.

    One query, on the refusal path only, and it reads both axes off one column.
    ``enabled_transports`` already filtered to the offered rows and came back empty, so
    what is left to learn is:

    * whether the node has any transport row AT ALL — which decides whether there is
      something here to OFFER again or nothing here to do but ENABLE one. The two
      answers send the operator to two different controls, and ``offer`` exists only on
      a row that was enabled once;
    * and whether any row that is still here has ever been APPLIED, which decides
      whether this panel may say what the host is still serving. ``applied_at`` survives
      a withdrawal (``nodes.set_transport_enabled`` touches only the flag) and is
      deleted with the row, so a TRUE here is knowledge and a FALSE is only the absence
      of it — which is exactly why the two sentences a FALSE leads to claim nothing
      about who the host is authorising.

    Queried rather than read off ``node.transports`` for the reason ``render_for_node``
    gives: this can be reached straight after a revocation deleted rows in the same
    session, where touching the collection is lazy IO on an async session.
    """
    applied_at = await session.execute(
        select(NodeTransport.applied_at).where(NodeTransport.node_id == node.id)
    )
    stamps = applied_at.scalars().all()
    if not stamps:
        refusal = NOTHING_TO_APPLY_YET
    elif any(stamp is not None for stamp in stamps):
        refusal = NOTHING_LEFT_TO_APPLY
    else:
        refusal = NOTHING_LEFT_TO_APPLY_UNPUSHED
    if delivery_material is None:
        return (
            refusal + DELIVERY_MAY_STILL_BE_THERE
            if refusal == NOTHING_LEFT_TO_APPLY
            else refusal
        )
    if delivery_material:
        return refusal.replace(NOTHING_CHANGED_ON_THE_NODE, DELIVERY_TAKEN_BACK)
    return refusal


async def _take_delivery_back(node: Node, node_settings: Settings) -> bool | None:
    """Take this host's delivery material off it when its apply is refused — M27.4.

    ``True`` when the host was holding some and no longer is, ``False`` when it was
    holding none, ``None`` when the host could not be reached to ask.

    WHY A REFUSED APPLY REACHES A HOST AT ALL. ``apply_node`` refuses a node with nothing
    enabled above everything it writes, so the ordinary way a host stops carrying users —
    withdraw its last transport, press apply — never reached the push, and the host kept
    its ex-users' rendered subscriptions, including a WireGuard-family client file's
    ``PrivateKey``, which the node's own server config never held. A host nothing will
    ever push to again keeping other people's configurations is not "absent" by any
    reading, and there is no other path in this product that would ever come back for it.

    M27.2 WEIGHED REACHING IT AND REFUSED, on three grounds, and this is a REMOVAL rather
    than the push it refused:

    * a push needs ``node_stack.prepare``, which has not run here. This creates nothing —
      ``rm -rf`` on a path that is not there succeeds — so it cannot make ``NODE_ROOT``
      under an account that should not own it, and it cannot reintroduce the raw
      ``Permission denied`` that ``HOST_NOT_PREPARED`` was written to replace;
    * the three refusals say "nothing on the node was changed". That clause is now
      conditional and is replaced on the one host where it is false — see
      ``DELIVERY_TAKEN_BACK``;
    * and a failure had nowhere to go. It has one now: ``None`` reaches the operator as
      ``DELIVERY_MAY_STILL_BE_THERE``. It is NOT a reason to degrade the node or to
      answer the apply with a failure — M18.1 settled that a node with nothing enabled is
      not a failed node, and a host we could not reach is in exactly the state the
      refusal already describes.

    Nothing about the node's record is written here, including a host key learned on a
    first connection: this path exists to take something off a host, and a refused apply
    that quietly edited the row would be a change nobody asked for.
    """
    try:
        target = target_for(node, node_settings)
    except NodeOperationFailed:
        # No address, no key, or a key this control plane cannot read. Nothing was
        # dialled, so nothing can be said about what is on the host.
        return None
    try:
        async with NodeConnection(target) as connection:
            return await node_delivery.remove_delivery(connection)
    except NodeUnreachable:
        return None


async def _record_failure(
    session: AsyncSession,
    node: Node,
    reason: str,
    granted: Sequence[Credential] = (),
) -> None:
    """Log why an apply failed, undo what it granted, then mark the node degraded.

    In that order.

    The order is the whole point, and it was bought with an evening in the field on
    2026-09-08. Recording the failure is itself a write that can fail, and when it did
    — a first apply starts from ``draft``, which the state machine would not let become
    ``degraded`` — the recording's own error REPLACED the failure it was recording. The
    operator was handed "a node cannot go from draft to degraded"; the actual cause was
    a permission error on the host, and it existed nowhere afterwards, because
    ``domain_error_handler`` logs a code and never a message. Logging first means the
    reason survives even when everything after this line goes wrong.

    A refused transition is therefore swallowed here rather than raised. It is still
    possible (a ``retired`` node has nowhere to go) and it is still worth a log line,
    but the caller is about to raise the real reason and that is the more useful of the
    two errors to put in front of an operator.

    The reason is the node's own diagnostic — our command, its stderr, our timeout. It
    names no user and no connection, which is what makes it loggable at all (core
    invariants §6).

    ``granted`` IS WHAT THIS APPLY MINTED ON ITS WAY IN — M23, round 3 — and it is deleted
    here rather than rolled back. Since this milestone an apply that puts a node into
    service grants every active user BEFORE it renders, because the peers in the file are
    exactly the people who hold a credential on the row; a failed push must still grant
    nobody, which is the property ``test_an_apply_that_fails_grants_nobody`` holds. A
    ``session.rollback()`` would do it in one line and would also discard the learned SSH
    host key ``apply_node`` may have put on the node inside the connection block —
    the pending edit ``nodes._node_to_write`` refreshes column by column to preserve. So
    the credentials are deleted explicitly and everything else stands.

    What that costs is worth naming: on the one failure where the push actually landed,
    the host is left authorising peers whose key material this database no longer holds.
    That is the ordinary orphaned-key-material shape of any interrupted push — the node
    is degraded, so nobody is routed onto it, and the next apply rewrites the file whole.
    """
    logger.error("apply failed for node %s: %s", node.id, reason)
    for credential in granted:
        await session.delete(credential)
    if granted:
        await session.flush()
    try:
        await nodes.set_node_state(
            session,
            node_id=node.id,
            state=NodeState.DEGRADED,
            # TRIMMED HERE and refused everywhere else, which is not two rules. A reason
            # an OPERATOR typed is theirs and is refused rather than clipped; this one is
            # a machine's, often an upstream checker's output, and there is nobody to
            # refuse it to — the alternative to trimming is a failed apply that also
            # fails to record why it failed. The bound is the column's own, read from the
            # one place that states it, so the two cannot drift into this call raising.
            detail=reason[: nodes.STATE_DETAIL_MAX_LENGTH],
        )
    except Conflict:
        logger.error(
            "node %s could not be marked degraded from %s; its state is unchanged and "
            "the line above is the whole record of what went wrong",
            node.id,
            node.state,
        )


async def _take_into_service(
    session: AsyncSession, node: Node, rows: Sequence[NodeTransport]
) -> list[Credential]:
    """Hand every active user a credential on the rows this apply is about to serve.

    THE ORDER AGAINST THE RENDER IS THE WHOLE OF THIS FUNCTION — M23, round 3. Round 2
    added this fan-out at the END of ``apply_node``, after the push, and the real-host
    walk found what that costs: a draft node applied once went active, handed both users
    a credential at that instant, and pushed a file with zero peer blocks in it, because
    ``render_for_node`` had already run. The users' archives then held a config for a node
    that holds none of their key material — a link that is live immediately and cannot
    work — and the repair was a second apply nothing asked for. Whether the product worked
    came down to the order the operator pressed two buttons in.

    So becoming serving happens BEFORE the render and the bytes carry the people. Three
    shapes were weighed: grant first (this one), re-render and push a second time after
    granting, and refusing to serve a draft node from apply at all — which also takes
    ``degraded -> active`` away, and that is the retry every failed apply depends on.

    IT DOES NOT TOUCH ``node.state``, and that is the second decision. Writing ACTIVE here
    so ``serving_transports`` could see the node would put this function's own answer
    above ``NodeState.allowed_from`` — a retired node would be flushed active, and the
    failure path would then read the row and find ``active -> degraded`` perfectly legal,
    resurrecting the one node the state machine exists to refuse. The state still moves in
    one place, on the success path, past every failure arm. What made that possible is
    ``users.grant_on``, which grants over the rows it is given rather than over the ones
    a query calls serving.

    THE ROWS ARE THIS NODE'S OWN, not the fleet's. An apply is about one node, and an
    apply of node A that quietly mints material on node B is a side effect nobody pressed.
    USER-FACING ONLY, filtered here because ``grant_on`` deliberately re-filters nothing:
    a hop end's consumer is the far NODE, and a user granted one would be routed straight
    past the entry node the topology exists to hide behind.

    Does NOT commit: the caller owns the transaction that carries the applied digests, the
    audit entries and this.
    """
    user_facing = [row for row in rows if row.purpose == TransportPurpose.USERS]

    # Refused before anything is minted, before anything is rendered and before the node is
    # dialled, which is what makes ``POOL_SHORT_TO_APPLY``'s own sentence true about the
    # host as well as about the record. ``shortfalls_among`` and not the fan-out's own
    # ``PoolFull``, for the reason ``nodes.set_transport_enabled`` gives at the same
    # measurement: the fan-out skips a user who already holds a credential here, so a row
    # everybody is already on refuses nothing and the node would go into service carrying a
    # pool with no room for the next person. ``PoolFull`` stays underneath as the backstop
    # for a pool that is big enough on paper and full in fact.
    short = await addresses.shortfalls_among(session, user_facing)
    if short:
        raise addresses.PoolFull(
            POOL_SHORT_TO_APPLY.format(
                pools="; ".join(addresses.named(row) for row in short)
            )
        )

    # Deferred import for the cycle its siblings name: ``users`` imports the services
    # this one does.
    from control.app.services import users  # noqa: PLC0415

    granted: list[Credential] = []
    for user in await users.list_users(session):
        if user.is_active:
            granted.extend(await users.grant_on(session, user, user_facing))
    return granted


async def apply_node(
    session: AsyncSession, *, node_id: str, only_if_serving: bool = False
) -> dict[str, str]:
    """Render, validate, push and verify one node. Returns what was applied.

    Marks the node degraded on any failure after the first byte is written, and
    active only once it came back up serving every transport we expect.

    A node the state machine will not let serve is refused before any of that — see the
    guard below, which is the only thing standing between this function's own write of
    ``node.state`` and ``NodeState.allowed_from``.

    ``only_if_serving`` is the SECOND guard and it is about the caller rather than the
    node: set by ``apply_many`` and by nothing else, it refuses a node that is not already
    serving instead of taking it into service. The operator's own apply button leaves it
    false, because taking a node into service is exactly what that button is for. See
    ``NOT_IN_SERVICE_TO_PUSH`` for the walk that made the distinction necessary.
    """
    node = await nodes.get_node(session, node_id)

    # Re-read off the ROW rather than trusted off the copy this session is holding, for
    # ``nodes._node_to_write``'s reason and against the same harm its docstring names: a
    # session keeps what it loaded (``expire_on_commit=False``), so a node another
    # session retired still reads ``draft`` here, and the guard below would wave through
    # the transition it exists to refuse. Named column, not a whole-object refresh,
    # because these sessions are ``autoflush=False`` and a refresh discards a pending
    # edit instead of writing it first.
    #
    # It also decides ``becoming_serving`` further down, which is the same question asked
    # for the fan-out: a stale ``active`` in memory over a row that says degraded would
    # grant nobody on a node going back into service.
    #
    # A READ, NOT A LOCK, exactly as ``_node_to_write`` says — and the window this one
    # leaves open is longer than that one's, because what sits between this read and the
    # write it decides is a host being dialled rather than two statements. An operator
    # who retires a node while an apply to it is in flight loses the race: that apply
    # finishes, and it finishes active and granted, because both decisions were taken
    # from the row as it read here. The repair is to retire it again once the apply has
    # landed, which works — ``active -> retired`` is legal and the state endpoint takes
    # it. Named rather than closed, for the reason ``_node_to_write`` gives: one operator,
    # one console, and the lock this would need is on the table the delivery endpoint
    # joins against.
    await session.refresh(node, ["state"])

    # THE MACHINE'S ANSWER, ASKED RATHER THAN RESTATED — and asked here, above everything
    # this function writes, dials and mints, which is the whole of the refusal. An apply
    # ends by writing ``active`` directly (see the end of this function), so without this
    # line ``POST /nodes/{id}/apply`` was the one door where ``retired -> active`` went
    # through: the node came back into ``serving_transports``, the fan-out below handed
    # every active user material on it, and its address was in every subscription at
    # the next fetch.
    #
    # ``!=`` first, for the same no-op ``set_node_state`` allows and for the same reason:
    # a node that is ALREADY active is re-applied constantly — that is what an ordinary
    # push is — and ``allowed_from`` lists no self-transition. ``degraded -> active`` and
    # ``draft -> active`` are both in the machine and both stay: they are the first apply
    # and the retry after a failed one, which is every apply this product has.
    #
    # The condition names no state. What may serve again is the machine's to say, so
    # widening ``allowed_from`` widens this with it and nothing here has to be found and
    # edited — which is what a second copy of a safety rule always needs and never gets.
    if cannot_serve_again(node.state):
        raise NodeCannotServe(CANNOT_SERVE_AGAIN.format(state=node.state))

    # AND THE DOOR'S OWN ANSWER, asked second and on the same fresh read. The machine's
    # refusal above is about the node and comes first so that a ``retired`` node keeps the
    # sentence written for it — a host that is gone and a host that is being rebuilt are
    # two different next actions, and both reach a fan-out through the same credential
    # rows that outlive a node going out of service.
    #
    # Everything this refuses is legal and stays legal from the operator's own button. A
    # node that is ALREADY serving is unaffected whatever this flag says, which is the
    # whole of its blast radius: ``becoming_serving`` below is false for it, nothing is
    # minted, and the write of ``active`` at the end is the no-op it has always been.
    if only_if_serving and node.state not in NodeState.serving():
        raise NodeNotInService(NOT_IN_SERVICE_TO_PUSH.format(state=node.state))

    node_settings = settings()

    # The rows this apply is about, read once and used three times — M23, round 3. It was
    # ``render_for_node``'s own empty return that answered "is anything enabled here", and
    # that answer had to move above the render, because ``_take_into_service`` below runs
    # before the render and must not mint anything for a node with nothing to push.
    enabled = await enabled_transports(session, node)

    # NOTHING ENABLED IS NOT A FAILURE — M18.1, and the position of this check is the
    # whole of it. It sits ABOVE everything this function writes and OUTSIDE both try
    # blocks below, so the node's recorded state is not touched: a draft stays a draft and
    # an already-active node keeps serving its last config, which is the same asymmetry a
    # render failure has always had. Inside either block it would degrade the node, which
    # is exactly the outcome this step exists to remove.
    #
    # Before validation and before the compose file, because the compose file is where
    # the old answer came from: zero services renders an empty ``services:`` mapping,
    # which the daemon rejects, and the operator was handed that rejection.
    if not enabled:
        # AND THE HOST IS STILL REACHED, for the one thing a refusal must not leave
        # behind — M27.4. Everything else about this refusal is unchanged: no state is
        # written, nothing is rendered, nothing is pushed, and the node goes on serving
        # whatever it was last given. See ``_take_delivery_back`` for why a removal is
        # allowed on a path a push was refused on, and ``_nothing_to_apply`` for what the
        # operator is told in each of its three outcomes.
        raise NothingToApply(
            await _nothing_to_apply(
                session,
                node,
                delivery_material=await _take_delivery_back(node, node_settings),
            )
        )

    # Whether this apply is what PUTS the node into service, read before the line that
    # does it — M23. The answer is not "did the state change": a re-apply of an active
    # node changes nothing and must grant nobody twice.
    becoming_serving = node.state not in NodeState.serving()
    # THE FOURTH PLACE A NODE STARTS SERVING. ``nodes.set_node_state``,
    # ``nodes.enable_and_grant`` and ``nodes.set_transport_enabled`` are the other three,
    # and each hands every active user a credential on whatever has just become theirs to
    # reach. Above the render since round 3, so the file carries them — see
    # ``_take_into_service``, which is where the whole of that reasoning lives.
    granted = await _take_into_service(session, node, enabled) if becoming_serving else []

    configs = await render_for_node(session, node)

    # Which transport is behind each placed config. Needed from here down wherever the
    # answer is the TRANSPORT's rather than the file's — the checker, the extension, the
    # data plane — because since M15 a config's name and its transport's name can differ.
    #
    # ``placed_transports``' own mapping, built from the rows already in hand rather than
    # asked for a second time: that function IS this comprehension over
    # ``enabled_transports``, and it stays for the probe, which reaches the same answer
    # from a route that has no rows.
    placed = {row.config_name: row.transport_name for row in enabled}

    # AND WHERE EACH OF THEM SHOULD BE ANSWERING — M26's third acceptance walk. The same
    # expectation the probe is given (``placed_listeners``), resolved from the same two
    # sources: the port off the operator's own row, the protocols off the transport's
    # declaration. It is read here, before the connection, because it is a database
    # question and the block below is not the place to ask one.
    #
    # WHY AN APPLY ASKS IT AT ALL, when walk 2 decided it would not: the walk that
    # followed replaced a leaf's image with one whose data plane exits 0 doing nothing,
    # and the node's own compose command then holds the container up for ever. Container
    # liveness did not degrade as a signal there — it stopped being a signal about
    # serving at all, and the apply cleared a true probe finding on the strength of it.
    # See ``services/serving`` for the whole of that argument.
    listeners = await placed_listeners(session, node)

    # AND WHAT A USER WOULD FETCH FROM THIS HOST — M27.2. Rendered here, above the
    # connection, for ``listeners``' reason: it is a database question, asked over the
    # rows this apply is pushing so that the material describes the configuration the
    # host is about to be given rather than what the fleet was serving a moment ago.
    #
    # It carries no other node's material — see ``services/delivery``, which holds that
    # narrowing at its own seam.
    #
    # Rendered before it is known whether this host is a delivery host at all, and that
    # is deliberate rather than an oversight: the second half of that question is a
    # reading of the HOST (``delivery.is_delivery_host``) and cannot be asked above the
    # connection, while this is a database question and this is where those are asked.
    # What it costs on a host that turns out not to be one is a render that is thrown
    # away; what the alternative costs is a database read inside the connection block,
    # where a slow query holds a half-restarted node open.
    artifacts = await delivery.artifacts_for_node(session, node, enabled)

    for config_name, config in configs.items():
        # The FORMAT comes from the transport's own declaration, so the right checker
        # runs without this module knowing which protocol it is looking at.
        transport_name = placed[config_name]
        validate_before_push(
            transport_name, config, profile(transport_name).meta.config_format
        )

    # The configs themselves, not their names: each service carries the digest of its
    # own config as a label, which is what makes `docker compose up -d` recreate a
    # container whose config changed. Sorted so the rendered compose file is byte-stable
    # regardless of the order the transports were read in — an unstable one would
    # recreate every container on every apply.
    compose = node_stack.render_compose(
        transports=node_stack.services_for(
            {name: configs[name] for name in sorted(configs)}, transports=placed
        )
    )

    # Built before the connection, and its refusal RECORDED. A record that cannot
    # produce a session at all — no address, or a stored key the SSH layer will not load
    # — is not the half-configured window below: nothing has been written to the host.
    # But the node is still one the operator cannot reach, and the reason on its row has
    # to be the current one rather than whatever the previous attempt left there (M4.5).
    # Re-raised unchanged, so what is recorded and what is answered are one sentence.
    try:
        target = target_for(node, node_settings)
    except NodeOperationFailed as exc:
        await _record_failure(session, node, exc.message, granted)
        raise

    try:
        async with NodeConnection(target) as connection:
            # Persist a learned host key on the FIRST successful connection, so every
            # later connection is pinned and an interception fails loudly.
            if connection.learned_host_key and not node.ssh_host_key:
                node.ssh_host_key = connection.learned_host_key

            await node_stack.prepare(connection)
            for config_name, config in configs.items():
                await node_stack.place_config(
                    connection,
                    transport_name=placed[config_name],
                    config=config,
                    path=node_stack.config_path_of(config_name, placed[config_name]),
                )
            await node_stack.place_compose(connection, compose=compose)
            await node_stack.restart(connection)

            # Verify rather than assume, and verify the right thing. `docker compose
            # up -d` returns success as soon as the containers are created — a daemon
            # that starts and immediately exits on a bad config satisfies that and
            # serves nothing, and one that was never recreated satisfies it while
            # serving the PREVIOUS config, which is the fault M1 measured in the field.
            #
            # The reading answers with the digest each running container was created
            # with, so the comparison below is against what the process was started from
            # rather than against what is on disk beside it. Without it this function
            # wrote an ``applied_digest`` recording a state the node was not in — and a
            # revoked user stayed connected.
            #
            # AND IT IS WATCHED RATHER THAN SAMPLED — M26's second acceptance walk, and
            # it is the same fault one layer in. This line used to look ONCE, straight
            # after the restart above, at a container in the first second of its first
            # start: running, not yet restarting, and in a crash loop by the time the
            # operator read the row. The walk saw that twice, and saw the same check fire
            # the other way on a leaf whose container came up a moment later — degraded,
            # while that user's ping was 0% loss. ``services/serving`` is the whole of
            # the fix: two readings an interval apart, comparable because each says which
            # LIFE of the container it looked at, bounded by a ceiling, and nothing
            # confirmed that was not observed staying up. See that module for why a
            # longer sleep would not have been an answer.
            #
            # AND IT ASKS THE SOCKET QUESTION — M26's THIRD acceptance walk, which is
            # where that fix turned out to be half of one. A container staying up says
            # nothing about a node serving: the compose command this file generates keeps
            # the container alive for as long as the data plane's ``up`` returned 0,
            # whatever it did, so a data plane that does nothing successfully is up for
            # ever. The walk built exactly that image and the apply reported success over
            # a host with no tunnel device and 100% loss across its hop.
            settled = await serving.confirm_serving(
                connection,
                expected=configs,
                listeners=listeners,
                interval=node_settings.node_settle_interval,
                timeout=node_settings.node_settle_timeout,
            )
            loaded = settled.staying_up
            # A crash loop and a container that was never created are both "it did not
            # come up" to the operator, and they are one clause below because the repair
            # they need is the same one: read what the container itself printed on the
            # node. The two are kept apart in ``Settled`` because the probe tells them
            # apart and the two surfaces must not come to different vocabularies for one
            # host — this is where they meet, not where they are decided.
            not_running = sorted(set(settled.restarting) | set(settled.absent))
            # Its own clause, and in the probe's own words: a container that is up and
            # holds nothing sends the operator somewhere else entirely from one that will
            # not start. The third socket answer — nobody could ask — is deliberately NOT
            # here: a host without ``ss`` still applies, and what it costs is written at
            # the clearing of the probe finding below, which is the claim it actually
            # undermines.
            not_listening = list(settled.not_listening)
            stale = sorted(
                name
                for name, config in configs.items()
                if name in loaded and loaded[name] != node_stack.digest_of(config)
            )
            # What this apply may say it re-measured for itself. Read inside the
            # connection block because it is a property of the readings just taken, and
            # used far below, where the last probe's finding is either contradicted or
            # left standing.
            unchecked_ports = list(settled.unchecked)

            # THE DELIVERY MATERIAL, LAST — M27.2, and the position is the decision.
            # Placing it before the restart would put a file nothing reads between a
            # revocation and the daemon that is still authorising the person it
            # removed; nothing this pushes is worth delaying that by one step.
            #
            # Inside the connection block, so a failure here degrades the node like
            # every other write to a host does (core invariants §4) rather than being
            # swallowed. That is knowingly strict while nothing serves the directory:
            # a host whose data plane came back correctly can be marked degraded over
            # material no user can currently fetch. The alternative — carrying on and
            # logging — is the silent half-applied host this file exists to refuse.
            #
            # AFTER THE READINGS AND NOT AFTER THE VERDICT, which is not the same
            # thing: ``confirm_serving`` measures, and whether those measurements are a
            # failure is decided below this block. So a node whose data plane did not
            # come back is handed fresh material and then marked degraded. Deliberate —
            # what is placed is a function of the database and not of whether the
            # daemon came back, and withholding it would leave the STALER directory on
            # a host that is about to be repaired.
            #
            # AN EMPTY ``artifacts`` IS NOT SKIPPED: it is how a node that still has a
            # transport enabled but no longer carries anybody stops holding delivery
            # material.
            #
            # AND WHICH OF THE TWO CALLS BELOW IS MADE IS DERIVED — M27.4. A host that
            # is not a delivery host does not hold an emptied directory, it holds no
            # directory: the feature is ABSENT there rather than switched off, which is
            # what the co-located arrangements require and what the same call gives a
            # host that has STOPPED being one. ``is_delivery_host`` is the whole of the
            # decision and it takes no setting from anybody — see it for how both halves
            # are read off what is already true.
            if await delivery.is_delivery_host(connection, enabled=enabled):
                await node_delivery.place_delivery(connection, artifacts=artifacts)
            else:
                await node_delivery.remove_delivery(connection)

    except (NodeUnreachable, node_stack.NodeStackUnsupported) as exc:
        await _record_failure(session, node, str(exc), granted)
        raise NodeOperationFailed(
            f"the node could not be configured and has been marked degraded: {exc}"
        ) from exc
    except NodeOperationFailed:
        # Already carries a sentence written for the operator. Re-raised untouched so it
        # cannot fall into the arm below and be replaced by a type name — a failure
        # destroyed while being handled is the fault this whole milestone is about.
        raise
    except _NOT_PER_NODE:
        raise
    except Exception as exc:
        # This block is the ONLY window in which a node can be left half-configured: the
        # config files are placed one by one and the restart happens inside it. Core
        # invariants §4 is unconditional there — a partially applied node is marked
        # degraded, never left active — and it does not care whether the interruption
        # was a node that went quiet or a bug in this file. Without this arm an
        # unexpected error left the node ACTIVE and therefore still in every user's
        # subscription, pointing them at a daemon that may be mid-swap.
        #
        # Logged with its traceback BEFORE it is converted, for the same reason
        # ``render_for_node`` does it: a DomainError reaches the operator without a
        # stack, so this is the only place the bug is recoverable from. It is not new
        # exposure — until now this exception escaped to ``unhandled_error_handler``,
        # which logged the same traceback and answered 500.
        logger.exception("unexpected failure while configuring node %s", node.id)
        # Only the exception's TYPE, never ``str(exc)``, unlike the neighbouring arms.
        # Their messages are written by us or by ``edge`` and name no host; an arbitrary
        # exception from the SSH layer routinely carries the node's address, and this
        # string is both an API response and a stored ``state_detail`` (core invariants
        # §4: no host names cross the boundary). The full text is in the log above.
        reason = (
            f"an unexpected internal error ({type(exc).__name__}) interrupted the push, "
            "so what reached the node is unknown; the traceback is in the control "
            "plane's log"
        )
        await _record_failure(session, node, reason, granted)
        raise NodeOperationFailed(
            f"the node could not be configured and has been marked degraded: {reason}"
        ) from exc

    if not_running or not_listening or stale:
        # Three different faults, named separately because they send the operator to
        # different places: a container that never came up is a config the daemon
        # rejected, one that is up holding nothing is a daemon that started and bound
        # nothing, and one still on an older config is a definition Compose did not
        # consider changed. All three leave the node degraded — core invariants §4, and
        # the loud failure M1's second "done when" asks for.
        #
        # The middle clause is the probe's own sentence, word for word (``edge.health.
        # probe``): two surfaces reporting one fault about one host must not teach the
        # operator two vocabularies for it, and this is the fault M26's third walk
        # watched the apply report as success.
        detail = "pushed, but " + "; ".join(
            part
            for part in (
                f"these did not come up: {', '.join(not_running)}" if not_running else "",
                f"nothing listening on the port for: {', '.join(not_listening)}"
                if not_listening
                else "",
                f"still running an older configuration: {', '.join(stale)}" if stale else "",
            )
            if part
        )
        await _record_failure(session, node, detail, granted)
        # ``ConfigNotServing`` since M23, and the type is the whole of the change — this
        # sentence was already true on the apply banner. What was not true was the
        # revocation's, which composes from the KIND rather than from these words and had
        # no kind for "the push landed and the daemon did not come back on it": it fell
        # through to UNREACHED and told the operator the node could not be reached, about
        # a host whose file had just been replaced.
        #
        # ``ORPHANED_ON_THE_HOST`` joins it when this apply minted material — round 4. It
        # is deliberately on the RAISED sentence and not in ``detail``: ``detail`` becomes
        # ``state_detail``, which is 500 characters and already carries however many
        # transport names did not come up, and a warning cut off mid-clause by that
        # ceiling is worse than one the operator read once on the banner they are
        # looking at.
        not_serving = (
            f"configuration was applied but the node is not serving it — marked "
            f"degraded: {detail}"
        )
        raise ConfigNotServing(
            f"{not_serving} {ORPHANED_ON_THE_HOST}" if granted else not_serving
        )

    now = datetime.datetime.now(datetime.UTC)
    # Queried rather than read off ``node.transports``, for the same reason as in
    # ``render_for_node`` and with the same shape. On the revocation path this node did
    # not arrive from a fresh SELECT: it was reached through the relationships the
    # revocation's own queries loaded, so its ``transports`` collection is unloaded and
    # touching it is lazy I/O — which on an async session raises MissingGreenlet
    # instead of issuing a query. That error is not a NodeOperationFailed, so it
    # escaped ``apply_many`` and the operator was handed a 500 in place of the
    # RevocationOutcome naming which nodes still carry the withdrawn credential.
    # ``apply_many`` now reports such an error per node instead of ending the fan-out,
    # but the explicit query stays: a caught bug is still a node that was not updated.
    #
    # Filtered on the rendered names rather than on ``enabled``: what is recorded here
    # is what was actually pushed, and a transport disabled between the render and now
    # must not be given an applied digest it never received.
    applied = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.config_name.in_(sorted(configs)))
    )
    for node_transport in applied.scalars().unique():
        node_transport.applied_at = now
        node_transport.applied_digest = node_stack.digest_of(
            configs[node_transport.config_name]
        )

    # THE ONE PLACE THE STATE MOVES, past every failure arm above — which is the whole
    # of ``_take_into_service``'s second decision: the fan-out runs before the render and
    # still does not touch this column, so a push that failed leaves the node degraded by
    # ``_record_failure`` and never claims to have served.
    #
    # Written directly rather than through ``nodes.set_node_state``, which commits and
    # would cut this transaction in half — the applied digests, the audit entries and the
    # grants are one write with this. What that skips is the machine, and the guard at the
    # top of this function is what asks it instead: every state that reaches this line may
    # legally become active, or already is. The comment that stood here said
    # ``_take_into_service`` had already written ACTIVE; it had not, and has not since
    # round 3 of M23 — a reader who believed it would have concluded the machine was
    # consulted somewhere it was not.
    #
    # Written unconditionally rather than only when the node was not serving, because a
    # node that was ALREADY active still ends an apply active with no reason on its row:
    # the same two lines close both paths.
    node.state = NodeState.ACTIVE
    node.state_detail = None

    # AND THE LAST PROBE'S FINDING GOES WITH IT — but only where this apply actually
    # contradicted it. Three walks have argued about this line and the rule it now
    # follows is the third one's, stated once here because every future change to it will
    # be tempted by the same shortcut:
    #
    #     AN APPLY MAY ONLY CLEAR A FINDING IT HAS CONTRADICTED, WITH A MEASUREMENT OF
    #     THE SAME KIND.
    #
    # WHAT WALK 1 SAID, AND WHY IT WAS WRONG: "a successful apply clears the finding,
    # because step 5 verifies the daemon came back on the config it just pushed —
    # strictly more than a probe establishes." It was not strictly more: it concluded
    # from one sample of a container in the first second of its first start, so walk 2
    # watched an apply delete a true finding while measuring nothing.
    #
    # WHAT WALK 2 SAID, AND WHY THAT WAS WRONG TOO: that watching the containers stay up
    # made the finding obsolete rather than contradicted, and that re-asking the socket
    # question would widen an apply's failure surface for a reading with a "nobody could
    # ask" third state. Walk 3 falsified it in one press. The compose command this file
    # generates supervises a data plane with ``sleep 86400``, so a container whose ``up``
    # returned 0 having done nothing stays up for ever: a container holding a port and a
    # container holding nothing are not merely hard to tell apart by liveness, they are
    # INDISTINGUISHABLE to it, permanently. The apply cleared a probe finding that said
    # "nothing listening on the port for: amneziawg" over a host whose hop was at 100%
    # loss, and deleted it again on the next press.
    #
    # SO THE READING IS TAKEN. ``settled.unchecked`` is every placed config this apply
    # could not ask the port question about — no port on the row, no protocols declared,
    # or a socket table the node would not give up. The third state is handled rather
    # than used as a reason to skip the reading: a reading that could not be taken is not
    # a confirmation, so the finding stands and the row goes on saying so. The apply
    # itself still succeeds — refusing a host for a missing tool is the failure surface
    # walk 2 was right to refuse to widen.
    #
    # The timestamp is cleared rather than set to now even when everything was checked,
    # and that is what keeps the row honest. An apply is not a probe: it asks nothing
    # about the file on disk, and a time written here would read as "probed at 13:05 and
    # nothing was wrong". The row says what is true instead — that nobody has probed this
    # host since it was applied. ``console.COUNTERS_COUNT_CONFIGURATION`` is the sentence
    # that tells the operator which of the two clears a finding and what each one
    # establishes.
    if not unchecked_ports:
        node.last_probe_at = None
        node.last_probe_finding = None

    if becoming_serving:
        # RECORDED THE WAY ``set_node_state`` RECORDS IT — M23, round 3. A node going into
        # service is an audited event wherever it is reached from, and reached from this
        # button it produced no entry at all: the walk watched a node go draft -> active
        # with every user granted on it and nothing in the trail saying so.
        #
        # HERE rather than in ``_take_into_service``, and that is the point of the split.
        # An entry is written only past every failure arm above, so a push that failed
        # leaves no record claiming the node went into service — which is the same rule
        # the ``node-applied`` entry below already follows, and the same rule
        # ``_record_failure`` follows when it deletes what the fan-out minted.
        #
        # The state is a member of a closed enum and the node's name is the whole of the
        # rest: no reason, no transports, no digests. ``state_detail`` is 500 characters
        # that can carry a remote host's words and is deliberately not in this table.
        audit.record(
            session,
            AuditAction.NODE_STATE_CHANGED,
            first_label=node.name,
            second_label=str(NodeState.ACTIVE),
        )

    # Success only, and only here — past every failure arm above, which record nothing.
    # A push that failed is not a change that committed, and its reason is a sentence
    # that can come from a remote host; the node's own row carries it for the operator.
    # The node's name is the whole entry: not which transports, not their digests, not
    # how long it took.
    audit.record(session, AuditAction.NODE_APPLIED, first_label=node.name)

    await session.commit()
    logger.info("node applied: %s (%d transports)", node.id, len(configs))
    return configs


class NotUpdated(enum.StrEnum):
    """Why one node in a fan-out was not updated — a closed set, not a sentence.

    A caller that has to tell the operator what to DO about a node needs to know which of
    these it was, and it must not find out by reading the message: a refusal's message can
    carry an upstream checker's output, which is known to quote the node's private key
    (``validate_before_push``; docs/tracker/M9/carry-over.md). So the kind travels beside
    the message as a value, and a surface with nowhere safe for the message — the
    revocation banner — is composed from this and the node's name alone.
    """

    # The node dials a hop and its record names no resolver (M16): it cannot be rendered,
    # and nothing but setting the resolver changes that.
    NO_RESOLVER = "no-resolver"

    # Its configuration could not be produced, or the upstream checker refused it. Nothing
    # was pushed, and retrying changes nothing on its own.
    REFUSED = "refused"

    # The host WAS reached and its files were replaced, and the daemon did not come back
    # on them — M23. Its own kind because the operator's next move differs from both of
    # the others: nothing about the record needs to change, and "apply it again once it
    # can be reached" is advice about a node that was reached. What is unknown here, and
    # what makes it the more dangerous of the three, is that the process may still be
    # running the file that authorises the withdrawn credential.
    NOT_SERVING = "not-serving"

    # The node is not serving anyone and the operation that reached it was not aimed at
    # this node — M23, round 4. Nothing was pushed, deliberately: a fan-out does not put a
    # node into service. Its own kind because the operator's next move is unlike all three
    # above — nothing is wrong with the record and nothing is wrong with the push, and
    # what is needed is a decision they have not made yet about a host they parked.
    OUT_OF_SERVICE = "out-of-service"

    # The node is one the state machine will not put back into service — M23, round 12.
    # Its own kind because REFUSED, which it used to be, ends by sending the operator to
    # press apply and read why, and apply is precisely the button this node refuses: the
    # banner named a remedy the product does not have. Nothing was pushed, no apply will
    # push, and what is left is a decision about the HOST rather than about this record.
    CANNOT_SERVE = "cannot-serve"

    # Everything else: the host could not be reached, the push or its verification failed,
    # or something unexpected happened. The one kind a retry can fix.
    UNREACHED = "unreached"


@dataclass(frozen=True)
class NodeNotUpdated:
    """One node a fan-out did not update: the operator's sentence, and which kind it was."""

    # The DomainError's own message — what the API returns and rotation prints, as before.
    # Never composed into the revocation banner; see ``NotUpdated``.
    reason: str
    why: NotUpdated


def why_not_updated(exc: BaseException) -> NotUpdated:
    """Which kind of failure ``exc`` was, read off its TYPE and never off its text."""
    if isinstance(exc.__cause__, ResolverMissing):
        return NotUpdated.NO_RESOLVER
    # ``NothingToApply`` joins ``ConfigRefused`` here rather than falling through to
    # UNREACHED, and the case is real rather than defensive: a withdrawn row keeps its
    # minted credentials, so revoking the last user on a node whose only transport was
    # withdrawn re-pushes a node with nothing to render. "Could not be reached — apply it
    # again once it can be" would send the operator to retry a button that will refuse
    # for the same reason for ever. Nothing was pushed and retrying changes nothing,
    # which is precisely what REFUSED means.
    #
    # ``NodeCannotServe`` HAS ITS OWN KIND SINCE ROUND 12, and it used to be one of the
    # three above. The reasoning that put it there was right about everything except where
    # it sent the operator: a retired node does keep the credentials minted on it, so
    # revoking somebody who holds one does fan out to a node this control plane will not
    # push to again — but REFUSED's sentence ends "apply it from the Nodes screen to read
    # why", and apply on that node answers "this node is retired… the one move a retired
    # node is refused". The banner named a remedy the product refuses. Measured in round
    # 12's walk; the data was correct throughout, and only the sentence was wrong.
    if isinstance(exc, NodeCannotServe):
        return NotUpdated.CANNOT_SERVE
    if isinstance(exc, ConfigRefused | NothingToApply):
        return NotUpdated.REFUSED
    # Its own kind rather than REFUSED, and the difference is the whole of the operator's
    # next move — M23, round 4. REFUSED says "retrying will not change that", which is
    # true of a retired node and false of a parked one: an apply on a draft or degraded
    # node is precisely what completes this, and it is a button they can press today.
    # Checked after the three above only because these types are siblings, not relatives.
    if isinstance(exc, NodeNotInService):
        return NotUpdated.OUT_OF_SERVICE
    # Checked after ``ConfigRefused`` only because the two are siblings rather than
    # related; neither is an instance of the other. ``apply_node`` raises this one past
    # every connection arm, so reaching it means the push landed — M23.
    if isinstance(exc, ConfigNotServing):
        return NotUpdated.NOT_SERVING
    return NotUpdated.UNREACHED


async def apply_many(
    session: AsyncSession, node_transports: list[NodeTransport]
) -> dict[str, NodeNotUpdated | None]:
    """Apply every node named by a set of node-transports. Returns per-node outcome.

    Used by revocation, where several nodes must be re-pushed at once. Every node is
    attempted even if an earlier one failed — stopping at the first failure would
    leave a revoked user live on nodes that were perfectly reachable, which is the
    exact failure criterion 6 forbids. Failures are collected and reported, each as its
    message and its kind (``NodeNotUpdated``).

    A node that is NOT SERVING is not attempted at all and is reported as not updated —
    M23, round 4. This function is reached from an operation aimed at a person or at one
    transport's material, and putting a node back into service is neither; see
    ``NOT_IN_SERVICE_TO_PUSH`` for what that was measured to cost and for what refusing
    it costs in return.
    """
    outcomes: dict[str, NodeNotUpdated | None] = {}
    for node_id in dict.fromkeys(nt.node_id for nt in node_transports):
        try:
            # ``only_if_serving`` — M23, round 4, and this call is the only place it is
            # ever set. A fan-out is a consequence of an operation aimed at somebody's
            # access or at one transport's material, and it must not decide that a node
            # the operator took out of service is back in it. A node that IS serving is
            # applied here exactly as it always was.
            await apply_node(session, node_id=node_id, only_if_serving=True)
            outcomes[node_id] = None
        except DomainError as exc:
            # Recorded, not raised: the caller needs the whole picture to tell the
            # operator which nodes still carry the revoked credential.
            #
            # The whole family, not just ``NodeOperationFailed``: every DomainError
            # carries a message written for the operator, so reporting it costs nothing
            # and reveals nothing. ``NotFound`` — the node record deleted between the
            # revocation's query and its turn in the fan-out — used to end the fan-out
            # in a 500 for that reason alone.
            logger.error("apply failed for node %s during fan-out", node_id)
            outcomes[node_id] = NodeNotUpdated(reason=exc.message, why=why_not_updated(exc))
        except _NOT_PER_NODE:
            raise
        except Exception as exc:
            # Anything unexpected from OUTSIDE the push window: the queries and the
            # render before it, and the bookkeeping after it. ``apply_node`` handles the
            # window itself, where a half-configured node has to be degraded; here the
            # node is either untouched or fully configured, so its recorded state is not
            # wrong and nothing is written to it.
            #
            # The historical case is the second one and it is why this milestone exists:
            # a MissingGreenlet while recording what was applied ended the fan-out, and
            # the operator was handed a 500 instead of the RevocationOutcome naming
            # which nodes still carry the withdrawn credential. Every node after the
            # first failure went unreported and, as far as the operator could tell,
            # unattempted.
            #
            # Type only, no ``str(exc)``, for the reason given in ``apply_node``.
            logger.exception("unexpected failure applying node %s during fan-out", node_id)
            outcomes[node_id] = NodeNotUpdated(
                reason=(
                    f"this node was not updated because of an unexpected internal error "
                    f"({type(exc).__name__}); its state is unchanged and the traceback "
                    f"is in the control plane's log"
                ),
                why=NotUpdated.UNREACHED,
            )
            # Last, deliberately: the same ordering ``_record_failure`` uses. The
            # session is the only thing carried from one node to the next, and an
            # unexpected error can leave it needing a rollback — after which every
            # remaining node would fail with a database error that has nothing to do
            # with it. Rolling back discards nothing that matters: a successful apply
            # has already committed, and the revocation itself committed before the
            # fan-out started. If the rollback ITSELF fails the session is gone, and
            # that exception is left to propagate — no later node can even be read, so
            # continuing would invent failures rather than report them.
            await session.rollback()
    return outcomes


# Set once by the application factory. A module-level accessor rather than a
# parameter on every function because these are called from routes, from the panel
# and from revocation, and threading settings through all three adds a parameter
# nobody reads.
_settings_instance: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _settings_instance
    _settings_instance = settings


def settings() -> Settings:
    """The bound settings, or a loud failure. Public: services/health.py uses it."""
    if _settings_instance is None:
        raise RuntimeError("bind_settings() must run before any node operation")
    return _settings_instance
