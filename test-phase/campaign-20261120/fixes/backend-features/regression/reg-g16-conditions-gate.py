#!/usr/bin/env python3
"""REG-G16: 报名条件确认服务端强制（consistency-recheck §3 / G16）。

Prerequisite: a running disposable campus-buddy instance, Shanghai wall clock,
BASE_URL env (bare root, default http://127.0.0.1:8080); the client appends
/api/v1. Creates its own organizer/members and two activities at different
times (no time-conflict overlap).

Expected (BuddyService.signup, G16):
- activity WITH conditions: signup without conditions_confirmed, or with
  conditions_confirmed=false -> 400, message contains 「请先确认已阅读参与条件」
  (the old code only logged CONDITIONS_CONFIRMED and never rejected).
- with conditions_confirmed=true -> 200.
- the same member calling signup again (already holding a valid participation)
  without the flag -> 200, not blocked (early-return exemption).
- activity WITHOUT conditions: signup without the flag -> 200.
Every signup uses a unique Idempotency-Key so a replayed first response cannot
mask the service-side gate.
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
    name = f"g16_{role}_{stamp}"
    credentials = {"account": name, "password": "G16a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org = account("org", stamp)
    member = account("m", stamp)
    other = account("o", stamp)
    seq = [0]

    def create(tag, start, conditions):
        body = {
            "title": f"REG-G16 {tag} {stamp}", "category": "羽毛球", "capacity": 2,
            "location": f"REG-G16 room {stamp}",
            "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
            "start_time": start.isoformat(timespec="seconds"),
            "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
        }
        if conditions is not None:
            body["conditions"] = conditions
        created = require_data(f"create {tag}", req("POST", "/activities", org, body))
        if created.get("id") is None:
            raise FixtureError(f"create {tag}: missing id")
        return created["id"]

    def signup(aid, token, body):
        seq[0] += 1
        return req("POST", f"/activities/{aid}/signup", token, body,
                   headers={"Idempotency-Key": f"g16-{stamp}-{seq[0]}"})

    gated = create("gated", now + timedelta(days=2), "请自备球拍和运动鞋")
    plain = create("plain", now + timedelta(days=3), None)

    reply = signup(gated, member, {})
    check("gated signup without flag returns 400 请先确认已阅读参与条件",
          reply[0] == 400 and "请先确认已阅读参与条件" in str(reply[1].get("message")),
          describe(reply))
    reply = signup(gated, member, {"conditions_confirmed": False})
    check("gated signup with conditions_confirmed=false returns 400",
          reply[0] == 400 and "请先确认已阅读参与条件" in str(reply[1].get("message")),
          describe(reply))

    reply = signup(gated, member, {"conditions_confirmed": True})
    data = ok_data(reply) or {}
    first_status = data.get("my_status")
    if not check("gated signup with conditions_confirmed=true returns 200",
                 first_status in ("FORMAL", "WAITING"), describe(reply)):
        return

    reply = signup(gated, member, {})
    data = ok_data(reply) or {}
    check("repeat signup by existing participant without flag is not blocked (200, same status)",
          data.get("my_status") == first_status, describe(reply))

    reply = signup(plain, other, {})
    data = ok_data(reply) or {}
    check("plain (no conditions) signup without flag returns 200",
          data.get("my_status") in ("FORMAL", "WAITING"), describe(reply))


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
