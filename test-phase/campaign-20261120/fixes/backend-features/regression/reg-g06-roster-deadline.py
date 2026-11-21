#!/usr/bin/env python3
"""REG-G06: 组织者名单截止裁剪（consistency-recheck G06a）。

Prerequisite: a running disposable campus-buddy instance, Shanghai wall clock,
BASE_URL env (bare root, default http://127.0.0.1:8080); the client appends
/api/v1. The activity deadline is ~75 s in the future, so the run waits ~80 s.

Expected (BuddyService.activityDetail, G06): before the deadline the
organizer's roster_sections.waiting holds the WAITING member (total 1); once
now >= deadline the waiting section is returned empty (items [], total 0) —
matching detail() dropping my_rank after the deadline — while the confirmed
section still shows the FORMAL member (total 1). The sweep may concurrently
close the WAITING row out to EXPIRED; the assertion targets the section
contract, not the stored row.
"""
import http.client
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
SHANGHAI = timezone(timedelta(hours=8))
RESULTS = []


class FixtureError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def req(method, path, token=None, body=None, headers=None):
    hdr = {"Accept": "application/json", "Content-Type": "application/json", **(headers or {})}
    if token:
        hdr["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    status = 0
    try:
        request = urllib.request.Request(BASE + path, data=data, headers=hdr, method=method)
        try:
            response = OPENER.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status, raw = response.getcode(), response.read(2**20 + 1)
        if len(raw) > 2**20:
            return status, {"code": "CLIENT_ERROR", "message": "response exceeds 1 MiB"}
        env = json.loads(raw.decode("utf-8"))
        return status, env if isinstance(env, dict) else {"code": "CLIENT_ERROR"}
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return status, {"code": "CLIENT_ERROR", "message": type(exc).__name__}


def check(name, condition, detail=""):
    passed = bool(condition)
    RESULTS.append(passed)
    print(f"{'PASS' if passed else 'FAIL'} - {name}" + (f" ({detail})" if detail and not passed else ""))
    return passed


def describe(reply):
    status, env = reply
    return f"HTTP {status}, success={env.get('success')!r}, code={env.get('code')!r}, message={env.get('message')!r}"


def ok_data(reply):
    status, env = reply
    data = env.get("data")
    if status == 200 and env.get("success") is True and env.get("code") == "OK" and isinstance(data, dict):
        return data
    return None


def require_data(label, reply):
    data = ok_data(reply)
    if data is None:
        raise FixtureError(f"{label}: {describe(reply)}")
    return data


def account(role, stamp):
    name = f"g06_{role}_{stamp}"
    credentials = {"account": name, "password": "G06a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def section(detail_data, name):
    sections = detail_data.get("roster_sections")
    if isinstance(sections, dict) and isinstance(sections.get(name), dict):
        return sections[name]
    return {}


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org = account("org", stamp)
    member_a = account("a", stamp)
    member_b = account("b", stamp)
    deadline = now + timedelta(seconds=75)
    start = deadline + timedelta(hours=1)
    created = require_data("create activity", req("POST", "/activities", org, {
        "title": f"REG-G06 roster {stamp}", "category": "桌游", "capacity": 1,
        "location": f"REG-G06 room {stamp}",
        "deadline": deadline.isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
    }))
    aid = created.get("id")
    if aid is None:
        raise FixtureError("create activity: missing id")

    signup_a = require_data("A signup", req("POST", f"/activities/{aid}/signup", member_a, {},
                                            headers={"Idempotency-Key": f"g06-a-{stamp}"}))
    if signup_a.get("my_status") != "FORMAL":
        raise FixtureError(f"A should be FORMAL: my_status={signup_a.get('my_status')!r}")
    signup_b = require_data("B signup", req("POST", f"/activities/{aid}/signup", member_b, {},
                                            headers={"Idempotency-Key": f"g06-b-{stamp}"}))
    if signup_b.get("my_status") != "WAITING":
        raise FixtureError(f"B should be WAITING: my_status={signup_b.get('my_status')!r}")

    before = require_data("organizer detail before deadline", req("GET", f"/activities/{aid}", org))
    waiting_before = section(before, "waiting")
    check("before deadline, organizer waiting section total == 1",
          waiting_before.get("total") == 1 and len(waiting_before.get("items") or []) == 1,
          f"waiting={waiting_before!r}")

    wait = (deadline - datetime.now(SHANGHAI).replace(tzinfo=None)).total_seconds() + 4
    if wait > 200:
        check("deadline wait bounded", False, f"wait={wait:.0f}s")
        return
    if wait > 0:
        time.sleep(wait)

    after = require_data("organizer detail after deadline", req("GET", f"/activities/{aid}", org))
    waiting_after = section(after, "waiting")
    confirmed_after = section(after, "confirmed")
    check("after deadline, organizer waiting section is empty (items [], total 0)",
          waiting_after.get("total") == 0 and (waiting_after.get("items") or []) == [],
          f"waiting={waiting_after!r}")
    check("after deadline, confirmed section still total == 1",
          confirmed_after.get("total") == 1, f"confirmed={confirmed_after!r}")


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
