#!/usr/bin/env python3
"""REG-41: scheduled signup closeout (remaining.md #6; brief-B.md B9).

Run against a disposable Campus Buddy instance with registration enabled,
Asia/Shanghai wall time, the outbox publisher running, and SWEEP_SECONDS=10
(default) or a similarly short sweep interval. Run during the invitation
window or use INVITE_DAY_START_HOUR=0 and INVITE_DAY_END_HOUR=24. Use
INVITE_TTL >= 35 s (default 120 s) so B's invitation is valid up to the
signup deadline, not lost to a shorter TTL. Both fixtures are capacity 1,
with deadlines about 35 s away and start times at least an hour later.
The shared fixture/poll budget is 105 s, plus up to 10 s for outbox settling.

Expect FORMAL to remain enrolled, WAITING and INVITED to become EXPIRED,
and the old invitation to become INVALID and refuse either response. The
SIGNUP_CLOSED events must explain each transition. READY is the normal
post-deadline activity status; OPEN is tolerated only for lifecycle read
timing. SDD v1.3 (design-review-20261115/sdd-v1.3.txt) §6.8 has no closeout
notice, and closeOutActivity does not enqueue one. Compare published ID
sets for fresh B accounts so a notice with unexpected wording also fails.

Sources: BuddyService.promote, closeOutActivity, activityDetail/detail,
listEvents, listNotifications and respondInvitation; SweepService.sweep
and publishOutbox; ApiV1Controller and ApiSupport for routes and envelopes.
Known issue in this tree: promote clips expiry to the deadline, and sweep
handles expires_at <= scan time *before* deadline closeout. Even with the
right TTL, B's invite reaches that sweep at equality, where expireOne takes
it first (EXPIRED / INVITE_EXPIRED, with an expiry notice). The regression
keeps the INVALID, SIGNUP_CLOSED and no-new-notice expectations strict.
"""

import http.client
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
SHANGHAI = timezone(timedelta(hours=8))
DEADLINE_SECONDS = 35
CLOSEOUT_BUDGET = 105
OUTBOX_SECONDS = 10
RESULTS = []


class FixtureError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect())


class Fixture(NamedTuple):
    label: str
    aid: str
    deadline: datetime
    pids: dict


def req(method, path, token=None, body=None, headers=None):
    """Return HTTP status, parsed envelope and any client-side problem."""
    hdr = {"Accept": "application/json", "Content-Type": "application/json"}
    if token is not None:
        hdr["Authorization"] = "Bearer " + token
    hdr.update(headers or {})  # Includes an optional Idempotency-Key.
    status = 0
    limit = 1024 * 1024
    try:
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(BASE + path, data=payload, headers=hdr, method=method)
        try:
            response = OPENER.open(request, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status, raw = response.getcode(), response.read(limit + 1)
        if len(raw) > limit:
            return status, {}, "response exceeds 1 MiB"
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            return status, {}, "JSON response is not an envelope object"
        return status, envelope, ""
    except urllib.error.URLError as exc:
        return status, {}, f"transport error: {type(exc.reason).__name__}"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return status, {}, f"request/response error: {type(exc).__name__}"


def check(name, condition, detail=""):
    passed = bool(condition)
    RESULTS.append(passed)
    print(f"{'PASS' if passed else 'FAIL'} - {name}" + (f" ({detail})" if detail and not passed else ""),
          flush=True)
    return passed


def describe(reply):
    status, env, problem = reply
    return (f"HTTP={status} success={env.get('success')!r} code={env.get('code')!r}"
            f" traceId={env.get('traceId')!r}" + (f", {problem}" if problem else ""))


def ok_data(reply, kind=dict):
    status, env, _ = reply
    data = env.get("data")
    if (status == 200 and env.get("success") is True and env.get("code") == "OK"
            and env.get("message") == "ok" and isinstance(data, kind)):
        return data
    return None


def now_wall():
    return datetime.now(SHANGHAI).replace(tzinfo=None)


def wall_second(value):
    # The relevant fields are Java LocalDateTime strings. Ignore fractional
    # seconds for comparison with the fixture's whole-second deadline.
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?", value):
        try:
            return datetime.fromisoformat(value.split(".", 1)[0])
        except ValueError:
            pass
    return None


def require_data(label, reply, *, before=None):
    data = ok_data(reply)
    if data is None:
        raise FixtureError(f"{label}: expected 200 OK with object data; {describe(reply)}")
    if before is not None:
        sampled = reply[1].get("serverTime")
        when = wall_second(sampled)
        if when is None or when >= before:
            raise FixtureError(f"{label}: need a read before {before.isoformat()}; serverTime={sampled!r}")
    return data


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value) is not None


def row_id(data, field, label):
    value = data.get(field)
    if not valid_id(value):
        raise FixtureError(f"{label}: missing/invalid string {field}")
    return value


def account(role, stamp):
    name = f"r41{role}_{stamp}"
    credentials = {"account": name, "password": "R41a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    login = req("POST", "/login", body=credentials)
    token = require_data(f"login {role}", login).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token; {describe(login)}")
    return token


def create_fixture(label, roles, tokens, stamp):
    deadline = now_wall().replace(microsecond=0) + timedelta(seconds=DEADLINE_SECONDS)
    start = deadline + timedelta(hours=1)
    reply = req("POST", "/activities", tokens["org"], {
        "title": f"REG-41 {label} {stamp}", "category": "桌游", "location": "REG-41 fixture", "capacity": 1,
        "deadline": deadline.isoformat(), "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat(),
    })
    aid = row_id(require_data(f"{label} create", reply), "id", f"{label} create")
    pids = {}
    for role, expected in zip(roles, ("FORMAL", "WAITING", "WAITING")):
        step = f"{label} signup {role}"
        reply = req("POST", f"/activities/{aid}/signup", tokens[role])
        data = require_data(step, reply, before=deadline)
        status = (data.get("activity_id"), data.get("status"), data.get("my_status"))
        if status != (aid, "OPEN", expected):
            raise FixtureError(f"{step}: wanted activity {aid} OPEN/{expected}, got {status!r}; {describe(reply)}")
        pids[role] = row_id(data, "participation_id", step)
    return Fixture(label, aid, deadline, pids)


def detail(fixture, role, tokens, *, before=False):
    label = f"{fixture.label} {role} detail for activity {fixture.aid}"
    reply = req("GET", f"/activities/{fixture.aid}", tokens[role])
    data = require_data(label, reply, before=fixture.deadline if before else None)
    if data.get("activity_id") != fixture.aid:
        raise FixtureError(f"{label}: wrong or missing activity_id; {describe(reply)}")
    if role in fixture.pids and (data.get("participation_id") != fixture.pids[role]
                                 or not isinstance(data.get("my_status"), str)):
        raise FixtureError(f"{label}: expected participation {fixture.pids[role]} and my_status; {describe(reply)}")
    return data


def pending_invitations(fixture, tokens, *, before=False):
    rows = detail(fixture, "org", tokens, before=before).get("pending_invitations")
    if not isinstance(rows, list) or not all(isinstance(row, dict) and valid_id(row.get("id")) for row in rows):
        raise FixtureError(f"{fixture.label} organizer detail: invalid pending_invitations list")
    return rows


def inbox(fixture, role, tokens, *, before=False):
    label = f"{fixture.label} {role} notifications"
    reply = req("GET", "/notifications?page=1&pageSize=100", tokens[role])
    page = require_data(label, reply, before=fixture.deadline if before else None)
    rows = page.get("items")
    if (not isinstance(rows, list) or page.get("page") != 1 or page.get("pageSize") != 100
            or page.get("total") != len(rows) or len(rows) > 100
            or not all(isinstance(row, dict) and valid_id(row.get("id")) for row in rows)):
        raise FixtureError(f"{label}: expected a complete page with string notification IDs; {describe(reply)}")
    return rows


def preclose_inboxes(fixture, tokens, iid):
    stop = time.monotonic() + OUTBOX_SECONDS
    seen = "no pre-deadline read"
    while time.monotonic() < stop and now_wall() < fixture.deadline:
        b_rows = inbox(fixture, "b", tokens, before=True)
        c_rows = inbox(fixture, "c", tokens, before=True)
        b_types = [(row.get("type"), row.get("invitation_id")) for row in b_rows
                   if row.get("activity_id") == fixture.aid]
        c_types = [row.get("type") for row in c_rows if row.get("activity_id") == fixture.aid]
        if any(kind == "候补" for kind, _ in b_types) and ("邀请", iid) in b_types and "候补" in c_types:
            return {"b": {row["id"] for row in b_rows}, "c": {row["id"] for row in c_rows}}
        seen = f"b types/ids={b_types!r}; c types={c_types!r}"
        time.sleep(0.5)
    raise FixtureError(f"outbox baseline: need b's waitlist/invite and c's waitlist published before deadline "
                       f"(waited up to {OUTBOX_SECONDS} s); {seen}")


def setup_waiting(tokens, stamp):
    roles = ("holder", "w1", "w2")
    fixture = create_fixture("A", roles, tokens, stamp)
    states = tuple(detail(fixture, role, tokens, before=True)["my_status"] for role in roles)
    if check("A before deadline: holder FORMAL, w1 and w2 WAITING",
             states == ("FORMAL", "WAITING", "WAITING"), f"states={states!r}"):
        return fixture
    return None


def setup_invited(tokens, stamp):
    fixture = create_fixture("B", ("a", "b", "c"), tokens, stamp)
    a = detail(fixture, "a", tokens, before=True)
    if a["my_status"] != "FORMAL":
        raise FixtureError(f"B a must be FORMAL before withdraw; got {a['my_status']!r}")
    body = {"confirmed": True}
    version = a.get("participation_version")
    if isinstance(version, str) and version:
        body["version"] = version
    reply = req("POST", f"/participations/{fixture.pids['a']}/withdraw", tokens["a"], body)
    withdrawn = require_data("B a confirmed withdraw", reply, before=fixture.deadline)
    if withdrawn.get("status") != "WITHDRAWN" or withdrawn.get("participation_id") != fixture.pids["a"]:
        raise FixtureError(f"B a withdraw: expected WITHDRAWN for the same participation; {describe(reply)}")

    b = detail(fixture, "b", tokens, before=True)
    c = detail(fixture, "c", tokens, before=True)
    iid = b.get("invitation_id")
    pending = pending_invitations(fixture, tokens, before=True)
    if not check("B before deadline: b INVITED with organizer-visible PENDING invite, c WAITING",
                 b["my_status"] == "INVITED" and c["my_status"] == "WAITING" and valid_id(iid)
                 and any((row.get("id"), row.get("participation_id"), row.get("status"))
                         == (iid, fixture.pids["b"], "PENDING") for row in pending),
                 f"b={b['my_status']!r}, c={c['my_status']!r}, invitation_id={iid!r}; check dispatch hours"):
        return None
    expiry = wall_second(b.get("invitation_expires_at"))
    if not check("B invitation expiry is not before the signup deadline",
                 expiry is not None and expiry >= fixture.deadline,
                 f"expires={b.get('invitation_expires_at')!r}, deadline={fixture.deadline.isoformat()}; check INVITE_TTL"):
        return None
    return fixture, iid, preclose_inboxes(fixture, tokens, iid)


def poll_closeouts(targets, tokens, stop):
    pending = dict(targets)
    final = {}
    last = {label: "no post-deadline detail read" for label in pending}
    while pending and time.monotonic() < stop:
        for label, (fixture, roles) in list(pending.items()):
            if time.monotonic() >= stop:
                break
            if now_wall() < fixture.deadline:
                continue
            try:
                views = {role: detail(fixture, role, tokens) for role in roles}
            except FixtureError as exc:
                last[label] = str(exc)
                continue
            states = {role: data["my_status"] for role, data in views.items()}
            last[label] = f"activity={fixture.aid}, deadline={fixture.deadline.isoformat()}, states={states}"
            if all(status == "EXPIRED" for status in states.values()):
                final[label] = views
                del pending[label]
        if pending:
            time.sleep(min(1, max(0, stop - time.monotonic())))
    return final, last


def one_closeout_event(fixture, role, tokens, from_status, expected_detail):
    pid = fixture.pids[role]
    reply = req("GET", f"/participations/{pid}/events", tokens[role])
    events = ok_data(reply, list)
    if events is None or not all(isinstance(row, dict) and row.get("participation_id") == pid
                                 and row.get("activity_id") == fixture.aid for row in events):
        return False, f"expected event list for participation {pid}; {describe(reply)}"
    closed = [(row.get("from_status"), row.get("to_status"), row.get("detail"))
              for row in events if row.get("event_type") == "SIGNUP_CLOSED"]
    return (closed == [(from_status, "EXPIRED", expected_detail)],
            f"SIGNUP_CLOSED rows={closed!r}, event types={[row.get('event_type') for row in events]!r}")


def no_new_ids(fixture, role, tokens, before):
    try:
        after = {row["id"] for row in inbox(fixture, role, tokens)}
    except FixtureError as exc:
        return False, str(exc)
    added = after - before[role]
    return not added, f"new published notification IDs={sorted(added)}"


def invalid_response(reply):
    status, env, _ = reply
    message = env.get("message")
    return (status == 400 and env.get("success") is False and env.get("code") == "ERROR"
            and isinstance(message, str) and "不可应答" in message and "INVALID" in message
            and "data" in env and env["data"] is None)


def verify_waiting(fixture, tokens):
    try:
        holder = detail(fixture, "holder", tokens)
    except FixtureError as exc:
        check("A post-closeout holder detail", False, str(exc))
        return
    check("A holder remains FORMAL", holder["my_status"] == "FORMAL", f"my_status={holder['my_status']!r}")
    status = holder.get("status")
    check("A remains READY (or OPEN before lifecycle advancement), not CANCELLED",
          status in ("READY", "OPEN"), f"activity status={status!r}")


def verify_invited(setup, b_view, tokens):
    fixture, iid, baseline = setup
    check("B b no longer has a pending invitation ID", b_view.get("invitation_id") is None,
          f"invitation_id={b_view.get('invitation_id')!r}")
    try:
        pending_ids = {row["id"] for row in pending_invitations(fixture, tokens)}
        problem = f"original invitation {iid}; pending IDs={sorted(pending_ids)}"
    except FixtureError as exc:
        pending_ids, problem = None, str(exc)
    check("B organizer no longer sees the original invite pending",
          pending_ids is not None and iid not in pending_ids, problem)
    check("B b has one SIGNUP_CLOSED event: INVITED to EXPIRED",
          *one_closeout_event(fixture, "b", tokens, "INVITED", "报名截止，原邀请作废"))
    check("B c has one SIGNUP_CLOSED event: WAITING to EXPIRED",
          *one_closeout_event(fixture, "c", tokens, "WAITING", "报名截止，未获得名额"))

    # Snapshot after many 500 ms outbox cycles, before either respond probe.
    time.sleep(OUTBOX_SECONDS)
    check("B no new published notifications for b", *no_new_ids(fixture, "b", tokens, baseline))
    check("B no new published notifications for c", *no_new_ids(fixture, "c", tokens, baseline))
    base_path = f"/invitations/{iid}"
    accept = req("POST", base_path + "/accept", tokens["b"], {"confirmConflict": True})
    check("B original invitation accept returns 400 for INVALID", invalid_response(accept),
          f"{describe(accept)}, message={accept[1].get('message')!r}")
    reject = req("POST", base_path + "/reject", tokens["b"])
    check("B original invitation reject returns 400 for INVALID", invalid_response(reject),
          f"{describe(reject)}, message={reject[1].get('message')!r}")


def main():
    try:
        health = require_data("health", req("GET", "/health"))
        ttl = health.get("invite_ttl_seconds")
        ttl_ok = check("B precondition: invite TTL >= 35 s", type(ttl) is int and ttl >= DEADLINE_SECONDS,
                       f"health invite_ttl_seconds={ttl!r}; set INVITE_TTL for the test instance")
        stamp = now_wall().strftime("%y%m%d%H%M%S") + secrets.token_hex(4)
        tokens = {role: account(role, stamp) for role in ("org", "holder", "w1", "w2", "a", "b", "c")}
    except FixtureError as exc:
        check("health and actor setup", False, str(exc))
        return

    stop = time.monotonic() + CLOSEOUT_BUDGET
    a = b = None
    try:
        a = setup_waiting(tokens, stamp)
    except FixtureError as exc:
        check("A WAITING fixture", False, str(exc))
    if ttl_ok:
        try:
            b = setup_invited(tokens, stamp)
        except FixtureError as exc:
            check("B INVITED fixture", False, str(exc))

    targets = {}
    if a is not None:
        targets["A"] = a, ("w1", "w2")
    if b is not None:
        targets["B"] = b[0], ("b", "c")
    final, last = poll_closeouts(targets, tokens, stop)
    timeout = f"no EXPIRED pair within {CLOSEOUT_BUDGET} s of fixture start; check sweep; last: "
    if a is not None and check("A w1 and w2 become EXPIRED after deadline", "A" in final, timeout + last["A"]):
        verify_waiting(a, tokens)
    if b is not None and check("B b and c become EXPIRED after deadline", "B" in final, timeout + last["B"]):
        verify_invited(b, final["B"]["b"], tokens)


if __name__ == "__main__":
    main()
    passed = sum(RESULTS)
    failed = len(RESULTS) - passed
    print(f"Summary: {passed} passed, {failed} failed")
    sys.exit(0 if RESULTS and not failed else 1)
