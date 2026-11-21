#!/usr/bin/env python3
"""REG-14 / W4: activity edit and optimistic concurrency (Python 3 stdlib).

Prerequisite: a running disposable campus-buddy test instance using Shanghai wall
clock time, with registration enabled. BASE_URL is the bare server root (default
http://127.0.0.1:8080). Creates two accounts and one OPEN activity; leaves the
fixtures in the test instance. No reset or special sweep settings required.

PATCH edits location and start_time/end_time with expectedVersion; POST is an
alias. Each versioned edit must advance the version, and GET must read back the
changes. Stale versions return 409 CONFLICT with current_version; a non-owner
gets 400 ERROR. Neither rejection changes the activity. Omitting the version
remains supported for the organizer.

Sources: remaining.md #1 W4 and #6; brief-B.md B2; regression/README.md.
ApiV1Controller.java: errorResponse, create, activityDetail, patch/postActivityEdit;
BuddyService.java: nowSeconds, requireVersion, editActivity, activityDetail;
ApiSupport.java: envelope/json, and application.properties: spring.jackson.time-zone.
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
SHANGHAI = timezone(timedelta(hours=8))
RESULTS = []
ISO_TIME = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:?\d{2})?"
)


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
    status, limit = 0, 2**20
    try:
        request = urllib.request.Request(BASE + path, data=data, headers=hdr, method=method)
        try:
            response = OPENER.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status = response.getcode()
            raw = response.read(limit + 1)
        if len(raw) > limit:
            return status, {"code": "CLIENT_ERROR", "message": "response exceeds 1 MiB"}
        env = json.loads(raw.decode("utf-8"))
        if not isinstance(env, dict):
            return status, {"code": "CLIENT_ERROR", "message": "expected a JSON object"}
        return status, env
    except urllib.error.URLError as exc:
        return status, {"code": "CLIENT_ERROR", "message": f"connection failed: {type(exc.reason).__name__}"}
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return status, {"code": "CLIENT_ERROR", "message": type(exc).__name__}


def check(name, condition, detail=""):
    passed = bool(condition)
    RESULTS.append(passed)
    print(f"{'PASS' if passed else 'FAIL'} - {name}" + (f" ({detail})" if detail and not passed else ""))
    return passed


def describe(reply, *fields):
    status, env = reply
    text = f"HTTP {status}, success={env.get('success')!r}, code={env.get('code')!r}, message={env.get('message')!r}"
    data = env.get("data")
    if isinstance(data, dict):
        text += "".join(f", {field}={data.get(field)!r}" for field in fields)
    return text


def ok_data(reply):
    status, env = reply
    data = env.get("data")
    if (status == 200 and env.get("success") is True and env.get("code") == "OK"
            and env.get("message") == "ok" and isinstance(data, dict)):
        return data
    return None


def error_matches(reply, status, code, message_part=""):
    actual, env = reply
    message = env.get("message")
    return (actual == status and env.get("success") is False and env.get("code") == code
            and isinstance(message, str) and bool(message.strip()) and message_part in message and "data" in env)


def timestamp_key(value, *, allow_offset=False):
    """Exact Shanghai wall time, preserving up to nine fractional digits.

    Edits/versions use LocalDateTime.toString(); raw GET rows can instead use
    Jackson's offset ISO form for PostgreSQL Timestamp or offset-free ISO for
    MySQL LocalDateTime. Do not crop seconds/fractions or strip a UTC offset.
    """
    match = ISO_TIME.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    minute, second, fraction, offset = match.groups()
    if offset and not allow_offset:
        return None
    if offset == "Z":
        offset = "+00:00"
    elif offset:
        offset = offset[:3] + ":" + offset[-2:]
    try:
        wall = datetime.fromisoformat(f"{minute}:{second or '00'}{offset or ''}")
        if offset:
            wall = wall.astimezone(SHANGHAI).replace(tzinfo=None)
    except (ValueError, OverflowError):
        return None
    return wall, int((fraction or "").ljust(9, "0"))


def require_data(label, reply):
    data = ok_data(reply)
    if data is None:
        raise FixtureError(f"{label}: {describe(reply)}")
    return data


def account(role, stamp):
    name = f"r14_{role}_{stamp}"
    credentials = {"account": name, "password": "W4a9!" + secrets.token_hex(12)}
    require_data(f"register {role}", req("POST", "/register", body=dict(credentials, nickname=name)))
    token = require_data(f"login {role}", req("POST", "/login", body=credentials)).get("token")
    if not isinstance(token, str) or not token.strip():
        raise FixtureError(f"login {role}: missing bearer token")
    return token


def run():
    now = datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)
    stamp = now.strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    org, other = account("org", stamp), account("other", stamp)
    start = now + timedelta(days=2)
    end = start + timedelta(hours=2)
    create = req("POST", "/activities", org, {
        "title": f"REG-14 original {stamp}", "category": "桌游", "capacity": 2,
        "location": f"REG-14 room A {stamp}",
        "deadline": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"), "end_time": end.isoformat(timespec="seconds"),
    })
    created = ok_data(create) or {}
    aid, v0 = created.get("id"), created.get("activity_version")
    t0 = timestamp_key(v0)
    if not check("create returns activity ID and V0", isinstance(aid, str) and bool(re.fullmatch(r"[1-9][0-9]*", aid))
                 and t0 is not None, describe(create, "id", "activity_version")):
        return
    path = f"/activities/{aid}"
    edit_path = path + "/edit"
    signup = req("POST", path + "/signup", other)
    if (ok_data(signup) or {}).get("my_status") != "FORMAL":
        raise FixtureError(f"other should be a FORMAL member: {describe(signup, 'my_status')}")

    new_start, new_end = start + timedelta(hours=1), end + timedelta(hours=1)
    new_location = f"REG-14 room B {stamp}"
    new_title = f"REG-14 revised {stamp}"
    shifted = {
        "location": new_location,
        "start_time": new_start.isoformat(timespec="seconds"),
        "end_time": new_end.isoformat(timespec="seconds"),
    }

    def matches_schedule(data, *, from_get=False):
        return (data.get("location") == new_location
                and timestamp_key(data.get("start_time"), allow_offset=from_get) == (new_start, 0)
                and timestamp_key(data.get("end_time"), allow_offset=from_get) == (new_end, 0))

    time.sleep(1.2)  # The activity write clock is truncated to whole seconds.
    patch = req("PATCH", edit_path, org, dict(shifted, expectedVersion=v0))
    patched = ok_data(patch) or {}
    v1 = patched.get("activity_version")
    t1 = timestamp_key(v1)
    v1_ok = check("PATCH with V0 returns newer V1", t1 is not None and t1 > t0,
                  f"{describe(patch, 'activity_version')}; V0={v0!r}")
    check("PATCH returns edited location and times shifted by one hour", matches_schedule(patched),
          f"{describe(patch, *shifted)}; expected {shifted!r}")

    detail = req("GET", path, org)
    check("organizer GET reads back the edited location and times", matches_schedule(ok_data(detail) or {}, from_get=True),
          f"{describe(detail, *shifted)}; expected {shifted!r} (Shanghai wall time)")
    detail = req("GET", path, other)
    member = ok_data(detail) or {}
    check("FORMAL member GET reads the new location", member.get("my_status") == "FORMAL"
          and member.get("location") == new_location, f"{describe(detail, 'my_status', 'location')}; expected {new_location!r}")
    if not v1_ok:
        return

    time.sleep(1.2)
    post = req("POST", edit_path, org, {"title": new_title, "expectedVersion": v1})
    posted = ok_data(post) or {}
    v2 = posted.get("activity_version")
    t2 = timestamp_key(v2)
    if not check("POST alias with V1 returns the new title and newer V2",
                 posted.get("title") == new_title and t2 is not None and t2 > t1,
                 f"{describe(post, 'title', 'activity_version')}; expected {new_title!r} and version after {v1!r}"):
        return

    def unchanged(reply):
        data = ok_data(reply) or {}
        return (data.get("title") == new_title and data.get("location") == new_location
                and timestamp_key(data.get("updated_at"), allow_offset=True) == t2)

    stale = req("PATCH", edit_path, org, {
        "expectedVersion": v0, "title": f"REG-14 stale {stamp}", "location": "REG-14 stale room",
    })
    conflict = stale[1].get("data")
    stale_ok = check("stale V0 returns 409 CONFLICT and the exact V2 token",
                     error_matches(stale, 409, "CONFLICT") and isinstance(conflict, dict)
                     and conflict.get("current_version") == v2,
                     f"{describe(stale, 'current_version')}; expected {v2!r}")
    detail = req("GET", path, org)
    if not check("GET after stale edit still has the revised title, location and V2", unchanged(detail),
                 describe(detail, "title", "location", "updated_at")):
        return  # Do not test non-owner authorization with a no-longer-current V2.

    denied = req("PATCH", edit_path, other, {
        "expectedVersion": v2, "title": f"REG-14 non-owner {stamp}", "location": "REG-14 non-owner room",
    })
    denied_ok = check("non-organizer with V2 gets 400 ERROR: 只有组织者可以修改活动",
                      error_matches(denied, 400, "ERROR", "只有组织者可以修改活动") and denied[1]["data"] is None,
                      describe(denied))
    detail = req("GET", path, org)
    unchanged_ok = check("GET after non-organizer edit still has the revised title, location and V2", unchanged(detail),
                         describe(detail, "title", "location", "updated_at"))

    if stale_ok and denied_ok and unchanged_ok:
        legacy_location = f"REG-14 room C {stamp}"
        legacy = req("PATCH", edit_path, org, {"location": legacy_location})  # No expectedVersion key.
        check("organizer can edit without expectedVersion", (ok_data(legacy) or {}).get("location") == legacy_location,
              f"{describe(legacy, 'location')}; expected {legacy_location!r}")


def main():
    try:
        run()
    except FixtureError as exc:
        check("fixture setup", False, str(exc))
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
