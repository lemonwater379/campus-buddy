#!/usr/bin/env python3
"""REG-32 / B7: R2 waitlist ranks and configured invitation-window text.

Source: brief-B.md:54 (候补通知名次 = R2 真实名次、文案窗口与配置一致), B7.
Prerequisites: an already-running disposable campus-buddy instance, with its
business clock using UTC+08:00. BASE_URL defaults to http://127.0.0.1:8080;
the client appends /api/v1. Only Python 3 standard-library modules are used.
Creates unique accounts and a capacity-1 activity; fixtures are left in place.
No database access, demo reset, configuration changes or service management.

Expected: WAITING ranks follow (queued_at, id), starting at 1, not the total
queue length. Published 候补 notifications contain the actual rank and the
window calculated from /health data.invite_ttl_seconds. Notification polling
is bounded to about 10 seconds. After w1 abandons, w2/w3 become ranks 1/2;
a fresh w1 reentry notification must agree with w1's newly read my_rank.
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
from decimal import Decimal, ROUND_HALF_UP

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
TZ = timezone(timedelta(hours=8))
RESULTS = []


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def req(method, path, token=None, body=None, headers=None, timeout=2, deadline=None):
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
        effective_timeout = timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("request deadline elapsed before connect")
            effective_timeout = min(timeout, remaining)
        try:
            response = opener.open(request, timeout=effective_timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status = response.getcode()
            if deadline is None:
                raw = response.read(1048577)
            else:
                chunks = []
                size = 0
                sock = response.fp.raw._sock
                while size <= 1048576:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("response deadline elapsed while reading")
                    sock.settimeout(min(timeout, remaining))
                    chunk = response.read(min(65536, 1048577 - size))
                    if time.monotonic() >= deadline:
                        raise TimeoutError("response exceeded its total deadline")
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                raw = b"".join(chunks)
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


def invite_window_text(ttl):
    if ttl < 60:
        return f"{ttl} 秒"
    if ttl % 60 == 0:
        return f"{ttl // 60} 分钟"
    # Java String.format(Locale.ROOT, "%.1f", ...) uses half-up, not Python's
    # ties-to-even rounding (75 seconds must produce "1.3 分钟", not "1.2").
    minutes = (Decimal(ttl) / Decimal(60)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{minutes:.1f} 分钟"


def account(role, stamp):
    name = f"r32{role}{stamp}"
    credentials = {"account": name, "password": "R32a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token:
        raise SetupError(f"login {role}: missing token")
    return token


def poll_notification(token, aid, old_ids=frozenset()):
    """Only accept published, activity-specific notices unseen before this signup."""
    stop = time.monotonic() + 10.0
    last_reply = (0, {"success": False, "code": "POLL_TIMEOUT",
                      "message": "notification publication deadline elapsed", "data": None}, b"")
    while time.monotonic() < stop:
        # Socket operations use the remaining budget so a slow response cannot
        # extend the overall polling deadline past the advertised ~10 seconds.
        last_reply = req("GET", "/notifications?page=1&pageSize=100", token,
                         timeout=2.0, deadline=stop)
        if time.monotonic() > stop:
            return last_reply, []
        data = ok_data(last_reply)
        items = data.get("items") if data is not None else None
        if not isinstance(items, list) or not all(isinstance(row, dict) for row in items):
            return last_reply, []
        matches = [row for row in items if row.get("type") == "候补"
                   and row.get("activity_id") == aid and row.get("id") not in old_ids]
        if matches:
            return last_reply, matches
        time.sleep(min(0.25, max(0.0, stop - time.monotonic())))
    return last_reply, []


def notice_checks(label, reply, notices, rank, window):
    notice = notices[0] if len(notices) == 1 else {}
    content = notice.get("content")
    valid = (ok_data(reply) is not None and len(notices) == 1
             and isinstance(notice.get("id"), str)
             and re.fullmatch(r"[1-9][0-9]*", notice["id"]) is not None
             and isinstance(content, str))
    check(f"{label}: one newly published 候补 notification", valid, describe(reply))
    check(f"{label}: notification uses R2 rank {rank}",
          valid and type(rank) is int and rank > 0 and f"第 {rank} 名" in content,
          f"rank={rank!r} content={content!r}")
    check(f"{label}: notification uses health TTL window",
          valid and f"须在 {window} 内确认" in content, f"window={window!r} content={content!r}")
    return {notice["id"]} if valid else set()


def run():
    health = req("GET", "/health")
    health_data = ok_data(health)
    ttl = health_data.get("invite_ttl_seconds") if health_data is not None else None
    valid_ttl = type(ttl) is int and ttl > 0
    check("prerequisite: health exposes a positive integer invitation TTL", valid_ttl, describe(health))
    if not valid_ttl:
        return
    window = invite_window_text(ttl)
    print(f"CONFIG invite_ttl_seconds={ttl} expected_window={window}", flush=True)

    now = datetime.now(TZ).replace(tzinfo=None)
    stamp = now.strftime("%y%m%d%H%M%S") + secrets.token_hex(3)
    organizer, holder = account("org", stamp), account("h", stamp)
    waiters = {role: account(role, stamp) for role in ("w1", "w2", "w3")}
    start = now + timedelta(days=2)
    activity = require_data("create capacity-1 activity", req("POST", "/activities", organizer, {
        "title": f"REG32 ranks {stamp}", "category": "桌游", "capacity": 1,
        "location": "REG-32 fixture", "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
    }))
    aid = row_id(activity, "id")
    path = f"/activities/{aid}"
    reply = req("POST", path + "/signup", holder)
    data = ok_data(reply)
    formal = data is not None and data.get("status") == "OPEN" and data.get("my_status") == "FORMAL"
    check("capacity 1: holder signs up FORMAL", formal, describe(reply))
    if not formal:
        return

    # Capture w1's first notification before it can re-enter, so the second
    # notice can be distinguished by ID without delaying the critical reentry.
    w1_signup_started = time.monotonic()
    reply = req("POST", path + "/signup", waiters["w1"])
    data = ok_data(reply)
    waiting = data is not None and data.get("my_status") == "WAITING"
    check("w1: signup is WAITING", waiting, describe(reply))
    if not waiting:
        raise SetupError("w1: cannot establish the WAITING fixture")
    participation_ids = {"w1": row_id(data, "participation_id")}
    reply, notices = poll_notification(waiters["w1"], aid)
    original_w1_ids = notice_checks("w1 original", reply, notices, 1, window)
    if not original_w1_ids:
        raise SetupError("w1: no baseline notification ID; refusing to mistake an old notice for reentry")

    # Notification idempotency keys include wall-clock seconds. Let the original
    # w1 signup's second pass before the reentry; then enqueue w2/w3 and keep the
    # abandon/reentry path free of sleeps so a same-second non-tail rank is possible.
    time.sleep(max(0.0, 1.1 - (time.monotonic() - w1_signup_started)))
    for role in ("w2", "w3"):
        reply = req("POST", path + "/signup", waiters[role])
        data = ok_data(reply)
        waiting = data is not None and data.get("my_status") == "WAITING"
        check(f"{role}: signup is WAITING", waiting, describe(reply))
        if not waiting:
            raise SetupError(f"{role}: cannot establish the WAITING fixture")
        participation_ids[role] = row_id(data, "participation_id")

    # Query ranks only after the whole three-person queue exists; earlier reads
    # would fail to detect an implementation that reports the current queue size
    # instead of each member's actual R2 position.
    for rank, role in enumerate(("w1", "w2", "w3"), start=1):
        detail = req("GET", path, waiters[role])
        current = ok_data(detail)
        check(f"{role}: own detail my_rank == {rank}",
              current is not None and current.get("my_status") == "WAITING"
              and type(current.get("my_rank")) is int and current["my_rank"] == rank,
              describe(detail))

    reply = req("POST", f"/participations/{participation_ids['w1']}/abandon",
                waiters["w1"], {"confirmed": True})
    data = ok_data(reply)
    abandoned = (data is not None and data.get("status") == "WITHDRAWN"
                 and data.get("participation_id") == participation_ids["w1"])
    check("w1: confirmed abandon succeeds", abandoned, describe(reply))
    if not abandoned:
        return
    for role, rank in (("w2", 1), ("w3", 2)):
        reply = req("GET", path, waiters[role])
        data = ok_data(reply)
        check(f"after w1 abandon: {role} my_rank == {rank}",
              data is not None and data.get("my_status") == "WAITING"
              and type(data.get("my_rank")) is int and data["my_rank"] == rank,
              describe(reply))

    reply = req("POST", path + "/signup", waiters["w1"])
    data = ok_data(reply)
    reentered = data is not None and data.get("my_status") == "WAITING"
    check("w1: reentry is WAITING", reentered, describe(reply))
    if not reentered:
        return
    detail = req("GET", path, waiters["w1"])
    data = ok_data(detail)
    rank = data.get("my_rank") if data is not None else None
    check("w1: reentry detail exposes a positive R2 my_rank",
          data is not None and data.get("my_status") == "WAITING" and type(rank) is int and rank > 0,
          describe(detail))
    # Same-second reentry reuses w1's lower participation ID and sorts by
    # (queued_at, id), so it must be non-tail to exercise the former
    # waitingCount-as-rank bug rather than merely compare a tail rank to itself.
    check("w1: same-second reentry exercises a non-tail R2 rank",
          type(rank) is int and 1 <= rank < 3, f"rank={rank!r}; three waiters expected")
    reply, notices = poll_notification(waiters["w1"], aid, original_w1_ids)
    notice_checks("w1 reentry", reply, notices, rank, window)

    # These published-notification polls follow the critical same-second
    # abandon/reentry path; the original rank texts remain tied to signup time.
    for role, expected_rank in (("w2", 2), ("w3", 3)):
        reply, notices = poll_notification(waiters[role], aid)
        notice_checks(role, reply, notices, expected_rank, window)


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
