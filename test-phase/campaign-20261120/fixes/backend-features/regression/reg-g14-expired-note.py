#!/usr/bin/env python3
"""REG-G14: EXPIRED waitlist rows must keep a result_note in /my (recheck G14).

Spec: test-phase/campaign-20261120/fixes/consistency-recheck-20261121.md G14 —
SRS v1.4 §3.3.7.2 and the design require "报名已截止，未获得名额" to stay
visible after closeout. Before the fix, ApiV1Controller.my() only wrote
result_note for rows still WAITING past the deadline; once
BuddyService.closeOutActivity() moved the row to EXPIRED (keeping the reason
in the participation_events SIGNUP_CLOSED detail), /my showed a bare
"已过期" with no reason. After the fix, EXPIRED rows also get result_note —
the SIGNUP_CLOSED event detail when present, else the default text
"报名已截止，未获得名额".

Preconditions: a running campus-buddy instance (BASE_URL, default
http://127.0.0.1:8080) with a short sweep interval (SWEEP_SECONDS <= 10) so
the deadline closeout lands quickly, registration enabled, and the run made
inside the invitation window (or INVITE_DAY_START_HOUR=0 /
INVITE_DAY_END_HOUR=24). Fixture: capacity-1 activity with deadline ~45 s
out; user A takes the only FORMAL seat, user B stays WAITING; after the
deadline passes and the sweep closes the queue out, B's row must be EXPIRED
with a non-empty result_note mentioning 未获得名额 (or the stored event
detail for an invalidated invitation). Poll budget: 150 s.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
SUFFIX = datetime.now().strftime("%Y%m%d%H%M%S")
PASSWORD = "Dazi@2026!"
POLL_BUDGET = 150

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token=None, body=None):
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    r = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=hdrs)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"success": False, "code": "HTTP_ERROR", "data": None}
    except Exception as e:
        return 0, {"success": False, "code": "NETWORK_ERROR", "message": str(e), "data": None}


def register_and_login(tag):
    acc = f"g14{tag}_{SUFFIX}"
    s, env = req("POST", "/register", body={"account": acc, "password": PASSWORD,
                                            "nickname": f"G14{tag}"})
    assert env.get("success"), f"register {acc} failed: {s} {env}"
    s, env = req("POST", "/login", body={"account": acc, "password": PASSWORD})
    assert env.get("success"), f"login {acc} failed: {s} {env}"
    return env["data"]["token"]


def my_row(token, aid, type_filter=None):
    path = "/my?page=1&pageSize=50"
    if type_filter:
        path += "&type=" + type_filter
    s, env = req("GET", path, token=token)
    if not env.get("success"):
        return None
    for row in env["data"].get("items", []):
        if str(row.get("activity_id")) == str(aid):
            return row
    return None


def main():
    org = register_and_login("org")
    user_a = register_and_login("a")
    user_b = register_and_login("b")

    now = datetime.now()
    fmt = "%Y-%m-%dT%H:%M:%S"
    deadline = now + timedelta(seconds=45)
    s, env = req("POST", "/activities", token=org, body={
        "title": f"G14候补截止_{SUFFIX}", "category": "其他",
        "description": "G14 回归", "conditions": "", "location": "线上",
        "capacity": 1,
        "deadline": deadline.strftime(fmt),
        "start_time": (now + timedelta(hours=3)).strftime(fmt),
        "end_time": (now + timedelta(hours=5)).strftime(fmt)})
    assert env.get("success"), f"create activity failed: {s} {env}"
    aid = env["data"]["id"]

    s, env = req("POST", f"/activities/{aid}/signup", token=user_a, body={})
    assert env.get("success"), f"A signup failed: {s} {env}"
    s, env = req("POST", f"/activities/{aid}/signup", token=user_b, body={})
    assert env.get("success"), f"B signup failed: {s} {env}"

    row = my_row(user_b, aid)
    check("截止前 B 为 WAITING", row is not None and row.get("status") == "WAITING",
          f"row={row}")

    # Wait for the deadline + sweep closeout to move B to EXPIRED.
    expired_row = None
    start_poll = time.time()
    while time.time() - start_poll < POLL_BUDGET:
        row = my_row(user_b, aid, type_filter="HISTORY")
        if row is not None and row.get("status") == "EXPIRED":
            expired_row = row
            break
        time.sleep(3)

    check("截止收尾后 B 在 HISTORY 中为 EXPIRED", expired_row is not None,
          f"last row={row}")
    if expired_row is not None:
        note = expired_row.get("result_note")
        check("EXPIRED 行 result_note 非空",
              isinstance(note, str) and note.strip() != "", f"note={note!r}")
        check("result_note 说明未获得名额/邀请作废原因",
              isinstance(note, str) and ("未获得名额" in note or "作废" in note),
              f"note={note!r}")

    # The default (unfiltered) /my view must carry the same note.
    row_default = my_row(user_b, aid)
    check("默认 /my 视图同一行也带 result_note",
          row_default is not None
          and isinstance(row_default.get("result_note"), str)
          and row_default["result_note"].strip() != "",
          f"row={row_default}")

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
