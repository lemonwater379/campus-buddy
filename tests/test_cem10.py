#!/usr/bin/env python3
"""阶段三 CEM-10（信用分）验收脚本：出勤结算 / 扣分与加分 / 上下限钳制 / 定版审查 / 更正重算。

运行前置（主会话验收口径，缺一不可）：
  后端以 INVITE_TTL=10、SWEEP_SECONDS=2、CHECKIN_WINDOW_SECONDS=60、
  ATTENDANCE_VERIFY_MINUTES=1、CREDIT_APPEAL_MINUTES=1 启动（核对期与申诉期都调到
  1 分钟；产品默认分别为 1440 与 10080 分钟，口径不变）。
  BASE_URL 默认 http://127.0.0.1:8080（A 版 PG）；B 版传 BASE_URL=http://127.0.0.1:8081。
脚本开头调用 /api/v1/demo/reset，全程使用相对时间，预计耗时约 9 分钟。

除 HTTP 外，本脚本用本地 DB CLI 做两件事：
  ① 结算后直接构造一条出勤更正 revision —— 这是「阶段四申诉复核产生新事实版本」的
     预演（阶段三尚无申诉接口，组织者定版后也无权再改）；
  ② 断言 credit_review / credit_recalc_history 两张内部表的落账（无对外接口）。
PG 走 /tmp/pgsql 的 psql（带 LD_LIBRARY_PATH），MySQL 走便携 mysql 客户端 socket
root 连接，按 BASE_URL 是否含 8081 分支。
"""
import json, os, sys, time, urllib.request, urllib.error
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


def login(acc, pwd="Dazi@2026!"):
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


def verify(org_tok, aid, uid, result):
    s, e = req("PUT", f"/activities/{aid}/attendance/{uid}", token=org_tok,
               body={"result": result, "evidence": ""})
    assert s == 200 and e.get("success"), f"verify {aid}/{uid} {result} failed: {s} {e}"


def do_checkin(org_tok, member_tok, aid):
    s, e = req("GET", f"/activities/{aid}/checkin-code", token=org_tok)
    code = ok_data(e)["code"]
    s, e = req("POST", f"/activities/{aid}/checkins", token=member_tok, body={"code": code})
    assert s == 200 and ok_data(e).get("checkin_at"), f"checkin {aid} failed: {s} {e}"


def main():
    # ---- 准备：重置 + 账号 ----
    try:
        tok0 = login("organizer")
    except AssertionError:
        req("POST", "/register", body={"account": "auditboot", "password": "12345678", "nickname": "审计"})
        tok0 = login("auditboot", "12345678")
    s, env = req("POST", "/demo/reset", token=tok0)
    assert env.get("success"), f"reset failed: {s} {env}"

    org = register("cem10org", "信用组织者")
    seq = register("cem10seq", "成员seq")
    hi = register("cem10hi", "成员hi")
    low = register("cem10low", "成员low")
    rev = register("cem10rev", "成员rev")
    zero1 = register("cem10zero1", "成员zero1")
    zero2 = register("cem10zero2", "成员zero2")
    fix = register("cem10fix", "成员fix")
    seq_id, hi_id, low_id, rev_id = my_id(seq), my_id(hi), my_id(low), my_id(rev)
    zero1_id, zero2_id, fix_id = my_id(zero1), my_id(zero2), my_id(fix)

    # ---- 单一时间波：所有活动共用同一 now，deadline +55s / start +80s / end +260s ----
    now = datetime.now()

    def mk(title):
        return make_activity(org, title, 5,
                             ts(now + timedelta(seconds=55)),
                             ts(now + timedelta(seconds=80)),
                             ts(now + timedelta(seconds=260)))

    a_seq_abs = mk("CEM10seq缺席")
    a_seq_pres = mk("CEM10seq到场")
    a_hi1 = mk("CEM10hi到场1")
    a_hi2 = mk("CEM10hi到场2")
    a_fix_abs = mk("CEM10fix缺席")
    a_fix_pres = mk("CEM10fix到场")
    a_zero = mk("CEM10零分豁免")
    a_rev1 = mk("CEM10复核01")
    a_rev2 = mk("CEM10复核02")
    a_rev3 = mk("CEM10复核03")
    lows = [mk(f"CEM10低分{i:02d}") for i in range(1, 12)]

    # 全部报名断言 FORMAL（同窗多活动走 confirmConflict，本脚本验信用不验冲突）
    pairs = [(seq, a_seq_abs), (seq, a_seq_pres), (hi, a_hi1), (hi, a_hi2),
             (fix, a_fix_abs), (fix, a_fix_pres), (zero1, a_zero), (zero2, a_zero),
             (rev, a_rev1), (rev, a_rev2), (rev, a_rev3)]
    pairs += [(low, x) for x in lows]
    for tok_m, aid in pairs:
        s, e = signup(tok_m, aid)
        assert data_of(e).get("my_status") == "FORMAL", f"signup {aid} failed: {s} {e}"

    # ---- 等 RUNNING（活动长 260s，给足 200s 覆盖报名耗时） ----
    print("  等待活动开始（约 80 秒）……")
    d = wait_status(org, a_seq_abs, "RUNNING", timeout=200)
    check("活动进入 RUNNING", d.get("status") == "RUNNING", str(d.get("status")))

    # ---- 签到：seq→a_seq_pres、hi→a_hi1/a_hi2、fix→a_fix_pres ----
    do_checkin(org, seq, a_seq_pres)
    do_checkin(org, hi, a_hi1)
    do_checkin(org, hi, a_hi2)
    do_checkin(org, fix, a_fix_pres)

    # ---- 等 ENDED ----
    print("  等待活动结束……")
    d = wait_status(org, a_seq_abs, "ENDED", timeout=300)
    check("活动进入 ENDED", d.get("status") == "ENDED", str(d.get("status")))

    # ---- 核对（均为首次结论且不覆盖签到事实，按阶段二规则无需依据；zero1 不核对留 UNVERIFIED） ----
    verify(org, a_seq_abs, seq_id, "ABSENT_VERIFIED")
    verify(org, a_seq_pres, seq_id, "PRESENT")
    verify(org, a_fix_abs, fix_id, "ABSENT_VERIFIED")
    verify(org, a_fix_pres, fix_id, "PRESENT")
    verify(org, a_zero, zero2_id, "EXEMPT")
    for x in (a_rev1, a_rev2, a_rev3):
        verify(org, x, rev_id, "ABSENT_VERIFIED")
    for x in lows:
        verify(org, x, low_id, "ABSENT_VERIFIED")

    # ---- 等定版（核对期配置 1 分钟） ----
    print("  等待核对期届满定版（约 60 秒）……")
    fin = None
    until = time.time() + 180
    while time.time() < until:
        row = att_of(org, a_seq_abs, seq_id)
        if row and row.get("finalized_at"):
            fin = row
            break
        time.sleep(3)
    check("核对期届满定版", fin is not None and fin.get("finalized_at"), str(fin))

    # ---- 申诉期未届满不结算 ----
    d = credit(seq)
    check("申诉期未届满：seq 仍 100 分且无流水",
          d.get("score") == 100 and d["entries"]["total"] == 0, str(d.get("score")))
    d = credit(low)
    check("申诉期未届满：low 无流水", d["entries"]["total"] == 0, str(d["entries"]["total"]))

    # ---- 等结算（申诉期配置 1 分钟） ----
    print("  等待申诉期届满结算（约 60 秒）……")
    d = wait_credit_total(seq, 2, timeout=240)

    # ---- 结算断言：seq 扣分 + 加分 ----
    check("seq 结算后 92 分", d.get("score") == 92, str(d.get("score")))
    ba = by_activity(seq)
    e_abs = ba.get(str(a_seq_abs)) or {}
    check("seq 缺席流水 -10（100→90，ABSENT_VERIFIED）",
          e_abs.get("delta") == -10 and e_abs.get("score_before") == 100
          and e_abs.get("score_after") == 90 and e_abs.get("fact_result") == "ABSENT_VERIFIED",
          str(e_abs))
    e_pres = ba.get(str(a_seq_pres)) or {}
    check("seq 到场流水 +2（90→92，PRESENT）",
          e_pres.get("delta") == 2 and e_pres.get("score_before") == 90
          and e_pres.get("score_after") == 92 and e_pres.get("fact_result") == "PRESENT",
          str(e_pres))

    # ---- 防重：结算不会重复落账 ----
    time.sleep(10)
    d = credit(seq)
    check("结算防重：10 秒后仍 2 条、92 分",
          d["entries"]["total"] == 2 and d.get("score") == 92,
          f"{d['entries']['total']} {d.get('score')}")

    # ---- hi：两条到场 +2，上限钳制在 100 ----
    d = credit(hi)
    hi_items = d["entries"]["items"]
    check("hi 两条到场流水均 +2 且 (100,100)",
          d["entries"]["total"] == 2 and len(hi_items) == 2
          and all(x.get("delta") == 2 and (x.get("score_before"), x.get("score_after")) == (100, 100)
                  for x in hi_items), str(hi_items))
    check("hi 总分 100（上限钳制）", d.get("score") == 100, str(d.get("score")))

    # ---- zero1（UNVERIFIED）与 zero2（EXEMPT）：0 分流水 ----
    d = credit(zero1)
    z1 = d["entries"]["items"][0] if d["entries"]["items"] else {}
    check("zero1 未核对流水 delta=0（UNVERIFIED）",
          d["entries"]["total"] == 1 and z1.get("delta") == 0
          and z1.get("fact_result") == "UNVERIFIED" and d.get("score") == 100, str(d))
    d = credit(zero2)
    z2 = d["entries"]["items"][0] if d["entries"]["items"] else {}
    check("zero2 豁免流水 delta=0（EXEMPT）",
          d["entries"]["total"] == 1 and z2.get("delta") == 0
          and z2.get("fact_result") == "EXEMPT" and d.get("score") == 100, str(d))

    # ---- rev：三条缺席 → 70 ----
    d = credit(rev)
    check("rev 三条缺席流水、总分 70",
          d["entries"]["total"] == 3 and d.get("score") == 70,
          f"{d['entries']['total']} {d.get('score')}")

    # ---- low：11 条缺席，下限钳制在 0 ----
    d = credit(low)
    check("low 十一条流水、总分 0（下限钳制）",
          d["entries"]["total"] == 11 and d.get("score") == 0,
          f"{d['entries']['total']} {d.get('score')}")
    items = list(reversed(d["entries"]["items"]))  # API 新→旧，反转为旧→新
    check("low 旧→新 score_after 序列",
          [x.get("score_after") for x in items] == [90, 80, 70, 60, 50, 40, 30, 20, 10, 0, 0],
          str([x.get("score_after") for x in items]))
    check("low 旧→新 score_before 序列",
          [x.get("score_before") for x in items] == [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0],
          str([x.get("score_before") for x in items]))

    # ---- 分页 ----
    s, e = req("GET", "/me/credit?page=1&pageSize=1", token=low)
    p1 = ok_data(e)
    it1 = (p1.get("entries") or {}).get("items") or []
    check("分页 page1：total=11、1 条",
          p1["entries"]["total"] == 11 and len(it1) == 1, str(p1["entries"]["total"]))
    s, e = req("GET", "/me/credit?page=2&pageSize=1", token=low)
    p2 = ok_data(e)
    it2 = (p2.get("entries") or {}).get("items") or []
    check("分页 page2：1 条且与 page1 不同",
          len(it1) == 1 and len(it2) == 1 and it1[0].get("id") != it2[0].get("id"),
          f"{len(it1)} {len(it2)}")

    # ---- 可见性 ----
    s, e = req("GET", "/me/credit")
    check("未登录访问 /me/credit 被拒", e.get("success") is False, f"{s} {e.get('message')}")
    d = credit(org)
    check("组织者无流水：0 条、100 分",
          d["entries"]["total"] == 0 and d.get("score") == 100,
          f"{d['entries']['total']} {d.get('score')}")
    act_ids = {str(x.get("activity_id")) for x in entries_of(seq)}
    check("seq 流水活动集合仅本人两活动",
          act_ids <= {str(a_seq_abs), str(a_seq_pres)}, str(act_ids))

    # ---- 审查记录（SQL）：rev 定版审查落账且去重 ----
    print("  等待审查记录落账……")
    cnt = "0"
    until = time.time() + 60
    while time.time() < until:
        cnt = sql(f"SELECT COUNT(*) FROM credit_review WHERE user_id={int(rev_id)}")
        if cnt == "1":
            break
        time.sleep(3)
    check("rev 审查记录落账 1 条", cnt == "1", cnt)
    row_s = sql(f"SELECT absence_count, status FROM credit_review WHERE user_id={int(rev_id)}")
    parts = row_s.replace("|", " ").split()
    check("rev 审查记录 absence_count=3、PENDING",
          len(parts) == 2 and parts[0] == "3" and parts[1] == "PENDING", row_s)
    time.sleep(8)
    cnt2 = sql(f"SELECT COUNT(*) FROM credit_review WHERE user_id={int(rev_id)}")
    check("审查记录去重：8 秒后仍 1 条", cnt2 == "1", cnt2)

    # ---- 更正重算（fix；结算后构造新事实版本，预演阶段四申诉复核） ----
    att_row = sql(f"SELECT id, version FROM attendance "
                  f"WHERE activity_id={int(a_fix_abs)} AND user_id={int(fix_id)}")
    att_id, ver = att_row.replace("|", " ").split()
    att_id, ver = int(att_id), int(ver)

    d = credit(fix)
    ba = by_activity(fix)
    fa = ba.get(str(a_fix_abs)) or {}
    check("更正前 fix 92 分、缺席流水 -10、版本一致",
          d.get("score") == 92 and fa.get("delta") == -10 and fa.get("fact_version") == ver,
          f"{d.get('score')} {fa}")

    if "8081" in BASE:
        now_expr, plus7_expr = "NOW()", "NOW() + INTERVAL 7 DAY"
    else:
        now_expr, plus7_expr = "now()", "now() + interval '7 day'"
    sql(f"INSERT INTO attendance_revision(attendance_id, version, actor_id, result, reason, "
        f"available_at, appeal_until) VALUES ({att_id}, {ver + 1}, NULL, 'EXEMPT', "
        f"'申诉复核更正（阶段四通道预演）', {now_expr}, {plus7_expr})")
    sql(f"UPDATE attendance SET result='EXEMPT', version={ver + 1}, updated_at={now_expr} "
        f"WHERE id={att_id}")
    rid = int(sql(f"SELECT id FROM attendance_revision "
                  f"WHERE attendance_id={att_id} AND version={ver + 1}"))

    until = time.time() + 120
    d = credit(fix)
    while time.time() < until and d.get("score") != 100:
        time.sleep(3)
        d = credit(fix)
    check("更正重算后 fix 回到 100 分", d.get("score") == 100, str(d.get("score")))

    ba = by_activity(fix)
    fa = ba.get(str(a_fix_abs)) or {}
    fp = ba.get(str(a_fix_pres)) or {}
    check("更正后缺席流水清零（EXEMPT、新版本、(100,100)）",
          fa.get("delta") == 0 and fa.get("fact_result") == "EXEMPT"
          and fa.get("fact_version") == ver + 1
          and (fa.get("score_before"), fa.get("score_after")) == (100, 100), str(fa))
    check("更正后到场流水保持 +2 且上限钳制",
          fp.get("delta") == 2
          and (fp.get("score_before"), fp.get("score_after")) == (100, 100), str(fp))
    cnt = sql(f"SELECT COUNT(*) FROM credit_recalc_history "
              f"WHERE user_id={int(fix_id)} AND source_revision_id={rid}")
    check("更正重算历史落账 1 条", cnt == "1", cnt)

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
