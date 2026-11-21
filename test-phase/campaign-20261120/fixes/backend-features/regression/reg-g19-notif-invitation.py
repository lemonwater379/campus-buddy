#!/usr/bin/env python3
"""REG-G19: 通知的邀请状态按本条邀请（consistency-recheck G19）。

Prerequisites: a running disposable campus-buddy instance, Shanghai wall
clock, BASE_URL env (bare root, default http://127.0.0.1:8080); the client
appends /api/v1. Invitations are only issued in the daytime window
(08:00-22:00) unless the instance sets INVITE_DAY_START_HOUR=0 /
INVITE_DAY_END_HOUR=24, and INVITE_TTL (default 120 s) must leave enough time
to reject the first invitation before it expires. Run inside the window.

Scenario (capacity 1): A FORMAL; B, C WAITING. A withdraws -> B is invited
(I1, notification N1). B rejects I1 -> C is invited. B re-signs up (WAITING).
C rejects -> B is invited again (I2, notification N2).

Expected (BuddyService.listNotifications, G19): each notification row carries
invitation_status from ITS OWN invitation_id: N1.invitation_status ==
"REJECTED" even though B's latest invitation I2 is PENDING, and
N2.invitation_status == "PENDING". The old controller-side
latestInvitationStatus(me, activityId) overwrote every row of the activity
with the newest invitation's status (see ApiV1Controller.notifications);
that overwrite is B2's fix — this script asserts the end-to-end contract.
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


def ok_data(reply, kind=dict):
    status, env = reply
    data = env.get("data")
    if status == 200 and env.get("success") is True and env.get("code") == "OK" and isinstance(data, kind):
        return data
    return None


def require_data(label, reply, kind=dict):
    data = ok_data(reply, kind)
    if data is None:
        raise FixtureError(f"{label}: {describe(reply)}")
    return data


def account(role, stamp):
    name = f"g19_{role}_{stamp}"
    credentials = {"account": name, "password": "G19a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def invite_notifications(token):
    data = ok_data(req("GET", "/notifications?page=1&pageSize=50", token)) or {}
    items = data.get("items")
    if not isinstance(items, list):
        return []
    return [row for row in items if isinstance(row, dict)
            and row.get("type") == "邀请" and row.get("invitation_id") is not None]


def wait_invite_notification(token, known_ids, timeout_s=20):
    """Poll until an invite notification with an invitation_id not in known_ids appears."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for row in invite_notifications(token):
            if str(row.get("invitation_id")) not in known_ids:
                return row
        time.sleep(0.5)
    return None


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    if not (8 <= now.hour < 22):
        raise FixtureError("outside invitation daytime window 08:00-22:00; "
                           "rerun in-window or set INVITE_DAY_START_HOUR=0/END_HOUR=24")
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org = account("org", stamp)
    tok_a, tok_b, tok_c = account("a", stamp), account("b", stamp), account("c", stamp)
    seq = [0]

    def keyed(token, method, path, body=None):
        seq[0] += 1
        return req(method, path, token, body, headers={"Idempotency-Key": f"g19-{stamp}-{seq[0]}"})

    start = now + timedelta(days=2)
    created = require_data("create activity", req("POST", "/activities", org, {
        "title": f"REG-G19 notif {stamp}", "category": "桌游", "capacity": 1,
        "location": f"REG-G19 room {stamp}",
        "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
    }))
    aid = created.get("id")
    if aid is None:
        raise FixtureError("create activity: missing id")

    signup_a = require_data("A signup", keyed(tok_a, "POST", f"/activities/{aid}/signup", {}))
    if signup_a.get("my_status") != "FORMAL" or signup_a.get("participation_id") is None:
        raise FixtureError(f"A should be FORMAL with participation_id: {signup_a!r}")
    signup_b = require_data("B signup", keyed(tok_b, "POST", f"/activities/{aid}/signup", {}))
    signup_c = require_data("C signup", keyed(tok_c, "POST", f"/activities/{aid}/signup", {}))
    if signup_b.get("my_status") != "WAITING" or signup_c.get("my_status") != "WAITING":
        raise FixtureError("B and C should both be WAITING")

    # A withdraws -> B invited (I1 / N1).
    withdrawn = keyed(tok_a, "POST", f"/participations/{signup_a['participation_id']}/withdraw",
                      {"confirmed": True, "version": signup_a.get("participation_version")})
    require_data("A withdraw", withdrawn)
    n1 = wait_invite_notification(tok_b, set())
    if n1 is None:
        raise FixtureError("B received no invitation notification (I1) within 20 s")
    i1 = str(n1.get("invitation_id"))

    # B rejects I1 -> C invited; B re-signs up -> WAITING again.
    require_data("B reject I1", keyed(tok_b, "POST", f"/invitations/{i1}/reject"))
    n_c = wait_invite_notification(tok_c, set())
    if n_c is None:
        raise FixtureError("C received no invitation notification within 20 s")
    i_c = str(n_c.get("invitation_id"))
    re_b = require_data("B re-signup", keyed(tok_b, "POST", f"/activities/{aid}/signup", {}))
    if re_b.get("my_status") != "WAITING":
        raise FixtureError(f"B re-signup should be WAITING: {re_b.get('my_status')!r}")

    # C rejects -> B invited again (I2 / N2).
    require_data("C reject", keyed(tok_c, "POST", f"/invitations/{i_c}/reject"))
    n2 = wait_invite_notification(tok_b, {i1})
    if n2 is None:
        raise FixtureError("B received no second invitation notification (I2) within 20 s")
    i2 = str(n2.get("invitation_id"))
    check("second invitation is a different invitation (I2 != I1)", i2 != i1, f"I1={i1} I2={i2}")
    check("N2 (own invitation I2) invitation_status is PENDING",
          n2.get("invitation_status") == "PENDING", f"N2={n2!r}")

    rows = {str(r.get("invitation_id")): r for r in invite_notifications(tok_b)}
    n1_now = rows.get(i1) or {}
    check("N1 (own invitation I1, rejected) invitation_status is REJECTED, not the latest PENDING",
          n1_now.get("invitation_status") == "REJECTED", f"N1={n1_now!r}")


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
