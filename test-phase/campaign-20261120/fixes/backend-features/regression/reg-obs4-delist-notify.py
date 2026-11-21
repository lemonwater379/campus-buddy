#!/usr/bin/env python3
"""OBS-4 HTTP regression -- PENDING UNIFIED INTEGRATION RETEST / 待统一复测.

PREREQUISITES (mandatory; missing/invalid input is FAIL, never a coverage PASS):
* An operator-prepared DISPOSABLE campus-buddy instance with the G/OBS-4 changes,
  existing schemas/migrations and the scheduled notification outbox publisher.
  Read daily-simulation/DUAL-DB.md and RUNBOOK.md step 0 before preparing it:
  JVM/database wall time is Asia/Shanghai; PG/MySQL instances are independent.
  This script NEVER resets demo data, runs SQL, starts/stops services, or sets an
  activity's lifecycle through an invented API. Never point it at production or
  shared fixtures. The operator, not this script, prepares ENDED/role fixtures.
* Python 3 standard library only. Reuses tests/test_api.py's urllib.request
  req(method, path, token=None, body=None, headers=None) and check() pattern;
  that repository client is NOT the third-party requests package.
* Explicit admin credentials below; /me must confirm ACTIVE, unbanned and
  is_admin=true (administrator membership, NOT app_user.role alone). No seeded
  password/admin assumption, appointment, password change or privilege setup.
* Three fresh, NOT delisted, exclusively leased fixture activities with EXACT
  titles/identities/membership below, no old DELIST notifications, no concurrent
  edits/signups/responses/relist. Every active roster member must be supplied.
  OPEN deadlines and PENDING invitations must remain valid at least 30 seconds
  at the final pre-mutation read. Do not use INVITE_TTL=10 fixtures: prepare a
  sufficiently long invitation window. INVITED is verified as an owned PENDING
  invitation by organizer detail AND the member's /my row, not just its label.

REQUIRED ENVIRONMENT (all required, with no credential defaults):
  OBS4_ALLOW_MUTATION=YES
  OBS4_ADMIN_ACCOUNT=<explicit administrator account>
  OBS4_ADMIN_PASSWORD=<explicit administrator password>
  OBS4_OPEN_MEMBER_FIXTURE=<JSON object in the format below>
  OBS4_OPEN_NONMEMBER_FIXTURE=<JSON object in the format below>
  OBS4_ENDED_FIXTURE=<JSON object in the format below>
Optional: BASE_URL (root WITHOUT /api/v1; default http://127.0.0.1:8080),
  OBS4_HTTP_TIMEOUT=10 (seconds, 1..60), OBS4_OBSERVE_SECONDS=8 (seconds, 3..120).
  Notification observation always runs the FULL interval, even after delivery;
  paginated reads fetch every page (100/page, maximum 1000 pages, or FAIL).

FIXTURE JSON FORMAT (JSON text in each env var, not a file path):
  {"activity_id":"<positive id>", "title":"<exact existing activity title>",
   "organizer":{"user_id":"<id>","account":"<account>","password":"<password>",
                "membership":"FORMAL"},
   "members":[
     {"user_id":"<id>","account":"<account>","password":"<password>",
      "membership":"FORMAL"},
     {"user_id":"<id>","account":"<account>","password":"<password>",
      "membership":"WAITING"},
     {"user_id":"<id>","account":"<account>","password":"<password>",
      "membership":"INVITED","invitation_id":"<owned PENDING invitation id>"}
   ]}
  * Do NOT duplicate the organizer in members. user_id/account must be unique
    within each object; the three activity_ids must be distinct.
  * OPEN_MEMBER: organizer.membership MUST be FORMAL; members MUST include at
    least one OTHER FORMAL, one WAITING and one INVITED (may include more).
  * OPEN_NONMEMBER: same member roles; organizer.membership MUST be NONE, with
    NO participation row at all (not even WITHDRAWN). Omit invitation_id unless
    membership is INVITED. NONE is allowed ONLY for the organizer.
  * ENDED: organizer.membership is NONE or FORMAL; members include at least one
    FORMAL. Any additional FORMAL/WAITING/INVITED members must ALL be listed.
    Do not fabricate WAITING/INVITED in normal ended data; they are not required
    here. If they exist, their identities/pending invitations are validated too.
  Actual title, lifecycle, organizer, ACTIVE account identity, full active roster,
  own /my rows and invitation ownership are read back before destructive use.

DESTRUCTIVE USE / RERUNS:
  Running with OBS4_ALLOW_MUTATION=YES explicitly authorizes delisting ALL three
  supplied fixtures, cancelling their active participations/pending invitations
  on the OPEN path, and attempting accept AND reject on invalidated invitations.
  The script also registers TWO timestamp+random-suffixed test accounts with
  generated passwords (never printed): an unrelated observer and a new organizer.
  It creates/cancels/delists ONE new organizer-only CANCELLED activity through
  existing public APIs. Data/notifications are deliberately retained; no cleanup
  or relist masks evidence. Rerun with FRESH fixture IDs/accounts/invitations.
  A failed/uncertain write is NOT automatically retried. Mutation may have
  happened even if its response was lost; inspect and replace the fixture.

EXPECTED RESULTS / SOURCE CONTRACT:
  brief-G.md G1: dedicated DELIST event namespace notify:delist: (separate from
  BuddyService's notify:cancel:); exactly ONE published DELIST per activity and
  affected user (FORMAL/WAITING/INVITED union organizer), including overlapping
  organizer/member only once. notification.activity_id/user_id/event_key/status
  are authoritative; notification.type is a schema category, NOT literal DELIST.
  Every DELIST content contains the API-read full activity title, the supplied
  unique reason, and '下架'; INVITED content also contains EXACT '原邀请作废'.
  An unrelated user has ZERO DELISTs for the activity. Cancellation notices are
  counted separately, never accepted as DELIST. Old same-activity DELISTs fail
  freshness; other activities' notifications cannot satisfy these assertions.
  OPEN -> CANCELLED with ordinary cancellation effects; original invitations
  disappear from PENDING reads and accept/reject return 400/ERROR with INVALID.
  ENDED stays ENDED with unchanged memberships and no NEW notify:cancel: or
  ACTIVITY_CANCELLED events; CANCELLED organizer-only stays CANCELLED. These are
  observable effects, NOT proof a Java method wasn't called or of DB rollback.
  Same Idempotency-Key/body replays the original success/decision. A NEW key for
  an already delisted activity is rejected 400/ERROR/'活动已下架', per the current
  GovernanceService/ApiV1Controller contract; no second decision/DELIST delivery.
  At authoring, GovernanceService still has the old no-DELIST notification path;
  these assertions intentionally target brief-G's fix, not that old behavior.

LIMITS: HTTP exposes PUBLISHED notifications only. Bounded observation cannot
  prove absence of forever-delayed PENDING rows or transaction atomicity/lock
  correctness. ENDED covers all active members actually validated, but need not
  contain WAITING/INVITED. CANCELLED coverage is explicitly organizer-only, not
  historical cancelled-member semantics. OBS-3 races are outside this script.
  Syntax compilation is NOT integration PASS. No integration execution has
  been performed during authoring; run later in the unified isolated retest.
"""

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
HTTP_TIMEOUT = 10.0
OBSERVE_SECONDS = 8.0
SHANGHAI = timezone(timedelta(hours=8))
RUN = datetime.now(timezone.utc).strftime("%m%d%H%M%S%f") + uuid.uuid4().hex[:5]
DELIST_PREFIX = "notify:delist:"
CANCEL_PREFIX = "notify:cancel:"
ACTIVE = {"FORMAL", "WAITING", "INVITED"}
CASES = (
    ("OPEN_MEMBER", "OBS4_OPEN_MEMBER_FIXTURE", "OPEN"),
    ("OPEN_NONMEMBER", "OBS4_OPEN_NONMEMBER_FIXTURE", "OPEN"),
    ("ENDED", "OBS4_ENDED_FIXTURE", "ENDED"),
)
results = []


class StopCase(Exception):
    """A failed prerequisite/read/write prevents dependent assertions."""


def check(name, condition, detail=""):
    condition = bool(condition)
    results.append((name, condition, detail))
    print(("PASS" if condition else "FAIL"), "-", name, detail, flush=True)
    return condition


def require(name, condition, detail=""):
    if not condition:
        check(name, False, detail)
        raise StopCase(name)


def req(method, path, token=None, body=None, headers=None):
    """Existing test_api.py shape; network/JSON failures remain assertable."""
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    if headers:
        hdrs.update(headers)
    request = urllib.request.Request(
        BASE + path, method=method, headers=hdrs,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except Exception as error:
        return 0, {"success": False, "code": "NETWORK_ERROR",
                   "message": type(error).__name__, "data": None}
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            raise ValueError("response is not an envelope")
        return status, envelope
    except (ValueError, UnicodeError):
        return status, {"success": False, "code": "BAD_JSON",
                        "message": "response is not a JSON object", "data": None}


def response_detail(status, envelope):
    # Do not log login data, bearer tokens, passwords or raw fixture JSON.
    return "HTTP={} code={} message={}".format(
        status, envelope.get("code"), str(envelope.get("message", ""))[:250])


def success(method, path, actor=None, body=None, headers=None):
    status, envelope = req(method, path, actor["token"] if actor else None,
                           body, headers)
    valid = (status == 200 and envelope.get("success") is True
             and envelope.get("code") == "OK"
             and isinstance(envelope.get("message"), str)
             and "data" in envelope)
    require(method + " " + path, valid, response_detail(status, envelope))
    return envelope


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return str(int(text)) if text.isascii() and text.isdigit() and int(text) > 0 else None


def wall_time(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed


def validate_actor_spec(spec, label, organizer=False):
    require(label + " JSON actor", isinstance(spec, dict))
    for field in ("account", "password"):
        require(label + " " + field + " supplied",
                isinstance(spec.get(field), str) and bool(spec[field].strip()))
    require(label + " user_id supplied", positive_id(spec.get("user_id")) is not None)
    membership = spec.get("membership")
    require(label + " membership supplied",
            membership in ACTIVE or (organizer and membership == "NONE"))
    require(label + " invitation_id contract",
            (membership == "INVITED" and positive_id(spec.get("invitation_id")) is not None)
            or (membership != "INVITED" and spec.get("invitation_id") is None))
    return dict(spec, user_id=positive_id(spec["user_id"]))


def fixture_from_env(label, variable):
    raw = os.environ.get(variable)
    require(label + " mandatory fixture supplied", bool(raw), variable + " is required JSON")
    try:
        fixture = json.loads(raw)
    except (ValueError, TypeError):
        require(label + " valid fixture JSON", False, variable + " is not valid JSON")
    require(label + " fixture JSON object", isinstance(fixture, dict))
    require(label + " activity_id supplied", positive_id(fixture.get("activity_id")) is not None)
    require(label + " exact title supplied",
            isinstance(fixture.get("title"), str) and bool(fixture["title"].strip()))
    organizer = validate_actor_spec(fixture.get("organizer"), label + " organizer", True)
    require(label + " members array", isinstance(fixture.get("members"), list))
    members = [validate_actor_spec(spec, label + " member " + str(index))
               for index, spec in enumerate(fixture["members"], 1)]
    actors = [organizer] + members
    require(label + " unique member identities",
            len({actor["user_id"] for actor in actors}) == len(actors)
            and len({actor["account"] for actor in actors}) == len(actors),
            "organizer must not be duplicated in members")
    if label.startswith("OPEN"):
        want = "FORMAL" if label == "OPEN_MEMBER" else "NONE"
        require(label + " organizer membership", organizer["membership"] == want)
        require(label + " FORMAL WAITING INVITED inputs",
                ACTIVE.issubset({actor["membership"] for actor in members}))
    else:
        require(label + " organizer membership", organizer["membership"] in {"NONE", "FORMAL"})
        require(label + " at least one FORMAL member input",
                any(actor["membership"] == "FORMAL" for actor in members))
    return dict(fixture, activity_id=positive_id(fixture["activity_id"]),
                organizer=organizer, members=members)


def login_actor(spec, label, admin=False):
    envelope = success("POST", "/login", body={
        "account": spec["account"], "password": spec["password"]})
    data = envelope["data"]
    require(label + " login token", isinstance(data, dict)
            and isinstance(data.get("token"), str) and bool(data["token"]))
    actor = {key: value for key, value in spec.items() if key != "password"}
    actor["token"] = data["token"]
    mine = success("GET", "/me", actor)["data"]
    user = mine.get("user") if isinstance(mine, dict) else None
    valid = (isinstance(user, dict) and positive_id(user.get("id")) is not None
             and user.get("account") == spec["account"] and user.get("status") == "ACTIVE"
             and user.get("role") in {"USER", "ADMIN"}
             and isinstance(user.get("is_admin"), bool) and user.get("banned") is False)
    if spec.get("user_id") is not None:
        valid = valid and positive_id(user.get("id") if isinstance(user, dict) else None) == spec["user_id"]
    if admin:
        valid = valid and isinstance(user, dict) and user.get("is_admin") is True
    require(label + " API identity/ACTIVE/role/admin", valid,
            "expected identity and ACTIVE/unbanned status; admin requires is_admin=true")
    actor["user_id"] = positive_id(user["id"])
    check(label + " API identity/ACTIVE/role/admin", True, "user_id=" + actor["user_id"])
    return actor


def new_actor(suffix):
    account = "g4" + suffix + "_" + RUN
    password = "G4a" + uuid.uuid4().hex
    success("POST", "/register", body={"account": account, "password": password,
                                       "nickname": account[:30]})
    actor = login_actor({"account": account, "password": password}, "fresh " + suffix)
    check("fresh " + suffix + " timestamp account registered", True, "user_id=" + actor["user_id"])
    return actor


def paged(path, actor, roster=False):
    """Read ALL pages; retry a moving pagination snapshot, never truncate it."""
    for attempt in range(3):
        rows, expected_total, last_envelope = [], None, None
        stable = True
        for page in range(1, 1001):
            query = {"rosterPage" if roster else "page": page,
                     "rosterPageSize" if roster else "pageSize": 100}
            envelope = success("GET", path + "?" + urllib.parse.urlencode(query), actor)
            outer = envelope["data"]
            data = outer.get("roster") if roster and isinstance(outer, dict) else outer
            valid = (isinstance(data, dict) and isinstance(data.get("items"), list)
                     and data.get("page") == page and data.get("pageSize") == 100
                     and type(data.get("total")) is int and data["total"] >= 0
                     and all(isinstance(row, dict) and positive_id(row.get("id")) is not None
                             for row in data["items"]))
            require("complete pagination " + path, valid, "invalid pagination/item identity")
            require("pagination safety limit " + path, data["total"] <= 100000,
                    "more than 1000 pages; cannot establish exact notification counts")
            if expected_total is None:
                expected_total = data["total"]
            if data["total"] != expected_total:
                stable = False
                break
            rows.extend(data["items"])
            last_envelope = envelope
            if page * 100 >= expected_total:
                break
        ids = [positive_id(row["id"]) for row in rows]
        if stable and len(rows) == expected_total and len(ids) == len(set(ids)):
            return rows, last_envelope
        if attempt < 2:
            time.sleep(0.2)
    require("stable full pagination " + path, False,
            "totals/IDs changed during three attempts; exact counts unavailable")


def my_row(actor, activity_id):
    rows, _ = paged("/my", actor)
    require("/my owner and activity identities",
            all(positive_id(row.get("user_id")) == actor["user_id"]
                and positive_id(row.get("activity_id")) is not None for row in rows))
    matches = [row for row in rows if positive_id(row["activity_id"]) == activity_id]
    require("unique /my activity row", len(matches) <= 1, "activity_id=" + activity_id)
    return matches[0] if matches else None


def notifications(actor):
    rows, _ = paged("/notifications", actor)
    require("authoritative notification fields user=" + actor["user_id"],
            all(positive_id(row.get("user_id")) == actor["user_id"]
                and (row.get("activity_id") is None or positive_id(row["activity_id"]) is not None)
                and isinstance(row.get("event_key"), str)
                and isinstance(row.get("type"), str)
                and isinstance(row.get("content"), str)
                and row.get("status") == "PUBLISHED" for row in rows),
            "need user_id/activity_id/event_key/type/content/status, not text-only matching")
    return rows


def matching(rows, activity_id, prefix):
    return [row for row in rows if positive_id(row.get("activity_id")) == activity_id
            and row["event_key"].startswith(prefix)]


def row_ids(rows):
    return {positive_id(row["id"]) for row in rows}


def events(actor, participation_id):
    rows = success("GET", "/participations/" + participation_id + "/events", actor)["data"]
    require("participation event ownership", isinstance(rows, list)
            and all(isinstance(row, dict) and positive_id(row.get("id")) is not None
                    and positive_id(row.get("participation_id")) == participation_id
                    and positive_id(row.get("user_id")) == actor["user_id"]
                    and isinstance(row.get("event_type"), str) for row in rows))
    return rows


def read_fixture(label, fixture, expected_status, actors, outsider):
    """Read/validate the fixture again immediately before every delist write."""
    aid, organizer = fixture["activity_id"], actors[0]
    roster, envelope = paged("/activities/" + aid, organizer, roster=True)
    data = envelope["data"]
    valid = (isinstance(data, dict) and positive_id(data.get("id")) == aid
             and positive_id(data.get("organizer_id")) == organizer["user_id"]
             and data.get("title") == fixture["title"]
             and data.get("status") == expected_status and data.get("delisted") is False)
    require(label + " activity identity/title/organizer/status/freshness", valid,
            "activity_id=" + aid + " expected=" + expected_status + ", not delisted")
    expected = {actor["user_id"]: actor["membership"] for actor in actors
                if actor["membership"] in ACTIVE}
    roster_map = {positive_id(row.get("user_id")): row.get("status") for row in roster}
    require(label + " exact complete active roster", roster_map == expected and len(roster) == len(expected)
            and all(positive_id(row.get("activity_id")) == aid for row in roster),
            "expected user/status=" + json.dumps(expected, sort_keys=True))
    server_now = wall_time(envelope["serverTime"])
    if expected_status == "OPEN":
        require(label + " OPEN deadline safety margin",
                wall_time(data.get("deadline")) > server_now + timedelta(seconds=30))
    if expected_status == "ENDED":
        require(label + " ENDED time validity", wall_time(data.get("end_time")) <= server_now)
    pending = data.get("pending_invitations")
    require(label + " pending invitation API list", isinstance(pending, list)
            and all(isinstance(row, dict) for row in pending))
    expected_invites, participations = {}, {}
    for actor in actors:
        own = my_row(actor, aid)
        uid, membership = actor["user_id"], actor["membership"]
        if membership == "NONE":
            require(label + " organizer has NO participation", own is None
                    and data.get("my_status") is None)
            continue
        require(label + " /my membership user=" + uid,
                own is not None and own.get("status") == membership
                and positive_id(own.get("user_id")) == uid)
        pid = positive_id(own["id"])
        roster_part = next(row for row in roster if positive_id(row.get("user_id")) == uid)
        require(label + " roster /my participation identity user=" + uid,
                positive_id(roster_part["id"]) == pid)
        participations[uid] = pid
        if membership == "INVITED":
            iid = positive_id(actor.get("invitation_id"))
            expected_invites[iid] = pid
            owned_pending = [row for row in pending if positive_id(row.get("id")) == iid]
            require(label + " owned PENDING invitation user=" + uid,
                    positive_id(own.get("invitation_id")) == iid and len(owned_pending) == 1
                    and owned_pending[0].get("status") == "PENDING"
                    and positive_id(owned_pending[0].get("participation_id")) == pid)
            require(label + " INVITED remaining lifetime user=" + uid,
                    wall_time(own.get("invitation_expires_at")) > server_now + timedelta(seconds=30)
                    and wall_time(owned_pending[0].get("expires_at"))
                    == wall_time(own.get("invitation_expires_at")))
        else:
            require(label + " no unexpected PENDING invitation user=" + uid,
                    own.get("invitation_id") is None)
    require(label + " full pending invitation ownership",
            len(pending) == len(expected_invites)
            and {positive_id(row.get("id")): positive_id(row.get("participation_id"))
                 for row in pending} == expected_invites)
    require(label + " unrelated observer is not a member/organizer",
            outsider["user_id"] != organizer["user_id"]
            and outsider["user_id"] not in expected and my_row(outsider, aid) is None)
    return data, participations


def snapshot(actors):
    return {actor["user_id"]: notifications(actor) for actor in actors}


def observe(actors, aid, before, label, reason, title, expected_cancel_users):
    """Observe the entire window: success at the first poll is insufficient."""
    until = time.monotonic() + OBSERVE_SECONDS
    latest = {}
    while True:
        latest = snapshot(actors)
        # Persist any duplicate observation even if a concurrent deletion hides it.
        for actor in actors:
            rows = matching(latest[actor["user_id"]], aid, DELIST_PREFIX)
            if len(rows) > 1:
                check(label + " duplicate DELIST observed user=" + actor["user_id"], False,
                      "ids=" + ",".join(sorted(row_ids(rows))))
        if time.monotonic() >= until:
            break
        time.sleep(min(0.5, max(0, until - time.monotonic())))
    expected_users = {actor["user_id"] for actor in actors[:-1]}
    for actor in actors:
        uid = actor["user_id"]
        rows = matching(latest[uid], aid, DELIST_PREFIX)
        wanted = 1 if uid in expected_users else 0
        check(label + " exactly " + str(wanted) + " DELIST user=" + uid,
              len(rows) == wanted,
              "activity_id=" + aid + " ids=" + ",".join(sorted(row_ids(rows))))
        if uid in expected_users:
            content_ok = (len(rows) == 1 and title in rows[0]["content"]
                          and reason in rows[0]["content"] and "下架" in rows[0]["content"])
            check(label + " DELIST full title and supplied reason user=" + uid, content_ok)
            if actor.get("membership") == "INVITED":
                check(label + " DELIST 原邀请作废 user=" + uid,
                      len(rows) == 1 and "原邀请作废" in rows[0]["content"])
            check(label + " fresh DELIST identity/event category user=" + uid,
                  len(rows) == 1 and positive_id(rows[0]["id"]) not in row_ids(before[uid])
                  and rows[0]["type"] != "取消",
                  "cancellation notifications cannot stand in for DELIST")
        old_cancel = row_ids(matching(before[uid], aid, CANCEL_PREFIX))
        cancellation = matching(latest[uid], aid, CANCEL_PREFIX)
        new_cancel = [row for row in cancellation if positive_id(row["id"]) not in old_cancel]
        expected_count = 1 if uid in expected_cancel_users else 0
        check(label + " separate new cancellation notices user=" + uid,
              len(new_cancel) == expected_count
              and all(row["type"] == "取消"
                      and row["event_key"] == CANCEL_PREFIX + aid + ":" + uid for row in new_cancel),
              "expected={} actual={}".format(expected_count, len(new_cancel)))
    return latest


def verify_state(label, fixture, expected_status, actors, participations, before_events):
    aid = fixture["activity_id"]
    roster, envelope = paged("/activities/" + aid, actors[0], roster=True)
    data = envelope["data"]
    after_status = "CANCELLED" if expected_status == "OPEN" else expected_status
    check(label + " delisted observable lifecycle/organizer/title",
          data.get("delisted") is True and data.get("status") == after_status
          and positive_id(data.get("organizer_id")) == actors[0]["user_id"]
          and data.get("title") == fixture["title"])
    if expected_status == "OPEN":
        check(label + " cancellation clears active roster and PENDING invitations",
              roster == [] and data.get("pending_invitations") == [])
    else:
        expected_roster = {actor["user_id"]: actor["membership"] for actor in actors
                           if actor["membership"] in ACTIVE}
        check(label + " no cancellation membership effects",
              {positive_id(row.get("user_id")): row.get("status") for row in roster} == expected_roster
              and len(roster) == len(expected_roster))
    for actor in actors:
        uid = actor["user_id"]
        own = my_row(actor, aid)
        if uid not in participations:
            check(label + " organizer remains nonparticipant", own is None)
            continue
        wanted = "CANCELLED" if expected_status == "OPEN" else actor["membership"]
        check(label + " participation after delist user=" + uid,
              own is not None and own.get("status") == wanted
              and positive_id(own["id"]) == participations[uid]
              and (expected_status != "OPEN" or own.get("invitation_id") is None))
        after = events(actor, participations[uid])
        old = row_ids(before_events[uid])
        new_cancels = [row for row in after if positive_id(row["id"]) not in old
                       and row["event_type"] == "ACTIVITY_CANCELLED"]
        check(label + " observable ACTIVITY_CANCELLED event effects user=" + uid,
              len(new_cancels) == (1 if expected_status == "OPEN" else 0),
              "new=" + str(len(new_cancels)))


def verify_invalid_invites(label, actors, aid):
    for actor in actors:
        if actor.get("membership") != "INVITED":
            continue
        iid = positive_id(actor["invitation_id"])
        for action in ("accept", "reject"):
            status, envelope = req("POST", "/invitations/" + iid + "/" + action,
                                   actor["token"], {} if action == "accept" else None,
                                   {"Idempotency-Key": "g4-" + RUN + "-" + iid + "-" + action})
            check(label + " invalidated invitation " + action + " user=" + actor["user_id"],
                  status == 400 and envelope.get("success") is False
                  and envelope.get("code") == "ERROR"
                  and "邀请已不可应答" in str(envelope.get("message", ""))
                  and "当前状态：INVALID" in str(envelope.get("message", "")),
                  response_detail(status, envelope))
        own = my_row(actor, aid)
        check(label + " stale invitation responses cannot rejoin",
              own is not None and own.get("status") == "CANCELLED"
              and own.get("invitation_id") is None)


def exercise(label, fixture, expected_status, actors, outsider, admin):
    aid, observed = fixture["activity_id"], actors + [outsider]
    # Check freshness twice across two publisher ticks. If old unpublished data
    # appears later, the unique reason check still prevents a false positive.
    before = snapshot(observed)
    time.sleep(1.1)
    before = snapshot(observed)
    for actor in observed:
        uid = actor["user_id"]
        require(label + " no pre-existing DELIST user=" + uid,
                not matching(before[uid], aid, DELIST_PREFIX),
                "fresh fixture required; do not relist and reuse this activity")
    # All member/PENDING identities are validated AFTER the notification reads.
    data, participations = read_fixture(label, fixture, expected_status, actors, outsider)
    before_events = {actor["user_id"]: events(actor, participations[actor["user_id"]])
                     for actor in actors if actor["user_id"] in participations}
    check(label + " API-validated mandatory fixture", True,
          "activity_id=" + aid + " active_members=" + str(len(participations)))
    reason = "OBS-4 HTTP regression " + label + " " + RUN
    key = "g4-delist-" + label + "-" + RUN
    path = "/admin/activities/" + aid + "/delist"
    print("INFO - destructive delist activity_id=" + aid + " case=" + label, flush=True)
    first = success("POST", path, admin, {"reason": reason}, {"Idempotency-Key": key})
    result = first["data"]
    decision = positive_id(result.get("decision_id")) if isinstance(result, dict) else None
    after_status = "CANCELLED" if expected_status == "OPEN" else expected_status
    require(label + " confirmed delist response", isinstance(result, dict)
            and positive_id(result.get("activity_id")) == aid and result.get("delisted") is True
            and result.get("activity_status") == after_status and decision is not None
            and result.get("cancel_failed") is not True,
            "expected activity_id/status/delisted/decision_id, no cancel_failed")
    check(label + " delist response", True, "activity_id=" + aid + " decision_id=" + decision)
    expected_cancel_users = set(participations) if expected_status == "OPEN" else set()
    after_first = observe(observed, aid, before, label + " first", reason,
                          data["title"], expected_cancel_users)
    verify_state(label, fixture, expected_status, actors, participations, before_events)
    if expected_status == "OPEN":
        verify_invalid_invites(label, actors, aid)

    # Deliberate confirmed-success repeats only: transport errors are not retries.
    replay_status, replay = req("POST", path, admin["token"], {"reason": reason},
                                {"Idempotency-Key": key})
    check(label + " same-key response replay", replay_status == 200 and replay == first,
          response_detail(replay_status, replay))
    status, repeat = req("POST", path, admin["token"], {"reason": reason},
                         {"Idempotency-Key": key + "-new"})
    check(label + " new-key repeat status/code", status == 400
          and repeat.get("success") is False and repeat.get("code") == "ERROR"
          and repeat.get("message") == "活动已下架", response_detail(status, repeat))
    after_repeat = observe(observed, aid, before, label + " repeats", reason,
                           data["title"], expected_cancel_users)
    for actor in observed:
        uid = actor["user_id"]
        for prefix, category in ((DELIST_PREFIX, "DELIST"), (CANCEL_PREFIX, "cancellation")):
            check(label + " repeats preserve " + category + " IDs user=" + uid,
                  row_ids(matching(after_first[uid], aid, prefix))
                  == row_ids(matching(after_repeat[uid], aid, prefix)))
    verify_state(label + " repeats", fixture, expected_status, actors, participations, before_events)


def cancelled_fixture(organizer):
    """CANCELLED is constructible through the REAL create/cancel APIs."""
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    title = "OBS4 cancelled " + RUN
    body = {"title": title, "category": "其他", "description": "OBS-4 disposable regression",
            "conditions": "", "location": "HTTP regression", "capacity": 1,
            "deadline": (now + timedelta(days=1)).isoformat(),
            "start_time": (now + timedelta(days=2)).isoformat(),
            "end_time": (now + timedelta(days=2, hours=1)).isoformat()}
    data = success("POST", "/activities", organizer, body,
                   {"Idempotency-Key": "g4-create-" + RUN})["data"]
    aid = positive_id(data.get("id")) if isinstance(data, dict) else None
    require("CANCELLED new activity created", aid is not None)
    fixture = {"activity_id": aid, "title": title, "organizer": organizer, "members": []}
    organizer["membership"] = "NONE"
    # Before cancellation ensure this is OUR fresh OPEN activity, with no members.
    rows, envelope = paged("/activities/" + aid, organizer, roster=True)
    require("CANCELLED setup OPEN organizer-only", not rows
            and envelope["data"].get("status") == "OPEN"
            and envelope["data"].get("delisted") is False
            and positive_id(envelope["data"].get("organizer_id")) == organizer["user_id"]
            and envelope["data"].get("title") == title and my_row(organizer, aid) is None)
    result = success("POST", "/activities/" + aid + "/cancel", organizer, {},
                     {"Idempotency-Key": "g4-cancel-" + RUN})["data"]
    require("CANCELLED setup ordinary cancellation", isinstance(result, dict)
            and result.get("status") == "CANCELLED" and result.get("ok") is True)
    check("CANCELLED setup through public API", True, "activity_id=" + aid)
    return fixture


def main():
    global HTTP_TIMEOUT, OBSERVE_SECONDS
    print("INFO - OBS-4 pending unified integration retest; execution mutates disposable fixtures", flush=True)
    configured, ready = {}, True
    root = urllib.parse.urlsplit(BASE[:-7])
    ready &= check("BASE_URL is an HTTP(S) root without API prefix/query/credentials",
                   root.scheme in {"http", "https"} and bool(root.netloc)
                   and root.path in {"", "/"} and not root.query and not root.fragment
                   and root.username is None and root.password is None)
    ready &= check("explicit destructive fixture consent", os.environ.get("OBS4_ALLOW_MUTATION") == "YES",
                   "OBS4_ALLOW_MUTATION=YES is required")
    for variable in ("OBS4_ADMIN_ACCOUNT", "OBS4_ADMIN_PASSWORD"):
        ready &= check(variable + " explicitly supplied", bool(os.environ.get(variable, "").strip()))
    try:
        HTTP_TIMEOUT = float(os.environ.get("OBS4_HTTP_TIMEOUT", "10"))
        OBSERVE_SECONDS = float(os.environ.get("OBS4_OBSERVE_SECONDS", "8"))
        ready &= check("bounded HTTP/published-notification timing",
                       math.isfinite(HTTP_TIMEOUT) and 1 <= HTTP_TIMEOUT <= 60
                       and math.isfinite(OBSERVE_SECONDS) and 3 <= OBSERVE_SECONDS <= 120)
    except ValueError:
        ready &= check("numeric timing configuration", False)
    for label, variable, _ in CASES:
        try:
            configured[label] = fixture_from_env(label, variable)
            check(label + " explicit fixture format", True)
        except StopCase:
            ready = False
    ids = [fixture["activity_id"] for fixture in configured.values()]
    ready &= check("distinct fixture activity IDs", len(ids) == 3 and len(set(ids)) == 3)
    if not ready:
        for label, _, _ in CASES:
            check(label + " mandatory coverage", False, "configuration/prerequisite failed; no HTTP performed")
        check("CANCELLED organizer-only coverage", False, "configuration/prerequisite failed; no HTTP performed")
        return

    try:
        admin = login_actor({"account": os.environ["OBS4_ADMIN_ACCOUNT"],
                             "password": os.environ["OBS4_ADMIN_PASSWORD"]}, "explicit admin", admin=True)
        outsider = new_actor("u")
    except StopCase:
        for label, _, _ in CASES:
            check(label + " mandatory coverage", False, "admin/observer prerequisite failed")
        check("CANCELLED organizer-only coverage", False, "admin/observer prerequisite failed")
        return

    for label, _, expected_status in CASES:
        start = len(results)
        try:
            fixture = configured[label]
            actors = [login_actor(spec, label + " actor " + str(index))
                      for index, spec in enumerate([fixture["organizer"]] + fixture["members"], 1)]
            exercise(label, fixture, expected_status, actors, outsider, admin)
        except StopCase:
            pass  # The originating prerequisite/read/write already emitted FAIL.
        except Exception as error:
            check(label + " unexpected author/runtime contract failure", False, type(error).__name__)
        check(label + " mandatory coverage", all(ok for _, ok, _ in results[start:]),
              "all prerequisites and assertions above must pass")

    start = len(results)
    try:
        organizer = new_actor("o")
        fixture = cancelled_fixture(organizer)
        exercise("CANCELLED", fixture, "CANCELLED", [organizer], outsider, admin)
    except StopCase:
        pass
    except Exception as error:
        check("CANCELLED unexpected author/runtime contract failure", False, type(error).__name__)
    check("CANCELLED organizer-only coverage", all(ok for _, ok, _ in results[start:]),
          "historical cancelled members are outside this scenario")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        check("run completed", False, "interrupted; fixtures may already be mutated")
    except Exception as error:
        check("run completed", False, type(error).__name__ + "; dependent coverage not established")
    failed = sum(not ok for _, ok, _ in results)
    print("SUMMARY - PASS={} FAIL={} (published HTTP effects only)".format(len(results) - failed, failed),
          flush=True)
    sys.exit(1 if failed or not results else 0)
