#!/usr/bin/env python3
"""本地真实 PostgreSQL 验收脚本（阶段一：/api/v1 + 统一返回体，对运行中的 http://127.0.0.1:8080）。
原有场景：报名转正式/候补、正式退出触发递补、接受转正式、邀请超时自动顺延、
20 并发报名上限 4 恰好 4 正式、同一账号并发多次只有一条记录。
新增阶段一场景：返回体形状、分页、幂等、事件流、资料修改、通知单条已读、
abandon、时间冲突、移出成员、outbox 可见性。
运行前：后端以 INVITE_TTL=10、SWEEP_SECONDS=2 启动；脚本开头调用 /api/v1/demo/reset。
"""
import concurrent.futures, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080") + "/api/v1"
# 活动时间取相对日期，避免写死日期过期导致创建被拒（2026-11-08 首次过期：截止 11-07 已过）。
# 形状与旧写死值一致：截止=明天 20:00，开始=后天 20:00，结束=后天 22:00。
_NOW = datetime.now()
DEADLINE = (_NOW + timedelta(days=1)).strftime("%Y-%m-%dT20:00:00")
START = (_NOW + timedelta(days=2)).strftime("%Y-%m-%dT20:00:00")
END = (_NOW + timedelta(days=2)).strftime("%Y-%m-%dT22:00:00")
# 阶段一新增用例统一用更远的日期，避免与种子活动/原有场景的活动时间重叠
# （时间冲突检测上线后，重叠会被 409 拦下）。
P1_DEADLINE = (_NOW + timedelta(days=5)).strftime("%Y-%m-%dT08:00:00")
P1_START = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT10:00:00")
P1_END = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT12:00:00")
P1_Y_START = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT11:00:00")
P1_Y_END = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT13:00:00")
P1_Z_START = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT14:00:00")
P1_Z_END = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT16:00:00")

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token=None, body=None, headers=None):
    """返回 (http_status, envelope)。headers 用于 Idempotency-Key 等自定义头。"""
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
    """断言 success 并返回 data。"""
    assert env.get("success") is True, f"expected success envelope: {env}"
    return env.get("data")


def data_of(env):
    d = env.get("data")
    return d if isinstance(d, dict) else {}


def items_of(data):
    """兼容 data 直接是列表或包装成 {items: [...]}/ {events: [...]}。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "events"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def login(acc, pwd="Dazi@2026!"):
    s, env = req("POST", "/login", body={"account": acc, "password": pwd})
    assert env.get("success"), f"login {acc} failed: {s} {env}"
    return ok_data(env)["token"]


def register(acc, pwd="12345678", nickname=None):
    body = {"account": acc, "password": pwd}
    if nickname:
        body["nickname"] = nickname
    return req("POST", "/register", body=body)


def my(token):
    """我的参与列表（data.items）。"""
    s, env = req("GET", "/my?pageSize=100", token=token)
    return ok_data(env)["items"]


def detail(token, aid):
    """活动详情（data，字段与旧接口一致，id 为字符串）。"""
    s, env = req("GET", f"/activities/{aid}", token=token)
    return ok_data(env)


def me_user(env):
    """兼容 /me 的 data 为 {user:{...}} 或直接用户对象。"""
    d = env.get("data")
    if not isinstance(d, dict):
        return {}
    u = d.get("user")
    return u if isinstance(u, dict) else d


def signup(token, aid, confirm=False, key=None):
    headers = {"Idempotency-Key": key} if key else None
    body = {"confirmConflict": True} if confirm else None
    return req("POST", f"/activities/{aid}/signup", token=token, body=body, headers=headers)


def make_activity(tok, title, cap=4, deadline=P1_DEADLINE, start=P1_START, end=P1_END,
                  category="其他"):
    s, env = req("POST", "/activities", token=tok, body={
        "title": title, "category": category, "description": "阶段一测试",
        "conditions": "", "location": "线上", "capacity": cap,
        "deadline": deadline, "start_time": start, "end_time": end})
    assert env.get("success") is True, f"create activity failed: {s} {env}"
    return ok_data(env)["id"]


def authed_reset():
    """演示重置现在需要登录（审计修复）：先用种子组织者登录再重置；
    空库极端情况下先注册一个账号再登录重置。"""
    try:
        tok = login("organizer")
    except AssertionError:
        req("POST", "/register", body={"account": "auditboot", "password": "12345678", "nickname": "审计"})
        tok = login("auditboot", "12345678")
    s, env = req("POST", "/demo/reset", token=tok)
    assert env.get("success"), f"reset failed: {s} {env}"


def main():
    authed_reset()
    org = login("organizer")
    toks = {f"demo{i:02d}": login(f"demo{i:02d}") for i in range(1, 21)}
    s, env = req("GET", "/activities?pageSize=100", token=org)
    acts = ok_data(env)["items"]
    a = [x for x in acts if x["title"] == "羽毛球双打"][0]
    aid = a["id"]
    check("种子活动 A 上限 4、已有 3 正式", a["formal_count"] == 3 and a["capacity"] == 4, str(a))

    # 报名：demo04 正式、demo05/06 候补
    s4, e4 = signup(toks["demo04"], aid)
    s5, e5 = signup(toks["demo05"], aid)
    s6, e6 = signup(toks["demo06"], aid)
    r4, r5, r6 = data_of(e4), data_of(e5), data_of(e6)
    check("第 4 人报名转正式", r4.get("my_status") == "FORMAL", str(r4))
    check("第 5 人报名转候补第 1", r5.get("my_status") == "WAITING" and r5.get("my_rank") == 1, str(r5))
    check("第 6 人报名转候补第 2", r6.get("my_status") == "WAITING" and r6.get("my_rank") == 2, str(r6))

    # 正式退出触发递补：demo04 退出 -> demo05 收到邀请
    p4 = [p for p in my(toks["demo04"]) if p["activity_id"] == aid][0]
    sw, ew = req("POST", f"/participations/{p4['id']}/withdraw", token=toks["demo04"])
    w = data_of(ew)
    check("正式退出成功", sw == 200 and w.get("my_status") == "WITHDRAWN", str(w))
    m5 = [p for p in my(toks["demo05"]) if p["activity_id"] == aid][0]
    check("退出后候补第 1 收到待确认邀请", m5["status"] == "INVITED" and m5["invitation_id"], str(m5))
    d = detail(org, aid)
    check("递补后有效占用仍 = 上限（正式 3 + 预留 1）",
          d["formal"] == 3 and d["reserved"] == 1, f"formal={d['formal']} reserved={d['reserved']} waiting={d['waiting']}")

    # 接受邀请转正式
    sacc, eacc = req("POST", f"/invitations/{m5['invitation_id']}/accept", token=toks["demo05"])
    acc = data_of(eacc)
    check("接受邀请转正式", sacc == 200 and acc.get("my_status") == "FORMAL", str(acc))
    d = detail(org, aid)
    check("接受后正式回到 4、预留 0", d["formal"] == 4 and d["reserved"] == 0, str(d))

    # 超时顺延：demo05 退出 -> demo06 邀请；等 10 秒 TTL + 扫描，demo06 邀请过期，demo07 收到邀请
    p5 = [p for p in my(toks["demo05"]) if p["activity_id"] == aid][0]
    req("POST", f"/participations/{p5['id']}/withdraw", token=toks["demo05"])
    # 先让 demo07 排队（此时 demo06 已是 INVITED，demo07 为候补）
    s7, e7 = signup(toks["demo07"], aid)
    r7 = data_of(e7)
    check("demo07 报名为候补", r7.get("my_status") == "WAITING", str(r7))
    print("  等待邀请超时（TTL 10s + 扫描）约 15 秒……")
    time.sleep(15)
    m6 = [p for p in my(toks["demo06"]) if p["activity_id"] == aid][0]
    m7 = [p for p in my(toks["demo07"]) if p["activity_id"] == aid][0]
    check("超时后原邀请失效（demo06 回到候补或过期）", m6["status"] in ("WAITING", "EXPIRED"), str(m6))
    check("超时后顺延到下一候补 demo07 收到邀请", m7["status"] == "INVITED" and m7["invitation_id"], str(m7))
    # 过期确认接口直接拒绝：demo06 的旧邀请已不是 PENDING，再次 accept 应失败（用旧 invitation_id）
    old_inv = m6.get("invitation_id")
    if old_inv:
        srej, erej = req("POST", f"/invitations/{old_inv}/accept", token=toks["demo06"])
        check("过期邀请确认被拒绝", erej.get("success") is False, str(erej))

    # 并发：新建上限 4 活动，20 个不同账号同时报名
    snew, enew = req("POST", "/activities", token=org, body={
        "title": "并发测试活动", "category": "其他", "description": "并发测试",
        "conditions": "", "location": "线上", "capacity": 4,
        "deadline": DEADLINE, "start_time": START, "end_time": END})
    check("新建并发测试活动", enew.get("success") is True, str(enew))
    cid = ok_data(enew)["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda t: signup(t, cid), toks.values()))
    dc = detail(org, cid)
    check("20 并发报名：恰好 4 正式、16 候补", dc["formal"] == 4 and dc["waiting"] == 16,
          f"formal={dc['formal']} waiting={dc['waiting']} reserved={dc['reserved']}")

    # 同一账号并发多次：demo01 对另一新活动并发 10 次
    snew2, enew2 = req("POST", "/activities", token=org, body={
        "title": "重复提交测试", "category": "其他", "description": "重复测试",
        "conditions": "", "location": "线上", "capacity": 10,
        "deadline": DEADLINE, "start_time": START, "end_time": END})
    cid2 = ok_data(enew2)["id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        # demo01 在前序场景已有同窗正式活动，须带 confirmConflict（与 test_audit 的适配一致）；
        # 本用例验的是同账号并发去重，不是冲突拦截。
        list(ex.map(lambda _: signup(toks["demo01"], cid2, confirm=True), range(10)))
    rows = [p for p in my(toks["demo01"]) if p["activity_id"] == cid2]
    check("同一账号并发 10 次只有一条有效记录", len(rows) == 1, f"rows={len(rows)}")

    # ================= 阶段一新增用例（各自独立活动/账号，避免污染上面的计数断言） =================

    # ---- 1. 返回体形状 ----
    sh, eh = req("GET", "/health")
    check("v1 health 返回统一返回体（success/code/serverTime/traceId）",
          sh == 200 and eh.get("success") is True and eh.get("code") == "OK"
          and bool(eh.get("serverTime")) and bool(eh.get("traceId")), str(eh))
    s, env = req("GET", "/activities?pageSize=100", token=org)
    shape_items = ok_data(env)["items"]
    check("v1 返回体中活动 id 为字符串",
          bool(shape_items) and all(isinstance(x["id"], str) for x in shape_items),
          str(shape_items[:1]))

    # ---- 2. 分页 ----
    s, ep1 = req("GET", "/activities?page=1&pageSize=2", token=org)
    s, ep2 = req("GET", "/activities?page=2&pageSize=2", token=org)
    pg1, pg2 = ok_data(ep1), ok_data(ep2)
    ids1 = {x["id"] for x in pg1["items"]}
    ids2 = {x["id"] for x in pg2["items"]}
    check("分页：page=1&pageSize=2 → total≥4 且 len(items)=2",
          pg1.get("total", 0) >= 4 and len(pg1["items"]) == 2, str(pg1.get("total")))
    check("分页：page=2 的 items 与 page=1 不重叠", len(ids2) == 2 and not (ids1 & ids2),
          f"page1={ids1} page2={ids2}")

    # ---- 3. 幂等 ----
    s, ebase = req("GET", "/my/organized?pageSize=100", token=org)
    base_total = ok_data(ebase)["total"]
    idem_body = {
        "title": "幂等创建-阶段一", "category": "其他", "description": "幂等测试",
        "conditions": "", "location": "线上", "capacity": 4,
        "deadline": P1_DEADLINE, "start_time": P1_START, "end_time": P1_END}
    k1 = "phase1-create-" + str(int(time.time() * 1000))
    si1, ei1 = req("POST", "/activities", token=org, body=idem_body,
                   headers={"Idempotency-Key": k1})
    si2, ei2 = req("POST", "/activities", token=org, body=idem_body,
                   headers={"Idempotency-Key": k1})
    idem_id1, idem_id2 = ok_data(ei1)["id"], ok_data(ei2)["id"]
    check("幂等创建：同 key 同 body 两次返回同一 id",
          si1 == 200 and si2 == 200 and idem_id1 == idem_id2, f"{idem_id1} vs {idem_id2}")
    s, eorg = req("GET", "/my/organized?pageSize=100", token=org)
    check("幂等创建：/my/organized 的 total 只 +1",
          ok_data(eorg)["total"] == base_total + 1,
          f"{base_total} -> {ok_data(eorg)['total']}")
    idem_body_diff = dict(idem_body, title="幂等创建-阶段一-不同")
    si3, ei3 = req("POST", "/activities", token=org, body=idem_body_diff,
                   headers={"Idempotency-Key": k1})
    check("幂等冲突：同 key 不同 body → HTTP 409 且 code=IDEMPOTENCY_CONFLICT",
          si3 == 409 and ei3.get("code") == "IDEMPOTENCY_CONFLICT", f"{si3} {ei3}")

    register("p1idem", nickname="幂等用户")
    tidem = login("p1idem", "12345678")
    sid = make_activity(org, "幂等报名-阶段一")
    k2 = "phase1-signup-" + str(int(time.time() * 1000))
    ssa, esa = signup(tidem, sid, key=k2)
    ssb, esb = signup(tidem, sid, key=k2)
    check("报名幂等：带同一 key 重复提交 my_status 一致",
          data_of(esa).get("my_status") == data_of(esb).get("my_status") == "FORMAL",
          f"{data_of(esa).get('my_status')} / {data_of(esb).get('my_status')}")
    rows = [p for p in my(tidem) if str(p["activity_id"]) == str(sid)]
    check("报名幂等：只有一条参与记录", len(rows) == 1, f"rows={len(rows)}")

    # ---- 4. 事件流 ----
    register("p1event", nickname="事件用户")
    tev = login("p1event", "12345678")
    eid = make_activity(org, "事件流-阶段一")
    signup(tev, eid)
    pev = [p for p in my(tev) if str(p["activity_id"]) == str(eid)][0]
    req("POST", f"/participations/{pev['id']}/withdraw", token=tev)
    s, eev = req("GET", f"/participations/{pev['id']}/events", token=tev)
    evs = items_of(eev.get("data")) if eev.get("success") else []
    etypes = {e.get("event_type") for e in evs}
    check("事件流：报名→退出 含 SIGNUP_FORMAL 与 WITHDRAW",
          s == 200 and {"SIGNUP_FORMAL", "WITHDRAW"} <= etypes, str(sorted(etypes)))
    register("p1other", nickname="无关用户")
    tother = login("p1other", "12345678")
    s, eother = req("GET", f"/participations/{pev['id']}/events", token=tother)
    check("事件流：无关用户访问 → 失败", eother.get("success") is False, f"{s} {eother}")

    # ---- 5. 资料修改 ----
    register("p1prof", nickname="资料原昵称")
    tprof = login("p1prof", "12345678")
    s, eme = req("GET", "/me", token=tprof)
    orig_nick = me_user(eme).get("nickname")
    s, eprof = req("PATCH", "/me/profile", token=tprof, body={"nickname": "资料新昵称"})
    check("资料修改：PATCH /me/profile 成功", s == 200 and eprof.get("success") is True, f"{s} {eprof}")
    s, eme2 = req("GET", "/me", token=tprof)
    check("资料修改：GET /me 反映新昵称", me_user(eme2).get("nickname") == "资料新昵称",
          str(me_user(eme2)))
    s, eempty = req("PATCH", "/me/profile", token=tprof, body={"nickname": ""})
    field_errors = data_of(eempty).get("fieldErrors") or {}
    check("资料修改：空昵称 → 400、code=VALIDATION、data.fieldErrors.nickname",
          s == 400 and eempty.get("code") == "VALIDATION" and "nickname" in field_errors,
          f"{s} {eempty}")
    if orig_nick:
        req("PATCH", "/me/profile", token=tprof, body={"nickname": orig_nick})

    # ---- 6. 通知单条已读 ----
    register("p1notif", nickname="通知用户")
    tnotif = login("p1notif", "12345678")
    s, en0 = req("GET", "/notifications?page=1&pageSize=50", token=org)
    known_ids = {x["id"] for x in ok_data(en0)["items"]}
    nact = make_activity(org, "通知单条已读-阶段一")
    signup(tnotif, nact)
    # 轮询等新通知经 outbox 发布出来，再取快照，避免“已读期间又有通知发布”导致 unread 计数漂移。
    target, unread_before = None, 0
    for _ in range(30):
        s, en = req("GET", "/notifications?page=1&pageSize=50", token=org)
        if en.get("success"):
            nd = ok_data(en)
            fresh_unread = [x for x in nd["items"]
                            if x.get("read_at") is None and x["id"] not in known_ids]
            if fresh_unread:
                target, unread_before = fresh_unread[0], nd["unread"]
                break
        time.sleep(0.1)
    check("通知：组织者存在未读通知", target is not None, str(target))
    if target:
        s, eread = req("POST", f"/notifications/{target['id']}/read", token=org)
        check("通知单条已读：接口成功且 data.read=true",
              s == 200 and eread.get("success") is True and data_of(eread).get("read") is True,
              f"{s} {eread}")
        s, en2 = req("GET", "/notifications?page=1&pageSize=50", token=org)
        nd2 = ok_data(en2)
        row = [x for x in nd2["items"] if x["id"] == target["id"]][0]
        check("通知单条已读：unread 减 1 且该条 read_at 非空",
              nd2["unread"] == unread_before - 1 and row.get("read_at") is not None,
              f"unread {unread_before} -> {nd2['unread']}")
        req("POST", "/notifications/read-all", token=org)
        s, en3 = req("GET", "/notifications?page=1&pageSize=50", token=org)
        check("通知 read-all 仍可用（未读归零）", ok_data(en3)["unread"] == 0,
              str(ok_data(en3)["unread"]))

    # ---- 7. abandon 与 withdraw 分开 ----
    for acc, nick in (("p1aba", "放弃A"), ("p1abb", "放弃B"), ("p1abc", "放弃C"), ("p1abd", "放弃D")):
        register(acc, nickname=nick)
    ta, tb, tc, td = (login(x, "12345678") for x in ("p1aba", "p1abb", "p1abc", "p1abd"))
    abid = make_activity(org, "放弃候补-阶段一", cap=1)
    signup(ta, abid)
    signup(tb, abid)
    signup(tc, abid)
    pb = [p for p in my(tb) if str(p["activity_id"]) == str(abid)][0]
    s, ewd = req("POST", f"/participations/{pb['id']}/withdraw", token=tb)
    check("abandon：候补用户调 withdraw → 失败（400）",
          s == 400 and ewd.get("success") is False, f"{s} {ewd}")
    s, eab = req("POST", f"/participations/{pb['id']}/abandon", token=tb)
    check("abandon：候补用户 abandon → 状态 WITHDRAWN",
          s == 200 and data_of(eab).get("my_status") == "WITHDRAWN", f"{s} {eab}")
    pa = [p for p in my(ta) if str(p["activity_id"]) == str(abid)][0]
    req("POST", f"/participations/{pa['id']}/withdraw", token=ta)
    mc = [p for p in my(tc) if str(p["activity_id"]) == str(abid)][0]
    check("abandon：正式退出后下一候补收到邀请",
          mc["status"] == "INVITED" and mc.get("invitation_id"), str(mc))
    sd, ed = signup(td, abid)
    check("abandon：新候补排队", data_of(ed).get("my_status") == "WAITING", str(data_of(ed)))
    s, eab2 = req("POST", f"/participations/{mc['id']}/abandon", token=tc)
    check("abandon：INVITED 用户 abandon → 状态 WITHDRAWN",
          s == 200 and data_of(eab2).get("my_status") == "WITHDRAWN", f"{s} {eab2}")
    mc2 = [p for p in my(tc) if str(p["activity_id"]) == str(abid)][0]
    check("abandon：邀请失效（无待确认邀请）",
          mc2["status"] == "WITHDRAWN" and not mc2.get("invitation_id"), str(mc2))
    md = [p for p in my(td) if str(p["activity_id"]) == str(abid)][0]
    check("abandon：下一候补收到邀请",
          md["status"] == "INVITED" and md.get("invitation_id"), str(md))

    # ---- 8. 报名时间冲突 ----
    register("p1conf", nickname="冲突用户")
    tconf = login("p1conf", "12345678")
    xid = make_activity(org, "时间冲突X-阶段一", start=P1_START, end=P1_END)
    signup(tconf, xid)
    yid = make_activity(org, "时间冲突Y-阶段一", start=P1_Y_START, end=P1_Y_END)
    s, econf = signup(tconf, yid)
    conflicts = (data_of(econf).get("conflicts") or []) if econf.get("success") is False else []
    titles = [c.get("title") for c in conflicts]
    check("时间冲突：无 confirm 报名重叠活动 → 409、code=CONFLICT、conflicts 含 X 标题",
          s == 409 and econf.get("code") == "CONFLICT"
          and bool(conflicts) and "时间冲突X-阶段一" in titles,
          f"{s} {econf}")
    s, econf2 = signup(tconf, yid, confirm=True)
    check("时间冲突：confirmConflict=true → 报名成功 FORMAL",
          s == 200 and data_of(econf2).get("my_status") == "FORMAL", f"{s} {econf2}")
    zid = make_activity(org, "时间冲突Z-阶段一", start=P1_Z_START, end=P1_Z_END)
    s, ez = signup(tconf, zid)
    check("时间冲突：不重叠活动直接成功",
          s == 200 and data_of(ez).get("my_status") == "FORMAL", f"{s} {ez}")

    # ---- 9. 组织者移出成员 ----
    register("p1rm1", nickname="被移出者")
    register("p1rm2", nickname="候补递补者")
    tr1 = login("p1rm1", "12345678")
    tr2 = login("p1rm2", "12345678")
    rmid = make_activity(org, "移出成员-阶段一", cap=1)
    signup(tr1, rmid)
    signup(tr2, rmid)
    s, eme3 = req("GET", "/me", token=tr1)
    uid1 = str(me_user(eme3).get("id"))
    reason = "多次缺席沟通未果"
    s, enoreason = req("POST", f"/activities/{rmid}/members/{uid1}/remove", token=org, body={})
    check("移出成员：无 reason → 400、code=VALIDATION",
          s == 400 and enoreason.get("code") == "VALIDATION", f"{s} {enoreason}")
    s, enonorg = req("POST", f"/activities/{rmid}/members/{uid1}/remove",
                     token=tr2, body={"reason": reason})
    check("移出成员：非组织者调用 → 400",
          s == 400 and enonorg.get("success") is False, f"{s} {enonorg}")
    s, erm = req("POST", f"/activities/{rmid}/members/{uid1}/remove",
                 token=org, body={"reason": reason})
    check("移出成员：组织者移出成功",
          s == 200 and erm.get("success") is True, f"{s} {erm}")
    m1 = [p for p in my(tr1) if str(p["activity_id"]) == str(rmid)][0]
    m2 = [p for p in my(tr2) if str(p["activity_id"]) == str(rmid)][0]
    # 移出 FORMAL 后 promote 会给下一候补发邀请（INVITED）；若实现直接转正则为 FORMAL。
    check("移出成员：成员状态 WITHDRAWN 且空缺由候补递补",
          m1["status"] == "WITHDRAWN" and m2["status"] in ("INVITED", "FORMAL"), f"{m1} / {m2}")
    # outbox 异步发布（SDD 允许 5 秒内可见，本实现发布任务 500ms）：轮询最多 3 秒。
    msgs = []
    for _ in range(15):
        s, etr1 = req("GET", "/notifications?pageSize=50", token=tr1)
        # notification 表正文列名为 content；兼容 message 键以免接口层改名。
        msgs = [(x.get("content") or x.get("message") or "") for x in ok_data(etr1)["items"]]
        if any(reason in m for m in msgs):
            break
        time.sleep(0.2)
    check("移出成员：被移出者收到含 reason 的通知",
          any(reason in m for m in msgs), str(msgs[:3]))

    # ---- 10. outbox 可见性 ----
    register("p1out", nickname="广播用户")
    tout = login("p1out", "12345678")
    s, eout0 = req("GET", "/notifications?pageSize=50", token=tout)
    base_ids = {x["id"] for x in ok_data(eout0)["items"]}
    oid = make_activity(org, "outbox可见性-阶段一")
    signup(tout, oid)
    visible, waited = False, 0.0
    for _ in range(30):
        s, eout = req("GET", "/notifications?pageSize=50", token=tout)
        if eout.get("success"):
            cur = {x["id"] for x in ok_data(eout)["items"]}
            if cur - base_ids:
                visible = True
                break
        time.sleep(0.1)
        waited += 0.1
    check("outbox：新通知 3 秒内可见（PUBLISHED）", visible and waited <= 3.0,
          f"waited={waited:.1f}s")

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
