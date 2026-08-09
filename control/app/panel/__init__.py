"""HTMX routes returning HTML, one module per screen.

The panel a single operator lives in (backlog items 18, 19 and 21). Server-rendered
Jinja + HTMX, no build step and no bundler — the charter's reasoning is that an
internal panel for one person should not buy a frontend zone, a build pipeline and
two more agents.
"""
