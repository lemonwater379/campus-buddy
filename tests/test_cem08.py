#!/usr/bin/env python3
"""阶段二 CEM-08（出勤与反馈）验收脚本：签到码 / 签到 / 限流 / 出勤快照与核对 / 定版 / 评价。

运行前置（主会话验收口径，缺一不可）：
  后端以 INVITE_TTL=10、SWEEP_SECONDS=2、CHECKIN_WINDOW_SECONDS=60、
  ATTENDANCE_VERIFY_MINUTES=1 启动（码轮换窗与核对期被调小以便在分钟级跑完；
  产品默认分别为 300 秒与 1440 分钟，口径不变）。
  BASE_URL 默认 http://127.0.0.1:8080（A 版 PG）；B 版传 BASE_URL=http://127.0.0.1:8081。
脚本开头调用 /api/v1/demo/reset，全程使用相对时间，预计耗时约 6 分钟。
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080") + "/api/v1"

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
    return req("POST", f"/activities/{aid}/signup", token=token, body={})


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


def main():
    # ---- 准备：重置 + 账号 ----
    try:
        tok0 = login("organizer")
    except AssertionError:
        req("POST", "/register", body={"account": "auditboot", "password": "12345678", "nickname": "审计"})
        tok0 = login("auditboot", "12345678")
    s, env = req("POST", "/demo/reset", token=tok0)
    assert env.get("success"), f"reset failed: {s} {env}"

    org = register("cem08org", "签到组织者")
    m1 = register("cem08m1", "成员甲")
    m2 = register("cem08m2", "成员乙")
    m3 = register("cem08m3", "成员丙")
    wait1 = register("cem08wait", "候补丁")
    org2 = register("cem08org2", "限流组织者")
    m9 = register("cem08m9", "限流成员")
    org_id, m1_id, m2_id, m3_id = my_id(org), my_id(m1), my_id(m2), my_id(m3)

    now = datetime.now()
    # 活动 A：容量 3，m1/m2/m3 正式、wait1 候补；start +80s，end +260s
    aid = make_activity(org, "CEM08签到核对", 3,
                        ts(now + timedelta(seconds=55)),
                        ts(now + timedelta(seconds=80)),
                        ts(now + timedelta(seconds=260)))
    # 活动 B：限流专用，容量 1，时间窗与 A 基本重合（不同用户，无冲突）
    bid = make_activity(org2, "CEM08限流", 1,
                        ts(now + timedelta(seconds=55)),
                        ts(now + timedelta(seconds=80)),
                        ts(now + timedelta(seconds=260)))

    for t in (m1, m2, m3):
        s, e = signup(t, aid)
        assert data_of(e).get("my_status") == "FORMAL", f"signup A failed: {e}"
    s, e = signup(wait1, aid)
    check("候补者进入 WAITING", data_of(e).get("my_status") == "WAITING", str(data_of(e)))
    s, e = signup(m9, bid)
    assert data_of(e).get("my_status") == "FORMAL", f"signup B failed: {e}"

    # ---- 开始前：读码/签到都应被拒（活动未 RUNNING） ----
    s, e = req("GET", f"/activities/{aid}/checkin-code", token=org)
    check("开始前组织者读码被拒", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")
    s, e = req("POST", f"/activities/{aid}/checkins", token=m2, body={"code": "123456"})
    check("开始前签到被拒", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")

    # ---- 等 RUNNING ----
    print("  等待活动开始（约 80 秒）……")
    d = wait_status(org, aid, "RUNNING")
    check("活动 A 进入 RUNNING", d.get("status") == "RUNNING", str(d.get("status")))
    wait_status(org2, bid, "RUNNING")

    # ---- 读码权限 ----
    s, e = req("GET", f"/activities/{aid}/checkin-code", token=m1)
    check("成员读码被拒（仅组织者）", s == 400 and e.get("success") is False, f"{s}")
    s, e = req("GET", f"/activities/{aid}/checkin-code")
    check("未登录读码被拒", s == 400 and e.get("success") is False, f"{s}")
    s, e = req("GET", f"/activities/{aid}/checkin-code", token=org)
    code_data = ok_data(e)
    code1 = code_data.get("code")
    check("组织者读到 6 位签到码", s == 200 and isinstance(code1, str) and len(code1) == 6
          and code1.isdigit() and code_data.get("seconds_left") is not None, str(code_data))
    wrong = "000000" if code1 != "000000" else "111111"

    # ---- 签到：资格与错码 ----
    s, e = req("POST", f"/activities/{aid}/checkins", token=wait1, body={"code": code1})
    check("候补者签到被拒（非正式成员）", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")
    s, e = req("POST", f"/activities/{aid}/checkins", token=m1, body={"code": wrong})
    check("错码签到被拒", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")

    # ---- m2 正常签到 + 重复幂等 ----
    s, e = req("POST", f"/activities/{aid}/checkins", token=m2, body={"code": code1},
               headers={"Idempotency-Key": "cem08-m2-checkin"})
    d1 = ok_data(e)
    check("m2 正确码签到成功", s == 200 and d1.get("checkin_at") and d1.get("already_checked_in") is False, str(d1))
    s, e = req("POST", f"/activities/{aid}/checkins", token=m2, body={"code": code1},
               headers={"Idempotency-Key": "cem08-m2-checkin"})
    d2 = ok_data(e)
    check("同幂等键重放返回同一签到时间", s == 200 and d2.get("checkin_at") == d1.get("checkin_at"), str(d2))
    s, e = req("POST", f"/activities/{aid}/checkins", token=m2, body={"code": code1})
    d3 = ok_data(e)
    check("重复签到返回原签到时间（业务幂等）",
          s == 200 and d3.get("checkin_at") == d1.get("checkin_at") and d3.get("already_checked_in") is True, str(d3))

    # ---- 限流（活动 B）：连续错 5 次后锁定，正确码也 429 ----
    s, eb = req("GET", f"/activities/{bid}/checkin-code", token=org2)
    bcode = ok_data(eb).get("code")
    bwrong = "000000" if bcode != "000000" else "111111"
    last = None
    for i in range(5):
        last = req("POST", f"/activities/{bid}/checkins", token=m9, body={"code": bwrong})
    check("连续第 5 次错码仍为 400", last[0] == 400, f"{last[0]}")
    s, e = req("POST", f"/activities/{bid}/checkins", token=m9, body={"code": bcode})
    check("锁定后正确码签到返回 429 TOO_MANY_ATTEMPTS",
          s == 429 and e.get("code") == "TOO_MANY_ATTEMPTS", f"{s} {e}")

    # ---- 上一窗码仍可签到（m3） ----
    print("  等待签到码轮换（窗 60 秒）……")
    code2 = code1
    deadline = time.time() + 90
    while time.time() < deadline and code2 == code1:
        time.sleep(3)
        s, e = req("GET", f"/activities/{aid}/checkin-code", token=org)
        if e.get("success"):
            code2 = ok_data(e).get("code")
    check("签到码按窗轮换", code2 != code1, f"{code1} -> {code2}")
    s, e = req("POST", f"/activities/{aid}/checkins", token=m3, body={"code": code1})
    check("上一窗码签到成功", s == 200 and ok_data(e).get("checkin_at"), f"{s} {e}")

    # ---- 等 ENDED ----
    print("  等待活动结束……")
    # 活动全长 260s，前序码轮换等待最长可消耗 ~90s，150s 默认超时会差几秒错过 ENDED，给足 300s。
    d = wait_status(org, aid, "ENDED", timeout=300)
    check("活动 A 进入 ENDED", d.get("status") == "ENDED", str(d.get("status")))

    # ---- 出勤快照与列表权限 ----
    s, e = req("GET", f"/activities/{aid}/attendance", token=org)
    rows = ok_data(e)
    by_user = {str(r["user_id"]): r for r in rows}
    check("快照含 3 名正式成员、不含候补",
          len(rows) == 3 and str(m1_id) in by_user and str(m2_id) in by_user and str(m3_id) in by_user,
          str([r.get("user_id") for r in rows]))
    check("初始出勤为 UNVERIFIED 且签到事实可见",
          by_user[str(m2_id)]["result"] == "UNVERIFIED" and by_user[str(m2_id)].get("checkin_at")
          and by_user[str(m1_id)].get("checkin_at") is None, str(by_user.get(str(m2_id))))
    s, e = req("GET", f"/activities/{aid}/attendance", token=m1)
    mine_rows = ok_data(e)
    check("成员查出勤只见本人行", len(mine_rows) == 1 and str(mine_rows[0]["user_id"]) == str(m1_id), str(mine_rows))
    s, e = req("GET", f"/activities/{aid}/attendance", token=wait1)
    check("候补查出勤为空", ok_data(e) == [], str(ok_data(e)))

    # ---- 核对 ----
    v_m2 = by_user[str(m2_id)]["version"]
    s, e = req("PUT", f"/activities/{aid}/attendance/{m2_id}", token=org,
               body={"result": "PRESENT", "evidence": "", "version": v_m2})
    r = ok_data(e)
    check("有签到核对到场无需依据", s == 200 and r.get("result") == "PRESENT" and r.get("version") == v_m2 + 1, str(r))
    # 出勤结论通知（outbox 发布后可见，轮询 5 秒）
    got = False
    until = time.time() + 5
    while time.time() < until and not got:
        s, e = req("GET", "/notifications?pageSize=50", token=m2)
        items = ok_data(e)["items"]
        got = any("出勤结果" in (it.get("content") or "") and "到场" in (it.get("content") or "") for it in items)
        if not got:
            time.sleep(0.5)
    check("被核对者收到出勤结果通知", got)
    s, e = req("PUT", f"/activities/{aid}/attendance/{m2_id}", token=org,
               body={"result": "EXEMPT", "evidence": "", "version": v_m2})
    check("旧 version 核对返回 409", s == 409 and e.get("code") == "CONFLICT", f"{s} {e.get('code')}")
    s, e = req("PUT", f"/activities/{aid}/attendance/{m2_id}", token=org,
               body={"result": "EXEMPT", "evidence": "", "version": v_m2 + 1})
    check("更正已有结论无依据被拒（VALIDATION）",
          s == 400 and e.get("code") == "VALIDATION", f"{s} {e.get('code')}")
    s, e = req("PUT", f"/activities/{aid}/attendance/{m2_id}", token=org,
               body={"result": "EXEMPT", "evidence": "临时有事，事后已核实", "version": v_m2 + 1})
    check("带依据更正成功", s == 200 and ok_data(e).get("result") == "EXEMPT", f"{s} {e}")
    s, e = req("PUT", f"/activities/{aid}/attendance/{m2_id}", token=org,
               body={"result": "PRESENT", "evidence": "复核签到记录无误", "version": v_m2 + 2})
    check("带依据改回 到场 成功", s == 200 and ok_data(e).get("result") == "PRESENT", f"{s} {e}")
    # 无签到补签到场：无依据拒绝、带依据成功
    s, e = req("PUT", f"/activities/{aid}/attendance/{m1_id}", token=org,
               body={"result": "PRESENT", "evidence": ""})
    check("无签到改判到场无依据被拒", s == 400 and e.get("code") == "VALIDATION", f"{s} {e.get('code')}")
    s, e = req("PUT", f"/activities/{aid}/attendance/{m1_id}", token=org,
               body={"result": "PRESENT", "evidence": "现场纸质签到表有签名"})
    check("无签到带依据补签成功", s == 200 and ok_data(e).get("result") == "PRESENT", f"{s} {e}")
    # 权限与对象校验
    s, e = req("PUT", f"/activities/{aid}/attendance/{m3_id}", token=m1,
               body={"result": "PRESENT", "evidence": "x"})
    check("非组织者核对被拒", s == 400 and e.get("success") is False, f"{s}")
    s, e = req("PUT", f"/activities/{aid}/attendance/{org_id}", token=org,
               body={"result": "PRESENT", "evidence": "x"})
    check("组织者核对本人被拒（由管理员处理）", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")
    s, e = req("PUT", f"/activities/{aid}/attendance/999999", token=org,
               body={"result": "PRESENT", "evidence": "x"})
    check("核对名单外用户被拒", s == 400 and e.get("success") is False, f"{s}")
    s, e = req("PUT", f"/activities/{aid}/attendance/{m3_id}", token=org,
               body={"result": "ABSENT", "evidence": "x"})
    check("非法 result 被拒（VALIDATION）", s == 400 and e.get("code") == "VALIDATION", f"{s} {e.get('code')}")

    # ---- 评价（定版前） ----
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m3, body={"rating": 5, "content": "很好"})
    check("未核对到场（UNVERIFIED）评价被拒", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=wait1, body={"rating": 5, "content": ""})
    check("候补（无出勤）评价被拒", s == 400 and e.get("success") is False, f"{s}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m1, body={"rating": 0, "content": ""})
    check("rating=0 被拒（VALIDATION）", s == 400 and e.get("code") == "VALIDATION", f"{s}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m1, body={"rating": 6, "content": ""})
    check("rating=6 被拒（VALIDATION）", s == 400 and e.get("code") == "VALIDATION", f"{s}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m1, body={"rating": 5, "content": "好" * 501})
    check("评价 501 字被拒（VALIDATION）", s == 400 and e.get("code") == "VALIDATION", f"{s}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m1, body={"rating": 5, "content": "组织得很好"})
    check("到场者评价成功", s == 200 and ok_data(e).get("rating") == 5, f"{s} {e}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m1, body={"rating": 4, "content": "改评：场地稍远"})
    check("7 日内修改评价成功（upsert）", s == 200 and ok_data(e).get("rating") == 4, f"{s} {e}")
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m2, body={"rating": 5, "content": ""})
    check("第二人评价成功", s == 200, f"{s} {e}")
    # 未结束活动不可评价
    now2 = datetime.now()
    cid = make_activity(org, "CEM08未结束", 2,
                        ts(now2 + timedelta(days=5)), ts(now2 + timedelta(days=7)), ts(now2 + timedelta(days=7, hours=2)))
    s, e = req("POST", f"/activities/{cid}/evaluations", token=m1, body={"rating": 5, "content": ""})
    check("未结束活动评价被拒", s == 400 and e.get("success") is False, f"{s}")

    # ---- 汇总与正文可见性 ----
    d = detail(wait1, aid)
    summ = d.get("evaluation_summary") or {}
    check("详情汇总 count=2 avg=4.5", summ.get("count") == 2 and abs(float(summ.get("avg_score")) - 4.5) < 1e-9, str(summ))
    s, e = req("GET", f"/activities/{aid}/evaluations", token=wait1)
    check("无关用户看评价正文被拒", e.get("success") is False, f"{s}")
    s, e = req("GET", f"/activities/{aid}/evaluations", token=org)
    evs = ok_data(e)
    check("组织者可见全部评价正文", len(evs) == 2 and all("content" in x for x in evs), str(len(evs)))
    s, e = req("GET", f"/activities/{aid}/evaluations", token=m1)
    evs = ok_data(e)
    check("本人只见自己评价", len(evs) == 1 and str(evs[0]["user_id"]) == str(m1_id), str(evs))
    d = detail(m1, aid)
    check("详情带本人评价与出勤", (d.get("my_evaluation") or {}).get("rating") == 4
          and (d.get("my_attendance") or {}).get("result") == "PRESENT", str(d.get("my_evaluation")))

    # ---- 定版（核对期配置 1 分钟，等待 sweep 定版） ----
    print("  等待核对期届满定版（约 60 秒）……")
    fin = None
    until = time.time() + 180
    while time.time() < until:
        row = att_of(org, aid, m3_id)
        if row and row.get("finalized_at"):
            fin = row
            break
        time.sleep(3)
    check("届满定版：有签到未核对者定版为 PRESENT",
          fin is not None and fin.get("result") == "PRESENT" and fin.get("finalized_at"), str(fin))
    s, e = req("PUT", f"/activities/{aid}/attendance/{m3_id}", token=org,
               body={"result": "EXEMPT", "evidence": "迟到更正"})
    check("定版后组织者再核对被拒", s == 400 and e.get("success") is False, f"{s} {e.get('message')}")
    # 定版后 m3 已到场，可评价；汇总更新为 3 人、均分 4.0
    s, e = req("POST", f"/activities/{aid}/evaluations", token=m3, body={"rating": 3, "content": "还行"})
    check("定版到场后可评价", s == 200, f"{s} {e}")
    d = detail(wait1, aid)
    summ = d.get("evaluation_summary") or {}
    check("汇总更新 count=3 avg=4.0", summ.get("count") == 3 and abs(float(summ.get("avg_score")) - 4.0) < 1e-9, str(summ))

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
