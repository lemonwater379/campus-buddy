#!/usr/bin/env python3
"""REG-G02: 编辑时间口径统一——截止 == 开始合法（consistency-recheck G02）。

Prerequisite: a running disposable campus-buddy instance, Shanghai wall clock,
BASE_URL env (bare root, default http://127.0.0.1:8080); the client appends
/api/v1. Creates its own organizer account and one activity; fixtures are left
in the test instance.

Expected: creating with deadline == start_time succeeds; a title-only edit of
that activity (with expectedVersion) returns 200 (the old editActivity required
deadline.isBefore(start) and rejected it); editing the deadline to after the
start returns 400.

Sources: BuddyService.editActivity (G02), ApiV1Controller create/edit.
"""
import http.client
import json
import os
import secrets
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
    name = f"g02_{role}_{stamp}"
    credentials = {"account": name, "password": "G02a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org = account("org", stamp)
    start = (now + timedelta(days=2)).replace(minute=0, second=0)
    end = start + timedelta(hours=2)
    create = req("POST", "/activities", org, {
        "title": f"REG-G02 deadline-eq {stamp}", "category": "桌游", "capacity": 2,
        "location": f"REG-G02 room {stamp}",
        "deadline": start.isoformat(timespec="seconds"),  # deadline == start_time
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": end.isoformat(timespec="seconds"),
    })
    created = ok_data(create) or {}
    aid, v0 = created.get("id"), created.get("activity_version")
    if not check("create with deadline == start succeeds and returns version",
                 aid is not None and isinstance(v0, str) and bool(v0), describe(create)):
        return
    edit_path = f"/activities/{aid}/edit"

    edited = req("PATCH", edit_path, org, {"title": f"REG-G02 renamed {stamp}", "expectedVersion": v0})
    data = ok_data(edited) or {}
    v1 = data.get("activity_version")
    check("title-only edit of deadline==start activity returns 200",
          data.get("title") == f"REG-G02 renamed {stamp}", describe(edited))
    check("successful edit advances activity_version", isinstance(v1, str) and v1 != v0,
          f"v0={v0!r} v1={v1!r}")
    if not isinstance(v1, str):
        return

    late = req("PATCH", edit_path, org, {
        "deadline": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
        "expectedVersion": v1,
    }, headers={"Idempotency-Key": "g02-late-" + stamp})
    check("edit with deadline after start returns 400",
          late[0] == 400 and late[1].get("success") is False, describe(late))


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
