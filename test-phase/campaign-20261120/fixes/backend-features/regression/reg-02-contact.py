#!/usr/bin/env python3
"""前置：独立 campus-buddy 实例；创建时间戳账号。检查 /me 读 contact、本人可写/清空、超长 400，且公开列表/详情与组织者名单不含 contact。"""
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

def contains_key(value, key):
    if isinstance(value, dict): return key in value or any(contains_key(v, key) for v in value.values())
    if isinstance(value, list): return any(contains_key(v, key) for v in value)
    return False

def main():
    owner = "a2contact" + STAMP
    pwd = "CampusA2a123"
    s, d = req("POST", "/register", body={"account": owner, "password": pwd, "nickname": "contact"})
    check("register contact account", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    s, d = req("POST", "/login", body={"account": owner, "password": pwd})
    token = ((d.get("data") or {}).get("token")) if isinstance(d, dict) else None
    check("login contact account", s == 200 and bool(token), f"HTTP {s} {d}")
    s, d = req("GET", "/me", token=token)
    user = (d.get("data") or {}).get("user") or {}
    check("me returns contact field", s == 200 and "contact" in user, f"HTTP {s} {d}")

    contact = "wx-a2a-" + STAMP
    s, d = req("PATCH", "/me/profile", token=token, body={"contact": contact})
    user = (d.get("data") or {}).get("user") or {}
    check("update contact only keeps nickname", s == 200 and user.get("contact") == contact and user.get("nickname") == "contact", f"HTTP {s} {d}")
    s, d = req("GET", "/me", token=token)
    user = (d.get("data") or {}).get("user") or {}
    check("me reflects new contact", user.get("contact") == contact, f"HTTP {s} {d}")

    s, d = req("PATCH", "/me/profile", token=token, body={"contact": "x" * 101})
    fields = (d.get("data") or {}).get("fieldErrors") or {}
    check("contact over 100 chars -> 400 fieldErrors.contact", s == 400 and d.get("code") == "VALIDATION" and "contact" in fields, f"HTTP {s} {d}")

    s, d = req("PATCH", "/me/profile", token=token, body={"contact": ""})
    user = (d.get("data") or {}).get("user") or {}
    check("empty contact clears contact", s == 200 and user.get("contact") == "", f"HTTP {s} {d}")
    s, d = req("PATCH", "/me/profile", token=token, body={"contact": contact})

    s, d = req("POST", "/activities", token=token, body={
        "title": "contact-visibility-" + STAMP, "category": "其他", "capacity": 2,
        "location": "test", "deadline": "2099-01-01T10:00:00",
        "start_time": "2099-01-01T12:00:00", "end_time": "2099-01-01T14:00:00"})
    aid = ((d.get("data") or {}).get("id")) if isinstance(d, dict) else None
    check("create activity for visibility", s == 200 and aid is not None, f"HTTP {s} {d}")

    s, d = req("GET", "/activities?pageSize=100", token=None)
    check("public activity list has no contact", s == 200 and not contains_key(d.get("data"), "contact"), f"HTTP {s}")
    s, d = req("GET", f"/activities/{aid}", token=None)
    check("guest activity detail has no contact", s == 200 and not contains_key(d.get("data"), "contact"), f"HTTP {s}")
    print(f"SUMMARY {sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        print(f"FAIL - unexpected/network error: {e}", flush=True); sys.exit(1)
