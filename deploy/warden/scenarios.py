#!/usr/bin/env python3
# =============================================================================
# Warden contract scenarios — deploy/warden/scenarios.py
# =============================================================================
# WHAT: drives every Warden<->Hub path through the real tracker HTTP API and
#       asserts the outcome: dispatch, cancel, at-capacity queueing, unsupported
#       kind, epic children, restart drop+requeue, the restart cooldown, and the
#       status relay.
# WHY:  these are protocol failures, and every one of them we hit so far was
#       silent — a Directive that looked accepted and did the wrong thing. They
#       are also the paths that cost a real fleet run to exercise, which is why
#       nobody tests them twice. With WARDEN_FAKE_PIPELINE=1 the whole sheet
#       runs in about a minute and costs nothing.
# HOW:  run it from the Kaizen tracker container, which is where the admin token
#       already lives — so the token is never read into anyone's context:
#         make warden-scenarios
# =============================================================================

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
HUB = "http://127.0.0.1:8770"
PROJECT = "hashi"
TOKEN = os.environ.get("TRACKER_ADMIN_TOKEN", "")

results: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        HUB + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:400]}


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def dispatch(title: str, intent: str, kind: str = "develop", task_id: str | None = None):
    body = {"project": PROJECT, "kind": kind, "title": title, "description": intent}
    if task_id:
        body["task_id"] = task_id
    return call("POST", "/tasks", body)


def status_of(did: int) -> str:
    return (call("GET", f"/tasks/{did}") or {}).get("task", {}).get("status", "?")


def wait_for(did: int, states: set[str], timeout: float = 60) -> str:
    """Poll until the Directive reaches one of `states`. Returns what it reached."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = status_of(did)
        if last in states:
            return last
        time.sleep(1)
    return last


# ---------------------------------------------------------------------------

def scenario_happy_path():
    print("\n1. a Directive is accepted, runs, and reports")
    d = dispatch("scenario: happy path", "quick — scenario run, no real work")
    did = d.get("task_id")
    if not check("accepted by the Hub", bool(did), json.dumps(d)[:120]):
        return
    reached = wait_for(did, {"done", "review", "failed"}, 90)
    check("reaches a terminal state", reached in ("done", "review"), f"status={reached}")


def scenario_cancel():
    print("\n2. a running Directive can be cancelled")
    d = dispatch("scenario: cancel", "hang — this one never finishes on purpose")
    did = d.get("task_id")
    if not check("accepted", bool(did)):
        return
    running = wait_for(did, {"running", "dispatched"}, 45)
    if not check("reaches the Warden", running in ("running", "dispatched"), f"status={running}"):
        return
    call("POST", f"/tasks/{did}/cancel")
    reached = wait_for(did, {"cancelled"}, 45)
    check("cancel takes effect", reached == "cancelled", f"status={reached}")


def scenario_capacity():
    print("\n3. a second Directive queues instead of being lost (max_concurrent=1)")
    a = dispatch("scenario: capacity A", "hang — occupies the only slot")
    b = dispatch("scenario: capacity B", "quick — must wait its turn")
    did_a, did_b = a.get("task_id"), b.get("task_id")
    if not check("both accepted", bool(did_a and did_b)):
        return
    wait_for(did_a, {"running"}, 45)
    time.sleep(4)
    st_b = status_of(did_b)
    check("second is still waiting, not failed", st_b in ("queued", "dispatched"), f"B={st_b}")
    call("POST", f"/tasks/{did_a}/cancel")
    reached = wait_for(did_b, {"done", "review", "running"}, 90)
    check("second runs once the slot frees", reached in ("done", "review", "running"),
          f"B={reached}")
    if reached == "running":
        call("POST", f"/tasks/{did_b}/cancel")


def scenario_unsupported_kind():
    print("\n4. a kind this fleet cannot run is refused, not approximated")
    d = dispatch("scenario: analyze", "anything", kind="analyze")
    did = d.get("task_id")
    if not check("Hub accepts the kind (it is in its vocabulary)", bool(did)):
        return
    reached = wait_for(did, {"failed", "done", "review"}, 60)
    check("Warden refuses it", reached == "failed", f"status={reached}")


def scenario_epic_children():
    print("\n5. an epic reports children, and the Hub queues them")
    before = {t["id"] for t in (call("GET", "/tasks") or {}).get("tasks", [])}
    d = dispatch("scenario: epic", "split this into pieces", kind="epic")
    did = d.get("task_id")
    if not check("accepted", bool(did)):
        return
    reached = wait_for(did, {"done", "review", "failed"}, 90)
    check("epic completes", reached in ("done", "review"), f"status={reached}")
    after = (call("GET", "/tasks") or {}).get("tasks", [])
    kids = [t for t in after if t["id"] not in before and t.get("parent_id") == did]
    check("children were queued under it", len(kids) > 0, f"{len(kids)} child directive(s)")
    for k in kids:
        call("POST", f"/tasks/{k['id']}/cancel")


def scenario_restart():
    print("\n6. restart drops in-flight work, the Hub requeues it, a second call is refused")
    d = dispatch("scenario: restart", "hang — must be dropped by the restart")
    did = d.get("task_id")
    if not check("accepted", bool(did)):
        return
    wait_for(did, {"running"}, 45)
    first = call("POST", f"/projects/{PROJECT}/restart",
                 {"scope": "jobs", "reason": "scenario: drop and requeue"})
    check("restart accepted", first.get("accepted") is True, json.dumps(first)[:120])
    check("the running Directive was dropped", did in (first.get("dropped") or []),
          f"dropped={first.get('dropped')}")
    check("and requeued, not lost", did in (first.get("requeued") or []),
          f"requeued={first.get('requeued')}")
    second = call("POST", f"/projects/{PROJECT}/restart",
                  {"scope": "jobs", "reason": "scenario: storm protection"})
    check("a second restart inside the cooldown is refused",
          second.get("accepted") is False, second.get("reason", ""))
    wait_for(did, {"running", "dispatched", "queued"}, 30)
    call("POST", f"/tasks/{did}/cancel")


def scenario_status_relay():
    print("\n7. a status file written by an agent reaches the Hub")
    d = dispatch("scenario: relay", "hang — stays up while we write a status file")
    did = d.get("task_id")
    if not check("accepted", bool(did)):
        return
    # AFTER it is running, not before: the Hub assigns `task_id` when the
    # Directive is dispatched, so reading it at creation time yields NULL and the
    # probe lands in docs/tracker/None/ — which looks exactly like a dead relay.
    wait_for(did, {"running"}, 45)
    task = (call("GET", f"/tasks/{did}") or {}).get("task", {})
    task_id = task.get("task_id")
    if not check("the Directive has a task_id once running", bool(task_id), str(task_id)):
        return
    marker = f"relay probe {int(time.time())}"
    # Written from the host: /repo in the container IS this directory, and a
    # printf through `docker exec` was mangling the newlines badly enough that
    # the file parsed to nothing — which reads exactly like a broken relay.
    probe = REPO / "docs" / "tracker" / str(task_id) / "status" / "dev-potts.yml"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        'agent: "dev-potts"\nrole: "dev"\nstate: "in_progress"\nphase: "relay"\n'
        f'progress: "{marker}"\nblockers: ""\n'
        'updated_at: "2026-01-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )
    seen = False
    for _ in range(8):
        time.sleep(2)
        out = subprocess.run(
            ["docker", "exec", "kaizen-postgres", "sh", "-c",
             'psql -U "$POSTGRES_USER" -d tracker -tAc '
             '"select progress from tracker_agent_status where agent_slug=\'dev-potts\'"'],
            capture_output=True, text=True, check=False,
        )
        if marker in out.stdout:
            seen = True
            break
    check("the relay pushed it within ~15s", seen,
          marker if seen else "not seen in tracker_agent_status")
    call("POST", f"/tasks/{did}/cancel")
    probe.unlink(missing_ok=True)


def main() -> int:
    if not TOKEN:
        print("TRACKER_ADMIN_TOKEN is not set — run this inside the tracker container")
        return 2
    for fn in (scenario_happy_path, scenario_cancel, scenario_capacity,
               scenario_unsupported_kind, scenario_epic_children, scenario_restart,
               scenario_status_relay):
        try:
            fn()
        except Exception as e:                    # a broken scenario is a FAIL, not a crash
            check(f"{fn.__name__} raised", False, repr(e)[:160])
        time.sleep(65 if fn is scenario_restart else 1)   # let the restart cooldown lapse

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED: {name} — {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
