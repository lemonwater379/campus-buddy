#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鲁棒性回归套件（批次1 · 2026-11-18）。

跑法：
    BASE_URL=http://127.0.0.1:8080 python3 tests/test_robustness.py   # A 版 PostgreSQL
    BASE_URL=http://127.0.0.1:8081 python3 tests/test_robustness.py   # B 版 MySQL

前提：后端以测试参数运行（INVITE_TTL=10、SWEEP_SECONDS=2）；脚本开头调用
/api/v1/demo/reset（仅本地演示库），然后按相对当前时间生成活动时间，不写死日期。
涉及递补邀请的用例要求当前处于白天时段（8:00–22:00，2026-11-08 已批准补丁）。

说明：标注 [待修] 的用例对应 audit-findings.md 中静态定位、尚未修复的候选缺陷；
在未打补丁的 jar 上这些用例应 FAIL，修复并重新打包后应全部转绿。
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE_ROOT = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/")
BASE = BASE_ROOT + "/api/v1"
PWD = "Dazi@2026!"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), str(detail)))
    print(("PASS" if cond else "FAIL"), "-", name, str(detail)[:400])


def req(method, path, token=None, body=None, raw=None, content_type="application/json",
        timeout=30):
    hdrs = {"Content-Type": content_type}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    if raw is not None:
        data = raw.encode() if isinstance(raw, str) else raw
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
    else:
        data = None
    r = urllib.request.Request(BASE + path, method=method, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            status, text = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            text = ""
    except Exception as e:
        return 0, {"success": False, "_error": str(e)}
    try:
        env = json.loads(text)
        if not isinstance(env, dict):
            env = {"_json": env, "success": None}
    except Exception:
        env = {"_raw": text, "success": None}
    return status, env


def data_of(env):
    return env.get("data") if isinstance(env.get("data"), dict) else {}


def is_4xx(s):
    return 400 <= s < 500


def at(seconds=0, days=0):
    return (datetime.now() + timedelta(seconds=seconds, days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def login(acc, pwd=PWD):
    s, env = req("POST", "/login", body={"account": acc, "password": pwd})
    return (data_of(env) or {}).get("token") if env.get("success") else None


def relogin(acc, pwd=PWD):
    tok = login(acc, pwd)
    if not tok:
        req("POST", "/register", body={"account": acc, "password": pwd})
        tok = login(acc, pwd)
    return tok


def reset():
    tok = login("organizer")
    if not tok:
        req("POST", "/register",
            body={"account": "roboot", "password": "12345678", "nickname": "回归"})
        tok = login("roboot", "12345678")
    s, env = req("POST", "/demo/reset", token=tok)
    assert env.get("success"), "demo/reset failed: %s %s" % (s, env)
    return login("organizer")


def make(org, title, cap=4, deadline=None, start=None, end=None):
    s, env = req("POST", "/activities", token=org, body={
        "title": title, "category": "其他", "description": "回归",
        "conditions": "", "location": "线上", "capacity": cap,
        "deadline": deadline or at(days=1),
        "start_time": start or at(days=2),
        "end_time": end or at(days=2, seconds=7200)})
    assert env.get("success"), "create failed: %s %s" % (s, env)
    return data_of(env)["id"]


def detail(tok, aid):
    s, env = req("GET", "/activities/%s" % aid, token=tok)
    return data_of(env)


def my(tok):
    s, env = req("GET", "/my?pageSize=100", token=tok)
    return data_of(env).get("items", [])


def part(tok, aid):
    for p in my(tok):
        if str(p.get("activity_id")) == str(aid):
            return p
    return None


def signup(tok, aid, confirm=False):
    return req("POST", "/activities/%s/signup" % aid, token=tok,
               body={"confirmConflict": True} if confirm else {})


def withdraw(tok, pid):
    return req("POST", "/participations/%s/withdraw" % pid, token=tok, body={})


def abandon(tok, pid):
    return req("POST", "/participations/%s/abandon" % pid, token=tok, body={})


def accept(tok, iid, confirm=False):
    return req("POST", "/invitations/%s/accept" % iid, token=tok,
               body={"confirmConflict": True} if confirm else {})


def reject(tok, iid):
    return req("POST", "/invitations/%s/reject" % iid, token=tok, body={})


def notifs(tok):
    s, env = req("GET", "/notifications?pageSize=100", token=tok)
    d = data_of(env)
    return d.get("items", []) if isinstance(d.get("items"), list) else []


def wait_part(tok, aid, statuses, timeout=8):
    if isinstance(statuses, str):
        statuses = {statuses}
    else:
        statuses = set(statuses)
    end = time.time() + timeout
    while time.time() < end:
        p = part(tok, aid)
        if p and p.get("status") in statuses:
            return p
        time.sleep(0.25)
    return part(tok, aid)


def wait_invite(tok, aid, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        p = part(tok, aid)
        if p and p.get("invitation_id"):
            return p
        time.sleep(0.25)
    return part(tok, aid)


def wait_notif(tok, needle, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        for n in notifs(tok):
            if needle in str(n.get("content") or n.get("message") or ""):
                return True
        time.sleep(0.25)
    return False


def notif_ids(tok):
    return {str(n.get("id")) for n in notifs(tok)}


def new_notif(tok, needle, before, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        for n in notifs(tok):
            if str(n.get("id")) not in before and needle in str(n.get("content") or ""):
                return n
        time.sleep(0.25)
    return None


def count_activities():
    s, env = req("GET", "/health")
    return data_of(env).get("activities")


# ---- DB 辅助：只用于精确构造“已过截止”的活动（结构不动） ----

def db_exec(sql):
    if ":8081" in BASE_ROOT:
        mysql = os.path.expanduser("~/workspace/.portable/mysql-8.0.28/bin/mysql")
        pw_path = "/tmp/cb_app_pw.txt"
        if os.path.exists(pw_path):
            with open(pw_path, encoding="utf-8") as f:
                env = dict(os.environ, MYSQL_PWD=f.read().strip())
            cmd = [mysql, "-h", "127.0.0.1", "-P", "3306", "-u", "cb_app",
                   "--default-character-set=utf8mb4", "-N", "-B", "campus_buddy", "-e", sql]
        else:
            env = dict(os.environ)
            cmd = [mysql, "-S", os.path.expanduser("~/workspace/.portable/mysql-data/mysql.sock"),
                   "-u", "root", "--default-character-set=utf8mb4", "-N", "-B",
                   "campus_buddy", "-e", sql]
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    else:
        env = dict(os.environ,
                   LD_LIBRARY_PATH="/tmp/pgsql/usr/lib/x86_64-linux-gnu:"
                                   "/tmp/pgsql/usr/lib/postgresql/16/lib")
        cmd = ["/tmp/pgsql/usr/lib/postgresql/16/bin/psql", "-h", "/tmp/pgrun",
               "-p", "5433", "-U", "postgres", "-d", "campus_buddy",
               "-t", "-A", "-F", "|", "-c", sql]
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def force_deadline_past(aid):
    if ":8081" in BASE_ROOT:
        sql = ("UPDATE activity SET deadline=DATE_SUB(NOW(), INTERVAL 1 SECOND), "
               "status='OPEN' WHERE id=%s" % aid)
    else:
        sql = ("UPDATE activity SET deadline=now() - INTERVAL '1 second', "
               "status='OPEN' WHERE id=%s" % aid)
    return db_exec(sql)


def invariants():
    now_expr = "NOW()" if ":8081" in BASE_ROOT else "now()"
    sql = (
        "SELECT "
        "(SELECT count(*) FROM activity a WHERE "
        " (SELECT count(*) FROM participation p WHERE p.activity_id=a.id AND p.status='FORMAL')"
        " + (SELECT count(*) FROM invitation i JOIN participation p ON p.id=i.participation_id"
        "    WHERE p.activity_id=a.id AND i.status='PENDING' AND i.expires_at > %s) > a.capacity),"
        "(SELECT count(*) FROM (SELECT activity_id,user_id FROM participation"
        " GROUP BY activity_id,user_id HAVING count(*)>1) d),"
        "(SELECT count(*) FROM participation p LEFT JOIN activity a ON a.id=p.activity_id"
        " LEFT JOIN app_user u ON u.id=p.user_id WHERE a.id IS NULL OR u.id IS NULL),"
        "(SELECT count(*) FROM invitation i LEFT JOIN participation p ON p.id=i.participation_id WHERE p.id IS NULL),"
        "(SELECT count(*) FROM notification n LEFT JOIN app_user u ON u.id=n.user_id WHERE u.id IS NULL)"
        % now_expr)
    rc, out, err = db_exec(sql)
    if rc != 0 or not out:
        return None
    try:
        return [int(x) for x in out.splitlines()[0].replace("\t", "|").split("|")]
    except Exception:
        return None


def main():
    org = reset()
    t1, t2, t3, t4 = (login("demo0%d" % i) for i in (1, 2, 3, 4))
    check("前置：reset 与种子账号登录", bool(org and t1 and t2 and t3 and t4), "")

    # ============ A1 名额边界 / 预留 ============
    a = make(org, "回归-名额", cap=2)
    signup(t1, a, True)
    signup(t2, a, True)
    s3, e3 = signup(t3, a, True)
    check("A1 容量 2：第 3 人候补第 1",
          data_of(e3).get("my_status") == "WAITING" and data_of(e3).get("my_rank") == 1,
          str(data_of(e3))[:160])
    p1 = part(t1, a)
    withdraw(t1, p1["id"])
    p3 = wait_invite(t3, a)
    d = detail(org, a)
    check("A1 退出 1 人 → 候补第 1 收邀请，正式 1 + 预留 1、不多发",
          p3 and p3.get("status") == "INVITED" and d.get("formal") == 1
          and d.get("reserved") == 1, "part=%s detail=%s" % (p3, d))
    s4, e4 = signup(t4, a, True)
    d = detail(org, a)
    check("A1 预留期间新报名只能 WAITING",
          data_of(e4).get("my_status") == "WAITING" and d.get("reserved") == 1,
          "r4=%s reserved=%s" % (str(data_of(e4))[:120], d.get("reserved")))

    # ============ A2 截止边界 ============
    a2 = make(org, "回归-截止前", cap=2, deadline=at(seconds=10),
              start=at(days=1), end=at(days=1, seconds=7200))
    s, env = signup(t1, a2, confirm=True)
    check("A2 截止前可报名",
          s == 200 and data_of(env).get("my_status") == "FORMAL",
          "status=%s" % s)
    a2b = make(org, "回归-过截止", cap=2)
    forced = False
    s, env = 0, {}
    for _ in range(3):
        rc, _, _ = force_deadline_past(a2b)
        if rc != 0:
            break
        s, env = signup(t2, a2b, confirm=True)
        if env.get("code") == "SIGNUP_DEADLINE_PASSED":
            forced = True
            break
        time.sleep(0.1)
    check("A2 过截止报名 → 4xx code=SIGNUP_DEADLINE_PASSED",
          forced and is_4xx(s) and env.get("code") == "SIGNUP_DEADLINE_PASSED",
          "status=%s code=%s env=%s" % (s, env.get("code"), str(env)[:160]))

    # ============ A3 候补顺序 ============
    a3 = make(org, "回归-候补顺序", cap=1)
    signup(t1, a3, True)
    signup(t2, a3, True)
    signup(t3, a3, True)
    d2, d3 = detail(t2, a3), detail(t3, a3)
    check("A3 候补 rank 1/2 按入队顺序",
          d2.get("my_rank") == 1 and d3.get("my_rank") == 2,
          "r2=%s r3=%s" % (d2.get("my_rank"), d3.get("my_rank")))
    abandon(t2, part(t2, a3)["id"])
    check("A3 队首放弃后第 2 名变第 1",
          detail(t3, a3).get("my_rank") == 1,
          "rank=%s" % detail(t3, a3).get("my_rank"))

    # ============ A4/A5 邀请应答与接口分工 ============
    a4 = make(org, "回归-接受", cap=1)
    signup(t1, a4, True)
    signup(t2, a4, True)
    t3b = relogin("robust03")
    signup(t3b, a4, True)
    withdraw(t1, part(t1, a4)["id"])
    inv = wait_invite(t2, a4)
    if inv:
        s1, _ = accept(t2, inv["invitation_id"], True)
        s2, _ = accept(t2, inv["invitation_id"], True)
        s3, _ = reject(t2, inv["invitation_id"])
        check("A4 接受→FORMAL；重复 accept/reject 不重复处理",
              s1 == 200 and part(t2, a4).get("status") == "FORMAL"
              and s2 == 200 and s3 == 200,
              "accept=%s re=%s reject=%s" % (s1, s2, s3))
    else:
        check("A4 接受→FORMAL；重复应答不重复处理 [待修/环境]", False, "未拿到邀请")

    a5 = make(org, "回归-分工", cap=1)
    signup(t1, a5, True)
    signup(t2, a5, True)
    pw = part(t2, a5)
    sw, _ = withdraw(t2, pw["id"])
    check("A5 WAITING 用 withdraw → 4xx 且状态不变",
          is_4xx(sw) and part(t2, a5).get("status") == "WAITING",
          "status=%s" % sw)
    sa, _ = abandon(t2, pw["id"])
    check("A5 WAITING 用 abandon → WITHDRAWN",
          sa == 200 and part(t2, a5).get("status") == "WITHDRAWN",
          "status=%s" % sa)
    pf = part(t1, a5)
    sf, _ = abandon(t1, pf["id"])
    check("A5 FORMAL 用 abandon → 4xx",
          is_4xx(sf) and part(t1, a5).get("status") == "FORMAL",
          "status=%s" % sf)

    # 超时 → EXPIRED + 顺延；过期后 accept 被拒 [待修]
    a4t = make(org, "回归-超时", cap=1)
    signup(t1, a4t, True)
    signup(t2, a4t, True)
    signup(t3b, a4t, True)
    withdraw(t1, part(t1, a4t)["id"])
    invt = wait_invite(t2, a4t)
    if invt:
        print("  等待邀请超时约 14 秒……")
        time.sleep(14)
        p2t = part(t2, a4t)
        nxt = wait_invite(t3b, a4t, timeout=6)
        check("A4 超时→EXPIRED 并顺延下一位",
              p2t.get("status") in ("EXPIRED", "WITHDRAWN")
              and nxt and nxt.get("status") == "INVITED",
              "expired=%s next=%s" % (p2t.get("status"), (nxt or {}).get("status")))
        s, env = accept(t2, invt["invitation_id"])
        msg = str(env.get("message") or env.get("data"))
        check("A4 [待修] 过期后 accept 被拒（4xx + 过期文案）",
              is_4xx(s) and "过期" in msg,
              "status=%s msg=%s env=%s" % (s, msg[:80], str(env)[:160]))
    else:
        check("A4 超时→EXPIRED 并顺延 [待修/环境]", False, "未拿到邀请")

    # ============ A6 错误码 ============
    ac = make(org, "回归-已取消")
    req("POST", "/activities/%s/cancel" % ac, token=org, body={})
    s, env = signup(t1, ac)
    check("A6 已取消报名 code=ACTIVITY_CANCELLED",
          is_4xx(s) and env.get("code") == "ACTIVITY_CANCELLED", "code=%s" % env.get("code"))
    ar = make(org, "回归-READY", deadline=at(seconds=1), start=at(seconds=30),
              end=at(seconds=32))
    end = time.time() + 8
    while time.time() < end and detail(org, ar).get("status") != "READY":
        time.sleep(0.25)
    s, env = signup(t1, ar)
    check("A6 非 OPEN 报名 code=ACTIVITY_NOT_OPEN",
          detail(org, ar).get("status") == "READY" and is_4xx(s)
          and env.get("code") == "ACTIVITY_NOT_OPEN",
          "status=%s code=%s act=%s" % (s, env.get("code"), detail(org, ar).get("status")))

    # ============ A7 通知矩阵 ============
    a7 = make(org, "回归-通知", cap=1)
    b1, bo = notif_ids(t1), notif_ids(org)
    signup(t1, a7, True)
    check("A7 报名通知本人+组织者",
          bool(new_notif(t1, "已成功报名", b1)) and bool(new_notif(org, "已报名活动", bo)), "")
    b2, bo = notif_ids(t2), notif_ids(org)
    signup(t2, a7, True)
    check("A7 候补通知本人+组织者",
          bool(new_notif(t2, "候补队列", b2)) and bool(new_notif(org, "候补队列", bo)), "")
    b1, bo = notif_ids(t1), notif_ids(org)
    withdraw(t1, part(t1, a7)["id"])
    check("A7 退出通知本人+组织者",
          bool(new_notif(t1, "已退出活动", b1)) and bool(new_notif(org, "已退出活动", bo)), "")
    inv7 = wait_invite(t2, a7)
    if inv7:
        before = notif_ids(t2)
        bo = notif_ids(org)
        accept(t2, inv7["invitation_id"], True)
        check("A7 递补确认通知组织者", bool(new_notif(org, "已确认参加", bo)), "")
        got = bool(new_notif(t2, "已确认参加", before, timeout=3))
        check("A7 [待修] 递补确认通知本人（硬约束 4）", got, "本人新确认通知=%s" % got)
    else:
        check("A7 递补确认通知 [待修/环境]", False, "未拿到邀请")

    # ============ B1 对抗输入 ============
    s, env = req("POST", "/register", body={"account": "    ", "password": "12345678"})
    check("B1 [待修] 纯空格账号 → 4xx", is_4xx(s) and env.get("success") is False,
          "status=%s env=%s" % (s, str(env)[:160]))
    s, env = req("POST", "/register", body={"account": "robustblank", "password": "      "})
    check("B1 [待修] 纯空格密码 → 4xx", is_4xx(s) and env.get("success") is False,
          "status=%s env=%s" % (s, str(env)[:160]))

    before = count_activities()
    s, env = req("POST", "/activities", token=org, body={
        "title": "回归-类别null", "category": None, "description": "",
        "conditions": "", "location": "线上", "capacity": 2,
        "deadline": at(days=1), "start_time": at(days=2),
        "end_time": at(days=2, seconds=7200)})
    check("B1 [待修] category=null → 4xx", is_4xx(s) and env.get("success") is False,
          "status=%s env=%s" % (s, str(env)[:160]))

    for name, raw in [("畸形 JSON", "{bad json"), ("空 body", ""), ("数组当对象", "[]"),
                      ("JSON null", "null")]:
        s, env = req("POST", "/activities", token=org, raw=raw)
        check("B1 %s → 4xx 不 500" % name,
              is_4xx(s) and env.get("success") is False,
              "status=%s" % s)

    s, env = req("POST", "/activities", token=org, body={
        "title": "x" * 51, "category": "其他", "description": "", "conditions": "",
        "location": "线上", "capacity": 2, "deadline": at(days=1),
        "start_time": at(days=2), "end_time": at(days=2, seconds=7200)})
    check("B1 标题 51 字 → 4xx", is_4xx(s), "status=%s" % s)

    s, env = req("POST", "/activities", token=org, body={
        "title": "'; DROP TABLE activity;--", "category": "其他", "description": "",
        "conditions": "", "location": "线上", "capacity": 2, "deadline": at(days=1),
        "start_time": at(days=2), "end_time": at(days=2, seconds=7200)})
    aid_sqli = data_of(env).get("id")
    check("B1 SQLi 标题不 500 且参数化存储",
          s == 200 and aid_sqli and detail(org, aid_sqli).get("title") == "'; DROP TABLE activity;--",
          "status=%s title=%s" % (s, detail(org, aid_sqli).get("title") if aid_sqli else None))

    s, env = req("GET", "/activities?pageSize=999999", token=org)
    check("B1 pageSize 超大被钳制到 100", data_of(env).get("pageSize") == 100,
          "pageSize=%s" % data_of(env).get("pageSize"))
    s, env = req("GET", "/activities/99999999999999999999", token=org)
    check("B1 超大 id → 4xx 不 500", is_4xx(s), "status=%s" % s)

    # 重复标记同一条通知已读（PG/MySQL 应一致）
    an = make(org, "回归-重复已读")
    signup(t4, an, True)
    unread = None
    end = time.time() + 6
    while time.time() < end and not unread:
        unread = next((n for n in notifs(t4) if n.get("read_at") is None), None)
        time.sleep(0.2)
    if unread:
        s1, _ = req("POST", "/notifications/%s/read" % unread["id"], token=t4, body={})
        s2, _ = req("POST", "/notifications/%s/read" % unread["id"], token=t4, body={})
        check("B1 [待修] 重复标记同一条通知已读两次均 200（双库一致）",
              s1 == 200 and s2 == 200, "first=%s second=%s" % (s1, s2))
    else:
        check("B1 重复标记同一条通知已读 [环境]", False, "无未读通知")

    # ============ B2 并发 ============
    toks = [relogin("demo%02d" % i) for i in range(1, 21)]
    a20 = make(org, "回归-20并发", cap=4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda tk: signup(tk, a20, True), toks))
    d = detail(org, a20)
    check("B2 20 并发抢容量 4 → 恰好 4 FORMAL、16 WAITING",
          d.get("formal") == 4 and d.get("waiting") == 16 and d.get("reserved") == 0,
          "formal=%s waiting=%s reserved=%s"
          % (d.get("formal"), d.get("waiting"), d.get("reserved")))

    adup = make(org, "回归-同用户并发", cap=10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(lambda _: signup(t1, adup, True), range(10)))
    rows = [p for p in my(t1) if str(p.get("activity_id")) == str(adup)]
    check("B2 同一用户 10 并发只 1 条记录、占 1 名额",
          len(rows) == 1 and detail(org, adup).get("formal") == 1,
          "rows=%d formal=%s" % (len(rows), detail(org, adup).get("formal")))

    aacc = make(org, "回归-双击接受", cap=1)
    signup(t1, aacc, True)
    signup(t2, aacc, True)
    withdraw(t1, part(t1, aacc)["id"])
    inva = wait_invite(t2, aacc)
    if inva:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(accept, t2, inva["invitation_id"], True)
            f2 = ex.submit(accept, t2, inva["invitation_id"], True)
            f1.result(); f2.result()
        check("B2 并发 accept 两次只转正一次",
              detail(org, aacc).get("formal") == 1
              and part(t2, aacc).get("status") == "FORMAL",
              "formal=%s" % detail(org, aacc).get("formal"))
    else:
        check("B2 并发 accept 两次只转正一次 [环境]", False, "未拿到邀请")

    # ============ B4 越权 ============
    xa = "robx" + str(int(time.time()))[-6:]
    ya = "roby" + str(int(time.time()))[-6:]
    req("POST", "/register", body={"account": xa, "password": "Robust2026!", "nickname": "X"})
    req("POST", "/register", body={"account": ya, "password": "Robust2026!", "nickname": "Y"})
    tx, ty = login(xa, "Robust2026!"), login(ya, "Robust2026!")
    aidor = make(org, "回归-IDOR", cap=4)
    signup(ty, aidor, True)
    wait_notif(ty, "已成功报名")
    yn = notifs(ty)
    ynid = yn[0]["id"] if yn else None
    ypid = part(ty, aidor)["id"]
    s, env = req("POST", "/notifications/%s/read" % ynid, token=tx, body={}) if ynid else (0, {})
    check("B4 X 标记 Y 的通知已读 → 4xx",
          bool(ynid) and is_4xx(s) and env.get("success") is False, "status=%s" % s)
    s, env = req("GET", "/participations/%s/events" % ypid, token=tx)
    check("B4 X 看 Y 的事件流 → 4xx", is_4xx(s) and env.get("success") is False,
          "status=%s" % s)
    s, env = withdraw(tx, ypid)
    check("B4 X 用 Y 的 participation_id withdraw → 4xx",
          is_4xx(s) and env.get("success") is False, "status=%s" % s)
    s, env = req("GET", "/admin/overview", token=tx)
    check("B4 普通用户调治理接口 → 403 FORBIDDEN",
          s == 403 and env.get("code") == "FORBIDDEN", "status=%s code=%s" % (s, env.get("code")))
    check("B4 越权后 Y 仍 FORMAL", part(ty, aidor).get("status") == "FORMAL",
          str(part(ty, aidor))[:160])

    # ============ B5 冲突回滚 ============
    b1 = make(org, "回归-冲突A", cap=4, start=at(days=5), end=at(days=5, seconds=7200))
    b2 = make(org, "回归-冲突B", cap=4, start=at(days=5), end=at(days=5, seconds=7200))
    signup(t1, b1, True)
    s, env = signup(t1, b2)
    check("B5 报名冲突 409 且不落参与记录",
          s == 409 and env.get("code") == "CONFLICT" and part(t1, b2) is None,
          "status=%s part=%s" % (s, part(t1, b2)))

    before = count_activities()
    req("POST", "/activities", token=org, body={
        "title": "", "location": "", "capacity": 0, "category": "其他",
        "deadline": "bad", "start_time": "bad", "end_time": "bad"})
    check("B5 建活动校验失败后活动数不变", before == count_activities(),
          "before=%s after=%s" % (before, count_activities()))

    vals = invariants()
    check("B5 不变量五项全 0", vals == [0, 0, 0, 0, 0], "vals=%s" % vals)

    failed = [r for r in results if not r[1]]
    print("\n共 %d 项，失败 %d 项" % (len(results), len(failed)))
    for name, _, det in failed:
        print("  FAIL:", name, det[:180])
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
