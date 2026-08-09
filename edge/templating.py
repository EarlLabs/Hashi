"""The one Jinja environment every transport renders through.

WHAT: builds a Jinja2 environment rooted in a transport's own package directory.
WHY:  three settings have to be identical for every transport, and each of them
      is a bug if a package sets it differently:
        - ``autoescape=False``, because these are JSON and INI configs, not HTML;
          HTML-escaping a private key produces a config the daemon rejects with a
          message that points nowhere near the cause. Values are escaped by the
          ``tojson`` filter at each use site instead, which is correct for JSON.
        - ``undefined=StrictUndefined``, so a template that references a
          parameter the ``Params`` model does not define fails at render time
          instead of writing an empty string into a node's configuration. An
          empty ``privateKey`` is a node that boots and serves nothing.
        - ``keep_trailing_newline=True``, so golden files are comparable byte for
          byte without every test stripping whitespace.
HOW:  ``environment_for(__file__)`` in a transport's ``render.py``. Loading the
      template reads a file, which is the single unavoidable filesystem touch in
      this pure zone — it reads *code shipped in the image*, never node data, and
      the result is cached per package so repeated renders do no further I/O.
"""

import pathlib
from functools import cache

from jinja2 import Environment, FileSystemLoader, StrictUndefined


@cache
def _environment(directory: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(directory),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def environment_for(module_file: str) -> Environment:
    """The environment for templates sitting beside ``module_file``."""
    return _environment(str(pathlib.Path(module_file).resolve().parent))
