#!/usr/bin/env python3
"""REG-09 / B2-1 (NC-10): claim-first idempotency target-behavior regression.

Sources: brief-A.md A13; brief-A2b2.md B2-1; remaining.md #2 B2-1 (NC-10).
Target: INSERT a claim (http_status=0) before execution, then UPDATE the
completed receipt. A completed same-key/same-digest request replays its exact
status/body; a different digest returns 409 IDEMPOTENCY_CONFLICT. An in-flight
claim is polled for <=2 seconds, then returns 409 IDEMPOTENCY_IN_PROGRESS.
IMPORTANT: the current main-tree IdempotencyService still saves the digest
only AFTER execution; claim-first is NOT implemented. This script tests the
target behavior. Concurrent assertions may FAIL on that implementation and
must not be relaxed to accommodate it.

Prerequisites: an already-running disposable campus-buddy instance using
UTC+08:00 business wall time. BASE_URL defaults to http://127.0.0.1:8080;
the client appends /api/v1. Python 3 stdlib only. Creates a unique organizer
and unique future activities; fixtures are left in place. No database access,
demo reset, service management or configuration changes are performed.

Expected: sequential same-key creation replays identical bytes and the same
ID, with exactly one title match in GET /my/organized?page=1&pageSize=100;
a changed title conflicts without creating anything. Two Barrier(2)-released
POST /activities requests with one new key create exactly one activity. At
least one returns 200; each response is either 200 with the same winning ID,
or 409 IDEMPOTENCY_IN_PROGRESS. A subsequent sequential retry returns 200
with that winning ID. Incomplete/truncated organized lists are not accepted
as proof of a unique creation.
"""
import http.client
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
TZ = timezone(timedelta(hours=8))
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
        # Each thread gets its own opener; request bodies and headers are only
        # read from shared fixture dictionaries, never mutated in the workers.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            response = opener.open(request, timeout=8)
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


def response_id(reply):
    data = ok_data(reply)
    value = data.get("id") if data is not None else None
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        return value
    return None


def error(reply, status, code):
    envelope = reply[1]
    message = envelope.get("message")
    return (reply[0] == status and envelope.get("success") is False
            and envelope.get("code") == code and isinstance(message, str) and bool(message.strip())
            and "data" in envelope and (envelope["data"] is None or isinstance(envelope["data"], dict)))


def account(stamp):
    name = "r09org" + stamp
    credentials = {"account": name, "password": "R09a9!" + secrets.token_hex(12)}
    require_data("register organizer", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data("login organizer", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token:
        raise SetupError("login organizer: missing token")
    return token


def activity_body(title, current, day):
    start = current + timedelta(days=day)
    return {
        "title": title, "category": "桌游", "capacity": 1, "location": "REG-09 fixture",
        "deadline": (current + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
    }


def organized_snapshot(token):
    reply = req("GET", "/my/organized?page=1&pageSize=100", token)
    data = ok_data(reply)
    rows = data.get("items") if data is not None else None
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or data.get("page") != 1 or data.get("pageSize") != 100
            or type(data.get("total")) is not int or data["total"] != len(rows) or len(rows) > 100):
        return reply, None
    return reply, rows


def title_count(rows, title):
    return None if rows is None else sum(row.get("title") == title for row in rows)


def sequential_case(token, stamp, current):
    title = f"REG09 sequential {stamp}"
    body = activity_body(title, current, 2)
    headers = {"Idempotency-Key": "reg09-seq-" + stamp}
    first = req("POST", "/activities", token, body, headers)
    xid = response_id(first)
    check("sequential: K1+B creates HTTP 200 with a valid activity ID", xid is not None, describe(first))
    if xid is None:
        return
    replay = req("POST", "/activities", token, body, headers)
    check("sequential: K1+B replays HTTP 200, identical bytes and the original ID",
          response_id(replay) == xid and bool(first[2])
          and (replay[0], replay[2]) == (first[0], first[2]), describe(replay))
    reply, rows = organized_snapshot(token)
    check("sequential: original title has exactly one organized activity",
          title_count(rows, title) == 1, describe(reply) + f"; title_count={title_count(rows, title)!r}")

    changed_title = title + " changed"
    conflict = req("POST", "/activities", token, dict(body, title=changed_title), headers)
    check("different digest: K1 with changed title returns 409 IDEMPOTENCY_CONFLICT",
          error(conflict, 409, "IDEMPOTENCY_CONFLICT"), describe(conflict))
    reply, rows = organized_snapshot(token)
    check("different digest: original title still occurs once and changed title was not created",
          title_count(rows, title) == 1 and title_count(rows, changed_title) == 0,
          describe(reply) + f"; original={title_count(rows, title)!r} changed={title_count(rows, changed_title)!r}")


def concurrent_case(token, stamp, current):
    title = f"REG09 concurrent {stamp}"
    body = activity_body(title, current, 3)
    headers = {"Idempotency-Key": "reg09-concurrent-" + stamp}
    barrier = threading.Barrier(2)
    replies = [None, None]

    def worker(index):
        try:
            barrier.wait(timeout=5)
            replies[index] = req("POST", "/activities", token, body, headers)
        except Exception as exc:
            replies[index] = (0, {"success": False, "code": "CLIENT_ERROR",
                                  "message": f"{type(exc).__name__}: {exc}", "data": None}, b"")

    threads = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    completed = not any(thread.is_alive() for thread in threads) and all(reply is not None for reply in replies)
    check("concurrent: both Barrier(2)-released requests completed", completed,
          "each worker has a bounded barrier wait, HTTP timeout and join")
    if not completed:
        barrier.abort()
        return

    ids = [response_id(reply) for reply in replies]
    successful_ids = [value for value in ids if value is not None]
    winner = successful_ids[0] if successful_ids else None
    check("concurrent: at least one response is HTTP 200 with a valid ID", winner is not None,
          "; ".join(describe(reply) for reply in replies))
    for index, reply in enumerate(replies, start=1):
        check(f"concurrent: response {index} is 200 with winning ID or 409 IDEMPOTENCY_IN_PROGRESS",
              (winner is not None and response_id(reply) == winner)
              or error(reply, 409, "IDEMPOTENCY_IN_PROGRESS"), describe(reply))
    check("concurrent: never two different activity IDs in HTTP 200 responses",
          len(set(successful_ids)) == 1, f"successful_ids={successful_ids!r}")
    reply, rows = organized_snapshot(token)
    check("concurrent: the unique title has exactly one organized activity",
          title_count(rows, title) == 1, describe(reply) + f"; title_count={title_count(rows, title)!r}")

    retry = req("POST", "/activities", token, body, headers)
    check("concurrent: subsequent sequential K2+B2 retry returns 200 with winning ID",
          winner is not None and response_id(retry) == winner, describe(retry))
    reply, rows = organized_snapshot(token)
    check("concurrent: sequential retry still leaves exactly one title match",
          title_count(rows, title) == 1, describe(reply) + f"; title_count={title_count(rows, title)!r}")


def run():
    current = datetime.now(TZ).replace(tzinfo=None)
    stamp = current.strftime("%y%m%d%H%M%S") + secrets.token_hex(3)
    organizer = account(stamp)
    sequential_case(organizer, stamp, current)
    concurrent_case(organizer, stamp, current)


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
