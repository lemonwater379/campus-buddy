#!/usr/bin/env python3
"""前置：独立 campus-buddy 实例；创建时间戳账号。检查当前令牌登出与连续五次密码错误后的锁定；不重置共享数据。"""
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
    acc = "a2logout" + STAMP
    pwd = "CampusA2a123"
    s, d = req("POST", "/auth/register", body={"account": acc, "password": pwd, "nickname": "logout"})
    check("register test account", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    s, d = req("POST", "/auth/login", body={"account": acc, "password": pwd})
    token = ((d.get("data") or {}).get("token")) if isinstance(d, dict) else None
    check("login before logout", s == 200 and bool(token), f"HTTP {s} {d}")
    s, d = req("POST", "/auth/logout", token=token)
    check("logout revokes current token", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    s, d = req("GET", "/me", token=token)
    check("revoked token cannot read me", s == 400 and d.get("success") is False, f"HTTP {s} {d}")

    locked = "a2lock" + STAMP
    s, d = req("POST", "/auth/register", body={"account": locked, "password": pwd, "nickname": "lock"})
    check("register lockout account", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    for i in range(5):
        s, d = req("POST", "/auth/login", body={"account": locked, "password": "WrongA2aPass9"})
        check(f"wrong password attempt {i+1} rejected", s == 400 and d.get("success") is False, f"HTTP {s} {d}")
    s, d = req("POST", "/auth/login", body={"account": locked, "password": pwd})
    check("correct password denied during lockout", s == 400 and d.get("success") is False and "分钟" in str(d.get("message", "")), f"HTTP {s} {d}")
    print(f"SUMMARY {sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        print(f"FAIL - unexpected/network error: {e}", flush=True); sys.exit(1)
