"""The two questions M19 added to ``node-bootstrap.sh``, put to a REAL host.

WHAT: runs the script's own sshd checks against a real ``sshd -T`` — including the two
      host shapes no machine in this fleet has, an sshd that takes keys only from a
      command and one that will not take a key from this account at all — and its own
      kernel read against this machine's real ``/proc/sys``.
WHY:  both checks parse something somebody else prints, and the unit suite beside them
      (``tests/infra/test_node_bootstrap_script.py``) feeds them a stub. A stub can only
      ever repeat what its author believed the output looks like, which is the same
      mistake one layer down as the one M19.2 exists to fix: the script used to verify
      its own work by reading back the file it had just written. If OpenSSH renames
      ``authorizedkeysfile``, prints the unset command as something other than ``none``,
      or stops reporting a relative path, every assertion over there still passes and
      every node bootstrapped after that is told ``ready`` on a guess.

      The metadata-only host is the whole acceptance line of M19 and there is no such
      host to rent here: one is BUILT, from the real sshd binary and a config that has
      ``AuthorizedKeysCommand`` and no usable ``AuthorizedKeysFile``. That is the
      configuration, not a model of it — the answer comes out of OpenSSH.
HOW:  the script's checking half, cut where ``tests/infra`` cuts it, with its own three
      sshd functions appended and called in the run's own order. ``sshd`` on the run's
      PATH is a two-line shim that execs the REAL daemon with ``-f`` pointing at the
      config under test, so what the script asks and what answers it are both real; the
      only thing invented is which configuration that sshd is running.

Boundary, stated plainly:

  * **This does not run the whole script.** Everything after the cut installs a
    container runtime, edits a firewall and rewrites ``authorized_keys`` — on the
    machine running the suite. So it proves the two checks, not a bootstrap.
  * **Nobody logs in.** ``sshd -T`` is the daemon's statement of what it will consult;
    an actual authentication would need the private half of a key, and the private half
    never comes to a node (the script's property 4). What is proven is that the run
    cannot say ``ready`` for a key sshd will not read, or will read and then decline —
    which is M19's second "done when", and still not the same sentence as "this key logs
    in": the account lists, PAM and a locked account are outside everything asked here,
    and section G of the script's own header names them.
  * **The kernel half reads THIS machine**, which is not a node. It proves the read
    reaches a real setting, not that any particular host forwards.
"""

import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "node-bootstrap.sh"

# The same cut ``tests/infra/test_node_bootstrap_script.py`` uses, by the same string:
# everything before it is checks, and the first line after it changes the host. Written
# out rather than imported because pytest runs with ``--import-mode=importlib``, under
# which importing across test directories is not reliable — the same reason
# ``tests/e2e/edge/conftest.py`` exposes helpers as fixtures instead.
WHERE_THE_HOST_IS_FIRST_TOUCHED = "# --- 2. the container runtime"

# Shape only, and not a key: the script checks the shape of what it is handed and this
# file never presents it to anything that would verify it.
A_PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAthisisnotakey hashi-control"

# The account every host has, and the ``ssh_user`` default the panel offers — so the
# file the script would write to is ``/root/.ssh/authorized_keys``.
THE_ACCOUNT = "root"
THE_KEY_FILE = "/root/.ssh/authorized_keys"


def real_sshd() -> str:
    """The OpenSSH daemon on this machine, or a skip that says what is missing.

    A skip and not a failure, unlike the docker engine the scenarios beside this one
    demand: ``sshd`` is not a documented prerequisite of ``make verify`` and turning it
    into one would make the gate red on a laptop for a reason that has nothing to do
    with the change under test. The message names the package, because a scenario that
    is quietly not running is the failure this file exists to prevent one layer up.
    """
    found = shutil.which("sshd") or "/usr/sbin/sshd"
    if not pathlib.Path(found).is_file():
        pytest.skip(
            "no sshd on this machine, so the one thing that holds node-bootstrap.sh's "
            "key check against a REAL daemon did not run. Install openssh-server."
        )
    return found


def a_host_running(configuration: str, tmp_path: pathlib.Path) -> pathlib.Path:
    """A directory holding an sshd config and the throwaway host key it names.

    The key is generated per run and thrown away with the test directory. It is the
    daemon's own key and never a client's — ``sshd -T`` refuses to print anything
    without one, which is the only reason there is a key in this file at all.
    """
    if shutil.which("ssh-keygen") is None:
        pytest.skip("no ssh-keygen, so a throwaway host key cannot be made for sshd")
    host_key = tmp_path / "host_key"
    generated = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(host_key), "-N", ""],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert generated.returncode == 0, generated.stderr
    config = tmp_path / "sshd_config"
    config.write_text(f"HostKey {host_key}\n{configuration}\n")
    return config


def function_in(script: str, name: str) -> str:
    """One of the script's own shell functions, lifted out of the file by name."""
    found = re.search(rf"^{re.escape(name)}\(\) \{{\n(?:.*\n)*?^\}}$", script, re.M)
    assert found, f"the script no longer defines {name}() at the top level"
    return found.group(0) + "\n"


def run_the_key_check(config: pathlib.Path, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    """The script's own sshd key check, with a real sshd running ``config``.

    The shim is what makes this real rather than modelled: the script asks ``sshd -T``
    exactly as it does on a node, and what answers is OpenSSH — with ``-f`` appended so
    the daemon it describes is the one this scenario built. ``sudo`` is stubbed with one
    that runs what it is given, because nothing privileged happens before the cut.
    """
    script = SCRIPT.read_text()
    assembled = tmp_path / "node-bootstrap-key-check.sh"
    assembled.write_text(
        script[: script.index(WHERE_THE_HOST_IS_FIRST_TOUCHED)]
        + function_in(script, "sshd_effective_config")
        + 'SSHD_CONFIG="$(sshd_effective_config)"\n'
        + 'printf "SSHD SAID: %s\\n" "${SSHD_CONFIG}"\n'
        + function_in(script, "refuse_if_sshd_cannot_be_asked")
        + function_in(script, "refuse_if_this_account_cannot_use_a_key")
        + function_in(script, "refuse_if_sshd_ignores_the_key_file")
        + "refuse_if_sshd_cannot_be_asked\n"
        + "refuse_if_this_account_cannot_use_a_key\n"
        + "refuse_if_sshd_ignores_the_key_file\n"
        + 'say "ready"\n'
    )
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    (stubs / "sudo").write_text('#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n')
    (stubs / "sudo").chmod(0o755)
    (stubs / "sshd").write_text(f'#!/bin/sh\nexec {real_sshd()} "$@" -f {config}\n')
    (stubs / "sshd").chmod(0o755)
    return subprocess.run(
        ["bash", str(assembled), "--authorized-key", A_PUBLIC_KEY, "--user", THE_ACCOUNT],
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
        env={"PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(tmp_path)},
    )


def test_a_host_that_takes_keys_only_from_a_command_is_never_called_ready(
    tmp_path: pathlib.Path,
) -> None:
    """M19's acceptance line, against a real daemon in that exact configuration.

    This is the host one of this project's own field hosts nearly is: its keys come from
    instance metadata through an ``AuthorizedKeysCommand``, and it works only because its
    sshd ALSO sets ``AuthorizedKeysFile``. Take that second line away — which is all this
    configuration does — and the script's old check, reading back the file it had just
    written, said ``ready`` for a key that cannot authenticate.
    """
    config = a_host_running(
        "AuthorizedKeysFile none\n"
        "AuthorizedKeysCommand /usr/local/bin/keys-from-metadata %u\n"
        "AuthorizedKeysCommandUser nobody",
        tmp_path,
    )

    refused = run_the_key_check(config, tmp_path)

    assert refused.returncode != 0, (
        f"a real sshd that reads no key file at all was accepted:\n{refused.stdout}"
    )
    assert "==> ready" not in refused.stdout, refused.stdout
    # And it says why. A non-zero exit with nothing on either stream is the same defect
    # as a wrong answer — M18's acceptance found exactly that in this script.
    assert refused.stderr.strip(), f"refused in silence: stdout {refused.stdout!r}"
    said = " ".join(refused.stderr.split())
    assert "/usr/local/bin/keys-from-metadata" in said, said
    assert THE_KEY_FILE in said, said


def test_an_ordinary_host_is_not_refused_by_the_same_check(tmp_path: pathlib.Path) -> None:
    """The other half, and the one that keeps the refusal above from being unconditional.

    An sshd told nothing about authorized keys reports its default, and that default is a
    RELATIVE path — so this is also where the expansion is held against the real string
    OpenSSH prints rather than against the one this repository imagines it prints.
    """
    config = a_host_running("AuthorizedKeysFile .ssh/authorized_keys", tmp_path)

    accepted = run_the_key_check(config, tmp_path)

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "==> ready" in accepted.stdout, accepted.stdout


def test_a_host_that_will_not_take_a_key_from_this_account_is_never_called_ready(
    tmp_path: pathlib.Path,
) -> None:
    """The second way ``ready`` was said for a key that cannot log in, in real daemons.

    Each of these hosts reads exactly the file the script writes — the file half of the
    check says yes and is right to — and then declines the key anyway. The first shipped
    round of M19 answered only the file question and reported ``ready`` for all three.
    ``PermitRootLogin no`` is here with the account the panel's node form offers by
    default, which is what makes that pairing the likely one rather than the exotic one.
    """
    for configuration, named in (
        ("AuthorizedKeysFile .ssh/authorized_keys\nPubkeyAuthentication no",
         "PubkeyAuthentication"),
        ("AuthorizedKeysFile .ssh/authorized_keys\nAuthenticationMethods publickey,password",
         "publickey,password"),
        ("AuthorizedKeysFile .ssh/authorized_keys\nPermitRootLogin no", "PermitRootLogin"),
    ):
        # One directory per host, because ``a_host_running`` generates a host key into it
        # and ``ssh-keygen`` will not overwrite one — which, with no stdin, is a failure
        # inside the fixture rather than an answer about the script.
        host = tmp_path / named.replace(",", "-")
        host.mkdir()
        config = a_host_running(configuration, host)

        refused = run_the_key_check(config, host)

        assert refused.returncode != 0, (
            f"a real sshd carrying '{named}' was accepted:\n{refused.stdout}"
        )
        assert "==> ready" not in refused.stdout, refused.stdout
        assert refused.stderr.strip(), f"refused in silence: stdout {refused.stdout!r}"
        said = " ".join(refused.stderr.split())
        assert named in said, said
        assert THE_KEY_FILE in said, said


def test_the_daemon_still_answers_in_the_words_the_check_reads(tmp_path: pathlib.Path) -> None:
    """The directive names, read off a real ``sshd -T`` rather than assumed.

    The check greps five lines out of that output. If OpenSSH renames any of them, or
    stops printing ``none`` for a command it does not have, the checks above would still
    pass on their own configurations while the script silently stopped being able to
    answer the question on a real host. Asserted separately so the failure names the
    drift — and it is not a theoretical one: the value a person writes as
    ``prohibit-password`` is printed here under its older spelling, ``without-password``,
    and a check accepting only what the manual calls it would refuse a stock host.
    """
    config = a_host_running("AuthorizedKeysFile .ssh/authorized_keys", tmp_path)
    printed = run_the_key_check(config, tmp_path).stdout

    assert "SSHD SAID:" in printed, printed
    effective = printed.split("SSHD SAID:", 1)[1]
    assert re.search(r"^authorizedkeysfile ", effective, re.M), effective
    assert re.search(r"^authorizedkeyscommand none$", effective, re.M), effective
    for directive in ("pubkeyauthentication", "authenticationmethods", "permitrootlogin"):
        assert re.search(rf"^{directive} \S", effective, re.M), (
            f"a real sshd no longer prints {directive}, so the check that reads it is "
            f"silently answering nothing:\n{effective}"
        )


def test_the_kernel_settings_are_read_off_a_real_proc_sys(tmp_path: pathlib.Path) -> None:
    """``sysctl_value`` reaches a real setting, with nothing stubbed in front of it.

    The unit suite feeds this function a stub ``sysctl``, which proves what the script
    does with an answer and nothing about whether it can get one. Here it reads this
    machine's own kernel. The VALUES are not asserted — this machine is not a node, and a
    scenario that required the host running the suite to forward packets would be
    asserting something about the laptop rather than about the script.
    """
    script = SCRIPT.read_text()
    assembled = tmp_path / "node-bootstrap-kernel-read.sh"
    assembled.write_text(
        script[: script.index(WHERE_THE_HOST_IS_FIRST_TOUCHED)]
        + function_in(script, "sysctl_value")
        + 'printf "forwarding=[%s]\\n" "$(sysctl_value net.ipv4.ip_forward)"\n'
        + 'printf "filtering=[%s]\\n" "$(sysctl_value net.ipv4.conf.all.rp_filter)"\n'
        + 'printf "absent=[%s]\\n" "$(sysctl_value net.ipv4.no_such_setting_at_all)"\n'
    )
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    (stubs / "sudo").write_text('#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n')
    (stubs / "sudo").chmod(0o755)

    read = subprocess.run(
        ["bash", str(assembled), "--authorized-key", A_PUBLIC_KEY, "--user", THE_ACCOUNT],
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
        env={"PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(tmp_path)},
    )

    assert read.returncode == 0, read.stdout + read.stderr
    assert re.search(r"^forwarding=\[[0-9]+\]$", read.stdout, re.M), read.stdout
    assert re.search(r"^filtering=\[[0-9]+\]$", read.stdout, re.M), read.stdout
    # And a setting that is not there comes back empty rather than as some other value —
    # the case the refusal for an unreadable ``ip_forward`` is written for, and the one
    # that must not look like a number.
    assert re.search(r"^absent=\[\]$", read.stdout, re.M), read.stdout
