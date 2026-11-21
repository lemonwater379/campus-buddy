#!/usr/bin/env python3
"""REG-G03: 活动编辑版本令牌可靠化（consistency-recheck G03）。

Prerequisite: a running disposable campus-buddy instance, Shanghai wall clock,
BASE_URL env (bare root, default http://127.0.0.1:8080); the client appends
/api/v1. Creates its own organizer account and one activity.

Expected (BuddyService.editActivity, G03):
- edit without expectedVersion (missing or blank) -> 400, message contains
  「缺少版本号」 (the old requireVersion silently allowed a missing version).
- two rapid consecutive edits (aiming at the same wall-clock second) each
  advance the token: V1 != V0 and V2 != V1 (the old code wrote updated_at at
  second precision, so a same-second edit could keep the same token).
- reusing the stale token V1 afterwards -> 409 CONFLICT with
  data.current_version == V2.
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
    name = f"g03_{role}_{stamp}"
    credentials = {"account": name, "password": "G03a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def is_400_with(reply, needle):
    status, env = reply
    message = env.get("message")
    return status == 400 and env.get("success") is False and isinstance(message, str) and needle in message


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org = account("org", stamp)
    start = now + timedelta(days=2)
    create = req("POST", "/activities", org, {
        "title": f"REG-G03 version {stamp}", "category": "桌游", "capacity": 2,
        "location": f"REG-G03 room {stamp}",
        "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=2)).isoformat(timespec="seconds"),
    })
    created = ok_data(create) or {}
    aid, v0 = created.get("id"), created.get("activity_version")
    if not check("create returns activity id and V0", aid is not None and isinstance(v0, str) and bool(v0),
                 describe(create)):
        return
    edit_path = f"/activities/{aid}/edit"
    n = [0]

    def edit(body):
        n[0] += 1
        return req("PATCH", edit_path, org, body,
                   headers={"Idempotency-Key": f"g03-{stamp}-{n[0]}"})

    missing = edit({"title": f"REG-G03 no-version {stamp}"})
    check("edit without expectedVersion returns 400 缺少版本号",
          is_400_with(missing, "缺少版本号"), describe(missing))
    blank = edit({"title": f"REG-G03 blank-version {stamp}", "expectedVersion": "  "})
    check("edit with blank expectedVersion returns 400 缺少版本号",
          is_400_with(blank, "缺少版本号"), describe(blank))

    # No sleep on purpose: both edits should land in the same wall-clock second.
    first = edit({"title": f"REG-G03 first {stamp}", "expectedVersion": v0})
    v1 = (ok_data(first) or {}).get("activity_version")
    if not check("first rapid edit succeeds and token changes (V1 != V0)",
                 isinstance(v1, str) and v1 != v0, f"{describe(first)}; v0={v0!r}"):
        return
    second = edit({"title": f"REG-G03 second {stamp}", "expectedVersion": v1})
    v2 = (ok_data(second) or {}).get("activity_version")
    if not check("second rapid edit succeeds and token changes again (V2 != V1)",
                 isinstance(v2, str) and v2 != v1, f"{describe(second)}; v1={v1!r}"):
        return

    stale = edit({"title": f"REG-G03 stale {stamp}", "expectedVersion": v1})
    conflict = stale[1].get("data")
    check("stale V1 edit returns 409 CONFLICT with current_version == V2",
          stale[0] == 409 and stale[1].get("code") == "CONFLICT"
          and isinstance(conflict, dict) and conflict.get("current_version") == v2,
          f"{describe(stale)}; expected current_version={v2!r}")


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
