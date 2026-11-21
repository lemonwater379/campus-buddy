#!/usr/bin/env python3
"""NC-01 并发回归：无论报名、接受邀请和退出如何交错，正式人数不得超过名额。

仅在本地演示环境运行：后端须以 INVITE_TTL=10、SWEEP_SECONDS=2 启动，
并能用本地 DB CLI 查 participation。脚本开头调用 /api/v1/demo/reset（重置演示数据）。
递补只在服务器时间 [08:00, 22:00)（Asia/Shanghai）发邀请；夜间跳过 B/D，
C 仍测重复报名，只跳过依赖邀请的重复接受子场景。所有并发账号均在脚本中批量注册，
账号和昵称带时间戳后缀；种子 organizer 仅负责登录、重置和创建活动。
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080") + "/api/v1"
DEMO_PWD = 'Dazi@2026!'
TEST_PWD = "12345678"
TZ = ZoneInfo("Asia/Shanghai")
INVITE_TTL = 10
SWEEP_SECONDS = 2
PG_ENV = dict(os.environ, LD_LIBRARY_PATH="/tmp/pgsql/usr/lib/x86_64-linux-gnu:/tmp/pgsql/usr/lib/postgresql/16/lib")

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token=None, body=None):
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    request = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None, headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        with exc:
            try:
                return exc.code, json.loads(exc.read())
            except (ValueError, OSError):
                return exc.code, {"success": False, "code": "HTTP_ERROR",
                                  "message": f"HTTP {exc.code}", "data": None}
    except (OSError, ValueError) as exc:
        return 0, {"success": False, "code": "NETWORK_ERROR", "message": str(exc), "data": None}


def ok_data(env):
    assert env.get("success") is True, f"expected success envelope: {env}"
    return env.get("data")


def data_of(env):
    data = env.get("data")
    return data if isinstance(data, dict) else {}


def items_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "events"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def expect_ok(response):
    status, env = response
    assert 200 <= status < 300, f"HTTP {status}: {env}"
    return ok_data(env)


def login(acc, pwd="Dazi@2026!"):
    return expect_ok(req("POST", "/login", body={"account": acc, "password": pwd}))["token"]


def register(acc, nickname, pwd):
    expect_ok(req("POST", "/register", body={"account": acc, "password": pwd, "nickname": nickname}))
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


def activity(org, label, capacity, day_offset):
    today = datetime.now(TZ).date()
    deadline = today + timedelta(days=1 + day_offset)
    start = today + timedelta(days=2 + day_offset)
    data = expect_ok(req("POST", "/activities", token=org, body={
        "title": f"并发回归 {label}", "category": "其他", "description": "并发报名回归",
        "conditions": "", "location": "线上", "capacity": capacity,
        "deadline": f"{deadline}T20:00:00", "start_time": f"{start}T20:00:00",
        "end_time": f"{start}T22:00:00",
    }))
    return int(data["id"])


def signup(token, aid):
    return req("POST", f"/activities/{aid}/signup", token=token)


def withdraw(token, pid):
    return req("POST", f"/participations/{pid}/withdraw", token=token)


def accept(token, iid):
    return req("POST", f"/invitations/{iid}/accept", token=token)


def expect_status(response, wanted, rank=None):
    data = expect_ok(response)
    assert data.get("my_status") == wanted, f"expected {wanted}: {data}"
    if rank is not None:
        assert data.get("my_rank") == rank, f"expected rank {rank}: {data}"


def my_rows(token, aid):
    data = expect_ok(req("GET", "/my?pageSize=100", token=token))
    return [row for row in items_of(data) if str(row["activity_id"]) == str(aid)]


def my_row(token, aid):
    rows = my_rows(token, aid)
    assert len(rows) == 1, f"activity {aid}: expected one participation, found {len(rows)}"
    return rows[0]


def verify_formal(label, org, aid, capacity, expected=None):
    detail = expect_ok(req("GET", f"/activities/{aid}", token=org))
    api_count = int(detail["formal"])
    db_count = int(sql(f"SELECT COUNT(*) FROM participation WHERE activity_id={aid} AND status='FORMAL'"))
    counts = f"详情={api_count} SQL={db_count} 名额={capacity}"
    check(f"{label} 正式人数不超员", max(api_count, db_count) <= capacity, counts)
    check(f"{label} 双口径一致", api_count == db_count, counts)
    if expected is not None:
        check(f"{label} 恰有 {expected} 名正式", api_count == db_count == expected, counts)


def verify_one_formal(label, token, aid):
    me = expect_ok(req("GET", "/me", token=token))
    uid = int(me.get("user", me)["id"])
    api_statuses = [row["status"] for row in my_rows(token, aid)]
    db_statuses = sql(f"SELECT status FROM participation WHERE activity_id={aid} AND user_id={uid}").splitlines()
    check(f"{label} 同账号只留一条记录且为正式", api_statuses == db_statuses == ["FORMAL"],
          f"/my={api_statuses} SQL={db_statuses}")


def race(action, args):
    barrier = threading.Barrier(len(args), timeout=10)

    def fire(arg):
        barrier.wait()
        return action(arg)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args)) as executor:
        return list(executor.map(fire, args))


def report(label, responses, success_status, reject_codes=(400, 403, 404, 409, 410, 422)):
    counts = Counter()
    problems = []
    for status, env in responses:
        my_status = data_of(env).get("my_status")
        if 200 <= status < 300 and env.get("success") is True and my_status == success_status:
            counts["成功"] += 1
        elif 200 <= status < 300 and env.get("success") is True and my_status == "WAITING":
            counts["候补"] += 1
        elif (status in reject_codes and env.get("success") is False and env.get("message")
              and env.get("code") not in (None, "", "HTTP_ERROR", "NETWORK_ERROR")):
            counts["拒绝"] += 1
        else:
            problems.append((status, env.get("code"), env.get("message"), my_status))
    errors_500 = sum(status == 500 for status, _ in responses)
    print(f"{label} 并发回执：成功={counts['成功']} 候补={counts['候补']} 拒绝={counts['拒绝']} "
          f"异常={len(problems)} HTTP 500={'有' if errors_500 else '无'} ({errors_500})")
    check(f"{label} 无 HTTP 500 且回执可判定", not errors_500 and not problems, str(problems) if problems else "")
    return counts


class NightWindow(Exception):
    pass


def require_daylight():
    now = datetime.now(TZ)
    if not 8 <= now.hour < 22:
        raise NightWindow(f"服务器时间 {now:%H:%M:%S} 不在递补邀请窗口 [08:00, 22:00)")


def poll(read, ready, timeout):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if ready(value) or time.monotonic() >= deadline:
            return value
        time.sleep(0.25)


def wait_invitation(token, aid):
    def invited(row):
        return row["status"] == "INVITED" and row.get("invitation_id")

    row = poll(lambda: my_row(token, aid), invited, 3 * SWEEP_SECONDS)
    if not invited(row):
        require_daylight()
        raise AssertionError(f"等不到 INVITED：{row}")
    return row["invitation_id"]


def scenario_a(org, tokens):
    aid = activity(org, "A 最后一席", 4, 0)
    for token in tokens[:3]:
        expect_status(signup(token, aid), "FORMAL")
    replies = race(lambda token: signup(token, aid), tokens[3:])
    counts = report("A", replies, "FORMAL", reject_codes=(400, 409, 422))
    verify_formal("A", org, aid, 4, expected=4)
    check("A 仅一人抢到最后一席，其余 11 人候补或收到明确业务拒绝",
          counts["成功"] == 1 and counts["候补"] + counts["拒绝"] == 11)


def scenario_b(org, tokens):
    require_daylight()
    aid = activity(org, "B 报名与接受递补", 2, 1)
    a, b, c, d = tokens
    for token in (a, b):
        expect_status(signup(token, aid), "FORMAL")
    expect_status(signup(c, aid), "WAITING", rank=1)
    require_daylight()
    expect_status(withdraw(a, my_row(a, aid)["id"]), "WITHDRAWN")
    iid = wait_invitation(c, aid)
    responses = race(lambda op: op(), [lambda: signup(d, aid), lambda: accept(c, iid)])
    report("B", responses, "FORMAL")
    verify_formal("B", org, aid, 2, expected=2)


def scenario_c(org, tokens):
    aid = activity(org, "C 同账号重复提交", 1, 2)
    first, next_up = tokens
    report("C 重复报名", race(lambda token: signup(token, aid), [first] * 6), "FORMAL")
    verify_formal("C 重复报名", org, aid, 1, expected=1)
    verify_one_formal("C 重复报名", first, aid)

    require_daylight()  # 夜间仍完成上面的重复报名检查。
    expect_status(signup(next_up, aid), "WAITING", rank=1)
    expect_status(withdraw(first, my_row(first, aid)["id"]), "WITHDRAWN")
    iid = wait_invitation(next_up, aid)
    report("C 重复接受", race(lambda token: accept(token, iid), [next_up] * 4), "FORMAL")
    verify_formal("C 重复接受", org, aid, 1, expected=1)
    verify_one_formal("C 重复接受", next_up, aid)


def scenario_d(org, tokens):
    require_daylight()
    aid = activity(org, "D 并发退出", 2, 3)
    leaving = []
    for token in tokens[:2]:
        expect_status(signup(token, aid), "FORMAL")
        leaving.append((token, my_row(token, aid)["id"]))
    queue = []
    for rank, token in enumerate(tokens[2:], start=1):
        expect_status(signup(token, aid), "WAITING", rank=rank)
        queue.append(int(my_row(token, aid)["id"]))
    require_daylight()
    counts = report("D", race(lambda pair: withdraw(*pair), leaving), "WITHDRAWN")
    check("D 两名正式成员均成功退出", counts["成功"] == 2)

    # 两个空位最多预留两份邀请；核实第 1、2 位按排队顺序收到邀请。
    # 用持久化发出顺序而非轮询看到的顺序，避免同轮发邀时读接口先后造成误判。
    def issued():
        rows = sql("SELECT i.participation_id FROM invitation i JOIN participation p "
                   f"ON i.participation_id=p.id WHERE p.activity_id={aid} ORDER BY i.issued_at, i.id")
        return [int(pid) for pid in rows.splitlines()]

    expected_order = queue[:2]
    order = poll(issued, lambda ids: len(ids) >= len(expected_order), 3 * SWEEP_SECONDS)
    verify_formal("D", org, aid, 2)
    check("D 递补邀请依候补顺序发出（第 1 位先获邀）", order == expected_order,
          f"候补顺序={queue} 应发邀={expected_order} 实际发邀={order}")


def main():
    stamp = str(time.time_ns() // 1_000_000)
    try:
        try:
            reset_token = login("organizer", DEMO_PWD)
        except AssertionError:
            boot = f"csboot{stamp}"
            reset_token = register(boot, boot, TEST_PWD)
        expect_ok(req("POST", "/demo/reset", token=reset_token))
        org = login("organizer", DEMO_PWD)
        accounts = [f"cs{i:02d}{stamp}" for i in range(26)]
        tokens = [register(acc, acc, TEST_PWD) for acc in accounts]
    except Exception as exc:
        check("重置及注册测试账号", False, str(exc))
    else:
        for label, scenario, batch in (
            ("A", scenario_a, tokens[:15]),
            ("B", scenario_b, tokens[15:19]),
            ("C 重复接受", scenario_c, tokens[19:21]),
            ("D", scenario_d, tokens[21:26]),
        ):
            try:
                scenario(org, batch)
            except NightWindow as exc:
                print("SKIP -", label, str(exc))
            except Exception as exc:
                check(f"{label} 场景执行", False, f"{type(exc).__name__}: {exc}")
    print(f"TOTAL {len(results)} PASS {sum(1 for _,c,_ in results if c)} FAIL {sum(1 for _,c,_ in results if not c)}")
    if any(not cond for _, cond, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
