#!/usr/bin/env python3
"""信用申诉全链验收：缺席定版 → 用户申诉 → 管理员更正/维持 → 信用落账。

仅在可重置的本地测试库运行。后端以 INVITE_TTL=10、SWEEP_SECONDS=2、
CHECKIN_WINDOW_SECONDS=60、ATTENDANCE_VERIFY_MINUTES=1、CREDIT_APPEAL_MINUTES=1
启动（仅测试加速，产品默认不变）。脚本开头调用 /api/v1/demo/reset；重置后 admin
密码为 123456。BASE_URL 默认 http://127.0.0.1:8080（PG），8081 走 MySQL。
全程使用相对时间，预计约 5 分钟。核对期与信用结算申诉期各等约 1 分钟；同一活动的
两条结局共用那一分钟的信用结算门槛，丙在驳回后继续轮询落账，不再另等一分钟。

先让丙申诉阻止其结算；乙须等原 -10 流水落账后再申诉，批准才能真正触发重算历史。
出勤修订允许申诉的 7 日窗口与信用结算门槛（finalized_at + 1 分钟）是两回事。
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080") + "/api/v1"
PG_ENV = dict(os.environ, LD_LIBRARY_PATH="/tmp/pgsql/usr/lib/x86_64-linux-gnu:/tmp/pgsql/usr/lib/postgresql/16/lib")
POLL_INTERVAL = 5
POLL_TIMEOUT = 150
DEMO_PASSWORD = "Dazi@2026!"
MEMBER_PASSWORD = "12345678"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


class StopScenario(Exception):
    """A recorded failure prevents the next dependent step."""


def require(name, cond, detail=""):
    check(name, cond, detail)
    if not cond:
        raise StopScenario


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
        with urllib.request.urlopen(r, timeout=10) as resp:
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


def items_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "events"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def login(acc, pwd="Dazi@2026!"):
    _, env = req("POST", "/login", body={"account": acc, "password": pwd})
    return ok_data(env)["token"]


def register(acc, nickname, pwd):
    _, env = req("POST", "/register", body={"account": acc, "password": pwd, "nickname": nickname})
    ok_data(env)
    return login(acc, pwd)


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


def poll(read, ready):
    until = time.monotonic() + POLL_TIMEOUT
    value = read()
    while not ready(value):
        remaining = until - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(POLL_INTERVAL, remaining))
        value = read()
    return value


def get(path, token):
    _, env = req("GET", path, token=token)
    return ok_data(env)


def my_id(token):
    data = get("/me", token)
    return int((data.get("user") or data)["id"])


def attendance(aid, org):
    return {int(row["user_id"]): row for row in items_of(get(f"/activities/{aid}/attendance", org))}


def credit(token, aid=None):
    data = get("/me/credit?page=1&pageSize=100", token)
    rows = data["entries"]["items"]
    return data["score"], [row for row in rows if aid is None or str(row["activity_id"]) == str(aid)]


def credit_matches(view, fact, result, delta, before, after):
    score, rows = view
    if score != after or len(rows) != 1:
        return False
    row = rows[0]
    return (str(row.get("attendance_id")) == str(fact["id"])
            and str(row.get("fact_version")) == str(fact["version"])
            and (row.get("fact_result"), row.get("delta"), row.get("score_before"), row.get("score_after"))
            == (result, delta, before, after))


def credit_sql(uid, fact, result, delta, before, after, after_cutoff=False):
    att_id = int(fact["id"])
    gate = ""
    if after_cutoff:
        cutoff = ("DATE_ADD(a.finalized_at, INTERVAL 1 MINUTE)" if "8081" in BASE
                  else "a.finalized_at + INTERVAL '1 minute'")
        gate = f" AND e.settled_at >= {cutoff}"
    row = sql("SELECT e.fact_result, e.fact_version, e.delta, e.score_before, e.score_after "
              "FROM credit_entry e JOIN attendance a ON a.id=e.attendance_id "
              f"WHERE e.attendance_id={att_id} AND e.user_id={uid}{gate}")
    return row.replace("|", " ").split() == [result, str(fact["version"]), str(delta), str(before), str(after)]


def pending_appeal(label, tok, uid, fact, body):
    status, env = req("POST", "/appeals", token=tok, body=body)
    data = data_of(env)
    require(f"{label}提交申诉，状态 PENDING（HTTP + SQL）",
            status == 200 and env.get("success") is True and data.get("id")
            and data.get("state") == "PENDING" and str(data.get("attendance_id")) == str(fact["id"])
            and sql("SELECT COUNT(*) FROM appeal a JOIN governance_decision d ON d.id=a.decision_id "
                    "JOIN attendance_revision r ON r.id=d.attendance_revision_id "
                    f"WHERE a.id={int(data['id'])} AND a.applicant_id={uid} AND a.state='PENDING' "
                    f"AND r.attendance_id={int(fact['id'])} AND r.version={int(fact['version'])}") == "1",
            f"{status} {env}")
    return int(data["id"])


def review(label, aid, state, admin, admin_id, body):
    status, env = req("POST", f"/admin/appeals/{aid}/review", token=admin, body=body)
    require(f"管理员复核{label}申诉 → {state}（HTTP + SQL）",
            status == 200 and env.get("success") is True and data_of(env).get("state") == state
            and sql(f"SELECT state FROM appeal WHERE id={aid} AND reviewer_id={admin_id}") == state,
            f"{status} {env}")


def main():
    suffix = str(time.time_ns())
    try:
        bootstrap = login("organizer", DEMO_PASSWORD)
    except AssertionError:
        bootstrap = register(f"acboot{suffix}", "申诉验收引导", MEMBER_PASSWORD)
    status, env = req("POST", "/demo/reset", token=bootstrap)
    require("演示库重置", status == 200 and env.get("success") is True, f"HTTP {status}")

    org = login("organizer", DEMO_PASSWORD)
    admin = login("admin", "123456")
    org_id, admin_id = my_id(org), my_id(admin)
    members = [register(f"ac{idx}{suffix}", f"申诉验收{label}", MEMBER_PASSWORD)
               for idx, label in enumerate("甲乙丙")]
    tok_a, tok_b, tok_c = members
    a_id, b_id, c_id = ids = [my_id(tok) for tok in members]
    baselines = [credit(tok) for tok in members]
    require("甲乙丙信用基线均为 100 分且无流水", baselines == [(100, [])] * 3, str(baselines))
    base_a, base_b, base_c = [score for score, _ in baselines]

    now = datetime.now()
    deadline, start, end = [(now + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S")
                            for seconds in (55, 80, 150)]
    status, env = req("POST", "/activities", token=org, body={
        "title": "信用申诉全链验收", "category": "其他", "description": "出勤及信用复核测试",
        "conditions": "", "location": "线上", "capacity": 3,
        "deadline": deadline, "start_time": start, "end_time": end})
    aid = int(data_of(env).get("id") or 0)
    require("organizer 创建活动（名额 3，HTTP + SQL）",
            status in (200, 201) and env.get("success") is True and aid > 0
            and sql(f"SELECT capacity FROM activity WHERE id={aid} AND organizer_id={org_id}") == "3",
            f"{status} {env}")
    states = [req("POST", f"/activities/{aid}/signup", token=tok, body={}) for tok in members]
    users = ",".join(map(str, ids))
    require("甲乙丙报名均为 FORMAL（HTTP + SQL）",
            all(s == 200 and e.get("success") is True and data_of(e).get("my_status") == "FORMAL"
                for s, e in states)
            and sql(f"SELECT COUNT(*) FROM participation WHERE activity_id={aid} "
                    f"AND user_id IN ({users}) AND status='FORMAL'") == "3", str(states))

    activity_path = f"/activities/{aid}"
    for want in ("RUNNING", "ENDED"):
        detail = poll(lambda: get(activity_path, org), lambda data: data.get("status") == want)
        require(f"活动进入 {want}（HTTP + SQL）", detail.get("status") == want
                and sql(f"SELECT status FROM activity WHERE id={aid}") == want, str(detail.get("status")))
        if want == "RUNNING":
            code = get(f"{activity_path}/checkin-code", org).get("code")
            require("组织者取得有效签到码", isinstance(code, str) and bool(code), str(code))
            status, env = req("POST", f"{activity_path}/checkins", token=tok_a, body={"code": code})
            require("仅甲签到，乙丙无签到（HTTP + SQL）",
                    status == 200 and env.get("success") is True and data_of(env).get("checkin_at")
                    and sql(f"SELECT user_id FROM checkin WHERE activity_id={aid}") == str(a_id),
                    f"{status} {env}")

    rows = attendance(aid, org)
    require("出勤快照与三人的签到事实一致", set(rows) == set(ids)
            and bool(rows[a_id].get("checkin_at")) and not rows[b_id].get("checkin_at")
            and not rows[c_id].get("checkin_at"), str(rows))
    marks = {a_id: "PRESENT", b_id: "ABSENT_VERIFIED", c_id: "ABSENT_VERIFIED"}
    for label, uid in zip("甲乙丙", ids):
        fact = rows[uid]
        version = int(fact["version"]) + 1
        expected = marks[uid]
        status, env = req("PUT", f"{activity_path}/attendance/{uid}", token=org,
                          body={"result": expected, "evidence": "", "version": version - 1})
        require(f"组织者标记{label}：{expected}（HTTP + SQL）",
                status == 200 and env.get("success") is True and data_of(env).get("result") == expected
                and sql(f"SELECT result FROM attendance WHERE id={int(fact['id'])} "
                        f"AND version={version} AND decided_by={org_id}") == expected,
                f"{status} {env}")

    rows = poll(lambda: attendance(aid, org), lambda data: all(data.get(uid, {}).get("finalized_at") for uid in ids))
    require("三人出勤定版（HTTP + SQL）",
            all(rows.get(uid, {}).get("finalized_at") and rows[uid].get("result") == marks[uid] for uid in ids)
            and sql(f"SELECT COUNT(*) FROM attendance WHERE activity_id={aid} "
                    f"AND user_id IN ({users}) AND finalized_at IS NOT NULL") == "3", str(rows))
    fact_a, fact_b, fact_c = [rows[uid] for uid in ids]
    batt, catt = int(fact_b["id"]), int(fact_c["id"])
    early_b, early_c = credit(tok_b, aid), credit(tok_c, aid)
    require("刚定版乙丙仍为基线、无本活动流水（HTTP + SQL）",
            early_b == (base_b, []) and early_c == (base_c, [])
            and sql(f"SELECT COUNT(*) FROM credit_entry WHERE attendance_id IN ({batt},{catt})") == "0",
            f"乙={early_b} 丙={early_c}")

    case_c = pending_appeal("丙", tok_c, c_id, fact_c,
                            {"attendance_id": catt, "reason": "请复核是否有补充到场凭证"})
    first_b = poll(lambda: credit(tok_b, aid), lambda view: bool(view[1]))
    require("乙原缺席流水结算 -10，为回滚建立前提（HTTP + SQL）",
            credit_matches(first_b, fact_b, "ABSENT_VERIFIED", -10, base_b, base_b - 10)
            and credit_sql(b_id, fact_b, "ABSENT_VERIFIED", -10, base_b, base_b - 10, after_cutoff=True),
            str(first_b))
    body_b = {"attendance_id": batt, "reason": "本人到场但未扫码，请复核现场记录"}
    case_b = pending_appeal("乙", tok_b, b_id, fact_b, body_b)
    status, env = req("POST", "/appeals", token=tok_b, body=body_b)
    print(f"OBSERVE - 乙重复申诉 HTTP {status} success={env.get('success')} "
          f"duplicate={data_of(env).get('duplicate')} id={data_of(env).get('id')}")
    same_fact = [row for row in items_of(get("/appeals/mine?page=1&pageSize=100", tok_b))
                 if str(row.get("attendance_id")) == str(batt)]
    count = sql("SELECT COUNT(*) FROM appeal a JOIN governance_decision d ON d.id=a.decision_id "
                "JOIN attendance_revision r ON r.id=d.attendance_revision_id "
                f"WHERE r.attendance_id={batt} AND r.version={int(fact_b['version'])}")
    require("乙重复提交同一事实后仍只有原申诉单（HTTP + SQL）",
            [str(row.get("id")) for row in same_fact] == [str(case_b)] and count == "1",
            f"列表={len(same_fact)} SQL={count}")

    review("乙", case_b, "CORRECTED", admin, admin_id,
           {"outcome": "CORRECT", "new_result": "PRESENT", "result": "复核现场记录，确认到场"})
    revised = attendance(aid, org).get(b_id, {})
    new_version = int(fact_b["version"]) + 1
    require("乙出勤更正为 PRESENT、事实版本 +1（HTTP + SQL）",
            str(revised.get("id")) == str(batt) and revised.get("result") == "PRESENT"
            and str(revised.get("version")) == str(new_version)
            and sql(f"SELECT result FROM attendance WHERE id={batt} AND version={new_version} "
                    f"AND decided_by={admin_id}") == "PRESENT", str(revised))
    corrected = poll(lambda: credit(tok_b, aid),
                     lambda view: any(str(row.get("fact_version")) == str(new_version) for row in view[1]))
    require("乙回到基线、原 -10 流水改为 +2（HTTP + SQL）",
            credit_matches(corrected, revised, "PRESENT", 2, base_b, base_b)
            and credit_sql(b_id, revised, "PRESENT", 2, base_b, base_b), str(corrected))
    neg_b = sql("SELECT COUNT(*) FROM credit_entry "
                f"WHERE attendance_id={batt} AND fact_result='ABSENT_VERIFIED' AND delta=-10")
    check("乙无 -10 缺席流水残留（SQL）", neg_b == "0", neg_b)
    recalc = sql("SELECT COUNT(*) FROM credit_recalc_history h "
                 "JOIN attendance_revision r ON r.id=h.source_revision_id "
                 f"WHERE h.user_id={b_id} AND r.attendance_id={batt} "
                 f"AND r.version={new_version} AND r.result='PRESENT'")
    check("乙更正重算历史与新事实版本一一对应（SQL）", recalc == "1", recalc)

    held = credit(tok_c, aid)
    require("申诉期已满但丙尚待复核，结算暂停（HTTP + SQL）", held == (base_c, [])
            and sql(f"SELECT state FROM appeal WHERE id={case_c}") == "PENDING"
            and sql(f"SELECT COUNT(*) FROM credit_entry WHERE attendance_id={catt}") == "0", str(held))
    review("丙", case_c, "UPHELD", admin, admin_id, {"outcome": "UPHOLD", "result": "未能证明到场，维持缺席"})
    unchanged = attendance(aid, org).get(c_id, {})
    require("丙出勤仍为 ABSENT_VERIFIED、事实版本不变（HTTP + SQL）",
            str(unchanged.get("id")) == str(catt) and unchanged.get("result") == "ABSENT_VERIFIED"
            and unchanged.get("version") == fact_c["version"]
            and sql(f"SELECT result FROM attendance WHERE id={catt} AND version={int(fact_c['version'])}")
            == "ABSENT_VERIFIED", str(unchanged))
    upheld = poll(lambda: credit(tok_c, aid), lambda view: bool(view[1]))
    check("丙驳回后结算 -10，流水不早于申诉期满（HTTP + SQL）",
          credit_matches(upheld, fact_c, "ABSENT_VERIFIED", -10, base_c, base_c - 10)
          and credit_sql(c_id, fact_c, "ABSENT_VERIFIED", -10, base_c, base_c - 10, after_cutoff=True),
          str(upheld))
    control = poll(lambda: credit(tok_a, aid), lambda view: bool(view[1]))
    check("甲正常到场流水 +2，分数在 100 封顶（HTTP + SQL）",
          credit_matches(control, fact_a, "PRESENT", 2, base_a, base_a)
          and credit_sql(a_id, fact_a, "PRESENT", 2, base_a, base_a), str(control))


if __name__ == "__main__":
    try:
        main()
    except StopScenario:
        pass
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
        check("验收执行异常", False, f"{type(exc).__name__}: {exc}")
    print(f"TOTAL {len(results)} PASS {sum(1 for _,c,_ in results if c)} FAIL {sum(1 for _,c,_ in results if not c)}")
    if any(not condition for _, condition, _ in results):
        sys.exit(1)
