#!/usr/bin/env bash
# WHAT: fetches the upstream data-plane binaries this repo validates configs with,
#       into ./.tools/ — today that is Xray-core's `xray`, whose `run -test` is the
#       only authority on whether a rendered config is acceptable.
# WHY:  the edge rulebook requires every rendered config to be checked by the
#       upstream binary's own checker rather than by a regex of ours, and the
#       backlog (item 1a) calls this the one "prove it with reality" step in M1.
#       A config we believe is valid is not a config the daemon accepts.
#
#       It is a script and not a documented curl line because "reproducibly
#       available" is the requirement: an unpinned download makes a green test run
#       unrepeatable, and core invariants §5 pins data-plane binaries to an exact
#       patch version for a sharper reason — an upstream that changes its default
#       TLS parameters silently changes how detectable every node is.
# HOW:  ./scripts/fetch-upstream-checkers.sh
#       Then `make test-edge` picks it up from .tools/ automatically
#       (tests/edge/conftest.py::xray_binary), or set HASHI_XRAY_BIN to override.
#
#       .tools/ is git-ignored: this vendors a third party's binary, which does
#       not belong in our history.
set -euo pipefail

# Pinned to an exact patch version, never a bare major and never "latest".
XRAY_VERSION="v1.8.24"

# The SHA-256 of the release asset for this version and platform. This is the
# line that makes the fetch reproducible rather than merely repeatable: without
# it, "v1.8.24" is whatever the tag points at today.
#
# Populated by running this script once and pasting the digest it prints. It is
# EMPTY on purpose rather than wrong — a placeholder digest would either fail
# forever or, worse, be "fixed" by someone pasting whatever they just downloaded,
# which is not verification. While it is empty the script fetches, prints the
# digest, and says in one line that the download was NOT verified.
XRAY_SHA256_LINUX_64="47a860787e823474a358d6bca536547df6dd08b69c6de482ea92a9e7e8f8969c"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${REPO_ROOT}/.tools"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET="Xray-linux-64.zip";   EXPECTED="${XRAY_SHA256_LINUX_64}" ;;
  Linux-aarch64) ASSET="Xray-linux-arm64-v8a.zip"; EXPECTED="" ;;
  Darwin-arm64)  ASSET="Xray-macos-arm64-v8a.zip"; EXPECTED="" ;;
  Darwin-x86_64) ASSET="Xray-macos-64.zip";   EXPECTED="" ;;
  *)
    echo "unsupported platform $(uname -s)-$(uname -m) — set HASHI_XRAY_BIN to a binary you trust" >&2
    exit 1 ;;
esac

URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/${ASSET}"

mkdir -p "${TOOLS}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "fetching ${ASSET} (${XRAY_VERSION})"
if ! curl -fsSL --retry 3 -o "${WORK}/${ASSET}" "${URL}"; then
  echo "could not download ${URL}" >&2
  echo "no network? set HASHI_XRAY_BIN to an xray binary you already trust instead." >&2
  exit 1
fi

DIGEST="$(sha256sum "${WORK}/${ASSET}" | cut -d' ' -f1)"

if [ -n "${EXPECTED}" ]; then
  if [ "${DIGEST}" != "${EXPECTED}" ]; then
    echo "CHECKSUM MISMATCH for ${ASSET}" >&2
    echo "  expected ${EXPECTED}" >&2
    echo "  got      ${DIGEST}" >&2
    echo "Refusing to install. Either the release was re-cut or the download was tampered with." >&2
    exit 1
  fi
  echo "checksum verified"
else
  echo "WARNING: this platform has no pinned checksum, so the download was NOT verified."
  echo "         Pin it by setting the matching variable in this script to:"
  echo "         ${DIGEST}"
fi

# Extract just the binary. `unzip` when it exists, otherwise Python's zipfile —
# not defensive programming for its own sake: `unzip` is absent from slim
# container images (including the fleet's own), and a fetch script that works on a
# laptop and not in the container is a validation step that quietly never runs
# where it matters most.
if command -v unzip >/dev/null 2>&1; then
  # -j: the archive has no useful directory structure, and we want one flat binary.
  unzip -o -j -q "${WORK}/${ASSET}" xray -d "${TOOLS}"
elif command -v python3 >/dev/null 2>&1; then
  python3 - "${WORK}/${ASSET}" "${TOOLS}" <<'PY'
import pathlib
import sys
import zipfile

archive, destination = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(archive) as bundle:
    # Match on the basename: the asset layout is flat today, but a future release
    # that nests the binary should still work rather than fail obscurely.
    member = next(n for n in bundle.namelist() if pathlib.PurePath(n).name == "xray")
    (destination / "xray").write_bytes(bundle.read(member))
PY
else
  echo "need either unzip or python3 to extract ${ASSET}" >&2
  exit 1
fi
chmod +x "${TOOLS}/xray"

echo "installed ${TOOLS}/xray"
"${TOOLS}/xray" version | head -1
echo
echo "next: make test-edge   (the validation tests stop skipping now)"
