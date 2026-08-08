# WHAT: the control-plane image.
# WHY:  the interpreter matches the one the local venv uses (3.14). A container
#       on a different minor than the developer's venv is the trap where "works
#       locally" and "works in the stack" quietly diverge.
# HOW:  built from the repo root (context: ..) because the package lives there.

FROM python:3.14-slim

# Build in /src and install, then throw the sources away and run from an empty
# directory. WHY the dance: the image used to `pip install .` in the same
# WORKDIR it then ran from, so `import edge` resolved to the COPIED tree (cwd is
# on sys.path), never to the installed distribution — the install was decoration
# and pyproject's package list was never exercised. A transport package missing
# from that list would have shipped fine here and vanished in any other
# consumer of the wheel. One copy of the code in the image, and it is the
# installed one.
WORKDIR /src

COPY pyproject.toml ./
COPY control ./control
COPY edge ./edge

RUN pip install --no-cache-dir . && rm -rf /src

WORKDIR /app

EXPOSE 8000

# --no-access-log is not a performance choice: uvicorn's access log records the
# request path, and subscription tokens live in the path.
CMD ["uvicorn", "control.app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
