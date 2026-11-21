#!/usr/bin/env python3
"""前置：独立 campus-buddy 实例；创建时间戳账号。检查 create capacity 拒绝小数/超 int 且不截断，响应 activity_version 与详情 updated_at 同口径。"""
import json, os, sys, time, urllib.error, urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
STAMP = str(int(time.time()))
results = []

def check(name, ok, detail=""):
    results.append(bool(ok)); print(("PASS" if ok else "FAIL") + " - " + name + (" " + str(detail) if detail else ""), flush=True)

def req(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=8) as resp: status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e: status, raw = e.code, e.read()
    except Exception as e: return 0, {"network_error": str(e)}
    try: return status, json.loads(raw.decode())
    except Exception: return status, {"raw": raw.decode(errors="replace")}

def main():
    acc = "a2cap" + STAMP
    pwd = "CampusA2a123"
    s, d = req("POST", "/register", body={"account": acc, "password": pwd, "nickname": "cap"})
    check("register capacity account", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    s, d = req("POST", "/login", body={"account": acc, "password": pwd})
    token = ((d.get("data") or {}).get("token")) if isinstance(d, dict) else None
    check("login capacity account", s == 200 and bool(token), f"HTTP {s} {d}")

    base = {"title": "capacity-" + STAMP, "category": "其他", "location": "test",
            "deadline": "2099-03-01T10:00:00", "start_time": "2099-03-01T12:00:00", "end_time": "2099-03-01T14:00:00"}
    for bad in (3.5, 2147483648, -0.5):
        body = dict(base); body["title"] = f"capacity-bad-{bad}-{STAMP}"; body["capacity"] = bad
        s, d = req("POST", "/activities", token=token, body=body)
        fields = (d.get("data") or {}).get("fieldErrors") or {}
        check(f"capacity {bad} -> 400 fieldErrors.capacity", s == 400 and d.get("code") == "VALIDATION" and "capacity" in fields, f"HTTP {s} {d}")

    body = dict(base); body["title"] = "capacity-ok-" + STAMP; body["capacity"] = 3
    s, d = req("POST", "/activities", token=token, body=body)
    data = d.get("data") or {}
    aid = data.get("id")
    version = data.get("activity_version")
    check("create response adds activity_version", s == 200 and aid is not None and isinstance(version, str) and version, f"HTTP {s} {d}")
    s, detail = req("GET", f"/activities/{aid}", token=token)
    detail_data = detail.get("data") or {}
    updated = detail_data.get("updated_at")
    check("activity_version equals detail updated_at rendering", version is not None and updated is not None and str(version) == str(updated), f"detail HTTP {s} updated_at={updated!r} version={version!r}")
    check("old id field preserved", "id" in data, f"data={data}")
    print(f"SUMMARY {sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        print(f"FAIL - unexpected/network error: {e}", flush=True); sys.exit(1)
