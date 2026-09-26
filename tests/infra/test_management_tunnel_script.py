"""The management tunnel generator — M7, and this one is RUN rather than read.

WHAT: runs ``scripts/management-tunnel.sh`` into a temporary directory and checks
      what it wrote and what it printed, plus a few static properties whose absence
      a passing run would not reveal.
WHY:  the other two bootstrap scripts are read rather than run (``read``, not
      ``execute`` — see ``test_panel_bootstrap_script.py``) because running them
      needs a docker engine and a host to install onto. This one needs neither: it
      generates keys, writes one file and prints text. So the division of labour
      that put "does it work" in the e2e tier does not apply here, and a test that
      only read the source would be strictly weaker for no saving.

      What is under test is the shape of the thing, and every property is one the
      decision of 2026-09-09 named: N peers rather than one, the obfuscated wire
      format rather than plain WireGuard, no forwarding and no NAT, and the owner's
      config printed exactly once and stored nowhere.
HOW:  each scenario writes its own env file and its own output directory. Skips
      loudly — never silently — when the host has neither ``wg`` nor ``openssl``,
      because a key cannot be generated without one and a vacuous pass here would
      be a claim about a script nobody ran.
"""

import os
import pathlib
import re
import shutil
import stat
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "management-tunnel.sh"

HOST_ADDRESS = "10.77.0.1/24"
PEERS = "laptop=10.77.0.2/32,phone=10.77.0.3/32"

pytestmark = pytest.mark.skipif(
    shutil.which("wg") is None and shutil.which("openssl") is None,
    reason="neither wg nor openssl is on this host, so no key can be generated — this "
           "is a skip rather than a pass because nothing was proved",
)


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


def env_file(directory: pathlib.Path, **overrides: str | None) -> pathlib.Path:
    """A complete env file, with keys removable by passing ``None``.

    Written per scenario rather than shared: half of what is under test is what the
    script does when a key is absent, and a shared file would have to be mutated,
    which is how two scenarios start depending on their order.
    """
    values: dict[str, str | None] = {
        "HASHI_MGMT_ADDRESS": HOST_ADDRESS,
        "HASHI_MGMT_PORT": "51821",
        "HASHI_MGMT_ENDPOINT": "panel.invalid",
        "HASHI_MGMT_MTU": "1420",
        "HASHI_MGMT_PEERS": PEERS,
    }
    values.update(overrides)
    path = directory / "mgmt.env"
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items() if value is not None)
    )
    return path


def run(
    env_path: pathlib.Path, out: pathlib.Path, *, raw: bool = False
) -> subprocess.CompletedProcess:
    """Run it exactly as the bootstrap does, with no TTY and no input.

    ``stdin`` is closed rather than inherited, which is the mechanism behind the
    "not one interactive question" property: a prompt anywhere would get EOF and
    fail here instead of hanging on a flaky SSH session in production.

    ``raw`` hands back bytes. ``text=True`` decodes with universal newlines, which
    turns a stray ``\r`` in a printed device config into a line break and hides the
    exact byte M28.13 is about — a test that cannot see the defect cannot pin it.
    """
    return subprocess.run(
        [str(SCRIPT), "--env-file", str(env_path), "--out", str(out)],
        capture_output=True,
        text=not raw,
        timeout=120,
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(out.parent)},
    )


@pytest.fixture
def generated(tmp_path: pathlib.Path):
    """One successful run, and the pieces every scenario below asks about."""
    out = tmp_path / "management"
    result = run(env_file(tmp_path), out)
    assert result.returncode == 0, f"the generator failed:\n{result.stderr}"
    return result, (out / "awg-mgmt.conf")


def client_configs(stdout: str) -> list[str]:
    """The device configs printed to the terminal, split apart.

    Anchored on the ``[Interface]`` header rather than on a progress line, because a
    progress line is prose and this is the thing whose absence would matter.
    """
    return re.findall(r"^\[Interface\]\n(?:.*\n)*?(?=^==> |\Z)", stdout, re.M)


def test_the_script_exists_and_is_executable() -> None:
    """A script that has to be invoked via `bash` is one an operator mistypes."""
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_it_fails_the_whole_run_on_any_error(script: str) -> None:
    """Without ``-u`` a typo in a variable name becomes an empty string in a key file."""
    assert re.search(r"^set -euo pipefail$", script, re.M)


def test_it_asks_no_questions(script: str) -> None:
    """Property 2. A prompt is a run that hangs until the SSH session dies."""
    assert not re.search(r"^\s*read\b", script, re.M), (
        "the script reads from somewhere; every input must come from the env file"
    )


def test_it_never_sources_the_env_file(script: str) -> None:
    """Sourcing runs it. A stray backtick in a value becomes a command on this host."""
    assert not re.search(r"^\s*(\.|source)\s+[\"']?\$\{?ENV_FILE", script, re.M)


def test_it_raises_no_interface_and_runs_nothing_as_root(script: str) -> None:
    """Property 4, checked at command position rather than in the prose.

    The script's own closing message names ``awg-quick`` as the operator's next step
    and explains why it is not this script's — so a presence check would match the
    explanation and pass for the wrong reason. Commands are at column zero or
    indented inside a block; a `say`/`fail` body is neither.
    """
    commands = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    commands = re.sub(r"\b(?:fail|say)\s+\"[^\"]*\"", " ", commands, flags=re.S)
    for verb in ("sudo", "awg-quick", "wg-quick", "ip link", "ip addr", "systemctl"):
        assert not re.search(rf"^\s*{re.escape(verb)}\b", commands, re.M), (
            f"the script runs {verb!r}. It writes files and prints; a script that "
            "raises an interface on the host it was reached over can lock you out of it"
        )


def test_it_refuses_to_write_key_material_into_the_repository(tmp_path) -> None:
    """A private key inside a checkout is one `git add -A` from being published."""
    result = run(env_file(tmp_path), REPO / "not-a-real-directory")
    assert result.returncode == 1
    assert "inside the repository" in result.stderr
    assert not (REPO / "not-a-real-directory").exists(), (
        "the script created the directory it then refused to use"
    )


def test_it_refuses_rather_than_defaulting_any_parameter(tmp_path, script: str) -> None:
    """A default here is a fleet-wide constant: a shared range, port, or MTU."""
    for key in (
        "HASHI_MGMT_ADDRESS",
        "HASHI_MGMT_PORT",
        "HASHI_MGMT_ENDPOINT",
        "HASHI_MGMT_MTU",
        "HASHI_MGMT_PEERS",
    ):
        path = env_file(tmp_path, **{key: None})
        result = run(path, tmp_path / f"out-{key}")
        assert result.returncode == 1, f"the script ran without {key}"
        assert key in result.stderr, f"the refusal does not name {key}"
        assert not re.search(rf"^\s*(export\s+)?{key}=", script, re.M), (
            f"the script supplies a default for {key}"
        )


def test_an_unknown_argument_exits_two(tmp_path) -> None:
    """Same contract as the other two bootstrap scripts (M11's notes)."""
    result = subprocess.run(
        [str(SCRIPT), "--tunnel-everything"],
        capture_output=True, text=True, timeout=30, cwd=REPO,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_this_host_gets_one_end_and_the_owner_gets_a_config_per_device(generated) -> None:
    """N peers by construction — the reason this is not a `node_transports` row.

    That shape carries ONE ``peer_tunnel_address`` and therefore serves exactly one
    device (M17, found in the field). An owner has a laptop and a phone, and being
    locked out of the console because you are holding the other one is the failure
    this milestone exists to prevent.
    """
    result, conf = generated
    assert conf.is_file(), "no host-side configuration was written"
    peers = re.findall(r"^# peer: (\w+)$", conf.read_text(), re.M)
    assert peers == ["laptop", "phone"], f"expected both devices as peers, got {peers}"

    configs = client_configs(result.stdout)
    assert len(configs) == 2, f"expected one printed config per device, got {len(configs)}"
    keys = re.findall(r"^PrivateKey = (\S+)$", "\n".join(configs), re.M)
    assert len(set(keys)) == 2, "two devices were given the same private key"


def test_no_peer_private_key_is_ever_written_to_disk(generated, tmp_path) -> None:
    """Property 3, stated as a fact about the filesystem rather than about intent.

    The private half of a device's key exists in the terminal that ran this and on
    the device it was imported into, and nowhere else. That is what makes "printed
    once" true: there is no copy to reprint, so a lost config is replaced by a new
    peer rather than recovered — which is also the safer answer.
    """
    result, conf = generated
    printed = re.findall(r"^PrivateKey = (\S+)$", result.stdout, re.M)
    assert printed, "no device config was printed at all"

    on_disk = "\n".join(
        path.read_text(errors="ignore")
        for path in conf.parent.rglob("*") if path.is_file()
    )
    host_key = re.search(r"^PrivateKey = (\S+)$", conf.read_text(), re.M)
    assert host_key, "the host's own config carries no private key"
    for key in printed:
        if key == host_key.group(1):
            continue
        assert key not in on_disk, (
            "a device's private key was written to disk — the only copies are meant to "
            "be the terminal and the device itself"
        )


def test_the_host_config_has_no_forwarding_and_no_nat(generated) -> None:
    """M14's rules must NOT be rendered here, and the plan says so in as many words.

    This tunnel carries traffic TO the host — an admin console — and never THROUGH
    it. A ``PostUp`` masquerade would quietly turn the management tunnel into an
    exit node, which is a change of what the host is, made by nobody.
    """
    # Directive lines only. The generated file EXPLAINS in its own comments that
    # these three are deliberately absent, so a plain substring search matches the
    # explanation and fails for describing itself — M11's notes call that out as the
    # mistake that teaches the next editor to delete the reason rather than keep the
    # property. Anchored at column zero, which is where a wg-quick directive lives.
    text = "\n".join(
        line for line in (generated[1]).read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    for directive in ("PostUp", "PostDown", "Table"):
        assert not re.search(rf"^{directive}\b", text, re.M), (
            f"the management tunnel renders {directive}, which belongs to a tunnel that "
            "carries traffic through a node. This one carries traffic to it."
        )


def test_a_device_is_routed_to_the_panel_host_and_not_to_the_internet(generated) -> None:
    """The client's ``AllowedIPs`` is the host's tunnel address, never a default route.

    The same field, the opposite answer from a user's exit config, because the
    consumer is different: a user wants everything to leave through the node, and
    the owner wants exactly one host reachable. A default route here would send the
    owner's whole internet into a host with no forwarding — which fails silently.
    """
    result, _ = generated
    for config in client_configs(result.stdout):
        allowed = re.findall(r"^AllowedIPs = (.+)$", config, re.M)
        assert allowed == ["10.77.0.1/32"], (
            f"a device config routes {allowed} into the management tunnel; it should "
            "reach the panel host and nothing else"
        )
        assert "0.0.0.0/0" not in config and "::/0" not in config


def test_the_wire_format_is_the_obfuscated_one_and_both_ends_agree(generated) -> None:
    """Junk packets and rewritten magic headers, identical on both ends.

    Plain WireGuard's handshake is fixed-shape and fingerprintable, which is what
    ТСПУ matches on, and this is the one tunnel that has to work when everything
    else is being blocked. The values are the wire format, not preferences: one
    mismatched header is a tunnel that never comes up, with nothing in any log to
    say why — because nothing here logs.
    """
    result, conf = generated
    fields = ("Jc", "Jmin", "Jmax", "H1", "H2", "H3", "H4")

    def values(text: str) -> dict[str, int]:
        return {
            field: int(re.search(rf"^{field} = (\d+)$", text, re.M).group(1))
            for field in fields
        }

    host = values(conf.read_text())
    for config in client_configs(result.stdout):
        assert values(config) == host, "a device's obfuscation values differ from the host's"

    headers = [host[field] for field in ("H1", "H2", "H3", "H4")]
    assert len(set(headers)) == 4, (
        "two magic headers are equal, so two message types are indistinguishable and "
        "the tunnel never comes up"
    )


def test_the_obfuscation_values_are_drawn_per_host_and_not_shared(tmp_path) -> None:
    """A set of values shared across the fleet would itself be the fingerprint.

    The same reasoning as a shared Reality decoy destination, and the reason edge's
    own Params validates these rather than defaulting them. Two independent runs
    stand in for two hosts.
    """
    def draw() -> tuple[int, ...]:
        out = tmp_path / f"host-{os.urandom(4).hex()}"
        result = run(env_file(tmp_path), out)
        assert result.returncode == 0, result.stderr
        text = (out / "awg-mgmt.conf").read_text()
        return tuple(
            int(re.search(rf"^{field} = (\d+)$", text, re.M).group(1))
            for field in ("Jc", "Jmin", "Jmax", "H1", "H2", "H3", "H4")
        )

    assert draw() != draw(), (
        "two hosts were given identical obfuscation values, so the values are a "
        "constant and the constant is the fleet's fingerprint"
    )


def test_what_it_generates_is_describable_by_this_project_s_own_transport(
    generated,
) -> None:
    """The generated values satisfy ``edge``'s AmneziaWG parameter rules.

    The tunnel is deliberately NOT a ``node_transports`` row, so nothing renders it
    through ``edge``. That freedom is also the risk: a junk-packet size or a magic
    header outside the range the project's own transport accepts would produce a
    config that no other part of hashi would ever have allowed, and nobody would
    notice until a device failed to connect. Reading the file back through the real
    ``Params`` is what keeps the two in step without coupling them.
    """
    from edge.transports.amneziawg.params import Params

    text = (generated[1]).read_text()

    def field(name: str) -> str:
        match = re.search(rf"^{name} = (.+)$", text, re.M)
        assert match, f"the generated config has no {name}"
        return match.group(1)

    key = re.search(r"^# PublicKey = (\S+)$", text, re.M).group(1)
    Params(
        port=int(field("ListenPort")),
        tunnel_address=field("Address"),
        peer_tunnel_address=re.search(r"^AllowedIPs = (\S+)$", text, re.M).group(1),
        # The same public key three times. This scenario is about the numbers, and
        # the private half is deliberately not read out of the file by a test.
        private_key=key,
        public_key=key,
        preshared_key=key,
        mtu=int(field("MTU")),
        junk_packet_count=int(field("Jc")),
        junk_packet_min_size=int(field("Jmin")),
        junk_packet_max_size=int(field("Jmax")),
        init_packet_magic_header=int(field("H1")),
        response_packet_magic_header=int(field("H2")),
        underload_packet_magic_header=int(field("H3")),
        transport_packet_magic_header=int(field("H4")),
    )


def test_a_second_run_changes_nothing_and_reprints_nothing(tmp_path) -> None:
    """Property 1, and the half of property 3 that a single run cannot show.

    A re-run must not regenerate the host's keys — every device already holding a
    config would stop working — and must not print a device's private key again,
    because it no longer has one to print.
    """
    out = tmp_path / "management"
    path = env_file(tmp_path)
    first = run(path, out)
    assert first.returncode == 0, first.stderr
    before = (out / "awg-mgmt.conf").read_bytes()

    second = run(path, out)
    assert second.returncode == 0, second.stderr
    assert (out / "awg-mgmt.conf").read_bytes() == before, (
        "a second run rewrote the host's configuration — every device already using "
        "the tunnel would stop working"
    )
    assert "PrivateKey" not in second.stdout, (
        "a second run reprinted key material it claims not to store"
    )
    assert "already a peer" in second.stdout


def test_adding_a_device_adds_exactly_that_device(tmp_path) -> None:
    """The laptop-and-then-a-phone case, which is why this takes N peers."""
    out = tmp_path / "management"
    run(env_file(tmp_path), out)
    conf = out / "awg-mgmt.conf"
    host_key_before = re.search(r"^PrivateKey = (\S+)$", conf.read_text(), re.M).group(1)

    result = run(env_file(tmp_path, HASHI_MGMT_PEERS=f"{PEERS},tablet=10.77.0.4/32"), out)
    assert result.returncode == 0, result.stderr

    assert re.findall(r"^# peer: (\w+)$", conf.read_text(), re.M) == [
        "laptop", "phone", "tablet",
    ]
    assert len(client_configs(result.stdout)) == 1, (
        "adding one device printed more than one config, so an existing device's key "
        "was regenerated"
    )
    assert re.search(r"^PrivateKey = (\S+)$", conf.read_text(), re.M).group(1) == \
        host_key_before, "adding a device rotated the host's own key"


def test_two_devices_cannot_be_given_one_address(tmp_path) -> None:
    """AllowedIPs is the routing table as well as the authorisation list.

    The second device silently takes over the first one's route and the first stops
    being reachable while still looking configured — the same refusal, for the same
    reason, as ``edge``'s ``AmbiguousPeerRoute``.
    """
    out = tmp_path / "management"
    result = run(
        env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32,phone=10.77.0.2/32"),
        out,
    )
    assert result.returncode == 1
    assert "already used by another device" in result.stderr


def test_the_files_it_writes_are_readable_only_by_their_owner(generated) -> None:
    """This file is the only copy of the host's tunnel private key."""
    _, conf = generated
    assert stat.S_IMODE(conf.stat().st_mode) == 0o600, "the host config is not 0600"
    assert stat.S_IMODE(conf.parent.stat().st_mode) == 0o700, "the directory is not 0700"


# --- the env file as somebody else's editor saved it ---------------------------
#
# Everything above writes a clean env file: LF line endings, bare values, one
# assignment per key. That is the file this script's author tested with and the file
# every scenario here produced for eleven milestones, and a parser is never wrong on
# that file — it is wrong on the file an operator saves from a Windows editor while
# rebuilding a host from their laptop, or after pasting a quoted value, or after
# leaving the first line in place and adding a corrected one under it. M28.12 round 1
# named the class (step-notes item 9) and left this script's copy of the weak parser
# for M28.13 to close.


def edited_env(directory: pathlib.Path, transform, **overrides: str | None):
    """The complete env file above, re-saved the way some other editor saves it.

    Bytes rather than text on the way out, because the transform under test is a line
    ending: ``write_text`` would translate it back on some platforms and the scenario
    would prove nothing.
    """
    path = env_file(directory, **overrides)
    path.write_bytes(transform(path.read_text()).encode())
    return path


def test_a_crlf_env_file_puts_no_carriage_return_in_the_tunnel(tmp_path) -> None:
    """The operator filled everything in correctly and the tunnel still does not come up.

    This is not the credential leak M28.12 closed — every value here is genuinely
    configured. It is config corruption: ``\\r`` is not whitespace to bash's default
    ``IFS`` and it is not a comment to AmneziaWG, so it lands inside ``Address``,
    ``ListenPort``, ``MTU`` and ``Endpoint``, in this host's own file AND in every
    device config the operator pastes onto a phone. The symptom is a handshake that
    never completes from a file that looks right in every editor that hides the byte.
    """
    out = tmp_path / "management"
    result = run(edited_env(tmp_path, lambda text: text.replace("\n", "\r\n")), out, raw=True)
    assert result.returncode == 0, result.stderr.decode()

    conf = (out / "awg-mgmt.conf").read_bytes()
    assert b"\r" not in conf, "a carriage return reached this host's own tunnel config"
    for line in (b"Address = 10.77.0.1/24", b"ListenPort = 51821", b"MTU = 1420"):
        assert line + b"\n" in conf, f"{line!r} is not what the env file said"

    # The half that leaves this machine. Anchored on the endpoint because that is the
    # value the defect was reproduced on, and on each peer's own address because the
    # comma split runs under an IFS that does not include `\r` either.
    assert b"\r" not in result.stdout, "a carriage return reached a printed device config"
    assert result.stdout.count(b"Endpoint = panel.invalid:51821\n") == 2, (
        "the endpoint an operator pastes onto a device is not the one they configured"
    )
    for address in (b"10.77.0.2/32", b"10.77.0.3/32"):
        assert b"AllowedIPs = " + address + b"\n" in conf
        assert b"Address = " + address + b"\n" in result.stdout


def test_the_last_assignment_of_a_key_is_the_one_used(tmp_path) -> None:
    """An env file means the last one, and so does compose reading the same file.

    Correcting a value by adding a line under it is ordinary, and the two readers of
    this file disagreeing about which line won is a tunnel built from a value nothing
    else on the host is using.
    """
    out = tmp_path / "management"
    result = run(
        edited_env(tmp_path, lambda text: text + "HASHI_MGMT_MTU=1280\n"), out
    )
    assert result.returncode == 0, result.stderr
    assert "MTU = 1280" in (out / "awg-mgmt.conf").read_text()
    assert "MTU = 1420" not in result.stdout, (
        "a device was handed the corrected line's predecessor"
    )


def test_a_quoted_value_arrives_without_its_quotes(tmp_path) -> None:
    """Quoting is how compose is told a value has a space in it, so it is legal here."""
    out = tmp_path / "management"
    result = run(
        edited_env(
            tmp_path,
            lambda text: text.replace(
                "HASHI_MGMT_ENDPOINT=panel.invalid", 'HASHI_MGMT_ENDPOINT="panel.invalid"'
            ),
        ),
        out,
    )
    assert result.returncode == 0, result.stderr
    assert "Endpoint = panel.invalid:51821" in result.stdout
    assert '"' not in result.stdout


def test_a_trailing_comment_is_not_part_of_the_value(tmp_path) -> None:
    """`.env.example` itself annotates keys this way, so an operator's file will too."""
    out = tmp_path / "management"
    result = run(
        edited_env(
            tmp_path,
            lambda text: text.replace(
                "HASHI_MGMT_MTU=1420", "HASHI_MGMT_MTU=1420  # 1420 is the AmneziaWG default"
            ),
        ),
        out,
    )
    assert result.returncode == 0, result.stderr
    assert "MTU = 1420\n" in (out / "awg-mgmt.conf").read_text()
    assert "default" not in (out / "awg-mgmt.conf").read_text(), (
        "the comment became part of the MTU"
    )
