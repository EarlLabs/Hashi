"""Alembic migrations for the control database.

A package rather than a bare directory so the migrations ship inside the installed
wheel — the container throws its sources away and runs ``alembic upgrade head``
against the installed distribution.
"""
