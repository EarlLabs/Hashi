"""Is a new protocol really one directory? — charter criterion 4, backlog item 30.

WHAT: creates a transport package that does not exist in this repository, in a throwaway
      copy of the tree, and proves the fleet picks it up whole — discovered, validated,
      rendered, serialised for a user, and offered by the panel's own form builder —
      with no edit anywhere else.
WHY:  criterion 4 is the hypothesis the entire design rests on: "a new protocol is one
      new package under edge/transports/ and not surgery". Until now it was tested only
      indirectly — the neighbouring scenarios prove the IMAGE ships what the TREE
      contains, which is a statement about packaging, not about surgery. Nothing put a
      genuinely new package down and checked that nothing else had to move.
HOW:  the tree is copied to a temporary directory, the new package is written INTO THE
      COPY, and everything runs in a subprocess with that copy first on ``sys.path``.

      The copy is the whole method, for two reasons. The repository is never modified, so
      a failing run leaves nothing behind. And "no surgery" becomes checkable by
      comparison: every file the copy shares with the real tree must be byte-identical
      afterwards, so the only difference is the directory that was added. The scenario
      therefore never reads a git diff and does not know what commit it is on — which the
      backlog requires of an acceptance scenario (revision 2, finding F1).

Boundary: no booted stack, no node, no daemon. This is about what the LIBRARY and the
control plane's own form builder do with a package they have never seen. That the built
image would also ship it is the neighbouring scenario's job, and that the rendered config
is one a daemon accepts is tests/edge/test_upstream_validation.py's.
"""

import filecmp
import json
import pathlib
import shutil
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# The name is deliberately not a real protocol: nothing in the fleet must have special
# knowledge of it, and a plausible name would make a reader wonder whether something
# somewhere recognised it.
NEW_TRANSPORT = "acme_tunnel"
NEW_TRANSPORT_NAME = "acme-tunnel"


def _package_files() -> dict[str, str]:
    """The whole new transport: four files, and none of them outside its own directory.

    Written out here in full rather than generated from a template, because the point of
    the scenario is what a transport author actually has to write. If this got shorter by
    borrowing from an existing package, the count would stop meaning anything.
    """
    return {
        "__init__.py": '"""A transport that exists only inside one acceptance run."""\n',
        "meta.py": textwrap.dedent(
            '''
            """What `control` may know about a protocol it has never heard of."""

            from edge.registry import (
                ConfigFormat,
                Datapath,
                KeyKind,
                KeyScope,
                KeySpec,
                Layer4,
                SubscriptionFormat,
                TransportMeta,
            )

            META = TransportMeta(
                name="acme-tunnel",
                family="tcp-tls",
                listens_on=frozenset({Layer4.TCP}),
                needs_tls=True,
                port_range=(443, 65535),
                config_format=ConfigFormat.XRAY_JSON,
                key_material=(
                    KeySpec(
                        name="private_key",
                        kind=KeyKind.X25519_KEYPAIR,
                        scope=KeyScope.NODE,
                        public_name="public_key",
                    ),
                    KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
                ),
                subscription_formats=frozenset({SubscriptionFormat.V1_URI_LIST}),
                # M25: this renderer terminates the consumer's connection and opens its
                # own (it calls ``egress.exit_origin`` below), so it says so — which is
                # what lets a node that dials a hop offer it to users. One more line in
                # the same file, which is the whole of what the eighth widening costs an
                # author; a package that leaves it out is held to the restrictive answer
                # rather than being accepted and refused at an apply.
                datapath=Datapath.RE_ORIGINATING,
            )
            '''
        ).lstrip(),
        "params.py": textwrap.dedent(
            '''
            """The knobs an operator types, validated by this package and nowhere else."""

            from pydantic import BaseModel, ConfigDict, Field, field_validator

            from edge.transports.acme_tunnel.meta import META


            class Params(BaseModel):
                model_config = ConfigDict(extra="forbid", frozen=True)

                port: int
                server_name: str = Field(min_length=1)
                private_key: str = Field(repr=False)
                public_key: str

                @field_validator("port")
                @classmethod
                def _port_in_declared_range(cls, value: int) -> int:
                    return META.clamp_port(value)
            '''
        ).lstrip(),
        "render.py": textwrap.dedent(
            '''
            """Pure rendering, through the same environment every transport uses."""

            from collections.abc import Mapping, Sequence

            from edge.egress import Egress, exit_origin
            from edge.node import Credential, NodeView
            from edge.registry import ClientEntry
            from edge.templating import environment_for
            from edge.transports.acme_tunnel.meta import META

            _TEMPLATES = environment_for(__file__)


            def render_server(
                node: NodeView,
                params: Mapping[str, object],
                clients: Sequence[Credential] = (),
                *,
                egress: Egress = Egress.NONE,
                exit_via: str | None = None,
            ) -> str:
                # Both are part of the contract every transport takes, whether or not its
                # data plane can act on them — see edge/egress.py. This one proxies rather
                # than forwarding in the kernel, so it renders no rule; where it opens its
                # connections FROM is the whole of its answer.
                return _TEMPLATES.get_template("server.j2").render(
                    node=node,
                    params=params,
                    exit_origin=exit_origin(egress, exit_via),
                    clients=[{"subject": c.subject} for c in clients],
                )


            def render_client(
                node: NodeView,
                params: Mapping[str, object],
                credential: Credential,
            ) -> ClientEntry:
                return ClientEntry(
                    entry=(
                        f"acme://{credential.subject}@{node.address}:{params['port']}"
                        f"?sni={params['server_name']}&pbk={params['public_key']}"
                    ),
                    display_label=node.display_name,
                    country_label=node.location_label,
                    node_id=node.id,
                )


            __all__ = ["META", "render_client", "render_server"]
            '''
        ).lstrip(),
        "server.j2": (
            '{"log": {"loglevel": "warning", "access": "none"}, "inbounds": '
            '[{"tag": "in", "protocol": "vless", "listen": "0.0.0.0", '
            '"port": {{ params.port | tojson }}, "settings": {"clients": '
            "[{% for client in clients %}{\"id\": {{ client.subject | tojson }}}"
            '{% if not loop.last %}, {% endif %}{% endfor %}], "decryption": "none"}}], '
            "{% if exit_origin %}"
            '"outbounds": [{"tag": "hop", "protocol": "freedom", "sendThrough": '
            "{{ exit_origin | tojson }}}]}\n"
            "{% else %}"
            '"outbounds": [{"tag": "direct", "protocol": "freedom"}]}\n'
            "{% endif %}"
        ),
    }


# Runs inside the copy. Exercises the whole path a real transport takes, including the
# control plane's own form builder — importing `control` from an edge-owned scenario is a
# deliberate boundary cross, because the claim under test is precisely "`control` needs no
# change", and only calling it can show that.
PROBE = textwrap.dedent(
    """
    import json

    from control.app.services import transports as control_transports
    from edge.bootstrap import node_stack
    from edge.node import Credential, NodeView
    from edge.registry import SubscriptionFormat, discover, profile

    name = "acme-tunnel"
    node = NodeView(
        id="99999999-9999-4999-8999-999999999999",
        address="192.0.2.99",
        location_label="Testland",
        display_name="leaf-brand-new",
        resolver=None,
    )

    found = discover()
    transport = profile(name)
    params = transport.validate(
        {
            "port": 8500,
            "server_name": "front.example.com",
            "private_key": "wEJ0aXpBQlFtNVFDbEZLTFVqRXFRUlRLZXJhcXZJZ0k",
            "public_key": "0Rf8h2v0aFVQVGxLZ0VNQmxwQVVCMFJmOGgydjBhRlY",
        }
    )
    credential = Credential(subject="aaaaaaaa-0000-4000-8000-000000000001")
    entry = transport.serialise(SubscriptionFormat.V1_URI_LIST, node, params, credential)
    server_config = transport.profile.render_server(node, params, [credential])

    print(json.dumps({
        "discovered": sorted(found),
        "server_config": server_config,
        "entry": entry.entry,
        # What the panel's "enable a transport" form would ask the operator for. Derived
        # from the new package's own model minus what is minted for them.
        "operator_params": control_transports.operator_params(name),
        # And the daemon the node would run it under, from the format it declared.
        "data_plane": node_stack.services_for({name: server_config})[0]["image"],
    }))
    """
)


def plant_a_copy(destination: pathlib.Path) -> pathlib.Path:
    """Copy the packages under test into ``destination`` and add the new transport."""
    for package in ("edge", "control"):
        shutil.copytree(
            REPO_ROOT / package,
            destination / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    directory = destination / "edge" / "transports" / NEW_TRANSPORT
    directory.mkdir()
    for filename, content in _package_files().items():
        (directory / filename).write_text(content)
    return directory


def run_probe(root: pathlib.Path) -> dict:
    """Run the probe with ``root`` first on the path, and fail loudly with its output."""
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=root,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, (
        "a brand-new transport package broke the fleet it was dropped into:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_package_nobody_has_seen_is_discovered_rendered_and_offered(tmp_path) -> None:
    """S1. One directory, and everything downstream works.

    Every assertion below is something a transport author would otherwise have to
    discover by deploying: that discovery finds it, that its own model validates the
    operator's input, that it renders, that it serialises into the subscription format it
    declared, that the panel can build a form for it, and that a daemon is pinned to run
    the format it chose. None of it required a line outside the new directory.
    """
    root = tmp_path / "tree"
    root.mkdir()
    plant_a_copy(root)

    probed = run_probe(root)

    assert NEW_TRANSPORT_NAME in probed["discovered"], probed["discovered"]
    # The transports already in the tree are still there: a new package must not shadow
    # or displace anything.
    assert {"vless-reality", "vless-ws-tls", "amneziawg", "wireguard"} <= set(
        probed["discovered"]
    ), probed["discovered"]

    # It rendered a complete config, and the user's own entry carries this transport's
    # scheme — which nothing outside its package knows about.
    assert json.loads(probed["server_config"])["inbounds"][0]["port"] == 8500
    assert probed["entry"].startswith("acme://")
    assert "aaaaaaaa-0000-4000-8000-000000000001" in probed["entry"]

    # The panel would ask for exactly the fields the new package declared and did NOT ask
    # for the key material, which is minted. This is criterion 4's "selectable in the
    # panel without modifying the control plane's core", asserted by calling the code the
    # panel calls.
    assert probed["operator_params"] == ["port", "server_name"], probed["operator_params"]

    # And a data plane is pinned for the format it declared, so the node would actually
    # run it rather than place a file nothing reads.
    assert probed["data_plane"]


def test_nothing_outside_the_new_directory_had_to_change(tmp_path) -> None:
    """The other half of "not surgery", and the half that is easy to fake.

    A scenario that quietly edited ``edge/registry.py`` in its copy would pass the test
    above while proving the opposite. So every file the copy shares with the real tree is
    compared, byte for byte, and the only permitted difference is the directory that was
    added.
    """
    root = tmp_path / "tree"
    root.mkdir()
    added = plant_a_copy(root)
    run_probe(root)

    for package in ("edge", "control"):
        differences = _differing_files(
            REPO_ROOT / package, root / package, skip={added.name}
        )
        assert not differences, (
            f"making a new transport work changed files outside its own directory: "
            f"{differences}"
        )

    # And the new directory really is self-contained: no file in it reaches up out of
    # ``edge/transports/`` by path.
    for path in sorted(added.glob("*.*")):
        # Only the files the scenario wrote; the probe run left a __pycache__ beside them.
        assert ".." not in path.read_text(), f"{path.name} refers to a parent directory"


def _differing_files(left: pathlib.Path, right: pathlib.Path, *, skip: set[str]) -> list[str]:
    """Every file present in both trees whose contents differ, plus anything only in one.

    Recursive by hand rather than ``filecmp.dircmp``'s report, because the report prints
    and this needs a value. ``shallow=False`` matters: comparing size and mtime would
    call a rewritten file identical.
    """
    found: list[str] = []
    comparison = filecmp.dircmp(str(left), str(right), ignore=["__pycache__"])

    found.extend(comparison.diff_files)
    found.extend(name for name in comparison.left_only if name not in skip)
    found.extend(name for name in comparison.right_only if name not in skip)

    for name in comparison.common_dirs:
        if name in skip:
            continue
        found.extend(
            f"{name}/{entry}"
            for entry in _differing_files(left / name, right / name, skip=skip)
        )
    return found


# --- S2: a package that breaks the contract is refused AT DISCOVERY ------------

DISCOVER_PROBE = textwrap.dedent(
    """
    from edge.registry import discover

    try:
        discover()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}")
    else:
        print("NO ERROR")
    """
)

# Each entry replaces ``meta.py`` in the planted package with something that breaks one
# rule, and names the phrase the error must contain. The phrase matters as much as the
# refusal: an operator reading "ContractViolation" alone learns nothing about what to fix.
BROKEN_DECLARATIONS = {
    "no META at all": (
        '"""A meta module that forgot the one symbol discovery reads."""\n',
        "not a TransportMeta",
    ),
    "META is not a TransportMeta": (
        'META = {"name": "acme-tunnel"}\n',
        "not a TransportMeta",
    ),
    "no client-scoped identity": (
        textwrap.dedent(
            '''
            from edge.registry import KeyKind, KeyScope, KeySpec, Layer4, TransportMeta

            META = TransportMeta(
                name="acme-tunnel",
                family="tcp-tls",
                listens_on=frozenset({Layer4.TCP}),
                needs_tls=True,
                port_range=(443, 65535),
                key_material=(
                    KeySpec(
                        name="private_key",
                        kind=KeyKind.X25519_KEYPAIR,
                        scope=KeyScope.NODE,
                        public_name="public_key",
                    ),
                ),
            )
            '''
        ).lstrip(),
        "'subject'",
    ),
    "a nonsensical port range": (
        textwrap.dedent(
            '''
            from edge.registry import KeyKind, KeyScope, KeySpec, Layer4, TransportMeta

            META = TransportMeta(
                name="acme-tunnel",
                family="tcp-tls",
                listens_on=frozenset({Layer4.TCP}),
                needs_tls=True,
                port_range=(65535, 443),
                key_material=(
                    KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
                ),
            )
            '''
        ).lstrip(),
        "port range",
    ),
    "declares no listening protocol": (
        textwrap.dedent(
            '''
            from edge.registry import KeyKind, KeyScope, KeySpec, TransportMeta

            META = TransportMeta(
                name="acme-tunnel",
                family="udp",
                # EMPTY rather than omitted, and the difference is why this case exists
                # at all: a field left out dies as a TypeError at import, before
                # `_check_declaration` is ever reached, so only the empty form can
                # exercise the check. A transport declaring nothing here would be read as
                # colliding with nothing, and the first pair on one port would be found
                # by a container that cannot bind (M15).
                listens_on=frozenset(),
                needs_tls=False,
                port_range=(1024, 65535),
                key_material=(
                    KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
                ),
            )
            '''
        ).lstrip(),
        "which transport-layer protocols its listener binds",
    ),
    "a pool declared with one half missing": (
        textwrap.dedent(
            '''
            from edge.registry import (
                KeyKind,
                KeyScope,
                KeySpec,
                Layer4,
                PeerAddress,
                TransportMeta,
            )

            META = TransportMeta(
                name="acme-tunnel",
                family="udp",
                listens_on=frozenset({Layer4.UDP}),
                needs_tls=False,
                port_range=(1024, 65535),
                key_material=(
                    KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
                ),
                # EMPTY rather than omitted, for the reason the listens_on case above
                # gives: a field left out of PeerAddress dies as a TypeError at import,
                # before `_check_declaration` is reached, so only the empty form can
                # exercise the check. Half a declaration is a pool `control` can read
                # the first address of and cannot size — or the reverse (M17).
                peer_address=PeerAddress(name="peer_address", within=""),
            )
            '''
        ).lstrip(),
        "one half of that declaration empty",
    ),
    "a pool whose address `control` would also mint": (
        textwrap.dedent(
            '''
            from edge.registry import (
                KeyKind,
                KeyScope,
                KeySpec,
                Layer4,
                PeerAddress,
                TransportMeta,
            )

            META = TransportMeta(
                name="acme-tunnel",
                family="udp",
                listens_on=frozenset({Layer4.UDP}),
                needs_tls=False,
                port_range=(1024, 65535),
                key_material=(
                    KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
                    KeySpec(
                        name="peer_address",
                        kind=KeyKind.TOKEN_32,
                        scope=KeyScope.CLIENT,
                    ),
                ),
                # An address is ALLOCATED from a pool and key material is GENERATED, so
                # a package declaring both under one name would have every user's
                # address overwritten the moment their credential was minted (M17).
                peer_address=PeerAddress(name="peer_address", within="tunnel_address"),
            )
            '''
        ).lstrip(),
        "allocated from a pool, never generated",
    ),
    "identified on the wire AND allowed on a hop": (
        textwrap.dedent(
            '''
            from edge.registry import KeyKind, KeyScope, KeySpec, Layer4, TransportMeta

            META = TransportMeta(
                name="acme-tunnel",
                family="udp",
                listens_on=frozenset({Layer4.UDP}),
                needs_tls=False,
                port_range=(1024, 65535),
                key_material=(
                    KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
                ),
                blocked_by_inspection=True,
                hop_capable=True,
            )
            '''
        ).lstrip(),
        "never forms a tunnel",
    ),
}


@pytest.mark.parametrize("description", sorted(BROKEN_DECLARATIONS))
def test_a_package_that_breaks_the_contract_is_refused_at_discovery(
    description: str, tmp_path
) -> None:
    """S2. Refused on being FOUND, with a sentence, rather than raising at render time.

    The moment is the whole finding. ``discover()`` runs on every panel screen and every
    subscription render, so a malformed package caught there is one error message an
    operator sees immediately. The same package caught later is an exception inside one
    user's refresh — or a node the operator was told was configured, which cannot mint a
    credential for anybody.

    Each variant also has to say what is wrong. A refusal an author cannot act on sends
    them reading our source, which is the opposite of "a new protocol is one directory".
    """
    meta_source, expected_phrase = BROKEN_DECLARATIONS[description]

    root = tmp_path / "tree"
    root.mkdir()
    added = plant_a_copy(root)
    (added / "meta.py").write_text(meta_source)

    result = subprocess.run(
        [sys.executable, "-c", DISCOVER_PROBE],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=root,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    reported = result.stdout.strip().splitlines()[-1]

    assert reported != "NO ERROR", (
        f"discovery accepted a package that {description} — the failure moves to render "
        "time, inside one user's subscription refresh"
    )
    assert reported.startswith("ContractViolation"), (
        f"a package that {description} failed, but not as a contract violation: {reported}"
    )
    assert expected_phrase in reported, (
        f"the refusal for {description!r} does not say what to fix: {reported}"
    )
