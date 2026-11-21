#!/usr/bin/env python3
"""REG-15 / A2b-1 W2: cancellation endpoint contract (Python 3 stdlib).

Prerequisites: already-running disposable campus-buddy app and private test DB.
Set A2B1_ISOLATED=1 and an explicit BASE_URL, e.g. http://127.0.0.1:18080.
Use a bare HTTP root on 127.0.0.1 or [::1], port 1024–65535, not a shared/DB
port. The conventional http://127.0.0.1:8080 default cannot be used. No proxy,
redirect, server management or demo reset. Fixtures are left in the test DB.

Expected: false -> 400, OPEN/FORMAL and the event stream unchanged; true ->
cancellation Map and the trimmed reason in the immediately readable event;
same key/body -> identical status/body; same key/changed reason -> 409;
a fresh activity can still be cancelled with a bodyless POST.
"""
import http.client
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

RESULTS = []


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def isolated_client():
    root = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
    match = re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\]):([1-9][0-9]{3,4})", root)
    port = int(match[1]) if match else 0
    if ("BASE_URL" not in os.environ or os.environ.get("A2B1_ISOLATED") != "1"
            or not 1024 <= port <= 65535 or port in {3306, 5432, 5433, 8080, 8081, 15451}):
        raise SetupError("require explicit HTTP loopback BASE_URL on an isolated high port and A2B1_ISOLATED=1")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def req(method, path, token=None, body=None, key=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if key:
            headers["Idempotency-Key"] = key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(root + "/api/v1" + path, data=data, headers=headers, method=method)
        status = 0
        try:
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status, raw = response.getcode(), response.read(1048577)
            if len(raw) > 1048576:
                return status, {"code": "CLIENT_RESPONSE_LIMIT"}, b""
            envelope = json.loads(raw)
            return status, envelope if isinstance(envelope, dict) else {}, raw
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return status, {"code": type(exc).__name__}, b""

    return req


def check(name, passed, detail=""):
    RESULTS.append(bool(passed))
    print(f"{'PASS' if passed else 'FAIL'} - {name}" + (f" ({detail})" if detail and not passed else ""))


def describe(reply):
    return f"HTTP={reply[0]} code={reply[1].get('code')!r}"


def error(reply, status, code, text):
    env = reply[1]
    message = env.get("message")
    return (reply[0] == status and env.get("success") is False and env.get("code") == code
            and isinstance(message, str) and text in message and "data" in env and env["data"] is None)


def ok_data(reply, kind=dict):
    status, env, _ = reply
    data = env.get("data")
    if (status == 200 and env.get("success") is True and env.get("code") == "OK"
            and env.get("message") == "ok" and isinstance(data, kind)):
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


def cancellation_map(reply, notified):
    data = ok_data(reply) or {}
    return (data.get("ok") is True and data.get("status") == "CANCELLED"
            and data.get("alreadyCancelled") is False and type(data.get("notified")) is int
            and data["notified"] == notified)


def main():
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    stamp = now.strftime("%y%m%d%H%M%S%f") + secrets.token_hex(2)

    def account(role):
        name = f"w2{role}{stamp}"
        credentials = {"account": name, "password": "W2a9!" + secrets.token_hex(12)}
        require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
        token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
        if not isinstance(token, str) or not token:
            raise SetupError(f"login {role}: missing token")
        return token

    try:
        req = isolated_client()
        host, member = account("host"), account("member")
    except SetupError as exc:
        check("setup", False, str(exc))
        return 1

    # Separate activities (and non-overlapping times): the old controller can
    # wrongly cancel the explicit-false fixture without poisoning another case.
    for day, case in enumerate(("false", "confirmed", "legacy"), start=2):
        start = now + timedelta(days=day)
        try:
            activity = require_data("create activity", req("POST", "/activities", host, {
                "title": f"W2 cancel {case} {stamp}", "category": "桌游", "capacity": 1,
                "location": "REG-15 isolated fixture", "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
                "start_time": start.isoformat(timespec="seconds"),
                "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
            }))
            aid = row_id(activity, "id")
            activity_path = f"/activities/{aid}"
            cancel_path = activity_path + "/cancel"
            if case != "legacy":
                signup = require_data("join activity", req("POST", activity_path + "/signup", member))
                pid = row_id(signup, "participation_id")
                if (signup.get("status"), signup.get("my_status")) != ("OPEN", "FORMAL"):
                    raise SetupError("expected a fresh OPEN activity with a FORMAL member")
                event_path = f"/participations/{pid}/events"
        except SetupError as exc:
            check(f"{case} fixture", False, str(exc))
            continue

        reason = f"  REG-15 {stamp} 场地不可用  "
        if case == "false":
            before = ok_data(req("GET", event_path, member), list)
            reply = req("POST", cancel_path, host, {"reason": reason, "confirmed": False})
            check("explicit false requires confirmation", error(reply, 400, "ERROR", "二次确认"), describe(reply))
            detail = req("GET", activity_path, member)
            data = ok_data(detail) or {}
            check("explicit false leaves activity OPEN and same member FORMAL",
                  (data.get("status"), data.get("my_status"), data.get("participation_id")) == ("OPEN", "FORMAL", pid),
                  f"{describe(detail)} status={data.get('status')!r} my_status={data.get('my_status')!r}")
            events = req("GET", event_path, member)
            check("explicit false leaves event stream unchanged",
                  before is not None and before == ok_data(events, list), describe(events))
        elif case == "confirmed":
            key = "reg15-" + stamp
            body = {"reason": reason, "confirmed": True}
            first = req("POST", cancel_path, host, body, key=key)
            check("confirmed cancellation returns success Map", cancellation_map(first, 1), describe(first))
            event_reply = req("GET", event_path, member)  # No wait/poll or asynchronous notification lookup.
            events = ok_data(event_reply, list)
            cancelled = [e for e in (events or []) if isinstance(e, dict) and e.get("event_type") == "ACTIVITY_CANCELLED"]
            expected = {"activity_id": aid, "participation_id": pid, "from_status": "FORMAL",
                        "to_status": "CANCELLED", "detail": "取消原因：" + reason.strip()}
            check("cancellation event immediately contains the actual reason",
                  len(cancelled) == 1 and all(cancelled[0].get(k) == v for k, v in expected.items()), describe(event_reply))
            replay = req("POST", cancel_path, host, body, key=key)
            check("same-key identical body replays status and exact response bytes",
                  cancellation_map(first, 1) and (replay[0], replay[2]) == (first[0], first[2]), describe(replay))
            conflict = req("POST", cancel_path, host, dict(body, reason="不同的取消原因"), key=key)
            check("same key with changed reason returns 409 IDEMPOTENCY_CONFLICT",
                  error(conflict, 409, "IDEMPOTENCY_CONFLICT", "幂等键"), describe(conflict))
            after = req("GET", event_path, member)
            check("replay and conflict leave events unchanged",
                  events is not None and events == ok_data(after, list), describe(after))
        else:
            reply = req("POST", cancel_path, host)  # Deliberately no body, not even {}.
            check("legacy bodyless POST returns success Map", cancellation_map(reply, 0), describe(reply))
            detail = req("GET", activity_path, host)
            check("legacy cancellation persists", (ok_data(detail) or {}).get("status") == "CANCELLED", describe(detail))

    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
