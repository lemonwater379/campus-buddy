#!/usr/bin/env python3
"""阶段四 CEM-09（平台治理）验收脚本：管理员任命/撤销、封禁影响与处置、活动下架/恢复、
举报处理、出勤申诉复核、信用审查消费、密码找回人工审核、治理审计留痕。

运行前置（主会话验收口径，缺一不可）：
  后端须以 INVITE_TTL=10、SWEEP_SECONDS=2、CHECKIN_WINDOW_SECONDS=60、
  ATTENDANCE_VERIFY_MINUTES=1、CREDIT_APPEAL_MINUTES=1 启动（产品默认 INVITE_TTL=120、
  核对期 1440 分钟、申诉期 10080 分钟，口径不变）。
  BASE_URL 默认 http://127.0.0.1:8080（A 版 PG）；B 版传 BASE_URL=http://127.0.0.1:8081。
  脚本开头调用 /api/v1/demo/reset（重置后种子含 admin / admin2 两名管理员，密码 123456，
  本地演示口径）。全程使用相对时间，预计耗时约 15 分钟。

除 HTTP 外，本脚本用本地 DB CLI 做内部断言（无对外接口的部分）：
  participation 处置状态、credit_recalc_history 落账、credit_review 生成；governance_action
  的留痕则通过 /admin/actions 读取。sql() 与阶段三 test_cem10.py 同实现：PG 走 /tmp/pgsql
  的 psql（带 LD_LIBRARY_PATH），MySQL 走便携 mysql 客户端 socket root 连接，按 BASE_URL
  是否含 8081 分支。

已知边界：
  封禁处置中的 INVITED（待确认邀请）一项依赖白天递补时段，本脚本不做实时构造，仅断言
  ban-impact 返回 invited 为列表；其处置代码与 WAITING 同路（服务层规格）。
"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse
import subprocess
from datetime import datetime, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080") + "/api/v1"

PG_ENV = dict(os.environ, LD_LIBRARY_PATH="/tmp/pgsql/usr/lib/x86_64-linux-gnu:/tmp/pgsql/usr/lib/postgresql/16/lib")


def sql(query):
    if "8081" in BASE:
        cmd = [os.path.expanduser("~/workspace/.portable/mysql-8.0.28/bin/mysql"),
               "-S", os.path.expanduser("~/workspace/.portable/mysql-data/mysql.sock"),
               "-u", "root", "-N", "-e", query, "campus_buddy"]
        out = subprocess.run(cmd, capture_output=True, text=True)
    else:
        cmd = ["/tmp/pgsql/usr/lib/postgresql/16/bin/psql", "-h", "127.0.0.1", "-p", "5433",
               "-U", "postgres", "-d", "campus_buddy", "-t", "-A", "-c", query]
        out = subprocess.run(cmd, capture_output=True, text=True, env=PG_ENV)
    assert out.returncode == 0, f"sql failed: {query} -> {out.stderr}"
    return out.stdout.strip()


results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token=None, body=None, headers=None):
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    if headers:
        hdrs.update(headers)
    r = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=hdrs)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"success": False, "code": "HTTP_ERROR",
                            "message": f"HTTP {e.code}", "data": None}
    except Exception as e:
        return 0, {"success": False, "code": "NETWORK_ERROR", "message": str(e), "data": None}


def ok_data(env):
    assert env.get("success") is True, f"expected success envelope: {env}"
    return env.get("data")


def data_of(env):
    d = env.get("data")
    return d if isinstance(d, dict) else {}


def login(acc, pwd="123456"):
    s, env = req("POST", "/login", body={"account": acc, "password": pwd})
    assert env.get("success"), f"login {acc} failed: {s} {env}"
    return ok_data(env)["token"]


def register(acc, nickname):
    s, env = req("POST", "/register",
                 body={"account": acc, "password": "12345678", "nickname": nickname})
    assert env.get("success"), f"register {acc} failed: {s} {env}"
    return login(acc, "12345678")


def detail(token, aid):
    s, env = req("GET", f"/activities/{aid}", token=token)
    return ok_data(env)


def signup(token, aid):
    return req("POST", f"/activities/{aid}/signup", token=token, body={"confirmConflict": True})


def make_activity(tok, title, cap, deadline, start, end):
    s, env = req("POST", "/activities", token=tok, body={
        "title": title, "category": "其他", "description": "CEM-08 验收",
        "conditions": "", "location": "线上", "capacity": cap,
        "deadline": deadline, "start_time": start, "end_time": end})
    assert env.get("success") is True, f"create activity failed: {s} {env}"
    return ok_data(env)["id"]


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def wait_status(token, aid, want, timeout=150):
    """轮询活动状态直到 want，返回最后一次 detail。"""
    deadline = time.time() + timeout
    d = None
    while time.time() < deadline:
        d = detail(token, aid)
        if d.get("status") == want:
            return d
        time.sleep(2)
    return d


def att_of(token, aid, uid):
    s, env = req("GET", f"/activities/{aid}/attendance", token=token)
    rows = ok_data(env)
    for r in rows:
        if str(r.get("user_id")) == str(uid):
            return r
    return None


def my_id(token):
    s, env = req("GET", "/me", token=token)
    d = ok_data(env)
    u = d.get("user") if isinstance(d, dict) else None
    return (u or d)["id"]


def verify(org_tok, aid, uid, result):
    s, e = req("PUT", f"/activities/{aid}/attendance/{uid}", token=org_tok,
               body={"result": result, "evidence": ""})
    assert s == 200 and e.get("success"), f"verify {aid}/{uid} {result} failed: {s} {e}"


def credit(token):
    s, e = req("GET", "/me/credit?page=1&pageSize=100", token=token)
    return ok_data(e)


def entries_of(token):
    return credit(token)["entries"]["items"]


def by_activity(token):
    return {str(x["activity_id"]): x for x in entries_of(token)}


def wait_credit_total(token, n, timeout=240):
    until = time.time() + timeout
    d = credit(token)
    while time.time() < until and d["entries"]["total"] < n:
        time.sleep(3)
        d = credit(token)
    return d


# ---- CEM-09 新增助手 ----

def login_raw(acc, pwd="123456"):
    return req("POST", "/login", body={"account": acc, "password": pwd})


def me(token):
    s, e = req("GET", "/me", token=token)
    return e


def me_user(token):
    s, e = req("GET", "/me", token=token)
    d = ok_data(e)
    return d.get("user") or d


def notif_texts(token):
    s, e = req("GET", "/notifications?page=1&pageSize=50", token=token)
    items = ok_data(e).get("items") or []
    return [x.get("content", "") for x in items]


def wait_notif(token, keyword, timeout=20):
    until = time.time() + timeout
    while time.time() < until:
        if any(keyword in t for t in notif_texts(token)):
            return True
        time.sleep(2)
    return False


def wait_finalized(org_tok, aid, uid, timeout=180):
    until = time.time() + timeout
    while time.time() < until:
        row = att_of(org_tok, aid, uid)
        if row and row.get("finalized_at"):
            return row
        time.sleep(3)
    return None


def mk_future(tok, title, cap=5):
    now = datetime.now()
    return make_activity(tok, title, cap,
                         ts(now + timedelta(days=2)),
                         ts(now + timedelta(days=3)),
                         ts(now + timedelta(days=3, hours=2)))


def main():
    # ---- 0. 准备：重置 + 账号 ----
    try:
        tok0 = login("organizer")
    except AssertionError:
        req("POST", "/register", body={"account": "auditboot", "password": "12345678", "nickname": "审计"})
        tok0 = login("auditboot", "12345678")
    s, env = req("POST", "/demo/reset", token=tok0)
    assert env.get("success"), f"reset failed: {s} {env}"

    admin = login("admin")
    admin2 = login("admin2")
    check("种子管理员 admin 可登录且 is_admin", me_user(admin).get("is_admin") is True,
          str(me_user(admin).get("is_admin")))
    check("admin2 亦为管理员", me_user(admin2).get("is_admin") is True,
          str(me_user(admin2).get("is_admin")))
    admin_id = int(my_id(admin))
    admin2_id = int(my_id(admin2))

    u1 = register("cem09u1", "普通用户u1")
    u2 = register("cem09u2", "普通用户u2")
    u1_id, u2_id = int(my_id(u1)), int(my_id(u2))

    s, e = req("GET", "/admin/overview", token=u1)
    check("普通用户访问 /admin/overview 返回 403",
          s == 403 and e.get("success") is False, f"{s} {e.get('message')}")
    s, e = req("GET", "/admin/overview")
    check("无 token 访问 /admin/overview 返回 403",
          s == 403 and e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("GET", "/admin/overview", token=admin)
    ov = data_of(e)
    ov_keys = ["complaints_pending", "appeals_pending", "recovery_pending",
               "credit_reviews_pending", "bans_active", "bans_expired_pending"]
    check("工作台总览含六项计数",
          s == 200 and e.get("success") is True
          and all(k in ov and isinstance(ov.get(k), int) and ov.get(k) >= 0 for k in ov_keys),
          str(ov))

    # ---- 1. 管理员任命 / 撤销 ----
    s, e = req("POST", "/admin/admins", token=admin,
               body={"user_id": u1_id, "note": "测试任命"})
    assert s == 200 and e.get("success") is True, f"appoint failed: {s} {e}"
    check("任命后 is_admin 生效", me_user(u1).get("is_admin") is True,
          str(me_user(u1).get("is_admin")))

    s, e = req("POST", "/admin/admins", token=admin,
               body={"user_id": u1_id, "note": "重复任命"})
    check("重复任命被拒", s != 200 and e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("POST", f"/admin/admins/{u1_id}/revoke", token=admin,
               body={"reason": "测试撤销"})
    assert s == 200 and e.get("success") is True, f"revoke failed: {s} {e}"
    check("撤销后 is_admin 失效", me_user(u1).get("is_admin") is False,
          str(me_user(u1).get("is_admin")))

    s, e = req("GET", "/admin/admins", token=admin)
    d = ok_data(e)
    adm_rows = d if isinstance(d, list) else (d.get("items") or [])
    adm_accounts = {str(x.get("account")) for x in adm_rows}
    check("管理员列表含两名种子管理员",
          {"admin", "admin2"} <= adm_accounts, str(adm_accounts))

    # ---- 2. 封禁影响清单 + 封禁处置 + 解封 ----
    orgA = register("cem09orga", "组织者A")
    t = register("cem09target", "封禁目标")
    w1 = register("cem09w1", "候补成员1")
    t_id, w1_id = int(my_id(t)), int(my_id(w1))

    actFull = mk_future(orgA, "CEM09满员活动", cap=1)
    s, e = signup(w1, actFull)
    assert data_of(e).get("my_status") == "FORMAL", f"signup full failed: {s} {e}"
    s, e = signup(t, actFull)
    assert data_of(e).get("my_status") == "WAITING", f"expect WAITING: {s} {e}"
    # 先拿封禁前会话
    tok_t = login("cem09target", "12345678")

    actFuture = mk_future(orgA, "CEM09未来活动", cap=5)
    s, e = signup(t, actFuture)
    assert data_of(e).get("my_status") == "FORMAL", f"signup future failed: {s} {e}"
    actOwn = mk_future(t, "CEM09自办活动", cap=5)

    s, e = req("GET", f"/admin/users/{t_id}/ban-impact", token=admin)
    imp = data_of(e)
    waiting = imp.get("waiting") or []
    future_formal = imp.get("future_formal") or []
    organized = imp.get("organized_active") or []
    check("影响清单：候补 1 项且含满员活动",
          s == 200 and len(waiting) == 1
          and any(str(x.get("activity_id")) == str(actFull) for x in waiting), str(waiting))
    check("影响清单：未来正式 1 项",
          len(future_formal) == 1
          and any(str(x.get("activity_id")) == str(actFuture) for x in future_formal),
          str(future_formal))
    check("影响清单：组织活动 1 项",
          len(organized) == 1
          and any(str(x.get("activity_id")) == str(actOwn) for x in organized),
          str(organized))
    check("影响清单 invited 为列表", isinstance(imp.get("invited"), list),
          str(imp.get("invited")))

    s, e = req("POST", f"/admin/users/{admin_id}/ban", token=admin,
               body={"days": 7, "reason": "x"})
    check("不得封禁自己", e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("POST", f"/admin/users/{t_id}/ban", token=admin,
               body={"days": 31, "reason": "测试封禁"})
    check("封禁期限超 30 日被拒",
          e.get("success") is False and e.get("code") == "VALIDATION",
          f"{s} {e.get('code')} {e.get('message')}")

    s, e = req("POST", f"/admin/users/{t_id}/ban", token=admin,
               body={"days": 7, "reason": "测试封禁：多次违规"})
    ban_data = data_of(e)
    check("封禁执行成功",
          s == 200 and e.get("success") is True and ban_data.get("decision_id") is not None,
          str(ban_data))

    e = me(tok_t)
    check("封禁后旧会话失效", e.get("success") is False, f"{e.get('message')}")

    s, e = login_raw("cem09target", "12345678")
    check("封禁后登录被拒且提示原因",
          e.get("success") is False and "封禁" in (e.get("message") or ""),
          f"{s} {e.get('message')}")

    st = sql(f"SELECT status FROM participation "
             f"WHERE activity_id={int(actFull)} AND user_id={t_id}")
    check("候补参与已撤销", st == "WITHDRAWN", st)
    st = sql(f"SELECT status FROM participation "
             f"WHERE activity_id={int(actFuture)} AND user_id={t_id}")
    check("未来正式参与已撤销", st == "WITHDRAWN", st)
    check("组织活动已取消", detail(orgA, actOwn).get("status") == "CANCELLED",
          str(detail(orgA, actOwn).get("status")))

    s, e = req("POST", f"/admin/users/{t_id}/unban", token=admin,
               body={"reason": "复核解封"})
    assert s == 200 and e.get("success") is True, f"unban failed: {s} {e}"
    s, e = login_raw("cem09target", "12345678")
    check("解封后可登录", e.get("success") is True, f"{s} {e.get('message')}")

    # ---- 3. 活动下架 / 恢复（未结束：按取消收尾） ----
    actPub = mk_future(orgA, "CEM09待下架活动")
    s, e = signup(u1, actPub)
    assert data_of(e).get("my_status") == "FORMAL", f"signup actPub failed: {s} {e}"

    s, e = req("POST", f"/admin/activities/{actPub}/delist", token=admin,
               body={"reason": "内容待核"})
    assert s == 200 and e.get("success") is True, f"delist failed: {s} {e}"

    s, e = req("GET", f"/activities/{actPub}", token=u1)
    check("下架后普通用户详情不可见", e.get("success") is False, f"{s} {e.get('message')}")

    d = detail(orgA, actPub)
    check("下架后组织者可见且带标记", bool(d.get("delisted")), str(d))

    s, e = req("GET", "/activities?q=" + urllib.parse.quote("CEM09待下架活动"), token=u1)
    items = data_of(e).get("items") or []
    check("下架后大厅不列出",
          s == 200 and e.get("success") is True
          and all(str(x.get("id")) != str(actPub) for x in items), str(items))

    s, e = signup(u2, actPub)
    check("下架后不可报名", e.get("success") is False, f"{s} {e.get('message')}")

    check("未结束下架按取消收尾", detail(orgA, actPub).get("status") == "CANCELLED",
          str(detail(orgA, actPub).get("status")))

    s, e = req("POST", f"/admin/activities/{actPub}/relist", token=admin,
               body={"reason": "核实通过"})
    assert s == 200 and e.get("success") is True, f"relist failed: {s} {e}"
    check("恢复展示后标记清除", not detail(orgA, actPub).get("delisted"),
          str(detail(orgA, actPub).get("delisted")))

    # ---- 4. 举报与处理通知 ----
    s, e = req("POST", "/complaints", token=u1,
               body={"activity_id": int(actFuture), "category": "违规内容",
                     "reason": "活动介绍含违规信息"})
    cid = str(data_of(e).get("id"))
    check("举报活动提交成功",
          s == 200 and e.get("success") is True and cid != "None", str(data_of(e)))

    s, e = req("POST", "/complaints", token=u1,
               body={"subject_user_id": u2_id, "category": "人身攻击",
                     "reason": "私信辱骂"})
    check("举报用户提交成功", s == 200 and e.get("success") is True, str(data_of(e)))

    s, e = req("POST", "/complaints", token=u1,
               body={"subject_user_id": u1_id, "category": "其他", "reason": "测试"})
    check("不能举报自己", e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("POST", "/complaints", token=u1,
               body={"activity_id": int(actFuture), "subject_user_id": u2_id,
                     "category": "其他", "reason": "测试"})
    check("双目标被拒", e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("GET", "/admin/complaints?state=PENDING&page=1&pageSize=100", token=admin)
    qitems = data_of(e).get("items") or []
    check("举报进入工作台队列",
          s == 200 and any(str(x.get("id")) == cid for x in qitems), str(qitems))

    s, e = req("POST", f"/admin/complaints/{cid}/handle", token=admin,
               body={"outcome": "RESOLVED", "result": "已核实，活动已下架处理"})
    assert s == 200 and e.get("success") is True, f"handle complaint failed: {s} {e}"

    notified = wait_notif(u1, "举报") or wait_notif(u1, "已核实")
    check("举报人收到处理通知", notified, "")

    s, e = req("GET", "/complaints/mine?page=1&pageSize=100", token=u1)
    mine_items = data_of(e).get("items") or []
    row = next((x for x in mine_items if str(x.get("id")) == cid), None)
    check("举报状态已更新", row is not None and row.get("state") == "RESOLVED", str(row))

    # ---- 5. 出勤申诉链（时间波，与第 7 节共用一波） ----
    org2 = register("cem09org2", "组织者2")
    mPause = register("cem09pause", "成员pause")
    mFix = register("cem09fix", "成员fix")
    mRev = register("cem09rev", "成员rev")
    org2_id = int(my_id(org2))
    mPause_id, mFix_id, mRev_id = int(my_id(mPause)), int(my_id(mFix)), int(my_id(mRev))

    now5 = datetime.now()

    def mk5(title):
        return make_activity(org2, title, 5,
                             ts(now5 + timedelta(seconds=55)),
                             ts(now5 + timedelta(seconds=80)),
                             ts(now5 + timedelta(seconds=260)))

    aPause = mk5("CEM09暂停结算")
    aFix = mk5("CEM09申诉更正")
    aRev1 = mk5("CEM09复核01")
    aRev2 = mk5("CEM09复核02")
    aRev3 = mk5("CEM09复核03")
    for tok_m, aid in [(mPause, aPause), (mFix, aFix),
                       (mRev, aRev1), (mRev, aRev2), (mRev, aRev3)]:
        s, e = signup(tok_m, aid)
        assert data_of(e).get("my_status") == "FORMAL", f"signup {aid} failed: {s} {e}"

    wait_status(org2, aPause, "RUNNING", timeout=200)
    wait_status(org2, aPause, "ENDED", timeout=300)

    verify(org2, aPause, mPause_id, "ABSENT_VERIFIED")
    verify(org2, aFix, mFix_id, "ABSENT_VERIFIED")
    verify(org2, aRev1, mRev_id, "ABSENT_VERIFIED")
    verify(org2, aRev2, mRev_id, "ABSENT_VERIFIED")
    verify(org2, aRev3, mRev_id, "ABSENT_VERIFIED")

    fin = wait_finalized(org2, aFix, mFix_id, timeout=180)
    check("出勤定版", fin is not None and bool(fin.get("finalized_at")), str(fin))
    # 同一批核对，等待 aPause 也定版（静默，避免申诉被“尚未定版”打断）
    wait_finalized(org2, aPause, mPause_id, timeout=180)

    # 暂停结算：提交申诉后申诉期届满也不结算
    att_pause = att_of(org2, aPause, mPause_id)
    s, e = req("POST", "/appeals", token=mPause,
               body={"attendance_id": int(att_pause["id"]),
                     "reason": "当天已到场，签到记录可查"})
    appeal_pause_id = str(data_of(e).get("id"))
    check("出勤申诉提交成功",
          s == 200 and e.get("success") is True and appeal_pause_id != "None",
          str(data_of(e)))

    print("  等待申诉期届满（约 100 秒）……")
    time.sleep(100)
    d = credit(mPause)
    check("申诉未决期间暂停结算",
          d["entries"]["total"] == 0 and d.get("score") == 100,
          f"{d['entries']['total']} {d.get('score')}")

    # mFix 先正常结算
    d = wait_credit_total(mFix, 1, timeout=240)
    fx = by_activity(mFix).get(str(aFix)) or {}
    check("mFix 缺席已结算 -10",
          d.get("score") == 90 and fx.get("delta") == -10,
          f"{d.get('score')} {fx}")

    # 任命 org2 为管理员 + 独立性
    s, e = req("POST", "/admin/admins", token=admin,
               body={"user_id": org2_id, "note": "复核测试"})
    assert s == 200 and e.get("success") is True, f"appoint org2 failed: {s} {e}"

    att_fix = att_of(org2, aFix, mFix_id)
    s, e = req("POST", "/appeals", token=mFix,
               body={"attendance_id": int(att_fix["id"]), "reason": "实际到场"})
    appeal_fix_id = str(data_of(e).get("id"))
    assert s == 200 and e.get("success") is True, f"file appeal fix failed: {s} {e}"

    s, e = req("POST", f"/admin/appeals/{appeal_fix_id}/review", token=org2,
               body={"outcome": "CORRECT", "new_result": "PRESENT", "result": "复核更正"})
    check("原处理人复核被拒（独立性）",
          e.get("success") is False and "独立" in (e.get("message") or ""),
          f"{s} {e.get('message')}")

    s, e = req("POST", f"/admin/appeals/{appeal_pause_id}/review", token=admin,
               body={"outcome": "CORRECT", "new_result": "EXEMPT",
                     "result": "情况属实，改判豁免"})
    assert s == 200 and e.get("success") is True, f"review pause appeal failed: {s} {e}"
    d = wait_credit_total(mPause, 1, timeout=240)
    ep = by_activity(mPause).get(str(aPause)) or {}
    check("暂停案更正后按豁免结算",
          ep.get("delta") == 0 and d.get("score") == 100,
          f"{d.get('score')} {ep}")

    s, e = req("GET", "/appeals/mine?page=1&pageSize=100", token=mPause)
    aitems = data_of(e).get("items") or []
    arow = next((x for x in aitems if str(x.get("id")) == appeal_pause_id), None)
    check("申诉状态 CORRECTED", arow is not None and arow.get("state") == "CORRECTED",
          str(arow))

    s, e = req("POST", f"/admin/appeals/{appeal_fix_id}/review", token=admin,
               body={"outcome": "CORRECT", "new_result": "PRESENT",
                     "result": "复核确认到场"})
    assert s == 200 and e.get("success") is True, f"review fix appeal failed: {s} {e}"

    until = time.time() + 120
    d = credit(mFix)
    while time.time() < until and d.get("score") != 100:
        time.sleep(3)
        d = credit(mFix)
    check("更正后重算回分至 100", d.get("score") == 100, str(d.get("score")))

    fx = by_activity(mFix).get(str(aFix)) or {}
    check("流水 delta 已改 +2", fx.get("delta") == 2, str(fx))

    cnt = sql(f"SELECT COUNT(*) FROM credit_recalc_history WHERE user_id={mFix_id}")
    check("重算历史落账", int(cnt) >= 1, cnt)

    notified = wait_notif(mFix, "申诉") or wait_notif(mFix, "更正")
    check("当事人收到复核通知", notified, "")

    # ---- 6. 信用审查消费（接第 5 节 mRev） ----
    d = wait_credit_total(mRev, 3, timeout=240)
    check("mRev 三次缺席结算为 70", d.get("score") == 70, str(d.get("score")))

    cnt = "0"
    until = time.time() + 120
    while time.time() < until:
        cnt = sql(f"SELECT COUNT(*) FROM credit_review "
                  f"WHERE user_id={mRev_id} AND status='PENDING'")
        if int(cnt) >= 1:
            break
        time.sleep(3)
    check("信用审查记录生成", int(cnt) >= 1, cnt)

    s, e = req("GET", "/admin/credit-reviews?state=PENDING&page=1&pageSize=100", token=admin)
    ritems = data_of(e).get("items") or []
    rrow = next((x for x in ritems if str(x.get("user_id")) == str(mRev_id)), None)
    assert rrow is not None, f"credit review row not found: {ritems}"
    rid = str(rrow.get("id"))
    s, e = req("POST", f"/admin/credit-reviews/{rid}/handle", token=admin,
               body={"outcome": "REVIEWED", "note": "已约谈"})
    assert s == 200 and e.get("success") is True, f"handle credit review failed: {s} {e}"
    s, e = req("GET", "/admin/credit-reviews?state=REVIEWED&page=1&pageSize=100", token=admin)
    ritems = data_of(e).get("items") or []
    check("信用审查可处置",
          any(str(x.get("id")) == rid for x in ritems), str(ritems))

    # ---- 7. 已结束活动下架只停展示（复用 aRev1） ----
    s, e = req("POST", f"/admin/activities/{aRev1}/delist", token=admin,
               body={"reason": "事后核查"})
    assert s == 200 and e.get("success") is True, f"delist aRev1 failed: {s} {e}"

    s, e = req("GET", f"/activities/{aRev1}", token=mRev)
    check("已结束活动下架后他人不可见", e.get("success") is False,
          f"{s} {e.get('message')}")

    d = detail(org2, aRev1)
    check("组织者仍可见已下架的已结束活动", bool(d.get("delisted")), str(d))

    d = credit(mRev)
    check("下架不删信用事实", d.get("score") == 70, str(d.get("score")))

    s, e = req("POST", f"/admin/activities/{aRev1}/relist", token=admin,
               body={"reason": "核查完毕"})
    assert s == 200 and e.get("success") is True, f"relist aRev1 failed: {s} {e}"
    s, e = req("GET", f"/activities/{aRev1}", token=mRev)
    check("恢复后可见", e.get("success") is True, f"{s} {e.get('message')}")

    # ---- 8. 密码找回人工审核 ----
    r = register("cem09rec", "找回用户")
    tok_r_old = r
    s, e = req("POST", "/recovery",
               body={"account": "cem09rec", "request_type": 1,
                     "reason": "忘记密码", "contact": "13800000000"})
    rec = data_of(e)
    rec_id = str(rec.get("id"))
    qtoken = rec.get("query_token")
    check("找回申请提交成功",
          s == 200 and e.get("success") is True and rec_id != "None" and bool(qtoken),
          str(rec))

    s, e = req("GET", f"/recovery/{rec_id}?query_token=wrong")
    check("查询凭据错误被拒", e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("GET", f"/recovery/{rec_id}?query_token=" + urllib.parse.quote(str(qtoken)))
    check("申请状态可查询",
          s == 200 and e.get("success") is True and data_of(e).get("state") == "PENDING",
          str(data_of(e)))

    s, e = req("GET", "/admin/recovery?state=PENDING&page=1&pageSize=100", token=admin)
    rcitems = data_of(e).get("items") or []
    assert any(str(x.get("id")) == rec_id for x in rcitems), f"recovery row not found: {rcitems}"

    s, e = req("POST", f"/admin/recovery/{rec_id}/review", token=admin,
               body={"outcome": "APPROVE", "note": "已核对身份"})
    rd = data_of(e)
    reset_cred = rd.get("reset_credential")
    check("批准签发重置凭据",
          s == 200 and e.get("success") is True
          and isinstance(reset_cred, str) and len(reset_cred) > 0, str(rd))

    s, e = req("POST", "/recovery/reset",
               body={"credential": "bad", "new_password": "newpass123"})
    check("错误凭据被拒", e.get("success") is False, f"{s} {e.get('message')}")

    s, e = req("POST", "/recovery/reset",
               body={"credential": reset_cred, "new_password": "newpass123"})
    check("凭据重置成功", s == 200 and e.get("success") is True,
          f"{s} {e.get('message')}")

    e = me(tok_r_old)
    check("重置后旧会话撤销", e.get("success") is False, f"{e.get('message')}")

    s_old, e_old = login_raw("cem09rec", "12345678")
    s_new, e_new = login_raw("cem09rec", "newpass123")
    check("旧密码失效新密码生效",
          e_old.get("success") is False and e_new.get("success") is True,
          f"old={e_old.get('message')} new={e_new.get('message')}")

    s, e = req("POST", "/recovery/reset",
               body={"credential": reset_cred, "new_password": "newpass456"})
    check("凭据不可重用", e.get("success") is False, f"{s} {e.get('message')}")

    # ---- 9. 找回批准不解封禁 + 封禁复核 ----
    b = register("cem09ban", "封禁用户")
    b_id = int(my_id(b))
    s, e = req("POST", f"/admin/users/{b_id}/ban", token=admin,
               body={"days": 3, "reason": "封禁复核测试"})
    assert s == 200 and e.get("success") is True, f"ban b failed: {s} {e}"

    s, e = req("POST", "/recovery",
               body={"account": "cem09ban", "request_type": 1, "reason": "改密"})
    assert s == 200 and e.get("success") is True, f"recovery b failed: {s} {e}"
    rid1 = str(data_of(e).get("id"))
    s, e = req("POST", f"/admin/recovery/{rid1}/review", token=admin,
               body={"outcome": "APPROVE", "note": "已核对身份"})
    assert s == 200 and e.get("success") is True, f"approve recovery b failed: {s} {e}"
    cred_b = data_of(e).get("reset_credential")

    s, e = req("POST", "/recovery/reset",
               body={"credential": cred_b, "new_password": "newpass123"})
    check("被封禁用户可完成改密", s == 200 and e.get("success") is True,
          f"{s} {e.get('message')}")

    s, e = login_raw("cem09ban", "newpass123")
    check("批准找回不解除封禁",
          e.get("success") is False and "封禁" in (e.get("message") or ""),
          f"{s} {e.get('message')}")

    s, e = req("POST", "/recovery",
               body={"account": "cem09ban", "request_type": 2,
                     "reason": "已认识错误，申请复核"})
    assert s == 200 and e.get("success") is True, f"recovery type2 failed: {s} {e}"
    rid2 = str(data_of(e).get("id"))

    s, e = req("POST", f"/admin/recovery/{rid2}/review", token=admin,
               body={"outcome": "APPROVE"})
    check("封禁复核须独立于原处理人",
          e.get("success") is False and "独立" in (e.get("message") or ""),
          f"{s} {e.get('message')}")

    s, e = req("POST", f"/admin/recovery/{rid2}/review", token=admin2,
               body={"outcome": "APPROVE"})
    assert s == 200 and e.get("success") is True, f"approve ban review failed: {s} {e}"
    s, e = login_raw("cem09ban", "newpass123")
    check("封禁复核通过后解封可登录", e.get("success") is True,
          f"{s} {e.get('message')}")

    # ---- 10. 治理审计 ----
    s, e = req("GET", "/admin/actions?page=1&pageSize=100", token=admin)
    acts = {str(x.get("action")) for x in (data_of(e).get("items") or [])}
    want = {"BAN_USER", "UNBAN_USER", "COMPLAINT_HANDLE", "APPEAL_REVIEW",
            "RECOVERY_REVIEW", "CREDIT_REVIEW_HANDLE", "DELIST_ACTIVITY"}
    check("治理动作全程留痕可查", s == 200 and want <= acts, str(sorted(acts)))

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
