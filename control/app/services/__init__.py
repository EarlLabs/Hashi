"""Everything a route does lives here.

The control rulebook's rule for this package: if a route function is longer than
wiring — validate input, call a service, shape a response — the logic belongs in a
module here. A route that queries the database directly is a rule violation rather
than a shortcut.
"""
