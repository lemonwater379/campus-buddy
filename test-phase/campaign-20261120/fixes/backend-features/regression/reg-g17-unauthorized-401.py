#!/usr/bin/env python3
"""REG-G17: unauthenticated requests must return HTTP 401 (consistency recheck G17).

Spec: test-phase/campaign-20261120/fixes/consistency-recheck-20261121.md G17 —
design requires HTTP 401 for unauthenticated calls; the frontend re-login
recovery branch (recoverMembershipFailure) only triggers on status 401.
Before the fix, ApiV1Controller.require() threw IllegalStateException("未登录"),
which errorResponse mapped to 400/ERROR, so a genuinely expired session never
entered the re-login flow. After the fix, require() throws a dedicated
UnauthorizedException mapped to 401 with code "UNAUTHORIZED" and message
"未登录" — the same shape the upload endpoint already used.

Preconditions: a running campus-buddy instance (BASE_URL, default
http://127.0.0.1:8080) with registration enabled. No demo reset is performed;
all accounts/activities are created by this script with timestamp suffixes.

Expect:
- POST signup with no Authorization header -> 401, code UNAUTHORIZED.
- POST signup with a forged Bearer token -> 401, code UNAUTHORIZED.
- GET /my with no Authorization header -> 401, code UNAUTHORIZED.
- The same signup with a real login token -> 200 (no collateral damage).
- Guard rails that must NOT change: wrong-password login still 400;
  admin endpoints without a token still 403/FORBIDDEN (requireAdmin口径).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
SUFFIX = datetime.now().strftime("%Y%m%d%H%M%S")
PASSWORD = "Dazi@2026!"

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token="__ABSENT__", body=None):
    """token: "__ABSENT__" sends no Authorization header; None also absent;
    any other string is sent as Bearer <token>."""
    hdrs = {"Content-Type": "application/json"}
    if token not in ("__ABSENT__", None):
        hdrs["Authorization"] = "Bearer " + token
    r = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=hdrs)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"success": False, "code": "HTTP_ERROR", "data": None}
    except Exception as e:
        return 0, {"success": False, "code": "NETWORK_ERROR", "message": str(e), "data": None}


def register_and_login(tag):
    acc = f"g17{tag}_{SUFFIX}"
    s, env = req("POST", "/register", body={"account": acc, "password": PASSWORD,
                                            "nickname": f"G17{tag}"})
    assert env.get("success"), f"register {acc} failed: {s} {env}"
    s, env = req("POST", "/login", body={"account": acc, "password": PASSWORD})
    assert env.get("success"), f"login {acc} failed: {s} {env}"
    return env["data"]["token"]


def main():
    org = register_and_login("org")
    now = datetime.now()
    fmt = "%Y-%m-%dT%H:%M:%S"
    s, env = req("POST", "/activities", token=org, body={
        "title": f"G17会话校验_{SUFFIX}", "category": "其他",
        "description": "G17 回归", "conditions": "", "location": "线上",
        "capacity": 4,
        "deadline": (now + timedelta(days=1)).strftime(fmt),
        "start_time": (now + timedelta(days=2)).strftime(fmt),
        "end_time": (now + timedelta(days=2, hours=2)).strftime(fmt)})
    assert env.get("success"), f"create activity failed: {s} {env}"
    aid = env["data"]["id"]

    # 1) No token at all -> 401 / UNAUTHORIZED (was 400 / ERROR before the fix).
    s, env = req("POST", f"/activities/{aid}/signup", body={})
    check("无 token 报名 -> HTTP 401", s == 401, f"status={s} env={env}")
    check("无 token 报名 -> code=UNAUTHORIZED",
          env.get("code") == "UNAUTHORIZED" and env.get("success") is False,
          f"code={env.get('code')}")

    # 2) Forged token -> 401 / UNAUTHORIZED.
    s, env = req("POST", f"/activities/{aid}/signup",
                 token="forged-token-" + SUFFIX, body={})
    check("伪造 token 报名 -> HTTP 401", s == 401, f"status={s}")
    check("伪造 token 报名 -> code=UNAUTHORIZED",
          env.get("code") == "UNAUTHORIZED", f"code={env.get('code')}")

    # 3) Another require() endpoint without a token -> 401 as well.
    s, env = req("GET", "/my")
    check("无 token GET /my -> HTTP 401 + UNAUTHORIZED",
          s == 401 and env.get("code") == "UNAUTHORIZED",
          f"status={s} code={env.get('code')}")

    # 4) Normal logged-in signup still works (200).
    user = register_and_login("usr")
    s, env = req("POST", f"/activities/{aid}/signup", token=user, body={})
    check("正常登录后报名 -> HTTP 200", s == 200 and env.get("success") is True,
          f"status={s} env={env}")

    # 5) Guard rail: wrong-password login keeps its 400口径 (not 401).
    s, env = req("POST", "/login",
                 body={"account": f"g17org_{SUFFIX}", "password": "WrongPass1!"})
    check("密码错误登录 -> 仍为 HTTP 400", s == 400, f"status={s} code={env.get('code')}")

    # 6) Guard rail: admin endpoint without token keeps 403/FORBIDDEN口径.
    s, env = req("GET", "/admin/users?page=1&pageSize=10")
    check("无 token 管理端点 -> 仍为 HTTP 403 + FORBIDDEN",
          s == 403 and env.get("code") == "FORBIDDEN",
          f"status={s} code={env.get('code')}")

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
