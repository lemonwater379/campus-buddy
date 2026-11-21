#!/usr/bin/env python3
"""REG-G04: 取消活动服务端贯通（consistency-recheck G04）。

Prerequisite: a running disposable campus-buddy instance, Shanghai wall clock,
BASE_URL env (bare root, default http://127.0.0.1:8080); the client appends
/api/v1. Each sub-case builds its own activity. The ended-activity sub-case
waits for a near-future activity to actually end (~2 minutes); the whole run
can take up to ~3 minutes.

Expected (BuddyService.cancelActivity, G04):
- missing confirmed / confirmed=false / missing reason / blank reason -> 400
  each, and the activity stays OPEN (the old code only rejected explicit
  false and stored a blank reason as no reason).
- confirmed=true with a non-blank reason -> 200, status CANCELLED.
- cancelling an activity whose end_time has passed (even with confirmed and
  reason present) -> 400 with 「已结束」 (the old code only checked the stored
  ENDED status, not the actual end time).
Every cancel call uses a unique Idempotency-Key so replays cannot mask the
service-side verdict.
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
    name = f"g04_{role}_{stamp}"
    credentials = {"account": name, "password": "G04a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org = account("org", stamp)
    seq = [0]

    def fresh_activity(tag, start, end, deadline):
        seq[0] += 1
        created = require_data(f"create {tag}", req("POST", "/activities", org, {
            "title": f"REG-G04 {tag} {stamp}-{seq[0]}", "category": "桌游", "capacity": 2,
            "location": f"REG-G04 room {stamp}",
            "deadline": deadline.isoformat(timespec="seconds"),
            "start_time": start.isoformat(timespec="seconds"),
            "end_time": end.isoformat(timespec="seconds"),
        }))
        return created.get("id")

    def cancel(aid, body):
        seq[0] += 1
        return req("POST", f"/activities/{aid}/cancel", org, body,
                   headers={"Idempotency-Key": f"g04-{stamp}-{seq[0]}"})

    def status_of(aid):
        return (ok_data(req("GET", f"/activities/{aid}", org)) or {}).get("status")

    start = now + timedelta(days=2)
    end = start + timedelta(hours=2)
    deadline = now + timedelta(days=1)

    aid = fresh_activity("missing", start, end, deadline)
    reply = cancel(aid, {})
    check("cancel with empty body returns 400", reply[0] == 400 and reply[1].get("success") is False,
          describe(reply))
    check("activity stays OPEN after missing-confirmed cancel", status_of(aid) == "OPEN",
          f"status={status_of(aid)!r}")

    reply = cancel(aid, {"confirmed": False, "reason": "测试原因"})
    check("cancel with confirmed=false returns 400", reply[0] == 400, describe(reply))
    check("activity stays OPEN after confirmed=false cancel", status_of(aid) == "OPEN",
          f"status={status_of(aid)!r}")

    reply = cancel(aid, {"confirmed": True})
    check("cancel without reason returns 400 取消原因不能为空",
          reply[0] == 400 and "取消原因不能为空" in str(reply[1].get("message")), describe(reply))
    reply = cancel(aid, {"confirmed": True, "reason": "   "})
    check("cancel with blank reason returns 400", reply[0] == 400, describe(reply))
    check("activity stays OPEN after blank-reason cancel", status_of(aid) == "OPEN",
          f"status={status_of(aid)!r}")

    reply = cancel(aid, {"confirmed": True, "reason": "  场地变更  "})
    data = ok_data(reply) or {}
    check("valid cancel returns 200 CANCELLED", data.get("status") == "CANCELLED", describe(reply))
    check("cancel persists as CANCELLED", status_of(aid) == "CANCELLED", f"status={status_of(aid)!r}")

    # Ended-activity boundary: near-future activity, wait until end_time passes.
    t0 = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    e_start = t0 + timedelta(seconds=70)
    e_end = e_start + timedelta(seconds=60)
    e_deadline = t0 + timedelta(seconds=30)
    aid2 = fresh_activity("ended", e_start, e_end, e_deadline)
    wait = (e_end - datetime.now(SHANGHAI).replace(tzinfo=None)).total_seconds() + 3
    if wait > 240:
        check("ended fixture wait bounded", False, f"wait={wait:.0f}s")
        return
    if wait > 0:
        time.sleep(wait)
    reply = cancel(aid2, {"confirmed": True, "reason": "活动已结束仍尝试取消"})
    check("cancel after end_time returns 400 已结束",
          reply[0] == 400 and "已结束" in str(reply[1].get("message")), describe(reply))


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
