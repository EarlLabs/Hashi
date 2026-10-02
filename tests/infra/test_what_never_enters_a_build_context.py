"""What `.dockerignore` keeps out of a layer, at every depth — M27.7.

WHAT: that the patterns guarding key material are anchored at every depth, and that the
      directory the delivery pair lives in is excluded by name as well as by extension.
WHY:  a `.dockerignore` pattern is matched against the WHOLE relative path — Go's
      `filepath.Match`, in which no `*` crosses a `/` — so the `*.pem` and `*.key` that
      stood here reached the repository root and nothing below it. M27.6 then put the
      private half of the fleet's delivery wildcard in `deploy/delivery/`, which answers
      for every delivery name until it expires, and the file's own header claimed the
      guard that was not covering it.
HOW:  read, not built, like every other static check in this zone. The claim this pins
      was MEASURED on 2026-09-27, both ways, with a throwaway `Dockerfile` doing
      `COPY . /ctx` against this repository: with the previous patterns the layer held
      `deploy/delivery/privkey.pem`, `some.key` and `fullchain.crt`; with the ones below
      it held none of the three. Nothing ships them either way — `control.Dockerfile`
      copies only `pyproject.toml`, `control/` and `edge/` — which is exactly why this
      cannot be left to the Dockerfile that exists today.
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCKERIGNORE = REPO / ".dockerignore"

# Extensions that are key material wherever they are. Not a list of the files in this
# repository: the point of the guard is the file somebody adds tomorrow.
SECRET_SUFFIXES = ("pem", "key")


def patterns() -> list[str]:
    return [
        line.strip()
        for line in DOCKERIGNORE.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_key_material_is_excluded_at_every_depth_and_not_only_at_the_root() -> None:
    """The defect itself: a bare ``*.pem`` is a guard over one directory."""
    listed = patterns()
    for suffix in SECRET_SUFFIXES:
        assert f"**/*.{suffix}" in listed, (
            f"`.dockerignore` does not exclude *.{suffix} below the repository root — a "
            "pattern here is matched against the whole relative path, so a bare "
            f"`*.{suffix}` covers the root directory only"
        )
        assert f"*.{suffix}" not in listed, (
            f"the root-only `*.{suffix}` is still here beside the deep one. It is not "
            "wrong, it is the pattern whose reach was misread once already — keep one "
            "spelling, so nobody reads the short one as the guard"
        )


def test_the_directory_the_delivery_key_lives_in_is_excluded_by_name() -> None:
    """Belt and braces, and they catch different things — M27.6's wildcard.

    The patterns above are about the extension; this is about the contents. An operator
    names those files whatever their issuer produced, and a `fullchain.crt` is the same
    key material under a name no extension rule matches.
    """
    assert "deploy/delivery/" in patterns(), (
        "`.dockerignore` no longer excludes the directory `.env.example` tells the "
        "operator to put the fleet's delivery certificate and its private key in"
    )


def test_the_file_still_says_why_it_is_here() -> None:
    """The header is the only place the reason survives, and a guard nobody understands
    is a guard somebody tidies away."""
    header = DOCKERIGNORE.read_text().split("\n\n")[0]
    assert ".env" in header and "layer" in header
