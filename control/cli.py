"""The few things the owner does from a shell rather than the panel.

WHAT: ``hash-password`` (produce the value for ``HASHI_OPERATOR_PASSWORD_HASH``) and
      ``check-config`` (validate a rendered config with the upstream checker).
WHY:  the operator's password hash has to be generated somewhere, and it must not be
      an endpoint — an endpoint that hashes a password is an endpoint that receives
      passwords. A local command keeps the plaintext on the owner's own machine.
HOW:  ``python -m control.cli hash-password``. Reads the password from a prompt
      rather than from an argument, because a command-line argument is world-readable
      in ``/proc`` and lands in shell history.
"""

import argparse
import getpass
import pathlib
import sys

from control.app.crypto import hash_password
from edge import checker


def command_hash_password(_args: argparse.Namespace) -> int:
    """Prompt for a password twice and print its hash."""
    password = getpass.getpass("operator password: ")
    if len(password) < 12:
        # Not arbitrary: this single credential guards the panel that can read every
        # node's key, and there is no lockout (a deliberate decision — see
        # control/app/auth.py), so length is the whole defence.
        print("refusing: use at least 12 characters", file=sys.stderr)
        return 2
    if password != getpass.getpass("again: "):
        print("refusing: the two entries differ", file=sys.stderr)
        return 2

    print()
    print("Put this in .env (the hash, never the password):")
    print(f"HASHI_OPERATOR_PASSWORD_HASH={hash_password(password)}")
    return 0


def command_check_config(args: argparse.Namespace) -> int:
    """Validate a rendered config file with the upstream checker."""
    path = pathlib.Path(args.path)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    result = checker.validate(path.read_text())
    if not result.available:
        print(
            "no upstream checker installed, so nothing was verified. "
            "Install it: scripts/fetch-upstream-checkers.sh",
            file=sys.stderr,
        )
        return 3
    if not result.ok:
        print(result.output, file=sys.stderr)
        return 1
    print("the daemon accepts this configuration")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="control", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    hash_parser = commands.add_parser(
        "hash-password", help="generate HASHI_OPERATOR_PASSWORD_HASH"
    )
    hash_parser.set_defaults(handler=command_hash_password)

    check_parser = commands.add_parser(
        "check-config", help="validate a rendered node config with the upstream checker"
    )
    check_parser.add_argument("path")
    check_parser.set_defaults(handler=command_check_config)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
