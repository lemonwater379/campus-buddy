#!/usr/bin/env python3
"""管理员 CEM-09 全流程 HTTP 回归，只使用 Python 标准库。

与 test_cem09.py 相同，后端须设置 INVITE_TTL=10、SWEEP_SECONDS=2、
CHECKIN_WINDOW_SECONDS=60、ATTENDANCE_VERIFY_MINUTES=1、CREDIT_APPEAL_MINUTES=1。
本脚本开头经授权 POST /api/v1/demo/reset，会重置演示数据。reset 后
admin/admin2 密码为 123456，与其 login 调用参数一致。
演示 organizer 密码为 Dazi@2026!；一次性注册账号密码为
12345678。BASE_URL 默认 http://127.0.0.1:8080，也可传
http://127.0.0.1:8081。所有一次性账号带本轮时间戳后缀。

仅创建一场活动。已知下架未结束活动会将状态改为 CANCELLED，而 relist 只清
下架标记、不恢复状态。本测试仍严格要求原活动上架后可报名且 my_status 为
FORMAL；不重开活动、不接受 CANCELLED，也不把已知缺陷改成预期通过。
业务或报名失败会保留结果，并继续独立的封禁、解封与五类审计检查。
不输出 token、密码、请求/响应正文、环境变量或原始异常文本。
"""

import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request


BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080") + "/api/v1"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


class CheckFailure(Exception):
    def __init__(self, kind="ASSERTION_FAILED", status=None):
        super().__init__()
        self.kind = kind
        self.status = status


def require(cond, kind="ASSERTION_FAILED", status=None):
    if not cond:
        raise CheckFailure(kind, status)


def safe_exception(exc):
    if isinstance(exc, CheckFailure):
        prefix = f"HTTP {exc.status} " if exc.status is not None else ""
        return prefix + exc.kind
    return "SAFE_TYPE=" + type(exc).__name__


def attempt(name, operation, dependencies=()):
    if any(value is None for value in dependencies):
        check(name, False, "DEPENDENCY_MISSING")
        return None
    try:
        value = operation()
        check(name, True)
        return value
    except Exception as exc:
        check(name, False, safe_exception(exc))
        return None


def decode_envelope(raw):
    try:
        envelope = json.loads(raw.decode("utf-8"))
        if isinstance(envelope, dict):
            return envelope
    except (UnicodeError, ValueError, TypeError):
        pass
    return {"success": False, "code": "HTTP_ERROR"}


def req(method, path, token=None, body=None):
    """Preserve HTTPError business envelopes; never log credentials or bodies."""
    headers = {"Accept": "application/json"}
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        BASE + path, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, decode_envelope(response.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            with exc:
                return status, decode_envelope(exc.read())
        except Exception:
            return status, {"success": False, "code": "HTTP_ERROR"}
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, {"success": False, "code": "NETWORK_ERROR"}
    except Exception:
        return 0, {"success": False, "code": "NETWORK_ERROR"}


def ok_data(envelope):
    assert isinstance(envelope, dict)
    assert envelope.get("success") is True
    assert "data" in envelope
    return envelope["data"]


def data_of(envelope):
    data = ok_data(envelope)
    require(isinstance(data, (dict, list)), "DATA_SHAPE")
    return data


def strict_object(value):
    require(isinstance(value, dict), "OBJECT_SHAPE")
    return value


def items_of(envelope):
    value = data_of(envelope)
    for _ in range(4):
        if isinstance(value, list):
            require(all(isinstance(row, dict) for row in value), "LIST_ROW_SHAPE")
            return value
        require(isinstance(value, dict), "LIST_SHAPE")
        keys = [key for key in ("items", "events") if key in value]
        require(len(keys) == 1, "LIST_WRAPPER_SHAPE")
        value = value[keys[0]]
    raise CheckFailure("LIST_WRAPPER_SHAPE")


def success_envelope(method, path, token=None, body=None):
    status, envelope = req(method, path, token, body)
    require(200 <= status < 300, "HTTP_STATUS", status)
    require(
        isinstance(envelope, dict)
        and envelope.get("success") is True
        and "data" in envelope,
        "SUCCESS_ENVELOPE",
        status,
    )
    return envelope


def get_object(path, token):
    return strict_object(data_of(success_envelope("GET", path, token)))


def get_items(path, token):
    return items_of(success_envelope("GET", path, token))


def write_success(path, token=None, body=None):
    ok_data(success_envelope("POST", path, token, body))
    return True


def positive_id(value):
    if isinstance(value, bool):
        raise CheckFailure("POSITIVE_ID_SHAPE")
    if isinstance(value, int):
        require(value > 0, "POSITIVE_ID_SHAPE")
        return value
    require(
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and not value.startswith("0"),
        "POSITIVE_ID_SHAPE",
    )
    parsed = int(value)
    require(parsed > 0, "POSITIVE_ID_SHAPE")
    return parsed


def same_id(value, expected):
    try:
        return positive_id(value) == positive_id(expected)
    except (CheckFailure, ValueError, TypeError):
        return False


def unwrapped_object(data, key):
    obj = strict_object(data)
    if key in obj and "id" not in obj:
        return strict_object(obj[key])
    return obj


def iso_datetime(value):
    require(
        isinstance(value, str)
        and bool(value.strip())
        and len(value) >= 16
        and value[10] in ("T", " "),
        "ISO_DATETIME_SHAPE",
    )
    try:
        return dt.datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        raise CheckFailure("ISO_DATETIME_SHAPE") from None


def denied(method, path, token=None, body=None, statuses=(400, 401, 403, 404, 409),
           semantic=None):
    status, envelope = req(method, path, token, body)
    require(
        status in statuses and status in (400, 401, 403, 404, 409),
        "EXPECTED_BUSINESS_REJECTION",
        status,
    )
    require(isinstance(envelope, dict), "ERROR_ENVELOPE_SHAPE", status)
    code = envelope.get("code")
    require(
        envelope.get("success") is False
        and isinstance(code, str)
        and bool(code.strip())
        and code not in ("NETWORK_ERROR", "HTTP_ERROR"),
        "BUSINESS_ERROR_CODE",
        status,
    )
    if semantic is not None:
        require(semantic(status, envelope), "REJECTION_SEMANTICS", status)
    return True


ACCOUNT_LABELS = {"organizer": "organizer", "admin": "admin", "admin2": "admin2"}
LOGIN_COUNTS = {}


def login(acc, pwd="Dazi@2026!"):
    label = ACCOUNT_LABELS[acc]
    LOGIN_COUNTS[label] = LOGIN_COUNTS.get(label, 0) + 1

    def authenticate():
        envelope = success_envelope(
            "POST", "/login", body={"account": acc, "password": pwd}
        )
        data = strict_object(data_of(envelope))
        token = data.get("token")
        require(isinstance(token, str) and bool(token.strip()), "TOKEN_SHAPE")
        return token

    return attempt(f"{label}.login.{LOGIN_COUNTS[label]}", authenticate)


def read_me(token, account, nickname=None, admin=None, expected_id=None,
            active=False):
    user = unwrapped_object(get_object("/me", token), "user")
    positive_id(user.get("id"))
    require(user.get("account") == account, "ACCOUNT_MISMATCH")
    if nickname is not None:
        require(user.get("nickname") == nickname, "NICKNAME_MISMATCH")
    if admin is not None:
        require(user.get("is_admin") is admin, "ADMIN_FLAG_MISMATCH")
    if expected_id is not None:
        require(same_id(user.get("id"), expected_id), "USER_ID_MISMATCH")
    if active:
        require(user.get("status") == "ACTIVE", "USER_STATUS_MISMATCH")
        require(user.get("banned") is False, "BANNED_FLAG_MISMATCH")
    return user


def register(acc, nickname, pwd):
    label = ACCOUNT_LABELS[acc]
    attempt(
        f"{label}.register",
        lambda: write_success(
            "/register", body={"account": acc, "password": pwd, "nickname": nickname}
        ),
    )
    token = login(acc, pwd)
    user = attempt(
        f"{label}.me_after_register",
        lambda: read_me(token, acc, nickname, admin=False),
        (token,),
    )
    return {"token": token, "id": positive_id(user["id"]) if user is not None else None,
            "account": acc, "nickname": nickname}


def overview(token):
    data = get_object("/admin/overview", token)
    for key in ("complaints_pending", "appeals_pending", "recovery_pending",
                "credit_reviews_pending", "bans_active", "bans_expired_pending"):
        value = data.get(key)
        require(
            key in data
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0,
            "OVERVIEW_COUNT_SHAPE",
        )
    return data


def seed_admins(rows, admin_user, admin2_user):
    for account, user in (("admin", admin_user), ("admin2", admin2_user)):
        matches = [row for row in rows if row.get("account") == account]
        require(len(matches) == 1, "SEED_ADMIN_MISSING_OR_DUPLICATE")
        row = matches[0]
        require(same_id(row.get("id"), user["id"]), "SEED_ADMIN_ID_MISMATCH")
        if "is_admin" in row:
            require(row["is_admin"] is True, "SEED_ADMIN_FLAG_MISMATCH")
    return True


def activity_detail(token, aid):
    data = get_object(f"/activities/{aid}", token)
    activity = unwrapped_object(data, "activity")
    require(same_id(activity.get("id"), aid), "ACTIVITY_ID_MISMATCH")
    return activity, data


def created_activity(token, payload):
    data = data_of(success_envelope("POST", "/activities", token, payload))
    return positive_id(unwrapped_object(data, "activity").get("id"))


def activity_create_readback(token, aid, publisher_id, payload):
    activity, _ = activity_detail(token, aid)
    require(same_id(activity.get("organizer_id"), publisher_id), "ORGANIZER_ID_MISMATCH")
    for key in ("title", "category", "description", "conditions", "location"):
        require(key in activity and activity[key] == payload[key], "ACTIVITY_FIELD_MISMATCH")
    require(type(activity.get("capacity")) is int and activity["capacity"] == 5,
            "CAPACITY_MISMATCH")
    for key in ("deadline", "start_time", "end_time"):
        require(iso_datetime(activity.get(key)) == iso_datetime(payload[key]),
                "ACTIVITY_TIME_MISMATCH")
    require(activity.get("delisted") is False, "DELISTED_FLAG_MISMATCH")
    return activity


def delisted_readback(token, aid, expected):
    activity, _ = activity_detail(token, aid)
    require(activity.get("delisted") is expected, "DELISTED_FLAG_MISMATCH")
    return activity


def complaint_create(token, aid, reason):
    data = data_of(success_envelope(
        "POST", "/complaints", token,
        {"activity_id": int(aid), "category": "违规内容", "reason": reason},
    ))
    return positive_id(unwrapped_object(data, "complaint").get("id"))


def complaint_readback(token, path, cid, aid, reason, state, result=None):
    rows = get_items(path, token)
    matches = [row for row in rows if same_id(row.get("id"), cid)]
    require(len(matches) == 1, "COMPLAINT_MISSING_OR_DUPLICATE")
    row = matches[0]
    require(same_id(row.get("activity_id"), aid), "COMPLAINT_ACTIVITY_MISMATCH")
    require(row.get("reason") == reason, "COMPLAINT_REASON_MISMATCH")
    require(row.get("state") == state, "COMPLAINT_STATE_MISMATCH")
    if result is not None:
        require(row.get("result") == result, "COMPLAINT_RESULT_MISMATCH")
    return row


def signup(token, aid):
    data = strict_object(data_of(success_envelope(
        "POST", f"/activities/{aid}/signup", token, {"confirmConflict": True}
    )))
    require(data.get("my_status") == "FORMAL", "SIGNUP_NOT_FORMAL")
    return data


def signup_readback(token, aid):
    activity, data = activity_detail(token, aid)
    status_source = data if "my_status" in data else activity
    require(status_source.get("my_status") == "FORMAL", "SIGNUP_NOT_FORMAL")
    require(isinstance(activity.get("status"), str)
            and activity["status"] != "CANCELLED", "ACTIVITY_CANCELLED_OR_MALFORMED")
    return activity


def activity_scenario(admin_token, publisher, reporter, state, suffix):
    tomorrow = (dt.datetime.now() + dt.timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    start = tomorrow + dt.timedelta(days=1)
    payload = {
        "title": "管理员全流程-" + suffix,
        "category": "其他",
        "description": state["marker"],
        "conditions": "",
        "location": "线上",
        "capacity": 5,
        "deadline": tomorrow.isoformat(timespec="seconds"),
        "start_time": start.isoformat(timespec="seconds"),
        "end_time": (start + dt.timedelta(hours=2)).isoformat(timespec="seconds"),
    }
    a_token, b_token = publisher["token"], reporter["token"]
    aid = attempt("activity.create", lambda: created_activity(a_token, payload), (a_token,))
    state["aid"] = aid
    attempt("activity.create.readback",
            lambda: activity_create_readback(a_token, aid, publisher["id"], payload),
            (a_token, aid, publisher["id"]))

    cid = attempt("complaint.create",
                  lambda: complaint_create(b_token, aid, state["complaint_reason"]),
                  (b_token, aid))
    state["cid"] = cid
    attempt("complaint.pending.readback", lambda: complaint_readback(
        admin_token, "/admin/complaints?state=PENDING&page=1&pageSize=100",
        cid, aid, state["complaint_reason"], "PENDING"), (admin_token, cid, aid))

    attempt("activity.delist", lambda: write_success(
        f"/admin/activities/{aid}/delist", admin_token,
        {"reason": state["delist_reason"]}), (admin_token, aid))
    attempt("activity.delist.publisher_readback",
            lambda: delisted_readback(a_token, aid, True), (a_token, aid))
    attempt("activity.delist.reporter_denied", lambda: denied(
        "GET", f"/activities/{aid}", b_token, statuses=(400, 401, 403, 404),
        semantic=lambda status, env: status != 400 or (
            env.get("code") == "ERROR" and env.get("message") == "活动已下架"
        )), (b_token, aid))

    attempt("complaint.handle", lambda: write_success(
        f"/admin/complaints/{cid}/handle", admin_token,
        {"outcome": "RESOLVED", "result": state["handle_result"]}), (admin_token, cid))
    attempt("complaint.handle.reporter_readback", lambda: complaint_readback(
        b_token, "/complaints/mine?page=1&pageSize=100", cid, aid,
        state["complaint_reason"], "RESOLVED", state["handle_result"]),
        (b_token, cid, aid))
    attempt("complaint.handle.admin_readback", lambda: complaint_readback(
        admin_token, "/admin/complaints?state=RESOLVED&page=1&pageSize=100", cid, aid,
        state["complaint_reason"], "RESOLVED", state["handle_result"]),
        (admin_token, cid, aid))

    attempt("activity.relist", lambda: write_success(
        f"/admin/activities/{aid}/relist", admin_token,
        {"reason": state["relist_reason"]}), (admin_token, aid))
    attempt("activity.relist.reporter_readback",
            lambda: delisted_readback(b_token, aid, False), (b_token, aid))
    # Deliberately require the original activity to be usable; preserve failures.
    attempt("activity.signup", lambda: signup(b_token, aid), (b_token, aid))
    attempt("activity.signup.reporter_readback", lambda: signup_readback(b_token, aid),
            (b_token, aid))


def ban_impact(token, user_id):
    data = get_object(f"/admin/users/{user_id}/ban-impact", token)
    for key in ("waiting", "future_formal", "organized_active", "invited"):
        require(key in data and isinstance(data[key], list), "BAN_IMPACT_LIST_SHAPE")
    return data


def ban_apply(token, user_id, reason):
    data = strict_object(data_of(success_envelope(
        "POST", f"/admin/users/{user_id}/ban", token, {"days": 7, "reason": reason}
    )))
    return positive_id(data.get("decision_id"))


def ban_scenario(admin_token, state, suffix):
    account = "af_ban_" + suffix
    nickname = "全流封禁" + suffix[-9:]
    ACCOUNT_LABELS[account] = "ban_target"
    target = register(account, nickname, "12345678")
    user_id, old_token = target["id"], target["token"]
    state["banid"] = user_id
    attempt("ban.impact", lambda: ban_impact(admin_token, user_id), (admin_token, user_id))
    attempt("ban.apply", lambda: ban_apply(admin_token, user_id, state["ban_reason"]),
            (admin_token, user_id))
    attempt("ban.old_token.me_denied", lambda: denied(
        "GET", "/me", old_token, statuses=(400, 401, 403)), (old_token, user_id))
    attempt("ban.login_denied", lambda: denied(
        "POST", "/login",
        body={"account": account, "password": "12345678"},
        statuses=(400, 401, 403),
        semantic=lambda status, env: isinstance(env.get("message"), str)
        and "封禁" in env["message"] and state["ban_reason"] in env["message"]),
        (user_id,))

    attempt("ban.lift", lambda: write_success(
        f"/admin/users/{user_id}/unban", admin_token,
        {"reason": state["unban_reason"]}), (admin_token, user_id))
    new_token = login(account, "12345678")
    attempt("ban_target.me_after_unban", lambda: read_me(
        new_token, account, nickname, admin=False, expected_id=user_id, active=True),
        (new_token, user_id))


def all_actions(token):
    rows = []
    seen_ids = set()
    page = 1
    expected_total = None
    page_size = 100
    while True:
        envelope = success_envelope(
            "GET", f"/admin/actions?page={page}&pageSize={page_size}", token
        )
        data = strict_object(data_of(envelope))
        require("items" in data and isinstance(data["items"], list), "AUDIT_ITEMS_SHAPE")
        batch = items_of(envelope)
        for key in ("page", "pageSize", "total"):
            require(type(data.get(key)) is int, "AUDIT_PAGINATION_SHAPE")
        require(data["page"] == page and data["pageSize"] == page_size
                and data["total"] >= 0, "AUDIT_PAGINATION_MISMATCH")
        if expected_total is None:
            expected_total = data["total"]
        require(data["total"] == expected_total, "AUDIT_TOTAL_CHANGED")
        require(len(batch) == min(page_size, max(0, expected_total - (page - 1) * page_size)),
                "AUDIT_PAGE_LENGTH_MISMATCH")
        for row in batch:
            row_id = positive_id(row.get("id"))
            require(row_id not in seen_ids, "AUDIT_DUPLICATE_ROW")
            seen_ids.add(row_id)
        rows.extend(batch)
        if page * page_size >= expected_total:
            break
        page += 1
    require(len(rows) == expected_total, "AUDIT_INCOMPLETE_PAGINATION")
    return rows


def action_match(rows, actor_id, action, target_type, target_id, reason):
    matches = [row for row in rows
               if row.get("action") == action
               and row.get("target_type") == target_type
               and same_id(row.get("target_id"), target_id)
               and same_id(row.get("actor_id"), actor_id)
               and row.get("reason") == reason]
    require(bool(matches), "AUDIT_ACTION_MISSING")
    # GovernanceService.handleComplaint logs its resultText in reason, not detail.
    for row in matches:
        iso_datetime(row.get("created_at"))
    return True


def audit_scenario(admin_token, admin_user, state):
    rows = attempt("audit.actions.pagination", lambda: all_actions(admin_token), (admin_token,))
    actor_id = positive_id(admin_user["id"]) if admin_user is not None else None
    expected = (
        ("DELIST_ACTIVITY", "ACTIVITY", state["aid"], state["delist_reason"]),
        ("RELIST_ACTIVITY", "ACTIVITY", state["aid"], state["relist_reason"]),
        ("BAN_USER", "USER", state["banid"], state["ban_reason"]),
        ("UNBAN_USER", "USER", state["banid"], state["unban_reason"]),
        ("COMPLAINT_HANDLE", "COMPLAINT", state["cid"], state["handle_result"]),
    )
    for action, target_type, target_id, reason in expected:
        attempt("audit." + action,
                lambda action=action, target_type=target_type, target_id=target_id,
                reason=reason: action_match(rows, actor_id, action, target_type, target_id, reason),
                (rows, actor_id, target_id))


def run_flow():
    reset_token = login('organizer', 'Dazi@2026!')
    reset_done = attempt("reset.authorized",
                         lambda: write_success("/demo/reset", reset_token), (reset_token,))
    if reset_done is None:
        return
    organizer = login('organizer', 'Dazi@2026!')
    attempt("organizer.me_after_reset", lambda: read_me(organizer, "organizer"), (organizer,))

    admin_token = login('admin', '123456')
    admin_user = attempt("admin.me", lambda: read_me(admin_token, "admin", admin=True),
                         (admin_token,))
    admin2_token = login("admin2", "123456")
    admin2_user = attempt("admin2.me", lambda: read_me(admin2_token, "admin2", admin=True),
                          (admin2_token,))

    attempt("admin.overview.six_counts", lambda: overview(admin_token), (admin_token,))
    attempt("admin.complaints.pending", lambda: get_items(
        "/admin/complaints?state=PENDING&page=1&pageSize=100", admin_token), (admin_token,))
    attempt("admin.appeals.pending", lambda: get_items(
        "/admin/appeals?state=PENDING&page=1&pageSize=100", admin_token), (admin_token,))
    admins = attempt("admin.admins.list", lambda: get_items("/admin/admins", admin_token),
                     (admin_token,))
    attempt("admin.admins.seed_accounts", lambda: seed_admins(admins, admin_user, admin2_user),
            (admins, admin_user, admin2_user))
    attempt("admin.credit_reviews.pending", lambda: get_items(
        "/admin/credit-reviews?state=PENDING&page=1&pageSize=100", admin_token), (admin_token,))
    attempt("admin.recovery.pending", lambda: get_items(
        "/admin/recovery?state=PENDING&page=1&pageSize=100", admin_token), (admin_token,))
    attempt("admin.actions.initial_list", lambda: get_items(
        "/admin/actions?page=1&pageSize=100", admin_token), (admin_token,))

    suffix = dt.datetime.now().strftime("%Y%m%d%H%M%S") + f"{time.time_ns() % 1000000:06d}"
    marker = "admin-full-flow-" + suffix
    state = {
        "aid": None, "cid": None, "banid": None, "marker": marker,
        "complaint_reason": "举报-" + marker,
        "delist_reason": "下架-" + marker,
        "handle_result": "已核实，活动已下架处理-" + marker,
        "relist_reason": "上架-" + marker,
        "ban_reason": "封禁-" + marker,
        "unban_reason": "解封-" + marker,
    }
    publisher_account, reporter_account = "af_a_" + suffix, "af_b_" + suffix
    ACCOUNT_LABELS[publisher_account] = "publisher"
    ACCOUNT_LABELS[reporter_account] = "reporter"
    publisher = register(publisher_account, "全流发布" + suffix[-9:], "12345678")
    reporter = register(reporter_account, "全流举报" + suffix[-9:], "12345678")
    attempt("reporter.admin_overview.denied", lambda: denied(
        "GET", "/admin/overview", reporter["token"], statuses=(401, 403)), (reporter["token"],))

    # An activity/signup failure must never suppress the independent ban/audit stages.
    stages = (
        ("activity", lambda: activity_scenario(admin_token, publisher, reporter, state, suffix)),
        ("ban", lambda: ban_scenario(admin_token, state, suffix)),
        ("audit", lambda: audit_scenario(admin_token, admin_user, state)),
    )
    for stage, operation in stages:
        try:
            operation()
        except Exception as exc:
            check(stage + ".unexpected_exception", False, safe_exception(exc))


def main():
    try:
        run_flow()
    except Exception as exc:
        check("flow.unexpected_exception", False, safe_exception(exc))
    finally:
        print(f"TOTAL {len(results)} PASS {sum(1 for _,c,_ in results if c)} FAIL {sum(1 for _,c,_ in results if not c)}")
    if any(not c for _, c, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
