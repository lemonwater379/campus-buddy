#!/usr/bin/env python3
"""REG-G05: pagination contract aligned to design §4 (recheck G05).

Spec: test-phase/campaign-20261120/fixes/consistency-recheck-20261121.md G05 —
design §4 fixes list pagination at default size 10, max 50, page shape
items/page/size/total. Before the fix, ApiSupport.pagination()/page() used
default 20, max 100, and emitted only "pageSize". After the fix the defaults
are 10/50 and the envelope carries BOTH "size" and "pageSize" with the same
value (frontend compatibility).

Preconditions: a running campus-buddy instance (BASE_URL, default
http://127.0.0.1:8080) with registration enabled. The clamp/default
assertions read the effective size echoed in the envelope, so they hold for
any dataset size; the item-count assertions are guarded on the reported
total so the script also passes on a nearly empty database.

Expect (on /activities, /my and /my/organized):
- No pagination params -> size == pageSize == 10, both keys present.
- pageSize=100 (the old "fetch all" habit) -> clamped to 50, size == 50.
- pageSize=999999 -> clamped to 50.
- Explicit pageSize=7 -> honoured as 7 in both keys.
- len(items) never exceeds the effective size.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
SUFFIX = datetime.now().strftime("%Y%m%d%H%M%S")
PASSWORD = "Dazi@2026!"

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token=None, body=None):
    hdrs = {"Content-Type": "application/json"}
    if token:
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
    acc = f"g05{tag}_{SUFFIX}"
    s, env = req("POST", "/register", body={"account": acc, "password": PASSWORD,
                                            "nickname": f"G05{tag}"})
    assert env.get("success"), f"register {acc} failed: {s} {env}"
    s, env = req("POST", "/login", body={"account": acc, "password": PASSWORD})
    assert env.get("success"), f"login {acc} failed: {s} {env}"
    return env["data"]["token"]


def assert_contract(label, path, token):
    s, env = req("GET", path, token=token)
    assert env.get("success"), f"{label} default request failed: {s} {env}"
    d = env["data"]
    check(f"{label} 默认请求信封含 size 与 pageSize 两键",
          "size" in d and "pageSize" in d, f"keys={sorted(d.keys())}")
    check(f"{label} 默认 size=10 且与 pageSize 同值",
          d.get("size") == 10 and d.get("pageSize") == 10,
          f"size={d.get('size')} pageSize={d.get('pageSize')}")
    check(f"{label} 默认 items 不超过 10 条",
          len(d.get("items", [])) <= 10, f"items={len(d.get('items', []))}")
    total = d.get("total")
    if isinstance(total, int) and total >= 10:
        check(f"{label} total>=10 时默认恰好返回 10 条",
              len(d.get("items", [])) == 10,
              f"items={len(d.get('items', []))} total={total}")

    sep = "&" if "?" in path else "?"
    s, env = req("GET", path + sep + "pageSize=100", token=token)
    d = env["data"]
    check(f"{label} pageSize=100 被钳制到 50（size 与 pageSize 同步）",
          d.get("pageSize") == 50 and d.get("size") == 50,
          f"size={d.get('size')} pageSize={d.get('pageSize')}")
    check(f"{label} 钳制后 items 不超过 50 条",
          len(d.get("items", [])) <= 50, f"items={len(d.get('items', []))}")

    s, env = req("GET", path + sep + "pageSize=999999", token=token)
    d = env["data"]
    check(f"{label} pageSize=999999 同样钳制到 50",
          d.get("pageSize") == 50 and d.get("size") == 50,
          f"size={d.get('size')} pageSize={d.get('pageSize')}")

    s, env = req("GET", path + sep + "pageSize=7", token=token)
    d = env["data"]
    check(f"{label} 显式 pageSize=7 被尊重且两键同值",
          d.get("pageSize") == 7 and d.get("size") == 7
          and len(d.get("items", [])) <= 7,
          f"size={d.get('size')} pageSize={d.get('pageSize')}")


def main():
    token = register_and_login("usr")
    assert_contract("GET /activities", "/activities", token)
    assert_contract("GET /my", "/my", token)
    assert_contract("GET /my/organized", "/my/organized", token)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
