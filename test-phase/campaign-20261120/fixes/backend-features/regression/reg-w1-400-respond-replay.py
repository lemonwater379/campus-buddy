#!/usr/bin/env python3
"""REG-W1 / A6: respond's committed HTTP 400 and exact idempotent replay.

Sources: remaining.md #1 W1; report-A2b1.md, W1 idempotency section.
Prerequisites (unmet prerequisites are FAIL, never a skipped PASS): an already
running disposable campus-buddy instance using UTC+08:00 business wall time;
/health data.invite_ttl_seconds must be a positive integer <= 150. Configure
INVITE_DAY_START_HOUR=0 / INVITE_DAY_END_HOUR=24, or run during the invitation
window. The invitation sweep interval must be long enough to leave PENDING /
INVITED intact until the expired invitation is answered. The script checks b
is still INVITED, with the same invitation, after waiting past its expiry.
The expiry+1-second wait is bounded to 155 seconds per fixture (310 total).
BASE_URL defaults to http://127.0.0.1:8080; the client appends /api/v1.

Expected for independent accept/reject activities: a FORMAL, b WAITING;
a's confirmed withdraw promotes b to INVITED/PENDING. After expiry, respond
commits EXPIRED and one INVITE_EXPIRED event, but returns HTTP 400 with
success=false, an expiry message and no private underscore-prefixed data keys.
The identical Idempotency-Key and body replay the same 400 and raw bytes,
without a second closeout. accept sends {"confirmConflict": true}; reject
sends no body. Fixtures remain; Python 3 stdlib only. No database access,
demo reset, service management or configuration changes are performed.
"""
import http.client
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
TZ = timezone(timedelta(hours=8))
MAX_EXPIRY_WAIT = 155.0
RESULTS = []


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def req(method, path, token=None, body=None, headers=None):
    request_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        request_headers["Authorization"] = "Bearer " + token
    if headers:
        request_headers.update(headers)
    payload = None if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    status, raw = 0, b""
    try:
        request = urllib.request.Request(BASE + path, data=payload,
                                         headers=request_headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status, raw = response.getcode(), response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError("response exceeds 1 MiB")
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            raise ValueError("response envelope is not an object")
        return status, envelope, raw
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return status, {"success": False, "code": "CLIENT_ERROR",
                        "message": f"{type(exc).__name__}: {exc}", "data": None}, raw


def check(name, condition, detail=""):
    RESULTS.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'} - {name}"
          + (f" ({detail})" if detail and not condition else ""), flush=True)


def describe(reply):
    return (f"HTTP={reply[0]} code={reply[1].get('code')!r} "
            f"message={reply[1].get('message')!r} data={str(reply[1].get('data'))[:350]}")


def ok_data(reply, kind=dict):
    status, envelope, _ = reply
    data = envelope.get("data")
    if (status == 200 and envelope.get("success") is True
            and envelope.get("code") == "OK" and envelope.get("message") == "ok"
            and isinstance(data, kind)):
        return data
    return None


def require_data(label, reply):
    data = ok_data(reply)
    if data is None:
        raise SetupError(f"{label}: {describe(reply)}")
    return data


def row_id(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise SetupError(f"missing/invalid {field}")
    return value


def now():
    return datetime.now(TZ).replace(tzinfo=None)


def wall(raw):
    if not isinstance(raw, str):
        raise SetupError("invitation_expires_at is missing or not a string")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SetupError(f"invalid invitation_expires_at: {raw!r}") from exc
    return value.astimezone(TZ).replace(tzinfo=None) if value.tzinfo else value


def account(role, stamp):
    name = f"rw1{role}{stamp}"
    credentials = {"account": name, "password": "Rw1a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token:
        raise SetupError(f"login {role}: missing token")
    return token


def pending(data, iid, pid):
    rows = data.get("pending_invitations") if data is not None else None
    return (isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
            and len([row for row in rows if row.get("id") == iid
                     and row.get("participation_id") == pid and row.get("status") == "PENDING"]) == 1)


def no_private_keys(value):
    if isinstance(value, dict):
        return all(not key.startswith("_") and no_private_keys(item) for key, item in value.items())
    if isinstance(value, list):
        return all(no_private_keys(item) for item in value)
    return True


def expired_error(reply, aid, iid, pid):
    status, envelope, _ = reply
    data, message = envelope.get("data"), envelope.get("message")
    return (status == 400 and envelope.get("success") is False
            and envelope.get("code") == "ERROR" and isinstance(message, str) and "过期" in message
            and isinstance(data, dict) and data.get("activity_id") == aid
            and data.get("participation_id") == pid and data.get("invitation_id") == iid
            and data.get("my_status") == "EXPIRED" and data.get("invitation_status") == "EXPIRED")


def expired_state(reply, pid):
    data = ok_data(reply)
    return (data is not None and data.get("participation_id") == pid
            and data.get("my_status") == "EXPIRED")


def one_expiry_event(reply, aid, pid):
    events = ok_data(reply, list)
    if events is None or not all(isinstance(row, dict) for row in events):
        return False
    expired = [row for row in events if row.get("event_type") == "INVITE_EXPIRED"]
    return (len(expired) == 1 and expired[0].get("activity_id") == aid
            and expired[0].get("participation_id") == pid
            and expired[0].get("from_status") == "INVITED" and expired[0].get("to_status") == "EXPIRED")


def run_case(action, day, organizer, a, b, ttl, stamp):
    current = now()
    start = current + timedelta(days=day)
    activity = require_data(f"{action}: create capacity-1 activity", req("POST", "/activities", organizer, {
        "title": f"REGW1 {action} {stamp}", "category": "桌游", "capacity": 1,
        "location": "REG-W1 fixture", "deadline": (current + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
    }))
    aid = row_id(activity, "id")
    detail_path = f"/activities/{aid}"
    a_reply, b_reply = req("POST", detail_path + "/signup", a), req("POST", detail_path + "/signup", b)
    a_data, b_data = ok_data(a_reply), ok_data(b_reply)
    ready = (a_data is not None and a_data.get("my_status") == "FORMAL"
             and b_data is not None and b_data.get("my_status") == "WAITING")
    check(f"{action}: prerequisite a FORMAL / b WAITING", ready,
          f"a: {describe(a_reply)}; b: {describe(b_reply)}")
    if not ready:
        return
    a_pid, pid = row_id(a_data, "participation_id"), row_id(b_data, "participation_id")
    withdrawal = req("POST", f"/participations/{a_pid}/withdraw", a, {"confirmed": True})
    data = ok_data(withdrawal)
    withdrawn = data is not None and data.get("participation_id") == a_pid and data.get("status") == "WITHDRAWN"
    check(f"{action}: a confirmed withdraw succeeds", withdrawn, describe(withdrawal))
    if not withdrawn:
        return

    b_detail = req("GET", detail_path, b)
    data = require_data(f"{action}: b invitation detail", b_detail)
    iid = row_id(data, "invitation_id")
    raw_expiry = data.get("invitation_expires_at")
    expires = wall(raw_expiry)
    organizer_detail = req("GET", detail_path, organizer)
    remaining = (expires - now()).total_seconds()
    invited = (data.get("my_status") == "INVITED" and data.get("participation_id") == pid
               and pending(ok_data(organizer_detail), iid, pid) and remaining <= ttl + 2)
    check(f"{action}: prerequisite fresh INVITED / PENDING invitation", invited,
          f"b: {describe(b_detail)}; host: {describe(organizer_detail)}; remaining={remaining:.3f}s")
    if not invited:
        return
    print(f"FIXTURE action={action} activity_id={aid} participation_id={pid} "
          f"invitation_id={iid} invitation_expires_at={raw_expiry}", flush=True)

    target = expires + timedelta(seconds=1)
    wait_seconds = max(0.0, (target - now()).total_seconds())
    bounded = wait_seconds <= MAX_EXPIRY_WAIT
    check(f"{action}: prerequisite expiry+1s wait <= {MAX_EXPIRY_WAIT:g}s", bounded,
          f"required_wait={wait_seconds:.3f}s")
    if not bounded:
        return
    stop = time.monotonic() + MAX_EXPIRY_WAIT
    while now() < target:
        if time.monotonic() >= stop:
            raise SetupError(f"{action}: expiry wait exceeded its monotonic bound")
        time.sleep(min(0.2, max(0.001, (target - now()).total_seconds())))

    # Crucial: an already-swept invitation only tests a terminal-state error,
    # not the branch that commits the expiry while returning _respond_error.
    still_reply = req("GET", detail_path, b)
    still = ok_data(still_reply)
    unswept = (still is not None and still.get("my_status") == "INVITED"
               and still.get("participation_id") == pid and still.get("invitation_id") == iid
               and still.get("invitation_expires_at") == raw_expiry and now() >= target)
    check(f"{action}: prerequisite expired invitation remains INVITED before respond", unswept,
          describe(still_reply) + "; require a longer sweep interval and an active invitation window")
    if not unswept:
        return

    path = f"/invitations/{iid}/{action}"
    body = {"confirmConflict": True} if action == "accept" else None  # reject deliberately has no body.
    headers = {"Idempotency-Key": f"regw1-{action}-{stamp}"}
    first = req("POST", path, b, body, headers)
    check(f"{action}: first respond is HTTP 400 expiry with committed EXPIRED state",
          expired_error(first, aid, iid, pid), describe(first))
    first_data = first[1].get("data")
    check(f"{action}: error data has no underscore-prefixed keys",
          expired_error(first, aid, iid, pid) and no_private_keys(first_data), describe(first))
    first_state = req("GET", detail_path, b)
    first_events = req("GET", f"/participations/{pid}/events", b)
    check(f"{action}: first respond persists b EXPIRED", expired_state(first_state, pid), describe(first_state))
    check(f"{action}: first respond creates exactly one INVITE_EXPIRED event",
          one_expiry_event(first_events, aid, pid), describe(first_events))

    replay = req("POST", path, b, body, headers)
    check(f"{action}: same-key same-body replay remains HTTP 400, never 200",
          expired_error(replay, aid, iid, pid), describe(replay))
    check(f"{action}: replay status and raw response bytes exactly match first",
          expired_error(first, aid, iid, pid) and expired_error(replay, aid, iid, pid)
          and bool(first[2]) and (replay[0], replay[2]) == (first[0], first[2]), describe(replay))
    after_state = req("GET", detail_path, b)
    after_events = req("GET", f"/participations/{pid}/events", b)
    check(f"{action}: replay leaves b EXPIRED", expired_state(after_state, pid), describe(after_state))
    check(f"{action}: replay does not repeat closeout; exactly one unchanged INVITE_EXPIRED",
          one_expiry_event(after_events, aid, pid) and one_expiry_event(first_events, aid, pid)
          and ok_data(after_events, list) == ok_data(first_events, list), describe(after_events))


def run():
    health = req("GET", "/health")
    data = ok_data(health)
    ttl = data.get("invite_ttl_seconds") if data is not None else None
    short_ttl = type(ttl) is int and 0 < ttl <= 150
    check("prerequisite: actual health invitation TTL is 1..150 seconds", short_ttl, describe(health))
    if not short_ttl:
        return
    stamp = now().strftime("%y%m%d%H%M%S") + secrets.token_hex(3)
    organizer, a, b = account("org", stamp), account("a", stamp), account("b", stamp)
    for day, action in enumerate(("accept", "reject"), start=2):
        try:
            run_case(action, day, organizer, a, b, ttl, stamp)
        except SetupError as exc:
            check(f"{action}: prerequisite / fixture", False, str(exc))


def main():
    try:
        run()
    except SetupError as exc:
        check("prerequisite / fixture", False, str(exc))
    except Exception as exc:
        check("unexpected error", False, f"{type(exc).__name__}: {exc}")
    print(f"SUMMARY {sum(RESULTS)}/{len(RESULTS)} PASS", flush=True)
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
