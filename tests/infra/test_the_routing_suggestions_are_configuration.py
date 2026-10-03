"""The routing sources the panel offers are configuration, never code — M34.

WHAT: reads the default of ``HASHI_ROUTING_SUGGESTED_SOURCES`` out of
      deploy/docker-compose.yml and holds it to what the decision journal says it is: four
      https suggestions, exactly one of them (the narrow list) switched on when added, and
      none of their hosts written anywhere in `control` or `edge` code.
WHY:  each suggestion is a URL, and a URL in code is a domain in code (CLAUDE.md). The
      default therefore lives in the compose file, where an install picks it up without
      editing its env file — and a default that stops parsing would empty the Routing
      screen's suggestions with nothing failing.
HOW:  the compose file's own text, parsed by the control plane's own reader.
"""

import pathlib
import re
from urllib.parse import urlsplit

import yaml

from control.app.services.routing import suggested_sources

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "docker-compose.yml"


def configured_default() -> str:
    environment = yaml.safe_load(COMPOSE.read_text())["services"]["control"]["environment"]
    value = environment["HASHI_ROUTING_SUGGESTED_SOURCES"]
    matched = re.fullmatch(r"\$\{HASHI_ROUTING_SUGGESTED_SOURCES:-(.*)\}", value)
    assert matched, f"not a pass-through with a default: {value!r}"
    return matched.group(1)


def test_the_default_offers_the_narrow_list_on_and_three_broader_ones_off() -> None:
    found = suggested_sources(configured_default())
    assert len(found) == 4
    assert [s.name for s in found if s.on] == ["itdoginfo-russia-outside"]
    assert all(urlsplit(s.url).scheme == "https" for s in found)


def test_no_suggested_host_is_written_in_code() -> None:
    hosts = {urlsplit(s.url).hostname for s in suggested_sources(configured_default())}
    offenders = []
    for zone in ("control", "edge"):
        for path in (ROOT / zone).rglob("*.py"):
            text = path.read_text()
            offenders += [f"{path.relative_to(ROOT)}: {h}" for h in hosts if h in text]
    assert offenders == []
