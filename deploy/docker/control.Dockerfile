# WHAT: the control-plane image.
# WHY:  the interpreter matches the one the local venv uses (3.14). A container
#       on a different minor than the developer's venv is the trap where "works
#       locally" and "works in the stack" quietly diverge.
# HOW:  built from the repo root (context: ..) because the package lives there.

FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml ./
COPY control ./control
COPY edge ./edge

RUN pip install --no-cache-dir .

EXPOSE 8000

# --no-access-log is not a performance choice: uvicorn's access log records the
# request path, and subscription tokens live in the path.
CMD ["uvicorn", "control.app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
