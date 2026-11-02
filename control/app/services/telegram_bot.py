"""The owner's Telegram commands, and silence for everyone else — M37.2.

WHAT: ``handle_update`` — given one Telegram update, decide whether it is the owner's
      own message and, if it is, carry out the one command the bot has (``/adduser``) or
      answer with the usage line. Everything else about the bot — polling, sessions,
      backoff, the lifespan task — is the caller's (``services/telegram_poller``): this
      module opens no session, dials nothing but the replies, and starts no task.
WHY:  anyone can find a bot by name and message it, so the first thing this module does
      with an update is decide whether it is from the owner, and the decision is taken
      BEFORE any call is made and before any log line is written. A message from anybody
      else returns as if it had never arrived: no reply, no user, and no record naming the
      sender — a record of who tried is a record about a person, and this product keeps
      none (CLAUDE.md). The gate is three facts that all have to hold: the sender's id,
      the chat's id and the chat being private. The sender alone is not enough — the
      owner's id as ``from`` inside a group is the owner's words relayed to a room — and
      a forwarded message is refused even in the owner's own private chat, because its
      words are another account's.
HOW:  the add is ``onboarding.add_users``, exactly what the panel's dialog calls, with the
      text after ``/adduser`` split the way that dialog splits its box: one nickname per
      line. Two replies: "adding" first, because the add blocks for every node it pushes
      to and the owner is looking at a phone with no spinner on it; then the links, one
      block per person, built from ``console.links_for`` so the bot and the panel cannot
      hand a link over differently. A refusal — a ``DomainError`` out of the add — is
      answered with the service's own sentence, the one the panel shows, and that nothing
      was added; when the person already exists (``users.NicknameTaken``), one more
      sentence points at the panel for what the bot does not do (re-send an existing user's
      links). The order of the two replies is load-bearing: if the "adding" message cannot
      be sent, the add is NOT started and the failure propagates — a command whose
      acknowledgement could not reach its author is re-sent by its author when Telegram is
      back, and a user they never heard about is not.

      TELEGRAM CAPS A MESSAGE AT 4096 CHARACTERS and the client does not split. The reply
      here is packed into as many messages as it needs at BLOCK boundaries — a person's
      links stay in one message — falling back to line boundaries, then to a hard cut, for
      a block or a line that would not fit a message on its own, which no block built here
      can be (two links and a 64-character nickname is a few hundred characters). Rejected:
      one message per person, which for a pasted list of fifty is fifty sends into one chat
      and the rate limit Telegram applies to exactly that; and sending the whole reply and
      letting Telegram refuse it, which loses every link after the first 4096 characters.

      ONE AT A TIME is the caller's promise, not this module's mechanism: ``handle_update``
      is one plain coroutine that assumes it is awaited to completion before the next
      update is handed to it, and takes no lock of its own — two concurrent calls would
      interleave their replies. The serialisation lives where the updates are read, and a
      lock here would state the same rule a second time in the wrong place.

      THE LOG gets one line from this module, and only when the add has completed and the
      reply carrying the links could not be sent — the one state a person reading the log
      cannot otherwise reconstruct (the users exist and are pushed; the owner never saw
      the links). It carries the failure's own sentence and a count; never a nickname,
      a link or any text that was sent or received. Every other failure propagates as it
      is, for the caller to log once.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Iterator, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import DomainError
from control.app.models import User
from control.app.services import console, onboarding, users
from control.app.services.telegram_api import TelegramApi, TelegramCallFailed

logger = logging.getLogger(__name__)

# Telegram's own ceiling on one message's text, in characters. A constant and not a
# setting: it is the Bot API's, not this install's.
TELEGRAM_MESSAGE_LIMIT = 4096

# What the owner reads. Each is a module constant so the test that pins a reply and the
# runbook that quotes it read the same words as the code.
#
# The usage line answers ``/start``, ``/help``, a bare ``/adduser``, any text that is not
# a command, and any command this bot does not have — one answer for "what does this
# do", rather than a second sentence per way of asking.
USAGE = (
    "/adduser <nickname> — one nickname per line — adds them, pushes them to every "
    "serving node and replies with their links. Everything else is on the panel."
)
ADDING = "adding, about a minute per node"
# Under every refusal. True of each one: ``onboarding.add_users`` refuses before it
# commits, and the one refusal raised after a write has rolled that write back.
NOTHING_ADDED = "Nothing was added."
# After NOTHING_ADDED, and only when the person already exists — the one refusal whose
# answer is on the panel. It used to close every refusal, where under "a nickname must
# be 64 characters or fewer" it read as a non-sequitur (M37 acceptance).
SEE_THE_PANEL = "The panel shows every user and their links; the bot never re-sends a link."

# A command is the first token when it starts with ``/``: everything up to the first
# whitespace, then the rest of the text — whatever follows on the same line and every
# line after it. Nothing is lowered, so ``/adduser`` is the command and ``/Adduser`` is
# text; the one thing cut off the token is an ``@…`` tail, and ``_parse`` says why.
_COMMAND = re.compile(r"\A\s*(/\S+)(.*)\Z", re.DOTALL)

# One handler per command, all with ``_adduser``'s signature, so a command is one entry
# here and one function. The dispatch is a mapping rather than a chain of ``if`` so that
# adding a command changes nothing about how the others are found.
Handler = Callable[..., Awaitable[None]]


async def handle_update(
    session: AsyncSession,
    api: TelegramApi,
    update: dict[str, Any],
    *,
    owner_id: int,
    base_url: str,
) -> None:
    """Act on one update if, and only if, it is the owner's own message.

    ``owner_id`` is the one account this bot answers; ``base_url`` is what a link is
    built on (``settings.public_base_url``). Returns having replied, or having done
    nothing. Raises what a reply raises (``TelegramCallFailed``) and what an add raises
    that is not a refusal; a refusal is answered, not raised.
    """
    message = _the_owners_message(update, owner_id)
    if message is None:
        return
    chat_id: int = message["chat"]["id"]
    text = message.get("text")
    command, argument = _parse(text) if isinstance(text, str) else (None, "")
    handler = _COMMANDS.get(command) if command is not None else None
    if handler is None:
        await api.send_message(chat_id, USAGE)
        return
    await handler(session, api, chat_id, argument, base_url=base_url)


def _the_owners_message(update: dict[str, Any], owner_id: int) -> dict[str, Any] | None:
    """The update's message when the owner typed it into their private chat, else ``None``.

    Decided from the update alone, with nothing called and nothing logged on the way to
    ``None``: that is the whole of "silence for everyone else". ``owner_id`` itself is
    checked first, so a caller that passed nothing cannot turn this into a bot that
    answers anyone — the setting refuses that at boot, and this is the same refusal one
    layer down.
    """
    if type(owner_id) is not int or owner_id <= 0:
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    # Forwarded, under either of the Bot API's two shapes for it: the words are another
    # account's, whoever pressed forward.
    if "forward_origin" in message or "forward_date" in message:
        return None
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    if _id_of(sender) != owner_id or _id_of(chat) != owner_id:
        return None
    if chat.get("type") != "private":
        return None
    return message


def _id_of(record: dict[str, Any]) -> int | None:
    """The ``id`` field as the integer Telegram sends, or ``None`` for anything else."""
    value = record.get("id")
    return value if type(value) is int else None


def _parse(text: str) -> tuple[str | None, str]:
    """The command the text starts with and what follows it; ``None`` when it is not one.

    ``/command@botname`` is Telegram's own form for a command aimed at one bot — what a
    client sends in a group, and some send for a pick from the bot's menu — so the ``@``
    and everything after it on the token are dropped before dispatch: ``/adduser@x hank``
    adds ``hank``, and ``/adduser@x`` alone is a bare ``/adduser``. The tail is NOT
    compared to the bot's username: this module is never told it, and the only chat a
    message reaches here from is the owner's private one, where there is no second bot
    the tail could be telling apart. Before this, the token ended at the first
    non-word character and ``@hashi_e2e_bot`` went on to be the nickname.
    """
    match = _COMMAND.match(text)
    if match is None:
        return None, text
    token, rest = match.group(1), match.group(2)
    return token.partition("@")[0], rest


async def _adduser(
    session: AsyncSession, api: TelegramApi, chat_id: int, argument: str, *, base_url: str
) -> None:
    """Add the people named, one per line, and hand their links over."""
    # The panel's own split of its box (``panel/routes.py``): a line is a nickname, blank
    # lines are nothing, and what the service then refuses it refuses for both doors.
    wanted = [line.strip() for line in argument.splitlines() if line.strip()]
    if not wanted:
        await api.send_message(chat_id, USAGE)
        return
    # Sent BEFORE the add, and not inside a ``try``: see the module header for why a
    # failure here means no add.
    await api.send_message(chat_id, ADDING)
    try:
        outcome = await onboarding.add_users(session, nicknames=wanted)
    except DomainError as exc:
        await api.send_message(chat_id, _refusal(exc))
        return

    blocks = [await _links_block(session, base_url, user) for user in outcome.users]
    # The outcome's own summary when a node does not know them yet — and when no node was
    # told at all, which is the add whose link resolves to nothing until a node serves.
    # Not on the ordinary add: the links arriving after "adding" is the confirmation.
    if not outcome.complete or not outcome.nodes_updated:
        blocks.append(outcome.summary())
    try:
        for text in _messages(blocks):
            await api.send_message(chat_id, text)
    except TelegramCallFailed as exc:
        logger.warning(
            "telegram: %d user(s) were added, but the reply with their links could not be "
            "sent (%s); their links, and which nodes took them, are on the panel",
            len(outcome.users),
            exc,
        )


def _refusal(exc: DomainError) -> str:
    """The service's own sentence, then that nothing was added — and, when the person
    already exists, where they are.

    Told apart by the exception's TYPE, not its sentence: ``users.NicknameTaken`` is the
    service's own word for "this person exists", which is what the panel shows; every
    other refusal is the list itself being wrong, and the panel has nothing to show for
    that. Matching the sentence was rejected — it would hold until the service reworded
    it, and nothing here would go red. So was keying on ``Conflict``: a name twice on one
    list is a conflict too, and the pointer under it was the same non-sequitur.
    """
    if isinstance(exc, users.NicknameTaken):
        return f"{exc.message}\n\n{NOTHING_ADDED} {SEE_THE_PANEL}"
    return f"{exc.message}\n\n{NOTHING_ADDED}"


async def _links_block(session: AsyncSession, base_url: str, user: User) -> str:
    """One person's links as plain text: their nickname, then one labelled link per line.

    The same set the panel's dialog hands over after an add, and only the links: the
    dialog's sentences about what each one carries and who may hold it are read once on
    a screen, and would be read once per person in a chat. ``links_for`` answers ``None``
    for a person with no live subscription, which an add never produces; said rather than
    assumed, because this is the one place the bot would otherwise print nothing.
    """
    handed = await console.links_for(session, base_url, user)
    if handed is None:
        return f"{user.nickname}: no live subscription — see the panel"
    return "\n".join([user.nickname, *(f"{link.heading}: {link.url}" for link in handed.links)])


def _messages(blocks: Sequence[str], *, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Pack blocks into messages no longer than ``limit``, in order, blank lines between.

    A block that fits is never split; see ``_pieces`` for the two that do not.
    """
    messages: list[str] = []
    current = ""
    for text, glue in _pieces(blocks, limit):
        if current and len(current) + len(glue) + len(text) <= limit:
            current += glue + text
        else:
            if current:
                messages.append(current)
            current = text
    if current:
        messages.append(current)
    return messages


def _pieces(blocks: Sequence[str], limit: int) -> Iterator[tuple[str, str]]:
    """Each block with what joins it to the text before it, cut only where it must be.

    A block that fits a message is one piece, joined by a blank line. One that does not
    is its lines, joined by a newline, so each stays whole; a line that does not fit on
    its own is slices of the limit, joined by nothing, so no character is lost.
    """
    for block in blocks:
        if len(block) <= limit:
            yield block, "\n\n"
            continue
        glue = "\n\n"
        for line in block.splitlines():
            for start in range(0, max(len(line), 1), limit):
                yield line[start : start + limit], glue
                glue = ""
            glue = "\n"


_COMMANDS: dict[str, Handler] = {
    "/adduser": _adduser,
}
