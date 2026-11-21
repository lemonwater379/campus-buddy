#!/usr/bin/env python3
"""NC-01: ordinary late-accept safety, NOT a deterministic stale-now reproduction.

Prerequisites / run (the operator prepares the instance; this script starts nothing):
  * FUTURE runtime only: operator prepares a disposable app at 127.0.0.1:18095
    backed by a private disposable DB on port 15451. NEVER use a shared instance.
    Operator must hold all sweeps and exclude other writers throughout the run;
    SWEEP_SECONDS=3600 alone is NOT verified sweep suspension.
  * Server environment: INVITE_TTL=12 (8 also supported), SWEEP_SECONDS=3600,
    INVITE_DAY_START_HOUR=0, INVITE_DAY_END_HOUR=24, TZ=Asia/Shanghai; JVM
    -Duser.timezone=Asia/Shanghai, Jackson and DB wall timezone must agree.
    The HTTP health contract exposes TTL, not sweep/day-window configuration;
    PENDING/state checks can detect interference, not prove its absence.
  * Stable server wall clock; client/server clocks synchronized within one second.
    Times below are Shanghai wall times (fixed UTC+08); dates are relative.
  * Exact FUTURE client recipe, ONLY after external preparation above:
    BASE_URL=http://127.0.0.1:18095 E1_ISOLATED=1 E1_EXPECT_TTL=12 \
      python3 /home/hatch/workspace/campus-buddy/test-phase/campaign-20261120/fixes/backend-features/regression/reg-nc01-oversell.py
    Optional TEST_PASSWORD is a test-only 8..64 character letter+digit password;
    otherwise a random per-run password is generated; no credentials are printed.

Safety / artifacts:
  BASE_URL conventionally defaults to http://127.0.0.1:8080, but that default is
  NOT runnable. Before ANY HTTP, require an explicitly set root URL with a literal
  loopback IP (127.0.0.1 or ::1), explicit unprivileged port, and E1_ISOLATED=1.
  Ports 3306, 5432, 5433, 8080, 8081, 15451, missing ports, DNS names, userinfo,
  paths (even '/'), queries
  and fragments are refused. HTTP only; inherited proxies and all redirects are
  disabled. No DB client, subprocess, reset, sweep request, or external fixture
  import. This creates its own timestamped accounts/activity and leaves them for
  unified retest; printed FIXTURE IDs bind them to RUN. No passwords/tokens logged.

Ordinary scenario:
  capacity=1; A FORMAL; B WAITING BEFORE A withdraws; withdrawal issues B's
  INVITED/PENDING invitation. Read the actual expires_at, check short TTL, wait
  only until expires_at+1.25s (maximum 18s), then C signs up FORMAL. B's subsequent
  accept must be a meaningful 4xx expired/invalid/full error. Independent /my,
  actor detail, organizer paged roster and counts must leave C FORMAL, B not
  FORMAL and formal+reserved<=1. GET detail and /my do not clean invitations in
  the inspected contract. The current baseline's C signup performs inline expiry
  cleanup, which may turn B EXPIRED and make this simple late-accept scenario PASS.
  Such a PASS is not a current-source oversell reproduction and cannot prove old
  NC-01. It also cannot diagnose direct-response cleanup rollback (the companion
  script tests that without a preceding signup).

UNIMPLEMENTED deterministic old NC-01 fixture -- not covered by default:
  The old respondInvitation samples now BEFORE participation/invitation/activity
  row locks. A B accept STARTED AFTER expiry cannot expose this stale-now race;
  neither a Python thread start nor HTTP arrival proves the server sampled now.
  An external, strictly isolated instrumented fixture would have to provide:
    1. Exact source/build identity; this run's activity/A/B/C/participation/
       invitation IDs, capacity=1, activity OPEN, deadline still in the future,
       B INVITED, same invitation PENDING, and actual issued_at/expires_at.
    2. Hold B's participation row in an external transaction before expiry,
       WITHOUT holding the activity row. Send B accept and obtain server-side
       evidence correlating that request/transaction with t_sample<expires_at
       at the OLD sampling line, then actual row-lock wait/blocker identity.
    3. After expires_at, C must COMMIT the one FORMAL seat while B is blocked;
       record commit time, formal count=1 and C's participation, and prove the
       SAME B invitation is still PENDING and participation still INVITED.
       IMPORTANT: current signup locks activity and cleans expired invitations
       inline. With B's row locked, naive C signup can block/deadlock; without
       that blocker it can expire B, hiding NC-01. Thus ordinary current signup
       is NOT sufficient fixture coordination. An end-to-end historical fixture
       needs a verified compatible historical signup path that permits this
       interleaving; otherwise an externally controlled transaction may insert
       C's seat under the activity lock without changing B, but that is a
       mechanism-isolation DB fixture, NOT proof of a reachable current-API race.
    4. Prove t_sample<expires_at<t_C_commit<t_release, statuses unchanged until
       release, no sweep/cleanup interference, then release B. Record B response,
       resulting rows/counts/events and post-lock server sampling evidence on the
       fixed build. Old behavior may create 2 FORMAL seats; fixed behavior must
       refuse and keep occupancy<=1. Client timestamps alone are insufficient.
  This script implements NONE of that lock/clock/DB coordination and accepts no
  trust-only flag/evidence file that could turn coverage green. The default exit
  status reflects only ordinary checks and prerequisites. E1_REQUIRE_DETERMINISTIC=1
  makes the missing external fixture an explicit mandatory FAIL, not a skip.

Implementation reuses tests/test_api.py's stdlib req/envelope/check idiom and
existing API contracts, with fail-closed isolation and bounded waits added. No
new framework. Only syntax compilation, not live regression, was authorized at
initial authoring time.
"""

import http.client
import ipaddress
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone


SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
BASE = ""
OPENER = None
TIMEOUT = 4.0
MAX_BYTES = 2 * 1024 * 1024
LATE_MARGIN = 1.25
RUN = datetime.now(SHANGHAI).strftime("%y%m%d%H%M%S") + uuid.uuid4().hex[:4]
RESULTS = []
SENSITIVE = []
PASSWORD = ""
EXPECTED_TTL = 12
TIME_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?"
)


class PrerequisiteError(Exception):
    pass


def safe(value):
    text = str(value)
    for secret in SENSITIVE:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def check(name, condition, detail=""):
    ok = bool(condition)
    RESULTS.append((name, ok))
    print(("PASS" if ok else "FAIL") + " - " + name
          + (" | " + safe(detail) if detail else ""), flush=True)
    return ok


def need(name, condition, detail=""):
    if not check(name, condition, detail):
        raise PrerequisiteError(name)


def wall_now():
    return datetime.now(SHANGHAI).replace(tzinfo=None)


def wall_time(raw):
    if not isinstance(raw, str) or not TIME_RE.fullmatch(raw):
        raise ValueError("missing/invalid ISO server wall time")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is not None:
        value = value.astimezone(SHANGHAI).replace(tzinfo=None)
    return value


def java_version(raw):
    """Render an ACTUAL updated_at as LocalDateTime.toString, preserving nanos."""
    if not isinstance(raw, str):
        raise ValueError("updated_at must be a server timestamp string")
    match = TIME_RE.fullmatch(raw)
    if not match:
        raise ValueError("unrecognized updated_at; refusing to invent a version")
    date, hour, minute, second, fraction, offset = match.groups()
    if offset and re.fullmatch(r"[+-]\d{4}", offset):
        offset = offset[:3] + ":" + offset[3:]
    value = wall_time(date + "T" + hour + ":" + minute + ":"
                      + (second or "00") + (offset or ""))
    nano = int((fraction or "").ljust(9, "0"))
    text = value.strftime("%Y-%m-%dT%H:%M")
    if value.second or nano:
        text += value.strftime(":%S")
    if nano:
        width = 3 if nano % 1000000 == 0 else (6 if nano % 1000 == 0 else 9)
        text += "." + ("%09d" % nano)[:width]
    return text


def version_of(row, field):
    """Fresh additive field, else render the row's RAW updated_at like Java.

    Returns None only when neither is exposed as a server-rendered timestamp;
    callers then omit the token (never fabricate one, never compare a made-up
    LocalDateTime). A malformed string is a prerequisite failure, not a bypass.
    """
    value = row.get(field)
    if value is None:
        value = row.get("version")
    if value is not None:
        need("fresh " + field + " is usable", isinstance(value, str) and bool(value))
        return value
    raw = row.get("updated_at")
    if isinstance(raw, str) and raw:
        return java_version(raw)
    return None


def maybe_time(raw):
    try:
        return wall_time(raw)
    except (TypeError, ValueError, KeyError):
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def isolated_root():
    if "BASE_URL" not in os.environ or os.environ.get("E1_ISOLATED") != "1":
        raise ValueError("explicit isolated BASE_URL and E1_ISOLATED=1 required; default is forbidden")
    raw = os.environ["BASE_URL"]
    if not raw or any(c.isspace() for c in raw) or any(c in raw for c in "\\@?#"):
        raise ValueError("BASE_URL must be a bare literal-loopback root URL")
    parsed = urllib.parse.urlsplit(raw)
    if (parsed.scheme != "http" or parsed.path or parsed.query or parsed.fragment
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("only http root URLs without userinfo/path/query/fragment are allowed")
    address = ipaddress.ip_address(parsed.hostname or "")
    port = parsed.port
    if str(address) not in {"127.0.0.1", "::1"}:
        raise ValueError("only canonical 127.0.0.1 or ::1 loopback hosts are allowed")
    if port is None or not 1024 <= port <= 65535 or port in {3306, 5432, 5433, 8080, 8081, 15451}:
        raise ValueError("explicit safe port required; DB/shared/privileged ports are forbidden")
    host = "[" + str(address) + "]" if address.version == 6 else str(address)
    if parsed.netloc != host + ":" + str(port):
        raise ValueError("use the canonical literal IP and explicit port, without URL decorations")
    return "http://" + host + ":" + str(port)


def client_failure(code, message):
    return {"success": False, "code": code, "message": message, "data": None,
            "_client_error": True}


def req(method, path, token=None, body=None, headers=None):
    """Return (HTTP status, envelope), including explicit client/JSON failures."""
    status = 0
    try:
        root = isolated_root()  # Recheck the guard before EVERY possible connection.
        if OPENER is None or BASE != root + "/api/v1":
            return 0, client_failure("CLIENT_SAFETY", "client has not passed isolation setup")
        parts = urllib.parse.urlsplit(path)
        if (not path.startswith("/") or path.startswith("//") or parts.scheme
                or parts.netloc or parts.fragment or "\\" in path):
            return 0, client_failure("CLIENT_SAFETY", "only relative API paths are allowed")
        hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            hdrs["Authorization"] = "Bearer " + token
        if headers:
            if any(k.lower() in {"host", "proxy-authorization"} for k in headers):
                return 0, client_failure("CLIENT_SAFETY", "routing headers are forbidden")
            hdrs.update(headers)
        request = urllib.request.Request(
            BASE + path, method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=hdrs,
        )
        # No automatic Idempotency-Key: terminal repeats must reach the service.
        try:
            response = OPENER.open(request, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            response = exc  # Preserve and decode the ACTUAL business error envelope.
        with response:
            status = response.code
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return status, client_failure("CLIENT_RESPONSE_LIMIT", "response exceeds 2 MiB")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            return status, client_failure("CLIENT_JSON_ERROR", "response is not UTF-8 JSON")
        if not isinstance(envelope, dict):
            return status, client_failure("CLIENT_ENVELOPE_ERROR", "JSON response is not an object")
        return status, envelope
    except (OSError, ValueError, TypeError, urllib.error.URLError,
            http.client.HTTPException) as exc:
        return status, client_failure("CLIENT_REQUEST_ERROR", type(exc).__name__ + ": " + safe(exc))


def envelope_shape(envelope):
    return (isinstance(envelope, dict) and not envelope.get("_client_error")
            and type(envelope.get("success")) is bool
            and isinstance(envelope.get("code"), str) and bool(envelope["code"])
            and isinstance(envelope.get("message"), str) and bool(envelope["message"])
            and "data" in envelope and (envelope["data"] is None
                 or isinstance(envelope["data"], (dict, list)))
            and isinstance(envelope.get("serverTime"), str)
            and isinstance(envelope.get("traceId"), str) and bool(envelope["traceId"]))


def diagnostic(status, envelope):
    # Never dump login data (which contains token) or request bodies/passwords.
    return "HTTP=%s code=%s message=%s" % (status, envelope.get("code"), envelope.get("message"))


def success(name, status, envelope, data_type=dict):
    need(name + " HTTP/business envelope",
         status == 200 and envelope_shape(envelope) and envelope["success"] is True
         and envelope["code"] == "OK" and envelope["message"] == "ok"
         and isinstance(envelope["data"], data_type), diagnostic(status, envelope))
    return envelope["data"]


def api_object(name, method, path, token=None, body=None):
    status, envelope = req(method, path, token=token, body=body)
    return success(name, status, envelope)


def valid_id(value):
    return isinstance(value, str) and value.isdecimal() and int(value) > 0


def paged_items(name, data):
    need(name + " paged shape",
         isinstance(data, dict) and isinstance(data.get("items"), list)
         and all(type(data.get(k)) is int for k in ("page", "pageSize", "total")))
    items = data["items"]
    need(name + " complete first page (no silent truncation)",
         data["page"] == 1 and data["pageSize"] == 100
         and data["total"] == len(items) <= 100 and all(isinstance(x, dict) for x in items))
    return items


def my_row(actor, aid):
    data = api_object(actor["role"] + " /my", "GET", "/my?page=1&pageSize=100", actor["token"])
    rows = paged_items(actor["role"] + " /my", data)
    matches = [row for row in rows if row.get("activity_id") == aid]
    need(actor["role"] + " exactly one participation", len(matches) == 1, "activity=" + aid)
    need(actor["role"] + " participation ID", valid_id(matches[0].get("id")))
    return matches[0]


def detail(actor, aid):
    return api_object(actor["role"] + " detail", "GET",
                      "/activities/" + aid + "?rosterPage=1&rosterPageSize=100", actor["token"])


def roster_of(data):
    rows = paged_items("organizer roster", data.get("roster"))
    need("organizer pending invitations shape", isinstance(data.get("pending_invitations"), list)
         and all(isinstance(row, dict) for row in data["pending_invitations"]))
    return rows


def capacity_check(name, data, expected_formal=None, expected_reserved=None):
    rows = roster_of(data)
    formal, reserved, capacity = data.get("formal"), data.get("reserved"), data.get("capacity")
    numeric = all(type(x) is int for x in (formal, reserved, capacity))
    condition = (numeric and capacity == 1 and 0 <= formal <= capacity
                 and reserved >= 0 and formal + reserved <= capacity
                 and sum(row.get("status") == "FORMAL" for row in rows) == formal)
    if expected_formal is not None:
        condition = condition and formal == expected_formal
    if expected_reserved is not None:
        condition = condition and reserved == expected_reserved
    return check(name, condition, "formal=%s reserved=%s capacity=%s" % (formal, reserved, capacity))


def actor(role):
    account = "nc01_" + role.lower() + "_" + RUN
    need("unique account/nickname length " + role, 4 <= len(account) <= 30)
    api_object("register " + role, "POST", "/register", body={
        "account": account, "password": PASSWORD, "nickname": account})
    data = api_object("login " + role, "POST", "/login", body={"account": account, "password": PASSWORD})
    token = data.get("token")
    if isinstance(token, str):
        SENSITIVE.append(token)
    need("login data.token " + role, isinstance(token, str) and bool(token))
    user = data.get("user")
    need("login user ID " + role, isinstance(user, dict) and valid_id(user.get("id")))
    print("FIXTURE " + json.dumps({"run": RUN, "role": role, "account": account, "user_id": user["id"]}), flush=True)
    return {"role": role, "token": token, "id": user["id"]}


def mutation_body(activity, participation=None):
    """confirmed=true plus only freshly-read, real tokens when the service exposes them."""
    body = {"confirmed": True}
    av = version_of(activity, "activity_version")
    if av is not None:
        body["activity_version"] = av
        body["version"] = av
    pv = version_of(participation, "participation_version") if participation is not None else None
    if pv is not None:
        body["participation_version"] = pv
        body["version"] = pv
    return body


def setup():
    global BASE, OPENER, PASSWORD, EXPECTED_TTL
    root = isolated_root()
    need("explicit isolated loopback target", True, root)
    PASSWORD = os.environ.get("TEST_PASSWORD")
    if PASSWORD is None:
        PASSWORD = "NC01" + secrets.token_hex(10) + "9a"
    SENSITIVE.append(PASSWORD)
    need("test-only password policy", 8 <= len(PASSWORD) <= 64
         and any(c.isalpha() for c in PASSWORD) and any(c.isdigit() for c in PASSWORD)
         and not PASSWORD.isspace())
    try:
        EXPECTED_TTL = int(os.environ.get("E1_EXPECT_TTL", "12"))
    except ValueError:
        EXPECTED_TTL = -1
    need("short expected TTL (never default 120s)", EXPECTED_TTL in (8, 12))
    BASE = root + "/api/v1"
    OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    status, envelope = req("GET", "/health")
    data = success("isolated health", status, envelope)
    need("actual server TTL matches short fixture", type(data.get("invite_ttl_seconds")) is int
         and data["invite_ttl_seconds"] == EXPECTED_TTL, "expected=%s actual=%s" % (EXPECTED_TTL, data.get("invite_ttl_seconds")))
    need("Shanghai server/client clock agreement", abs((wall_time(envelope["serverTime"]) - wall_now()).total_seconds()) <= 1.0,
         "require server JVM/DB/Jackson TZ=Asia/Shanghai and synchronized clocks")


def wait_past(expires):
    remaining = (expires + timedelta(seconds=LATE_MARGIN) - wall_now()).total_seconds()
    need("bounded actual expires_at wait", 0 < remaining <= 18.0,
         "remaining=%.3fs; expired setup / wrong TTL / timezone must be corrected" % remaining)
    stop = time.monotonic() + 18.0
    while wall_now() < expires + timedelta(seconds=LATE_MARGIN):
        need_remaining = (expires + timedelta(seconds=LATE_MARGIN) - wall_now()).total_seconds()
        if time.monotonic() >= stop:
            need("expiry wait completed before bound", False, "clock changed or fixture mismatched")
        time.sleep(min(0.2, max(0.01, need_remaining)))
    check("ordinary wait crossed expiry (not exact equality)", wall_now() > expires, expires.isoformat())


def late_accept_scenario():
    org, a, b, c = (actor(role) for role in ("ORG", "A", "B", "C"))
    now = wall_now().replace(microsecond=0)
    created = api_object("create capacity-one activity", "POST", "/activities", org["token"], {
        "title": "NC01-late-" + RUN, "category": "其他", "description": "Isolated NC01 late-accept regression",
        "conditions": "", "location": "isolated test only", "capacity": 1,
        "deadline": (now + timedelta(days=1)).isoformat(),
        "start_time": (now + timedelta(days=2)).isoformat(),
        "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
    })
    aid = created.get("id")
    need("created activity ID", valid_id(aid))
    print("FIXTURE " + json.dumps({"run": RUN, "scenario": "ordinary-late-accept", "activity_id": aid}), flush=True)
    da = api_object("A signup", "POST", "/activities/" + aid + "/signup", a["token"], {})
    need("A signup detail is FORMAL", da.get("my_status") == "FORMAL" and valid_id(da.get("participation_id")))
    db = api_object("B signup BEFORE A withdrawal", "POST", "/activities/" + aid + "/signup", b["token"], {})
    need("B queued WAITING before withdrawal", db.get("my_status") == "WAITING"
         and valid_id(db.get("participation_id")))
    pb = my_row(b, aid)
    # Fetch the actual participation and activity versions immediately before withdrawal.
    pa = my_row(a, aid)
    activity = detail(a, aid)
    need("independent A FORMAL / B WAITING prerequisites", pa.get("status") == "FORMAL" and pb.get("status") == "WAITING"
         and activity.get("my_status") == "FORMAL" and activity.get("participation_id") == pa["id"])
    withdrawn = api_object("A confirmed/versioned withdrawal", "POST", "/participations/" + pa["id"] + "/withdraw",
                           a["token"], mutation_body(activity, pa))
    need("withdrawal object refers to A", withdrawn.get("participation_id", pa["id"]) == pa["id"])
    need("A independent WITHDRAWN", my_row(a, aid).get("status") == "WITHDRAWN")

    # Read-only, short polling only. Signup would clean expiry and hide the setup.
    poll_end = time.monotonic() + 3.0
    while True:
        db = detail(b, aid)
        if db.get("my_status") == "INVITED" and valid_id(db.get("invitation_id")):
            break
        if time.monotonic() >= poll_end:
            need("B invitation issued", False, "nighttime gate / slow or expired setup; require day window 0..24")
        time.sleep(0.15)
    iid = db["invitation_id"]
    expires = wall_time(db.get("invitation_expires_at"))
    before = detail(org, aid)
    pending = [x for x in before.get("pending_invitations", []) if x.get("id") == iid]
    need("B same invitation PENDING before wait", len(pending) == 1 and pending[0].get("status") == "PENDING"
         and pending[0].get("participation_id") == pb["id"])
    issued = maybe_time(pending[0].get("issued_at"))
    if issued is not None:
        need("issued short TTL matches actual expires_at",
             (expires - issued).total_seconds() == EXPECTED_TTL)
    else:
        # Raw activity rows may serialize Timestamp differently; never guess a version/time.
        remaining = (expires - wall_now()).total_seconds()
        need("actual expires_at proves a short TTL", 0 < remaining <= EXPECTED_TTL + 2.0,
             "remaining=%.3fs" % remaining)
    need("invitation setup is still unexpired", (expires - wall_now()).total_seconds() >= 2.0,
         "expired setup: use short-TTL isolated instance without competing sweep")
    pending_expiry = maybe_time(pending[0].get("expires_at"))
    if pending_expiry is not None:
        need("pending expiry agrees across independent reads", pending_expiry == expires)
    need("initial reservation safe", capacity_check("before expiry capacity", before, 0, 1))
    print("FIXTURE " + json.dumps({"run": RUN, "activity_id": aid, "A_participation_id": pa["id"],
          "B_participation_id": pb["id"], "B_invitation_id": iid,
          "issued_at": issued.isoformat() if issued is not None else None,
          "expires_at": expires.isoformat()}), flush=True)
    wait_past(expires)

    # No cleanup-commit claim is made here: C signup explicitly performs cleanup.
    dc = api_object("C signup after actual expiry", "POST", "/activities/" + aid + "/signup", c["token"], {})
    need("C becomes FORMAL", dc.get("my_status") == "FORMAL" and valid_id(dc.get("participation_id")))
    pc = my_row(c, aid)
    need("C independently holds the sole formal seat", pc.get("status") == "FORMAL")
    status, envelope = req("POST", "/invitations/" + iid + "/accept", b["token"], {})
    text = str(envelope.get("message", "")) + " " + json.dumps(envelope.get("data"), ensure_ascii=False)
    reason = any(word in text.lower() for word in ("过期", "失效", "作废", "已满", "名额", "expired", "invalid", "full"))
    check("ordinary late accept is a meaningful 4xx business refusal",
          400 <= status < 500 and status not in (401, 403, 404, 405, 409, 429)
          and envelope_shape(envelope) and envelope["success"] is False
          and envelope["code"] != "OK" and (envelope["data"] is None or isinstance(envelope["data"], dict))
          and reason, diagnostic(status, envelope))
    # Continue independent reads even if the refusal check failed.
    after = detail(org, aid)
    db_after, dc_after = detail(b, aid), detail(c, aid)
    pb_after, pc_after = my_row(b, aid), my_row(c, aid)
    capacity_check("after late accept formal/reserved never oversell", after, 1, 0)
    check("C still FORMAL in independent detail AND /my", dc_after.get("my_status") == "FORMAL"
          and pc_after.get("status") == "FORMAL" and pc_after.get("id") == pc["id"])
    check("B neither FORMAL nor still INVITED in independent detail AND /my",
          db_after.get("my_status") in {"EXPIRED", "WITHDRAWN"}
          and pb_after.get("status") == db_after.get("my_status")
          and pb_after.get("id") == pb["id"] and db_after.get("invitation_id") is None,
          "detail=%s /my=%s invitation_id=%s" % (db_after.get("my_status"), pb_after.get("status"),
                                                  db_after.get("invitation_id")))
    rows = roster_of(after)
    check("organizer roster contains only C as FORMAL", [x.get("id") for x in rows if x.get("status") == "FORMAL"] == [pc["id"]])
    print("FIXTURE " + json.dumps({"run": RUN, "activity_id": aid, "C_participation_id": pc["id"],
          "B_invitation_id": iid, "B_status": pb_after.get("status"), "C_status": pc_after.get("status")}), flush=True)


def main():
    print("RUN " + RUN + " | ordinary late-accept checks; no deterministic lock coordination", flush=True)
    print("INFO/UNVERIFIED - deterministic NC-01 proof is unavailable; ordinary late-accept "
          "PASS is observational only, not pre-expiry sampling/row-lock/C-commit proof", flush=True)
    if os.environ.get("E1_REQUIRE_DETERMINISTIC") == "1":
        check("deterministic old NC-01 stale-now/lock coverage", False,
              "unmet deterministic prerequisite: externally prepared lock/clock/DB fixture required; "
              "these scripts cannot supply it. Late accept is NOT that proof.")
    try:
        setup()
        late_accept_scenario()
    except PrerequisiteError as exc:
        check("ordinary late-accept coverage completed", False, "unmet prerequisite: " + str(exc))
    except (Exception, KeyboardInterrupt) as exc:
        check("ordinary late-accept coverage completed", False, type(exc).__name__ + ": " + safe(exc))
    failed = sum(not ok for _, ok in RESULTS)
    print("SUMMARY run=%s PASS=%d FAIL=%d; not a current-source oversell reproduction; "
          "E1_REQUIRE_DETERMINISTIC=1 requires the unavailable deterministic NC-01 fixture"
          % (RUN, len(RESULTS) - failed, failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
