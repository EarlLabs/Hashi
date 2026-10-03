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
    env_path: pathlib.Path,
    out: pathlib.Path,
    *,
    raw: bool = False,
    extra: tuple[str, ...] = (),
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
        [str(SCRIPT), "--env-file", str(env_path), "--out", str(out), *extra],
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



# --- M33: a host end that follows the env file, in both directions ---------------------
#
# Found switching the tunnel on, on the real host, 2026-10-03. Everything above proves
# the first run and the run that adds a device. What the field walk needed next was the
# run that REMOVES one, the run after the operator changed the port, and a device config
# a phone's QR decoder could read.


def peer_names(conf: pathlib.Path) -> list[str]:
    return re.findall(r"^# peer: (\S+)$", conf.read_text(), re.M)


def test_removing_a_device_removes_exactly_that_device_and_says_so(tmp_path) -> None:
    """Finding 4: deleting a name used to change nothing, so a lost phone kept its access.

    The run converges the host file to HASHI_MGMT_PEERS. Everything that is not the
    removed peer is byte-for-byte what it was — the host's keys, the obfuscation values
    and the other device's keys — because each of those is inside a config already on a
    device, and the other devices must keep working.
    """
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    three = f"{PEERS},tablet=10.77.0.4/32"
    assert run(env_file(tmp_path, HASHI_MGMT_PEERS=three), out).returncode == 0
    before = conf.read_text()

    result = run(
        env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32,tablet=10.77.0.4/32"), out
    )
    assert result.returncode == 0, result.stderr
    after = conf.read_text()

    assert peer_names(conf) == ["laptop", "tablet"]
    assert "10.77.0.3/32" not in after, "the removed device's route is still allowed"
    assert re.search(r"^==> removed phone \(10\.77\.0\.3/32\)", result.stdout, re.M), (
        "the run removed a device without saying which"
    )
    assert "PrivateKey" not in result.stdout.replace(str(conf), ""), (
        "removing a device handed out key material"
    )
    assert "systemctl reload awg-quick@awg-mgmt" in result.stdout, (
        "the run does not say how to load the removal into the running interface, so the "
        "device keeps its access until the next reboot"
    )

    def blocks(text: str) -> dict[str, str]:
        return {
            m.group(1): m.group(0)
            for m in re.finditer(r"^\[Peer\]\n# peer: (\S+)\n(?:[^\n]+\n?)*", text, re.M)
        }

    interface = before.split("\n[Peer]")[0]
    assert after.startswith(interface), "removing a device changed this host's own end"
    for name in ("laptop", "tablet"):
        assert blocks(after)[name].strip() == blocks(before)[name].strip(), (
            f"removing phone changed {name}'s peer, so {name} would stop working"
        )
    assert not after.endswith("\n\n"), "the rewrite left blank lines behind"
    assert "\n\n\n" not in after, "the rewrite left a double blank line where phone was"

    # And the converged file is a fixed point: the next run with the same list is a no-op.
    again = run(
        env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32,tablet=10.77.0.4/32"), out
    )
    assert again.returncode == 0, again.stderr
    assert conf.read_text() == after, "a converged file changed on the next identical run"
    assert "==> removed" not in again.stdout


def test_removing_the_last_listed_peer_leaves_a_file_the_next_add_extends_cleanly(
    tmp_path,
) -> None:
    """The last block is the one whose trailing blank line the rewrite has to drop."""
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    assert run(env_file(tmp_path), out).returncode == 0
    assert run(env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32"), out).returncode == 0
    assert peer_names(conf) == ["laptop"]
    assert conf.read_text().endswith("AllowedIPs = 10.77.0.2/32\n")

    result = run(
        env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32,phone2=10.77.0.3/32"), out
    )
    assert result.returncode == 0, result.stderr
    assert peer_names(conf) == ["laptop", "phone2"]
    assert "\n\n\n" not in conf.read_text()
    assert len(client_configs(result.stdout)) == 1


def test_a_device_can_take_a_removed_device_s_address(tmp_path) -> None:
    """The field collision: a new peer's address was "already used" by a retired one.

    Removal happens before addition, so swapping one device for another at the same
    address is one run rather than two — and no error about a device the operator has
    already taken out of the list.
    """
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    assert run(env_file(tmp_path), out).returncode == 0
    result = run(
        env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32,newphone=10.77.0.3/32"), out
    )
    assert result.returncode == 0, result.stderr
    assert peer_names(conf) == ["laptop", "newphone"]
    assert len(re.findall(r"^AllowedIPs = 10\.77\.0\.3/32$", conf.read_text(), re.M)) == 1


def test_a_peer_written_by_hand_is_converged_away_and_named_by_its_key(tmp_path) -> None:
    """The file says not to edit it; a block somebody added anyway is still a peer.

    It has no ``# peer:`` line, so it cannot be listed in HASHI_MGMT_PEERS, so it is
    not a device this deployment declares — and an undeclared way into the console is
    exactly what convergence is for. The message names it by public key, the one field
    every block has.
    """
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    assert run(env_file(tmp_path), out).returncode == 0
    stray = "STRAYSTRAYSTRAYSTRAYSTRAYSTRAYSTRAYSTRAY000="
    conf.write_text(
        conf.read_text() + f"\n[Peer]\nPublicKey = {stray}\nAllowedIPs = 10.77.0.9/32\n"
    )

    result = run(env_file(tmp_path), out)
    assert result.returncode == 0, result.stderr
    assert stray not in conf.read_text()
    assert stray in result.stdout and "removed an unnamed peer" in result.stdout
    assert peer_names(conf) == ["laptop", "phone"]


def test_moving_a_listed_device_to_a_new_address_is_refused_and_changes_nothing(
    tmp_path,
) -> None:
    """The address is inside the config on that device; "moving" it is a new config."""
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    assert run(env_file(tmp_path), out).returncode == 0
    before = conf.read_bytes()
    result = run(env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.9/32,phone=10.77.0.3/32"), out)
    assert result.returncode == 1
    assert "laptop" in result.stderr and "NEW name" in result.stderr
    assert conf.read_bytes() == before
    assert "PrivateKey" not in result.stdout


@pytest.mark.parametrize(
    ("key", "value", "file_value"),
    [
        ("HASHI_MGMT_PORT", "51999", "51821"),
        ("HASHI_MGMT_MTU", "1280", "1420"),
        ("HASHI_MGMT_ADDRESS", "10.88.0.1/24", "10.77.0.1/24"),
    ],
)
def test_an_env_file_that_no_longer_describes_the_host_end_is_refused(
    tmp_path, key: str, value: str, file_value: str
) -> None:
    """Finding 1: the old tunnel came back with a "kept" message after the port changed.

    Refused rather than rewritten, because each of the three is inside every device
    config already handed out. The message has to carry both values and the way out —
    the operator on the real host had neither.
    """
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    assert run(env_file(tmp_path), out).returncode == 0
    before = conf.read_bytes()

    peers = PEERS.replace("10.77.", "10.88.") if key == "HASHI_MGMT_ADDRESS" else PEERS
    result = run(env_file(tmp_path, **{key: value, "HASHI_MGMT_PEERS": peers}), out)
    assert result.returncode == 1, "a host end the env file disagrees with was kept"
    assert conf.read_bytes() == before, "the refusal changed the host file anyway"
    assert key in result.stderr
    assert file_value in result.stderr and value in result.stderr, (
        "the refusal does not show both values, so the operator cannot tell which is wrong"
    )
    assert f"mv {conf} {conf}.retired-" in result.stderr, (
        "the refusal does not say how to retire the old host end"
    )
    if key == "HASHI_MGMT_PORT":
        assert f"ufw delete allow {file_value}/udp" in result.stderr, (
            "the refusal does not name the OLD port's firewall rule"
        )
    assert "PrivateKey" not in result.stdout


def test_a_retired_host_end_is_started_over_with_new_keys(tmp_path) -> None:
    """The way out the refusal names: move the file aside and run again."""
    out = tmp_path / "management"
    conf = out / "awg-mgmt.conf"
    assert run(env_file(tmp_path), out).returncode == 0
    old_key = re.search(r"^PrivateKey = (\S+)$", conf.read_text(), re.M).group(1)

    conf.rename(out / "awg-mgmt.conf.retired-20261003")
    result = run(env_file(tmp_path, HASHI_MGMT_PORT="51999"), out)
    assert result.returncode == 0, result.stderr
    assert "ListenPort = 51999" in conf.read_text()
    assert re.search(r"^PrivateKey = (\S+)$", conf.read_text(), re.M).group(1) != old_key
    assert len(client_configs(result.stdout)) == 2, "every device needs its new config"


def test_a_name_listed_twice_is_refused(tmp_path) -> None:
    """A name is how a device is matched on every later run."""
    result = run(
        env_file(tmp_path, HASHI_MGMT_PEERS="laptop=10.77.0.2/32,laptop=10.77.0.3/32"),
        tmp_path / "management",
    )
    assert result.returncode == 1
    assert "twice" in result.stderr
    assert not (tmp_path / "management" / "awg-mgmt.conf").exists(), (
        "a refused list still created the host end"
    )


@pytest.mark.parametrize("name", ["../evil", ".hidden", "my phone", "a/b"])
def test_a_device_name_that_is_not_a_plain_token_is_refused(tmp_path, name: str) -> None:
    """With --configs-to a name becomes a file name, so it must not be a path."""
    result = run(
        env_file(tmp_path, HASHI_MGMT_PEERS=f"laptop=10.77.0.2/32,{name}=10.77.0.3/32"),
        tmp_path / "management",
    )
    # A space is stripped by the split (it was before M33 too), so "my phone" arrives
    # as "myphone" and is a legal name; every other case is refused.
    if name == "my phone":
        assert result.returncode == 0, result.stderr
        return
    assert result.returncode == 1
    assert "device name" in result.stderr


def test_every_byte_of_a_printed_device_config_is_ascii(tmp_path) -> None:
    """Finding 6: a phone's QR decoder misread the em dash in the config's first comment."""
    result = run(env_file(tmp_path), tmp_path / "management", raw=True)
    assert result.returncode == 0, result.stderr.decode()
    configs = re.findall(
        rb"^# hashi - management tunnel, device: .*?^PersistentKeepalive = 25$",
        result.stdout, re.M | re.S,
    )
    assert len(configs) == 2
    for config in configs:
        assert all(byte < 0x80 for byte in config), (
            "a device config carries a non-ASCII byte, which a QR decoder can misread"
        )


def test_configs_to_writes_one_private_file_per_new_device_and_prints_no_key(
    tmp_path,
) -> None:
    """Finding 6, the option: a file per device instead of the SSH session's scrollback.

    Property 3 holds in its exact form: the script writes each new device's config
    once, never a second time, and keeps nothing it could reprint — a re-run writes no
    file for a device that already has a peer.
    """
    out = tmp_path / "management"
    devices = tmp_path / "devices"
    result = run(env_file(tmp_path), out, extra=("--configs-to", str(devices)))
    assert result.returncode == 0, result.stderr
    assert "PrivateKey" not in result.stdout, "a key went to the terminal as well"
    assert sorted(p.name for p in devices.iterdir()) == ["laptop.conf", "phone.conf"]
    assert stat.S_IMODE(devices.stat().st_mode) == 0o700
    for path in devices.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        text = path.read_bytes()
        assert all(byte < 0x80 for byte in text)
        assert b"AllowedIPs = 10.77.0.1/32" in text
    host = (out / "awg-mgmt.conf").read_text()
    for path in devices.iterdir():
        key = re.search(r"^PrivateKey = (\S+)$", path.read_text(), re.M).group(1)
        assert key not in host, "a device's private key reached the host file"

    # The operator moved them to their devices. A re-run writes nothing.
    for path in devices.iterdir():
        path.unlink()
    again = run(env_file(tmp_path), out, extra=("--configs-to", str(devices)))
    assert again.returncode == 0, again.stderr
    assert list(devices.iterdir()) == []


def test_configs_to_never_overwrites_a_config_nobody_has_moved_yet(tmp_path) -> None:
    out = tmp_path / "management"
    devices = tmp_path / "devices"
    devices.mkdir()
    (devices / "phone.conf").write_text("an earlier device config\n")
    result = run(env_file(tmp_path), out, extra=("--configs-to", str(devices)))
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert (devices / "phone.conf").read_text() == "an earlier device config\n"
    assert not (out / "awg-mgmt.conf").exists(), "the refusal still created the host end"


def test_configs_to_is_refused_inside_the_repository(tmp_path) -> None:
    result = run(env_file(tmp_path), tmp_path / "management",
                 extra=("--configs-to", str(REPO / "not-a-real-directory")))
    assert result.returncode == 1
    assert "inside the repository" in result.stderr
    assert not (REPO / "not-a-real-directory").exists()


def test_the_root_commands_it_prints_name_the_real_file_and_survive_a_reboot(
    tmp_path,
) -> None:
    """Findings 2, 3 and 5, as the text an operator copies.

    ``~`` in a root shell is /root, so the path printed is absolute; the interface is a
    systemd unit, so it comes back after a reboot and a later change is a ``reload``;
    and ip_nonlocal_bind is what keeps a missing tunnel from failing the caddy
    container and the public delivery endpoint with it.
    """
    out = tmp_path / "management"
    result = run(env_file(tmp_path), out)
    assert result.returncode == 0, result.stderr
    conf = out / "awg-mgmt.conf"
    assert f"ln -sfn {conf} /etc/amnezia/amneziawg/awg-mgmt.conf" in result.stdout
    assert "~/" not in result.stdout
    for command in (
        "sudo systemctl enable --now awg-quick@awg-mgmt",
        "sudo systemctl reload awg-quick@awg-mgmt",
        "sudo ufw allow 51821/udp",
        "net.ipv4.ip_nonlocal_bind = 1",
    ):
        assert command in result.stdout, f"the run does not print {command!r}"


def test_a_relative_output_directory_is_printed_as_an_absolute_path(tmp_path) -> None:
    """The symlink root creates is resolved from root's directory, not the operator's."""
    env_path = env_file(tmp_path)
    result = subprocess.run(
        [str(SCRIPT), "--env-file", str(env_path), "--out", "management"],
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert f"ln -sfn {tmp_path}/management/awg-mgmt.conf " in result.stdout
