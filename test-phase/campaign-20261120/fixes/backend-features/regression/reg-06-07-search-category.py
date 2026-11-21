#!/usr/bin/env python3
"""前置：独立 campus-buddy 实例；创建时间戳账号与活动。检查 category 封闭集/空与“全部”不筛/非法 400，以及 q 的 %、_、反斜线、escape 字符按字面匹配。"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

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

def titles(d):
    data = d.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    return [x.get("title") for x in (items or [])]

def main():
    acc = "a2search" + STAMP
    pwd = "CampusA2a123"
    s, d = req("POST", "/register", body={"account": acc, "password": pwd, "nickname": "search"})
    check("register search account", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    s, d = req("POST", "/login", body={"account": acc, "password": pwd})
    token = ((d.get("data") or {}).get("token")) if isinstance(d, dict) else None
    check("login search account", s == 200 and bool(token), f"HTTP {s} {d}")

    base = {"category": "其他", "capacity": 4, "location": "test",
            "deadline": "2099-02-01T10:00:00", "start_time": "2099-02-01T12:00:00", "end_time": "2099-02-01T14:00:00"}
    special = [
        "a2a-normal-" + STAMP,
        "a2a-100%off-" + STAMP,
        "a2a-under_score-" + STAMP,
        "a2a-back\\slash-" + STAMP,
        "a2a-bang!mark-" + STAMP,
    ]
    ids = []
    for title in special:
        body = dict(base); body["title"] = title
        s, d = req("POST", "/activities", token=token, body=body)
        ok = s == 200 and d.get("success") is True
        check("create activity " + repr(title), ok, f"HTTP {s} {d}")
        if ok: ids.append(((d.get("data") or {}).get("id")))

    s, d = req("GET", "/activities?category=" + urllib.parse.quote("羽毛球"))
    check("valid category accepted", s == 200 and d.get("success") is True, f"HTTP {s} {d}")
    s, d = req("GET", "/activities?category=")
    check("empty category does not filter", s == 200 and all(t in titles(d) for t in special), f"HTTP {s} {titles(d)}")
    s, d = req("GET", "/activities?category=" + urllib.parse.quote("全部"))
    check("全部 category does not filter", s == 200 and all(t in titles(d) for t in special), f"HTTP {s} {titles(d)}")
    s, d = req("GET", "/activities?category=" + urllib.parse.quote("篮球"))
    fields = (d.get("data") or {}).get("fieldErrors") or {}
    check("invalid category -> 400 VALIDATION fieldErrors.category", s == 400 and d.get("code") == "VALIDATION" and "category" in fields, f"HTTP {s} {d}")

    cases = [
        ("100%off-" + STAMP, "a2a-normal-" + STAMP, "a2a-100%off-" + STAMP),
        ("under_score-" + STAMP, "a2a-normal-" + STAMP, "a2a-under_score-" + STAMP),
        ("back\\slash-" + STAMP, "a2a-normal-" + STAMP, "a2a-back\\slash-" + STAMP),
        ("bang!mark-" + STAMP, "a2a-normal-" + STAMP, "a2a-bang!mark-" + STAMP),
    ]
    for query, absent, present in cases:
        s, d = req("GET", "/activities?pageSize=100&q=" + urllib.parse.quote(query))
        ts = titles(d)
        check("q literal " + repr(query) + " matches only itself", s == 200 and present in ts and absent not in ts, f"HTTP {s} hits={[t for t in ts if t.startswith('a2a-')][:20]}")
    print(f"SUMMARY {sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        print(f"FAIL - unexpected/network error: {e}", flush=True); sys.exit(1)
