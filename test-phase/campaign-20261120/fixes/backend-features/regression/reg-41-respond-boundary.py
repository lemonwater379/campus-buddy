#!/usr/bin/env python3
"""REG-41: invitation response boundaries; stdlib req/envelope/check conventions.

FUTURE runtime prerequisites (operator prepares everything; script starts nothing):
  * Disposable app on 127.0.0.1:18095, private disposable DB on port 15451. Never
    use shared instances/data. Hold ALL sweeps and exclude every other writer for
    the entire run; SWEEP_SECONDS=3600 alone is NOT verified sweep suspension.
  * Server: INVITE_TTL=12, SWEEP_SECONDS=3600, INVITE_DAY_START_HOUR=0,
    INVITE_DAY_END_HOUR=24, TZ=Asia/Shanghai, JVM -Duser.timezone=Asia/Shanghai;
    Jackson/DB wall timezone agrees. Health verifies TTL, not sweep/day settings.
  * Stable non-decreasing server wall clock with no time adjustments; synchronized
    client Shanghai clock (within one second). E1_STABLE_CLOCK=1 explicitly
    acknowledges this assumption; E1_NO_SWEEPS_OR_WRITERS=1 acknowledges operator
    control, not server-side instrumentation or proof that sweeps were suspended.
  * Exact FUTURE client recipe, only AFTER external preparation above:
      BASE_URL=http://127.0.0.1:18095 E1_ISOLATED=1 E1_EXPECT_TTL=12 \
        E1_STABLE_CLOCK=1 E1_NO_SWEEPS_OR_WRITERS=1 \
        python3 /home/hatch/workspace/campus-buddy/test-phase/campaign-20261120/fixes/backend-features/regression/reg-41-respond-boundary.py
    TEST_PASSWORD supplies a test-only password; the existing placeholder is
    preserved exactly. Passwords/tokens are never printed. TTL 8 is also supported
    when explicitly configured on both sides. Each boundary wait is capped at 18s.

Cases A/B/C/D: normal unexpired accept/reject; direct expired accept cleanup;
organizer cancel. All four terminal states ACCEPTED/REJECTED/EXPIRED/INVALID must
reject BOTH accept and reject with HTTP400 failed envelopes and their real state.
Every response probe uses a fresh Idempotency-Key; normal accept checks capacity.
C (NC-13) requires the SAME B INVITED/PENDING at past expiry before the 400, then
independent EXPIRED/no pending, INVITE_EXPIRED INVITED->EXPIRED, next C INVITED and
sole reservation. These are observable checks under the operator guarantees, NOT
strong causal instrumentation proof; no signup is inserted before the late accept.

E is the VALID natural deadline behavior: expires=min(issued+TTL,deadline), so the
after-deadline request also crosses expiry. No inconsistent DB fixture is needed.
Isolating the deadline guard alone would need future expiry after deadline; this
unavailable stronger fixture is INFO/UNVERIFIED, not a default mandatory failure.

F is a REAL bounded HTTP proof for CURRENT nowSeconds()=LocalDateTime.now().withNano(0):
create fresh capacity1 A FORMAL/B WAITING, withdraw A, require B INVITED/PENDING
with WHOLE-SECOND expires E. Wait toward E+0.1 on the synchronized Shanghai clock;
fresh GETs must still show that SAME B INVITED/PENDING past expiry. GET /health
immediately before accept, capture envelope.serverTime H, then accept with a fresh
key and response timestamp R. Require E<=H<=R<E+1s. With the stable wall-clock
assumption, respond's fresh sample after participation/invitation/activity locks
lies between H and R, hence floor(sample)==E. Require HTTP400 failed EXPIRY envelope
and independent B EXPIRED/no pending. Fractional E, missed bracket/slow network,
non-pending pre-state or missing acknowledgements FAIL prerequisite, never label a
merely late response equality PASS. This cannot prove equality for OLD untruncated
LocalDateTime.now(); no clock injection or source modification is used.
E1_REQUIRE_DETERMINISTIC=1 additionally FAILs for unavailable stronger guard-isolation/
NC-13 causal instrumentation; default success means only the stated HTTP checks.

Contract: inspected accept/reject controller still wraps respond in support.ok;
service _respond_error must be mapped to HTTP400 after commit. A missing mapping
FAILs, not green. Withdraw/cancel currently ignore bodies, but these clients send
confirmed:true and only freshly read actual version tokens (Java timestamp rendering,
never numeric Timestamp guesses), including activity_version when exposed. Detail
and /my GETs do not clean invitations. No reset, DB client, subprocess or sweep call.
Only canonical 127.0.0.1/::1 HTTP roots with explicit isolated ports are accepted;
3306/5432/5433/8080/8081/15451 are blocked. Proxies and redirects stay disabled.

AUTHORING STATUS: py_compile only, NOT executed/imported; no runtime proof claimed.
"""
import http.client
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
TZ = timezone(timedelta(hours=8))
RUN = datetime.now(TZ).strftime("%y%m%d%H%M%S%f")
RESULTS = []
BASE = OPENER = None
EXPECTED_TTL = 12
TIME_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?"
)

class Unmet(Exception):
    pass
def  check(name, condition, detail=""):
    RESULTS.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'} - {name}" + (f" | {detail}" if detail else ""), flush=True)
def need(name, condition, detail=""):
    check(name, condition, detail)
    if not condition:
        raise Unmet

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
def isolated_root():
    raw = os.environ.get("BASE_URL", "")
    if not raw or os.environ.get("E1_ISOLATED") != "1" or any(c.isspace() or c in "\\@?#" for c in raw):
        raise ValueError("explicit isolated BASE_URL + E1_ISOLATED=1 required")
    url = urllib.parse.urlsplit(raw)
    ip = ipaddress.ip_address(url.hostname or "")
    port = url.port
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    if (url.scheme != "http" or url.path or url.query or url.fragment or str(ip) not in {"127.0.0.1", "::1"}
            or port is None or not 1024 <= port <= 65535 or port in {3306, 5432, 5433, 8080, 8081, 15451}
            or url.netloc != f"{host}:{port}"):
        raise ValueError("bare HTTP literal loopback on an isolated port required")
    return f"http://{host}:{port}"
def req(method, path, token=None, body=None, headers=None):
    """Return HTTP status/envelope; optional explicit keys, never log raw data."""
    status, limit = 0, 2 * 1024 * 1024
    try:
        parts = urllib.parse.urlsplit(path)
        if (BASE != isolated_root() + "/api/v1" or OPENER is None
                or not path.startswith("/") or path.startswith("//")
                or parts.scheme or parts.netloc or parts.fragment or "\\" in path):
            return 0, {}
        hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            hdrs["Authorization"] = "Bearer " + token
        if headers:
            if any(k.lower() == "host" or k.lower().startswith("proxy-") for k in headers):
                return 0, {}
            hdrs.update(headers)
        request = urllib.request.Request(BASE + path, method=method, headers=hdrs,
                                         data=None if body is None else json.dumps(body).encode("utf-8"))
        try:
            response = OPENER.open(request, timeout=4)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status, raw = response.code, response.read(limit + 1)
        env = json.loads(raw.decode("utf-8")) if len(raw) <= limit else None
        return status, env if isinstance(env, dict) else {}
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        return status, {}
def envelope(e):
    return (type(e.get("success")) is bool and "data" in e
            and all(isinstance(e.get(k), str) and e[k] for k in ("code", "message", "serverTime", "traceId")))
def ok(name, reply, kind=dict):
    status, e = reply
    need(name, status == 200 and envelope(e) and e["success"] and e["code"] == "OK"
         and e["message"] == "ok" and isinstance(e["data"], kind), f"HTTP={status}; expected 200 OK envelope")
    return e["data"]
def denied(name, reply, *hints, terminal=None):
    status, e = reply
    data = e.get("data")
    text = str(e.get("message", "")).casefold()
    reason = (not hints or any(h in text for h in hints))
    if terminal:
        reason = terminal.casefold() in text or (isinstance(data, dict) and data.get("invitation_status") == terminal)
    check(name, status == 400 and envelope(e) and not e["success"] and e["code"] != "OK"
          and (data is None or isinstance(data, dict)) and reason, f"HTTP={status}; expected 400 business envelope")
def now():
    return datetime.now(TZ).replace(tzinfo=None)
def wall(raw):
    if not isinstance(raw, str) or not TIME_RE.fullmatch(raw):
        raise ValueError("missing/invalid ISO server wall time")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return dt.astimezone(TZ).replace(tzinfo=None) if dt.tzinfo else dt

def maybe_wall(raw):
    try:
        return wall(raw)
    except (TypeError, ValueError):
        return None

def java_version(raw):
    """Same LocalDateTime rendering as NC01; preserve actual nanoseconds."""
    match = TIME_RE.fullmatch(raw) if isinstance(raw, str) else None
    need("raw updated_at is a server timestamp", match is not None)
    date, hour, minute, second, fraction, offset = match.groups()
    if offset and re.fullmatch(r"[+-]\d{4}", offset):
        offset = offset[:3] + ":" + offset[3:]
    value = wall(date + "T" + hour + ":" + minute + ":" + (second or "00") + (offset or ""))
    nano = int((fraction or "").ljust(9, "0"))
    text = value.strftime("%Y-%m-%dT%H:%M")
    if value.second or nano:
        text += value.strftime(":%S")
    if nano:
        width = 3 if nano % 1000000 == 0 else (6 if nano % 1000 == 0 else 9)
        text += "." + ("%09d" % nano)[:width]
    return text

def confirmation(row, field):
    value = row.get(field)
    if value is None:
        value = row.get("version")
    if value is None and isinstance(row.get("updated_at"), str):
        value = java_version(row["updated_at"])
    # Raw numeric Timestamp is not a Java version: omit it, never invent one.
    need(f"fresh {field} if exposed", value is None or isinstance(value, str) and bool(value.strip()))
    return {"confirmed": True} if value is None else {"confirmed": True, field: value, "version": value}
def paged(data):
    items = data["items"]
    need("complete paged read", isinstance(items, list) and data["page"] == 1 and data["pageSize"] == 100
         and data["total"] == len(items) <= 100 and all(isinstance(row, dict) for row in items))
    return items
def detail(aid, token):
    return ok("independent detail", req("GET", f"/activities/{aid}?rosterPage=1&rosterPageSize=100", token))
def mine(aid, token):
    data = ok("independent /my", req("GET", "/my?page=1&pageSize=100", token))
    rows = [p for p in paged(data) if p.get("activity_id") == aid]
    need("one matching /my row", len(rows) == 1)
    return rows[0]
def counts(d, expected=None):
    roster = paged(d["roster"])
    f, r, c = (d[k] for k in ("formal", "reserved", "capacity"))
    need("numeric capacity accounting", all(type(n) is int for n in (f, r, c)))
    check("formal + reserved <= capacity=1; roster agrees", c == 1 and 0 <= f <= c and 0 <= r <= c - f
          and f == sum(p.get("status") == "FORMAL" for p in roster) and (expected is None or (f, r) == expected),
          f"formal={f} reserved={r} capacity={c}")
def server_id(raw):
    need("valid API ID", isinstance(raw, str) and re.fullmatch(r"[1-9][0-9]*", raw))
    return raw
def pending(d, iid, pid):
    rows = d.get("pending_invitations")
    need("pending_invitations shape", isinstance(rows, list) and all(isinstance(i, dict) for i in rows))
    return len([i for i in rows if i.get("id") == iid and i.get("participation_id") == pid
                and i.get("status") == "PENDING"]) == 1
def snapshot(aid, b):
    p, d = mine(aid, b), detail(aid, b)
    events = ok("independent participation events", req("GET", f"/participations/{server_id(p['id'])}/events", b), list)
    return p, {k: d.get(k) for k in ("status", "my_status", "invitation_id", "invitation_expires_at")}, events
def wait_past(boundary, margin=1.25):
    target = boundary + timedelta(seconds=margin)
    seconds = (target - now()).total_seconds()
    need("bounded boundary wait", 0 < seconds <= 18, "unmet timing prerequisite: require a short fresh fixture")
    stop = time.monotonic() + 18
    while now() < target:
        need("boundary wait within monotonic bound", time.monotonic() < stop)
        time.sleep(min(0.1, max(0.001, (target - now()).total_seconds())))
    need("local wall clock crossed boundary (alone NOT equality proof)", now() >= target)

def fixture(case, org, a, b, w):
    t = now().replace(microsecond=0)
    deadline = t + (timedelta(seconds=max(6, EXPECTED_TTL - 2)) if case == "E" else timedelta(days=1))
    start = t + timedelta(days=2 + "ABCDEF".index(case))  # No cross-case signup time conflicts.
    created = ok("create capacity 1", req("POST", "/activities", org, {
        "title": f"R41-{case}-{RUN}", "location": "isolated test", "category": "其他", "capacity": 1,
        "deadline": deadline.isoformat(), "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat()}))
    aid = server_id(created["id"])
    for token, expected in [(a, "FORMAL"), (b, "WAITING")] + ([(w, "WAITING")] if case == "C" else []):
        signup = ok("signup", req("POST", f"/activities/{aid}/signup", token, {"confirmConflict": True}))
        need(f"{expected} before A withdraws", signup.get("my_status") == expected)
    # Fresh /my participation AND detail immediately before the mutation.
    pa, ad = mine(aid, a), detail(aid, a)
    need("A independently FORMAL", pa["status"] == ad.get("my_status") == "FORMAL"
         and pa["id"] == ad.get("participation_id"))
    body = confirmation(ad, "activity_version")
    body.update(confirmation(pa, "participation_version"))
    withdrawn = ok("A confirmed/versioned withdraw", req("POST", f"/participations/{server_id(pa['id'])}/withdraw", a, body))
    need("withdrawal persists WITHDRAWN", withdrawn.get("status") == "WITHDRAWN"
         and mine(aid, a).get("status") == "WITHDRAWN")
    bd, od = detail(aid, b), detail(aid, org)
    iid, bid = server_id(bd.get("invitation_id")), server_id(bd.get("participation_id"))
    raw_expiry = bd.get("invitation_expires_at")
    expires = wall(raw_expiry)
    need("unexpired B INVITED with PENDING invitation", bd.get("my_status") == "INVITED"
         and pending(od, iid, bid) and (expires - now()).total_seconds() >= 1.0,
         "missing invitation/expired setup is a prerequisite failure")
    invitation = next(i for i in od["pending_invitations"] if i.get("id") == iid)
    issued = maybe_wall(invitation.get("issued_at"))
    expected_deadline = deadline if case == "E" else None
    if issued is not None:
        expected_expiry = issued + timedelta(seconds=EXPECTED_TTL)
        if expected_deadline is not None:
            expected_expiry = min(expected_expiry, expected_deadline)
        need("expiry equals min(issued+TTL, deadline) when clipped", expires == expected_expiry)
    else:
        need("actual expiry proves fresh short TTL", 0 < (expires - now()).total_seconds() <= EXPECTED_TTL + 2)
    if expected_deadline is not None:
        need("natural deadline-clipped expiry", expires == expected_deadline)
    pending_expiry = maybe_wall(invitation.get("expires_at"))
    if pending_expiry is not None:
        need("independent pending expiry agrees", pending_expiry == expires)
    counts(od, (0, 1))
    print(f"FIXTURE run={RUN} case={case} activity_id={aid} A_participation_id={pa['id']} "
          f"B_participation_id={bid} invitation_id={iid} expires_at={raw_expiry}", flush=True)
    return aid, iid, bid, expires, od, deadline, raw_expiry

def scenario_exact_equality(aid, iid, bid, expires, raw_expiry, org, b):
    fraction = TIME_RE.fullmatch(raw_expiry).group(5)
    need("whole-second expiry prerequisite", fraction is None or not fraction.strip("0"),
         "fractional expiry cannot prove floor(sample)==expires_at")
    wait_past(expires, margin=0.1)
    pre = req("GET", f"/activities/{aid}?rosterPage=1&rosterPageSize=100", b)
    bd = ok("past-expiry B detail", pre)
    pb, od = mine(aid, b), detail(aid, org)
    need("SAME B still INVITED/PENDING at past server expiry",
         wall(pre[1]["serverTime"]) >= expires and now() > expires
         and bd.get("my_status") == pb.get("status") == "INVITED"
         and bd.get("participation_id") == pb.get("id") == bid
         and bd.get("invitation_id") == iid and wall(bd.get("invitation_expires_at")) == expires
         and pending(od, iid, bid), "sweep/writer or a missed setup is a prerequisite FAIL")
    headers = {"Idempotency-Key": "reg41-equality-" + uuid.uuid4().hex}
    body = {"confirmConflict": True}
    health = req("GET", "/health")  # Same guarded server root; last HTTP before accept.
    ok("immediate pre-accept health", health)
    lower = wall(health[1]["serverTime"])
    end = expires + timedelta(seconds=1)
    need("health lower bracket within [E,E+1s)", expires <= lower < end,
         "missed bracket/clock offset/slow network: prerequisite FAIL, NOT equality PASS")
    reply = req("POST", f"/invitations/{iid}/accept", b, body, headers)
    need("accept response has a server timestamp envelope", envelope(reply[1]))
    upper = wall(reply[1]["serverTime"])
    need("fresh post-lock sample bracket prerequisite E<=H<=R<E+1s", lower <= upper < end,
         f"H={lower.isoformat()} R={upper.isoformat()} E={expires.isoformat()}; missed bracket is NOT equality")
    denied("NC-03 bounded CURRENT nowSeconds()==expires_at -> 400 expiry", reply, "过期", "expired")
    p, d, _ = snapshot(aid, b)
    od = detail(aid, org)
    check("equality fixture independently EXPIRED with no pending", p["id"] == bid
          and p.get("status") == d.get("my_status") == "EXPIRED"
          and p.get("invitation_id") is None and d.get("invitation_id") is None
          and not pending(od, iid, bid) and not od["pending_invitations"])
    counts(od, (0, 0))
    print("INFO/UNVERIFIED - current floored-sample bracket cannot prove OLD untruncated-now equality", flush=True)
def scenario(case, org, a, b, w):
    print(f"CASE {case}", flush=True)
    aid, iid, bid, expires, od, deadline, raw_expiry = fixture(case, org, a, b, w)
    def respond(action):
        return req("POST", f"/invitations/{iid}/{action}", b,
                   {"confirmConflict": True} if action == "accept" else None,
                   {"Idempotency-Key": "reg41-" + uuid.uuid4().hex})
    if case == "F":
        scenario_exact_equality(aid, iid, bid, expires, raw_expiry, org, b)
        return
    if case == "E":
        need("E natural expires_at equals deadline", expires == deadline)
        wait_past(deadline)
        reply = respond("accept")
        denied("E natural deadline/expiry denial", reply, "过期", "失效", "截止", "不可报名", "expired", "deadline")
        check("E server response after deadline", envelope(reply[1]) and wall(reply[1]["serverTime"]) >= deadline)
        p, d, _ = snapshot(aid, b)
        od = detail(aid, org)
        check("E B independently EXPIRED with no pending", p["id"] == bid
              and p.get("status") == d.get("my_status") == "EXPIRED"
              and p.get("invitation_id") is None and d.get("invitation_id") is None
              and not pending(od, iid, bid))
        counts(od, (0, 0))
        print("INFO/UNVERIFIED - natural min(TTL,deadline) behavior is valid; isolating the deadline "
              "guard alone needs an optional inconsistent future-expiry fixture", flush=True)
        return
    if case == "A":
        need("normal accept fixture still unexpired", now() < expires)
        accepted = ok("A accept unexpired invitation", respond("accept"))
        check("A accept returns FORMAL detail", accepted.get("activity_id") == aid and accepted.get("my_status") == "FORMAL")
        counts(detail(aid, org), (1, 0))
    elif case == "B":
        ok("B reject unexpired invitation", respond("reject"))
    elif case == "C":
        pc = mine(aid, w)
        need("next C still WAITING after B invited", pc["status"] == "WAITING")
        wait_past(expires)
        pre_b, pre_d, pre_o = mine(aid, b), detail(aid, b), detail(aid, org)
        need("NC-13 SAME B INVITED/PENDING at past expiry prerequisite",
             now() > expires and pre_b.get("status") == pre_d.get("my_status") == "INVITED"
             and pre_b.get("id") == pre_d.get("participation_id") == bid
             and pre_d.get("invitation_id") == iid and wall(pre_d.get("invitation_expires_at")) == expires
             and pending(pre_o, iid, bid), "sweep/other writer or missing fixture: FAIL prerequisite, do not continue")
        denied("C direct expired accept observable 400", respond("accept"), "邀请已过期", "invitation expired", "invitation has expired")
    else:
        fresh = detail(aid, org)
        need("fresh pre-cancel activity OPEN", fresh.get("status") == "OPEN")
        ok("D confirmed/versioned organizer cancel", req("POST", f"/activities/{aid}/cancel", org,
                                                        confirmation(fresh, "activity_version")))
    # Independent post-400 reads precede any repeat or signup.
    before = snapshot(aid, b)
    p, d, events = before
    terminal, expected = {"A": ("ACCEPTED", "FORMAL"), "B": ("REJECTED", "WITHDRAWN"),
                          "C": ("EXPIRED", "EXPIRED"), "D": ("INVALID", "CANCELLED")}[case]
    check(f"{case} B persists as {expected} with no pending invitation", p["id"] == bid
          and p["status"] == d["my_status"] == expected and p.get("invitation_id") is None and d["invitation_id"] is None)
    od = detail(aid, org)
    check(f"{case} original invitation independently no longer pending", not pending(od, iid, bid))
    if case == "C":
        check("C exactly one INVITE_EXPIRED (INVITED -> EXPIRED)",
              [(e["from_status"], e["to_status"]) for e in events if e["event_type"] == "INVITE_EXPIRED"] == [("INVITED", "EXPIRED")])
        pw, dw = mine(aid, w), detail(aid, w)
        check("next C INVITED in /my AND detail with the sole live PENDING reservation",
              pw.get("id") == dw.get("participation_id") == pc["id"]
              and pw.get("status") == dw.get("my_status") == "INVITED"
              and dw.get("invitation_id") is not None and len(od["pending_invitations"]) == 1
              and pending(od, dw["invitation_id"], pw["id"]) and wall(dw.get("invitation_expires_at")) > now())
        counts(od, (0, 1))
        print("INFO/UNVERIFIED - NC-13 observable post-400 cleanup under operator no-sweep/no-writer "
              "guarantee, NOT strong causal instrumentation proof; SWEEP_SECONDS alone proves no suspension", flush=True)
    if case == "D":
        check("D activity CANCELLED", d["status"] == "CANCELLED")
    for action in ("accept", "reject"):
        # Real terminal state, both verbs, fresh key on EVERY request.
        denied(f"{case} {action} on {terminal}", respond(action), terminal=terminal)
        check(f"{case} {action} leaves participation, invitation view and events unchanged", snapshot(aid, b) == before)
def actor(role, password):
    account = f"r41_{role}_{RUN}"
    credentials = {"account": account, "password": password}
    ok(f"register {role}", req("POST", "/register", body={**credentials, "nickname": account}))
    token = ok(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    need(f"login token for {role}", isinstance(token, str) and bool(token.strip()))
    return token
def main():
    global BASE, OPENER, EXPECTED_TTL
    print(f"RUN {RUN} | future runtime checks; authoring validation was py_compile only", flush=True)
    try:
        BASE = isolated_root() + "/api/v1"
        need("operator acknowledges stable synchronized Shanghai wall clocks", os.environ.get("E1_STABLE_CLOCK") == "1",
             "require E1_STABLE_CLOCK=1; no server clock adjustments during the run")
        need("operator guarantees sweeps held and no other writers", os.environ.get("E1_NO_SWEEPS_OR_WRITERS") == "1",
             "require E1_NO_SWEEPS_OR_WRITERS=1; long SWEEP_SECONDS is not verified suspension")
        EXPECTED_TTL = int(os.environ.get("E1_EXPECT_TTL", "12"))
        need("short TTL fixture", EXPECTED_TTL in (8, 12))
        OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        reply = req("GET", "/health")
        ttl = ok("isolated health", reply).get("invite_ttl_seconds")
        need("server TTL matches E1_EXPECT_TTL", type(ttl) is int and ttl == EXPECTED_TTL)
        need("Shanghai server/client clock agreement", abs(now() - wall(reply[1]["serverTime"])) <= timedelta(seconds=1))
        password = os.environ.get("TEST_PASSWORD", "E1Regression42")
        actors = [actor(role, password) for role in ("org", "a", "b", "c")]
    except Unmet:
        pass
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        check("isolated setup", False, f"{type(exc).__name__}; require explicit safe BASE_URL, E1_ISOLATED=1 and valid health")
    else:
        for case in "ABCDEF":  # Equality runs only AFTER successful isolation/actor setup.
            try:
                scenario(case, *actors)
            except Unmet:
                continue  # Already reported as FAIL by need().
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                check(f"{case} invalid response shape or timestamp", False, type(exc).__name__)
    print("INFO/UNVERIFIED - deadline guard isolation and NC-13 causal instrumentation are unavailable; "
          "old untruncated-now equality is not proved", flush=True)
    if os.environ.get("E1_REQUIRE_DETERMINISTIC") == "1":
        check("optional stronger deterministic fixtures", False,
              "missing inconsistent deadline guard-isolation fixture and instrumented NC-13 attribution; "
              "operator acknowledgements are not that evidence")
    print(f"SUMMARY run={RUN} PASS={sum(RESULTS)} FAIL={RESULTS.count(False)}; "
          "HTTP checks only; CURRENT floored equality conditional on timestamp bracket and stable wall clock; "
          "stronger guard-isolation/causal instrumentation UNVERIFIED", flush=True)
    return 0 if RESULTS and all(RESULTS) else 1

if __name__ == "__main__":
    sys.exit(main())
