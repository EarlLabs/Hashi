"""Pre-rendered delivery material on a node: where it lives, and how it is replaced.

WHAT: the directory a node's pushed subscription artifacts are placed in, the name
      and path one artifact is written under, and the SSH sequence that REPLACES the
      whole of that directory in one step.
WHY:  M27. The control plane pre-renders what a user's client fetches and pushes it
      to a node over the channel that already exists, so a refresh does not have to
      reach the control plane's own host. Rendering needs the database and stays
      there; what arrives here is finished bytes and a name, and nothing in this
      module learns what is inside one.
HOW:  the placement is REPLACE, never merge — ``place_delivery`` writes into a
      staging directory and swaps it over the live one, so an artifact this control
      plane no longer renders is gone from the host at the end of the same call. That
      is the one property this module exists to provide and it is the reason the
      write does not simply target the live directory: an artifact is a rendered
      subscription, and one left behind after its user stopped holding a credential
      is a document that keeps being served to whoever can still fetch it.

      Nothing here opens a listening socket and nothing here serves the directory. A
      node that has been handed this material and has nothing reading it is the state
      this module leaves a host in.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from edge.bootstrap.node_stack import NODE_ROOT
from edge.bootstrap.ssh import NodeConnection
from edge.registry import SubscriptionFormat

# Where a node's pushed delivery material lives, and it is a SIBLING of the config
# directory rather than a subdirectory of it. ``node_stack.CONFIG_DIR`` is bind-mounted
# into every data-plane container by the compose file this package renders
# (``node-compose.yml.j2``), so an artifact placed under it would be readable by every
# daemon on the node — and these artifacts are other people's client configurations,
# which no transport's daemon has any reason to be able to read.
DELIVERY_DIR = f"{NODE_ROOT}/delivery"

# The two paths the replacement passes through, both beside the live directory so the
# final move is a rename WITHIN one filesystem, which is atomic. A staging directory
# somewhere else — /tmp, say — would make that last step a copy, and a half-copied
# delivery directory is exactly the state this sequence exists to make unreachable.
INCOMING_DIR = f"{DELIVERY_DIR}.incoming"
REPLACED_DIR = f"{DELIVERY_DIR}.replaced"

# The suffix each shape is written with. It is the only thing about an artifact that
# says which of the two shapes it is: the NAME is opaque to this zone, and both shapes
# of one subscription are written under the same one.
#
# Keyed by the subscription FORMAT, like everything else that dispatches on a shape
# rather than on a protocol — a transport is never named here and adding one adds
# nothing to this table.
ARTIFACT_EXTENSION = {
    SubscriptionFormat.V1_URI_LIST: ".txt",
    SubscriptionFormat.CLIENT_CONFIG_FILE: ".zip",
}

# What a name may be, checked rather than trusted. It is a SINGLE path segment with no
# dot and no separator in it, so a name can neither escape ``DELIVERY_DIR`` nor collide
# with the extension that is appended to it.
#
# The lower bound is not cosmetic and not a length rule for its own sake: whatever a
# caller derives this name from, it is the name a request will have to carry to reach
# the artifact, and a short one is a directory a stranger can enumerate. Sixteen
# characters of this alphabet is 96 bits, which is past enumeration; a caller passing
# something shorter has not derived it from anything.
ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class UndeliverableArtifact(Exception):
    """This artifact cannot be placed on a node as named, and no retry will help.

    Raised while building the PATH rather than on the node, for the reason
    ``node_stack.UnrunnableTransport`` is: it is a property of what the caller passed
    and is the same on every host, so the first person to see it should be whoever
    derived the name.
    """


@dataclass(frozen=True)
class Artifact:
    """One pre-rendered document, under the name it is placed and fetched by.

    ``content`` is bytes rather than text because one of the two shapes is an archive.
    Nothing in this zone parses it, and nothing here decides what goes in it — that
    keeps this module ignorant of what a subscription contains, which is what lets the
    same sequence carry a shape that does not exist yet.
    """

    name: str
    shape: SubscriptionFormat
    content: bytes


def artifact_path(
    name: str, shape: SubscriptionFormat, *, directory: str = DELIVERY_DIR
) -> str:
    """Where one artifact is written, by the name it is placed under.

    ``directory`` is how the staging copy is addressed: the same name resolves to the
    same relative path in both, so what is written under ``INCOMING_DIR`` is what
    appears under ``DELIVERY_DIR`` when the two are swapped, with nothing recomputed
    in between.
    """
    if not ARTIFACT_NAME.match(name):
        raise UndeliverableArtifact(
            f"{name!r} is not a name an artifact can be placed under — a name is 16 to "
            "128 characters from a-z A-Z 0-9 _ - and nothing else, so that it is one "
            "path segment and cannot name anything outside the directory it is written "
            "into"
        )
    return f"{directory}/{name}{ARTIFACT_EXTENSION[shape]}"


# Making the staging directory, from whatever state a previous interrupted call left
# it in. ``rm -rf`` first, because a leftover ``.incoming`` holds artifacts this call
# is not placing, and a swap would put them live.
_STAGE = f"rm -rf {INCOMING_DIR} && mkdir -p {INCOMING_DIR} && chmod 700 {INCOMING_DIR}"

# And the swap, which is the whole of "replace, never merge". The live directory is
# moved aside rather than deleted first, so the window in which neither exists is one
# rename long and a call that dies between the two leaves the previous material on
# disk under a name the next call clears.
#
# ``if`` rather than ``rm -rf`` on the live directory: the first call on a host has
# nothing there, and a conditional that is false is not a failure, whereas a missing
# operand to ``mv`` is.
_SWAP = (
    f"rm -rf {REPLACED_DIR} && "
    f"if [ -d {DELIVERY_DIR} ]; then mv {DELIVERY_DIR} {REPLACED_DIR}; fi && "
    f"mv {INCOMING_DIR} {DELIVERY_DIR} && "
    f"rm -rf {REPLACED_DIR}"
)


async def place_delivery(
    connection: NodeConnection, *, artifacts: Iterable[Artifact]
) -> None:
    """Make this host's delivery material be exactly ``artifacts``, and nothing else.

    Three steps and the last one is the reason for the first two: stage, write, swap.
    Writing into the live directory would make this call a merge, and a merge cannot
    take anything away — the material a host serves would then only ever grow, and
    would go on naming people who no longer hold a credential on it.

    AN EMPTY ``artifacts`` IS NOT A NO-OP. It is how a host stops holding delivery
    material at all: the staged directory is empty, the swap makes it the live one,
    and what was there is removed. That is the only removal path in this package, and
    it reaches exactly the hosts an apply still runs against — a node the control
    plane never applies again keeps whatever it was last given, which is true of every
    file this package places and is not something this call can change.

    0600 on every file, for the reason ``node_stack.place_config`` sets it: what is
    written here is a user's own configuration, and the account this runs as is not
    the only one on the host.
    """
    await connection.run(_STAGE)
    # Sorted so one set of artifacts always produces the same sequence of writes. It
    # changes nothing on the host — the files are independent — and it is what makes a
    # recorded trace of this call comparable with the next one's.
    for artifact in sorted(artifacts, key=lambda one: (one.name, one.shape)):
        await connection.write_file(
            artifact_path(artifact.name, artifact.shape, directory=INCOMING_DIR),
            artifact.content,
            mode=0o600,
        )
    await connection.run(_SWAP)
