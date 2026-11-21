"""首次用户桌面 Web 旅程：游客浏览 → 注册 → 搜索 → 报名 → 通知 → 签到 → 我的活动。

前置：启动可写的本地/演示站点（BASE_URL 默认 http://127.0.0.1:8080），
安装 Playwright 和 Chromium，保留种子 organizer，脚本与服务端使用同一时区。
建议后端参数 INVITE_TTL=10、SWEEP_SECONDS=2、CHECKIN_WINDOW_SECONDS=60。
沿用 test_cem08.py 的口径：60 秒是签到码轮换周期，不是活动的签到资格时长。
本脚本不重置演示数据，会新增一场活动和一个一次性账号。预计耗时约 2–3 分钟
（含约 2 分钟等待活动开场，签到腿依赖真实时钟，不篡改 UI 时钟）。
若运行配置下活动未在等待上限内进入签到窗口，或提交时窗口已关，只走到签到入口
（未开放而没有按钮时到达活动详情），保存现场并记 OBS，不记 FAIL。其他错误照常断言。
产出：功能总计、逐步耗时/点击/first_try/困惑点、编号困惑点清单及
screenshots/ux-journey-{hall,registered,detail,signup,notifications,checkin}.png。
"""

import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import expect, sync_playwright


BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8080")
OUT = Path(__file__).resolve().parents[1] / "screenshots"
VIEWPORT = {"width": 1280, "height": 800}
UI_TIMEOUT = 8000
WINDOW_CLOSED = "当前不在签到时间内"
JARGON = re.compile(r"正式成员|递补|预留名额|入列|\b(?:FORMAL|WAITING|INVITED)\b")
STEPS = ("游客逛大厅", "UI 注册并自动登录", "大厅搜索活动", "详情页报名",
         "查看报名通知", "活动签到", "我的活动确认状态")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


# 困惑点判定：目标不在首屏需滚动；文案含内部术语或需猜；操作后 1 秒内无可见
# 反馈；成功/失败状态不明确；下一步去向不明显。只记 OBS，不写进 results。
observations = {name: [] for name in STEPS}


def observe(step, text):
    if text not in observations[step]:
        observations[step].append(text)


class StopJourney(Exception):
    """前置步骤失败，无法继续走真实用户路径。"""


def require(name, cond, detail=""):
    check(name, cond, detail)
    if not cond:
        raise StopJourney


def req(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        BASE.rstrip("/") + "/api/v1" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read())
        except (ValueError, OSError):
            return error.code, {"success": False, "code": "HTTP_ERROR",
                                "message": f"HTTP {error.code}", "data": None}
    except (ValueError, OSError) as error:
        return 0, {"success": False, "code": "REQUEST_ERROR",
                   "message": str(error), "data": None}


def ok_data(env):
    assert env.get("success") is True, env.get("message", "请求失败")
    return env.get("data")


def data_of(env):
    data = env.get("data")
    return data if isinstance(data, dict) else {}


def login(acc, pwd="Dazi@2026!"):
    status, env = req("POST", "/login", body={"account": acc, "password": pwd})
    require(f"备菜：{acc} 登录", status == 200 and env.get("success") is True
            and bool(data_of(env).get("token")), env.get("message", ""))
    return ok_data(env)["token"]


def seed_activity(token, title):
    # 预留 100 秒报名、约 120 秒后开场（给慢首屏留余量），RUNNING 后签到窗口才生效；
    # CEM-08 的 CHECKIN_WINDOW_SECONDS=60 在这里只是签到码轮换周期。
    now = datetime.now().replace(microsecond=0)
    start = now + timedelta(seconds=120)
    status, env = req("POST", "/activities", token=token, body={
        "title": title, "category": "其他", "description": "一起安静自习，零基础可来。",
        "conditions": "请自带学习资料。", "location": "线上", "capacity": 8,
        "deadline": (now + timedelta(seconds=100)).isoformat(),
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(minutes=3)).isoformat(),
    })
    require("备菜：发布可搜索活动", status in (200, 201) and env.get("success") is True
            and bool(data_of(env).get("id")), env.get("message", ""))
    return ok_data(env)["id"], start


def visible(locator, timeout=UI_TIMEOUT):
    try:
        locator.wait_for(state="visible", timeout=timeout)
        return True
    except BrowserTimeout:
        return False


def on_screen(locator):
    if not locator.is_visible():
        return False
    box = locator.bounding_box(timeout=150)
    return bool(box and 0 <= box["x"] + box["width"] / 2 < VIEWPORT["width"]
                and 0 <= box["y"] + box["height"] / 2 < VIEWPORT["height"])


@dataclass
class Step:
    name: str
    elapsed: float | None = None
    clicks: int = 0
    scrolls: int = 0
    first_try: bool = True
    metrics: dict = field(default_factory=dict)

    def __enter__(self):
        self.started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.elapsed = time.monotonic() - self.started
        if exc_type is not None:
            self.first_try = False

    def note(self, text):
        observe(self.name, text)

    def seek(self, page, target, label):
        target.wait_for(state="visible", timeout=UI_TIMEOUT)
        if on_screen(target):
            return
        # 先测首屏，再滚动，避免 locator.click 的自动滚动吞掉这次发现成本。
        self.first_try = False
        self.note(f"找「{label}」时，目标不在当前首屏，需要滚动。")
        for _ in range(6):
            box = target.bounding_box()
            if not box:
                break
            page.mouse.wheel(0, -520 if box["y"] < 0 else 520)
            self.scrolls += 1
            page.wait_for_timeout(120)  # wheel 事件的滚动动画异步完成
            if on_screen(target):
                return
        target.scroll_into_view_if_needed()
        self.scrolls += 1

    def click(self, page, target, label):
        self.seek(page, target, label)
        started = time.monotonic()
        target.click()
        self.clicks += 1
        return started

    def feedback(self, page, started, action, *signals):
        # 检查当前视口里的加载态、对话框、结果或错误；不能把后台请求当作反馈。
        until = started + 1
        while time.monotonic() <= until:
            if any(on_screen(signal) for signal in signals):
                return
            remaining = until - time.monotonic()
            if remaining > 0:
                page.wait_for_timeout(min(50, remaining * 1000))
        self.note(f"{action}后 1 秒内未看到反馈。")


def nav(page, step, name):
    # 沿用 test_mobile.py：窄屏先开菜单；名前缀锚定，避开「菜单，通知未读…」。
    menu = page.get_by_role("button", name=re.compile(r"^菜单"))
    if menu.is_visible() and menu.get_attribute("aria-expanded") != "true":
        step.click(page, menu, "菜单")
    step.click(page, page.locator("#mobile-nav").get_by_role(
        "button", name=re.compile(r"^" + re.escape(name))), name)


def shot(page, name):
    page.screenshot(path=str(OUT / f"ux-journey-{name}.png"))


def signed_card(page, step, title):
    nav(page, step, "我的活动")
    tab = page.get_by_role("button", name="已报名", exact=True)
    tab.wait_for(state="visible")
    if "active" not in (tab.get_attribute("class") or "").split():
        step.click(page, tab, "已报名页签")
    heading = page.get_by_role("heading", name=title, exact=True)
    step.seek(page, heading, "已报名活动卡片")
    return heading, heading.locator("xpath=..")


def organizer_code(token, aid, wait_seconds):
    """只将明确的窗口不可用视为降级，不吞掉鉴权、网络或响应格式错误。"""
    until = time.monotonic() + wait_seconds
    while True:
        status, env = req("GET", f"/activities/{aid}/checkin-code", token=token)
        message = env.get("message") or ""
        if status == 200 and env.get("success") is True:
            data = data_of(env)
            code = data.get("code")
            left = data.get("seconds_left")
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code) or not isinstance(left, (int, float)):
                require("备菜：签到码响应形状", False, "预期六位码及剩余秒数")
            if left >= 4:
                return code, ""
            reason = "运行配置下未等到剩余有效期足够的签到码"
        elif status == 400 and WINDOW_CLOSED in message:
            reason = "等待上限内活动未开放签到窗口"
        else:
            require("备菜：组织者取签到码", False, f"HTTP {status} {message}")
        remaining = until - time.monotonic()
        if remaining <= 0:
            return None, reason
        time.sleep(min(1, remaining))


def checkin(page, step, token, aid, title, start):
    # 按真实时钟等开场，不用 UI 改时钟或直接替主角发签到请求。
    began = time.monotonic()
    time.sleep(max(0, (start - datetime.now()).total_seconds()))
    code, reason = organizer_code(token, aid, wait_seconds=16)
    step.metrics["等开场和取码秒"] = f"{time.monotonic() - began:.2f}"

    heading, _ = signed_card(page, step, title)
    step.click(page, heading, "活动标题（进入详情）")
    page.get_by_role("heading", name=f"详情：{title}", exact=False).wait_for(state="visible")
    entry = page.get_by_role("button", name="签到", exact=True)
    if code is None:
        if visible(entry, timeout=1200):
            step.seek(page, entry, "签到入口")
            step.note(f"{reason}，已到签到入口，未提交。")
        else:
            step.first_try = False
            step.note(f"{reason}，已到活动详情，但页面没有显示签到入口。")
        shot(page, "checkin")
        return False

    require("签到窗口开放时详情显示签到入口", visible(entry))
    step.seek(page, entry, "签到入口")
    # 找到入口后再取一次，避免把导航过程中即将轮换的码填入弹窗。
    code, reason = organizer_code(token, aid, wait_seconds=6)
    if code is None:
        step.note(f"{reason}，已到签到入口，未提交。")
        shot(page, "checkin")
        return False

    prompt = {}

    def answer(dialog):
        prompt["ok"] = dialog.type == "prompt" and "签到码" in dialog.message
        if prompt["ok"]:
            prompt["started"] = time.monotonic()
            dialog.accept(code)
            step.clicks += 1  # 用户在原生输入框上点「确定」
        else:
            dialog.dismiss()

    page.once("dialog", answer)
    step.click(page, entry, "签到")
    require("签到入口弹出签到码输入框", prompt.get("ok"))
    banner = page.locator(".msg")
    signed = page.locator("p.signup-hint").filter(has_text=re.compile(r"^已签到"))
    closed = banner.filter(has_text=WINDOW_CLOSED)
    step.feedback(page, prompt["started"], "提交签到码", signed, banner)
    visible(signed.or_(closed).first)
    if closed.is_visible():
        step.note("提交时签到窗口已关闭；已保存签到现场，跳过成功断言。")
        shot(page, "checkin")
        return False
    ok = signed.is_visible()
    check("UI 签到后显示已签到", ok)
    if ok:
        step.seek(page, signed, "已签到状态")
    else:
        step.note("提交后没有明确的「已签到」结果，无法判定签到是否成功。")
    shot(page, "checkin")
    return ok


def journey(page, steps, organizer, aid, start, keyword, title, nickname, account, password):
    guest, registration, search, signup, notifications, attendance, mine = steps
    with guest as step:
        page.goto(BASE, wait_until="domcontentloaded")
        preview = page.locator(".login-hall-summary")
        example = preview.locator("p").first
        require("游客无需登录即可看到活动预览", visible(example))
        step.seek(page, example, "大厅活动预览")
        copy = preview.inner_text()
        check("游客预览中有活动名额信息", bool(re.search(r"\d+\s*/\s*\d+", copy)))
        guidance = page.get_by_text("登录后可查看详情、报名参加", exact=False)
        check("游客看到登录后可报名的引导且没有直接报名按钮",
              guidance.is_visible() and not page.get_by_role("button", name="报名", exact=True).is_visible())
        if " 正式 " in copy and "正式名额" not in copy:
            step.note("游客预览写「正式 X/Y」，但没解释它是已占用名额/总名额。")
        if example.evaluate("el => el.closest('a,button,[role=button]') === null"):
            step.note("游客预览里的活动只能看标题和名额，点不进去看详情。")
        step.seek(page, guidance, "登录后可报名的说明")
        shot(page, "hall")

    with registration as step:
        register_link = page.locator(".login-page").get_by_role("button", name="注册新账号", exact=True)
        step.click(page, register_link, "注册新账号")
        form = page.locator(".register-page")
        form.locator("#reg-account").fill(account)
        form.locator("#reg-password").fill(password)
        form.locator("#reg-nickname").fill(nickname)
        h = form.get_by_text("注册后可报名活动、接收递补通知", exact=False)
        if h.is_visible() and "递补" in h.inner_text():
            step.note("还未认识候补流程，注册页已使用「递补通知」，未解释含义。")
        started = step.click(page, form.locator("#reg-submit"), "提交注册")
        profile = page.get_by_role("button", name=re.compile(r"^" + re.escape(nickname)))
        banner = page.locator(".msg").filter(has_text="注册成功，已自动登录")
        step.feedback(page, started, "提交注册", profile, banner,
                      form.get_by_role("button", name="提交中…"), page.get_by_role("dialog"))
        require("UI 注册后自动登录新账号", visible(profile))
        if not on_screen(banner):
            step.note("自动登录后没有在首屏看到注册成功提示，需要从昵称判断是否成功。")
        shot(page, "registered")

    with search as step:
        field = page.get_by_placeholder("试试搜：羽毛球、自习")
        step.click(page, field, "大厅搜索框")
        began = time.monotonic()
        field.fill(keyword)
        cards = page.locator(".hall-card")
        expect(cards).to_have_count(1, timeout=UI_TIMEOUT)
        found = cards.filter(has_text=title)
        require("用关键词搜到唯一的备菜活动", visible(found))
        if not on_screen(found.get_by_role("heading")):
            step.first_try = False
            step.note("搜索后匹配结果不在首屏，需要滚动才能看到。")
        open_button = found.get_by_role("button", name="查看详情", exact=True)
        step.seek(page, open_button, "搜索结果的查看详情按钮")
        step.metrics["搜索定位秒"] = f"{time.monotonic() - began:.2f}"
        step.click(page, open_button, "查看详情")
        detail = page.get_by_role("heading", name=f"详情：{title}", exact=False)
        require("搜索结果可打开对应活动详情", visible(detail))
        shot(page, "detail")

    with signup as step:
        registered = page.locator(".status-card-title").filter(has_text="已报名")
        confirmation = page.get_by_role("button", name="我已阅读，继续报名", exact=True)
        busy = page.get_by_role("button", name=re.compile(r"^(报名中|提交中|正在报名)"))
        banner = page.locator(".msg").filter(has_text="你报上了")
        error = page.get_by_text(re.compile(r"^报名失败，未报名成功"))
        started = step.click(page, page.get_by_role("button", name="报名", exact=True), "报名")
        step.metrics["额外确认步数"] = 0
        step.feedback(page, started, "点击报名", confirmation, busy, registered, error)
        require("有参与条件的活动展示报名确认", visible(confirmation))
        started = step.click(page, confirmation, "我已阅读，继续报名")
        step.metrics["额外确认步数"] = 1
        step.feedback(page, started, "确认报名", busy, registered, banner, error)
        visible(registered.or_(error).first)
        ok = registered.is_visible()
        check("详情页报名后显示已报名", ok, error.inner_text() if error.is_visible() else "")
        if not on_screen(registered) and not on_screen(banner) and not on_screen(error):
            step.note("确认报名后未在当前视口看到清楚的成功或失败状态。")
        if ok and not on_screen(page.get_by_role("button", name="查看我报名的活动", exact=True)):
            step.note("报名成功后首屏没有就近的下一步入口，需要自己回顶部找通知或我的活动。")
        shot(page, "signup")
        if not ok:
            raise StopJourney

    with notifications as step:
        nav(page, step, "通知")
        notice = page.locator(".notif-summary").filter(has_text=title).first
        arrived = visible(notice)
        check("通知页收到该活动的报名通知", arrived)
        if arrived:
            step.seek(page, notice, "对应活动的报名通知")
            text = notice.inner_text()
            step.metrics["通知正文"] = text
            if not re.search(r"成功报名|报名成功|报上了|已报名", text):
                step.note("通知提到活动，但没有明确说报名是否成功。")
            if JARGON.search(text):
                step.note(f"报名通知使用了未解释的术语「{JARGON.search(text).group()}」。")
            if "线上" not in text or not re.search(r"\d{1,2}:\d{2}", text):
                step.note("通知里没找到完整的活动时间和地点，需要再找详情确认。")
        else:
            step.first_try = False
        shot(page, "notifications")

    with attendance as step:
        checked_in = checkin(page, step, organizer, aid, title, start)

    with mine as step:
        heading, card = signed_card(page, step, title)
        state = card.get_by_text(re.compile(r"^状态："))
        require("我的活动在已报名页签展示同一活动和状态", visible(state))
        step.seek(page, state, "我的活动状态")
        text = state.inner_text()
        step.metrics["列表状态"] = text
        if JARGON.search(text):
            step.note(f"状态使用「{JARGON.search(text).group()}」，未直接说明能否参加。")
        if checked_in:
            signed = card.get_by_text(re.compile(r"^已签到"))
            if not signed.is_visible():
                step.note("已报名列表没直接显示签到结果，要点活动标题再到详情确认。")
                step.click(page, heading, "已报名活动标题")
                signed = page.locator("p.signup-hint").filter(has_text=re.compile(r"^已签到"))
            check("从我的活动再次确认已签到", visible(signed))

    # 唯一的主角 API 访问在旅程结束后：复用 UI 登录会话，只读复核，绝不代点。
    token = page.evaluate("() => localStorage.getItem('token')")
    require("末尾复核：UI 会话可用", bool(token))
    status, env = req("GET", f"/activities/{aid}", token=token)
    data = data_of(env)
    check("末尾复核：主角是正式报名成员",
          status == 200 and env.get("success") is True and data.get("my_status") == "FORMAL")
    if checked_in:
        check("末尾复核：签到时间已持久化", bool((data.get("my_checkin") or {}).get("checkin_at")))


def main():
    steps = [Step(name) for name in STEPS]
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    keyword = f"自习小组 {stamp}"
    title = f"体验{keyword}"
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport=VIEWPORT)
                page.set_default_timeout(UI_TIMEOUT)
                organizer = login("organizer", "Dazi@2026!")
                aid, start = seed_activity(organizer, title)
                journey(page, steps, organizer, aid, start, keyword, title,
                        f"新同学{stamp}", f"ux{stamp}", "Ux7-" + secrets.token_hex(8))
            finally:
                browser.close()
    except StopJourney:
        pass  # 具体检查项已计入 FAIL。
    except Exception as error:
        active = next((step.name for step in reversed(steps) if step.elapsed is not None), "备菜/浏览器")
        check(active, False, f"{type(error).__name__}: {str(error).partition(chr(10))[0]}")

    print(f"TOTAL {len(results)} PASS {sum(1 for _,c,_ in results if c)} FAIL {sum(1 for _,c,_ in results if not c)}")
    print("步骤记录（first_try=首轮无需滚动或改路；点击数含弹窗确定，不含键入）")
    for step in steps:
        cost = f"{step.elapsed:.2f}" if step.elapsed is not None else "未执行"
        first = str(step.first_try).lower() if step.elapsed is not None else "未执行"
        notes = "；".join(observations[step.name]) or "无"
        extra = " ".join(f"{k}={v}" for k, v in step.metrics.items())
        print(f"- {step.name}：耗时秒={cost} 点击数={step.clicks} 滚动次数={step.scrolls} "
              f"first_try={first} {extra} 困惑点={notes}")
    print("困惑点清单")
    notes = [(step.name, note) for step in steps for note in observations[step.name]]
    for index, (name, note) in enumerate(notes, 1):
        print(f"{index}. OBS - {name}：{note}")
    if not notes:
        print("无")
    if any(not cond for _, cond, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
