#!/usr/bin/env python3
"""REG-17 / A2b-1 W3: withdraw/abandon JSON and idempotency contract.

Prerequisites: Python 3 and an already-running, disposable campus-buddy app
with a private test DB and no other writers to the fixtures. For example, on
an operator-prepared instance: BASE_URL=http://127.0.0.1:18080 A2B1_ISOLATED=1
python3 reg-17-withdraw-abandon-contract.py (set both variables for that process).
Only explicit literal loopback HTTP roots on isolated high ports are allowed;
the conventional BASE_URL default http://127.0.0.1:8080 is not runnable. No
proxies, redirects, demo reset, or service/DB management. Fixtures are retained.
Authenticated activity detail must publish the actor's participation_version
for the versioned success/replay case; a missing field fails that case.

Expected for FORMAL withdraw and WAITING abandon: explicit false -> 400 ERROR
(confirmation required); stale nonempty version -> 409 CONFLICT with
current_version; neither changes participation state or events. The exact detail
version -> 200 Map with participation_id, WITHDRAWN and the resulting version.
Same key/body replays exact status/body; changed body -> 409 IDEMPOTENCY_CONFLICT.
A fresh fixture also accepts an old, genuinely bodyless POST.
"""
import http.client
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Reply(NamedTuple):
    status: int
    envelope: dict
    raw: bytes = b""
    problem: str = ""


def isolated_client():
    root = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
    match = re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\]):([1-9][0-9]{3,4})/?", root)
    port = int(match[1]) if match else 0
    if ("BASE_URL" not in os.environ or os.environ.get("A2B1_ISOLATED") != "1"
            or not 1024 <= port <= 65535 or port in {3306, 5432, 5433, 8080, 8081, 15451}):
        raise SetupError("explicit loopback HTTP BASE_URL on an isolated high port and A2B1_ISOLATED=1 required")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    base = root.rstrip("/") + "/api/v1"

    def req(method, path, token=None, body=None, headers=None):
        hdr = {"Accept": "application/json", **(headers or {})}
        if token:
            hdr["Authorization"] = "Bearer " + token
        data = None
        if body is not None:
            hdr["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        status = 0
        try:
            request = urllib.request.Request(base + path, data=data, headers=hdr, method=method)
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status, raw = response.getcode(), response.read(2**20 + 1)
            if len(raw) > 2**20:
                return Reply(status, {}, problem="response too large")
            env = json.loads(raw)
            return Reply(status, env, raw) if isinstance(env, dict) else Reply(status, {}, problem="not a JSON object")
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return Reply(status, {}, problem=type(exc).__name__)

    return req


RESULTS = []
STALE = "2000-01-01T00:00"  # Never a freshly-created row's token.


def check(name, passed, detail=""):
    RESULTS.append(bool(passed))
    print(f"{'PASS' if passed else 'FAIL'} - {name}" + (f" ({detail})" if detail and not passed else ""))


def describe(reply):
    # Don't print raw responses, input bodies, tokens or other credentials.
    code = reply.envelope.get("code")
    if code not in ("OK", "ERROR", "CONFLICT", "IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_IN_PROGRESS",
                    "VALIDATION", "FORBIDDEN", "TOO_MANY_ATTEMPTS"):
        code = "missing/unexpected"
    return f"HTTP {reply.status}, code={code}" + (f", {reply.problem}" if reply.problem else "")


def text(value):
    return isinstance(value, str) and bool(value.strip())


def matches(reply, status, code, message_part=""):
    env = reply.envelope
    msg = env.get("message")
    return (reply.status == status and env.get("success") is (status == 200)
            and env.get("code") == code and text(msg) and message_part in msg and "data" in env)


def require_data(label, reply, kind=dict):
    data = reply.envelope.get("data")
    if not matches(reply, 200, "OK") or not isinstance(data, kind):
        raise SetupError(f"{label}: {describe(reply)}")
    return data


def row_id(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise SetupError(f"missing/invalid {field}")
    return value


def account(req, role, stamp):
    name = f"w3{role}_{stamp}"
    credentials = {"account": name, "password": "W3a9" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not text(token):
        raise SetupError(f"login {role}: missing token")
    return token


def state(data):
    return tuple(data.get(k) for k in ("participation_id", "my_status", "formal", "waiting", "reserved"))


def run_case(req, action, case, host, member, holder, stamp, now, slot):
    label = f"{action} {case}"
    start = now + timedelta(days=2, hours=2 * slot)
    created = require_data("create activity", req("POST", "/activities", host, {
        "title": f"W3 {label} {stamp}", "category": "桌游", "location": "REG-17 fixture", "capacity": 1,
        "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
    }))
    detail_path = f"/activities/{row_id(created, 'id')}"
    waiting = action == "abandon"
    if waiting:  # Occupy the only seat; the tested member stays WAITING (not INVITED).
        require_data("fill only seat", req("POST", detail_path + "/signup", holder))
    require_data("sign up member", req("POST", detail_path + "/signup", member))

    def detail():
        return require_data("read activity detail", req("GET", detail_path, member))

    before = detail()
    pid = row_id(before, "participation_id")
    expected = "WAITING" if waiting else "FORMAL"
    if before.get("status") != "OPEN" or state(before) != (pid, expected, 1, int(waiting), 0):
        raise SetupError(f"expected OPEN capacity-1 fixture with actor {expected}")
    path = f"/participations/{pid}/{action}"
    version = before.get("participation_version")

    def events():
        return require_data("read participation events", req("GET", f"/participations/{pid}/events", member), list)

    if case in ("false", "stale"):
        initial_events = events()
        if case == "false":
            reply = req("POST", path, member, {"confirmed": False})
            check(label + " -> 400 ERROR (confirmation required)",
                  matches(reply, 400, "ERROR", "二次确认"), describe(reply))
        else:
            reply = req("POST", path, member, {"confirmed": True, "version": STALE})
            data = reply.envelope.get("data")
            current = data.get("current_version") if isinstance(data, dict) else None
            check(label + " -> 409 CONFLICT with current_version",
                  matches(reply, 409, "CONFLICT") and text(current) and current != STALE
                  and (version is None or current == version), describe(reply))
        after = detail()
        check(label + " preserves status, version and counts",
              state(after) == state(before) and after.get("participation_version") == version)
        check(label + " preserves participation events", events() == initial_events)
        return

    versioned = case == "versioned"
    if versioned and not text(version):
        raise SetupError("detail missing participation_version; cannot test exact-token success or replay")
    body = {"confirmed": True, "version": version} if versioned else None
    headers = {"Idempotency-Key": f"reg17-{stamp}-{action}"} if versioned else None
    first = req("POST", path, member, body, headers)
    data = first.envelope.get("data")
    result_version = data.get("participation_version") if isinstance(data, dict) else None
    succeeded = (matches(first, 200, "OK") and text(result_version)
                 and data.get("participation_id") == pid and data.get("status") == "WITHDRAWN"
                 and data.get("already") is not True)
    check(label + " -> 200 Map with ID, WITHDRAWN and version", succeeded, describe(first))
    after = detail()
    check(label + " persists WITHDRAWN", state(after) == (pid, "WITHDRAWN", int(waiting), 0, 0))
    if versioned:
        # updated_at is second-granularity: the old and new values can be equal.
        check(label + " response version equals detail version",
              text(result_version) and result_version == after.get("participation_version"))
        transition_events = events()
        replay = req("POST", path, member, body, headers)
        check(label + " same-key identical replay", succeeded and (replay.status, replay.raw) == (first.status, first.raw),
              describe(replay))
        changed = req("POST", path, member, dict(body, version=STALE), headers)
        check(label + " same key, changed version -> 409 IDEMPOTENCY_CONFLICT",
              matches(changed, 409, "IDEMPOTENCY_CONFLICT"), describe(changed))
        check(label + " replay/conflict append no events", events() == transition_events)


def main():
    try:
        req = isolated_client()
        now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None, microsecond=0)
        stamp = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S%f") + secrets.token_hex(2)
        host, member, holder = (account(req, role, stamp) for role in ("org", "mem", "cap"))
    except SetupError as exc:
        check("setup", False, str(exc))
        return 1
    check("isolated client and dummy accounts", True)

    # Both bad-body probes can mutate on the baseline. Give every probe its own
    # activity and non-overlapping times, so neither can spoil another fixture.
    cases = ("false", "stale", "versioned", "bodyless")
    for index, action in enumerate(("withdraw", "abandon")):
        for slot, case in enumerate(cases, start=index * len(cases)):
            try:
                run_case(req, action, case, host, member, holder, stamp, now, slot)
            except SetupError as exc:
                check(f"{action} {case} setup/read", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
