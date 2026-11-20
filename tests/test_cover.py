#!/usr/bin/env python3
"""活动封面图验收脚本（2026-11-17，靶子 C）。

对运行中的后端（默认 http://127.0.0.1:8080）验证：
上传成功 / 超限拒绝 / 非图片拒绝 / 未登录 401 / 建活动带封面 /
改封面与清除 / 外链封面拒绝。

依赖与 test_api.py 相同：只用标准库；multipart 由本脚本手工拼 boundary；
PNG 由 zlib + struct 现场生成，不依赖外部 fixture。
运行前后端须已启动；脚本开头调用 /api/v1/demo/reset（需登录）。
"""
import json
import os
import random
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta

ROOT = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/")
BASE = ROOT + "/api/v1"
MAX_BYTES = 5 * 1024 * 1024

# 用远期且互不重叠的时间，避免与种子活动/其他套件的时间冲突检测撞车。
_NOW = datetime.now()
DEADLINE = (_NOW + timedelta(days=40)).strftime("%Y-%m-%dT08:00:00")
START = (_NOW + timedelta(days=42)).strftime("%Y-%m-%dT10:00:00")
END = (_NOW + timedelta(days=42)).strftime("%Y-%m-%dT12:00:00")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail)


def req(method, path, token=None, body=None, headers=None):
    """返回 (http_status, envelope)。"""
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    if headers:
        hdrs.update(headers)
    r = urllib.request.Request(
        BASE + path, method=method,
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
        return 0, {"success": False, "code": "NETWORK_ERROR",
                   "message": str(e), "data": None}


def multipart_upload(path, filename, content, token=None, content_type=None):
    """手工拼 multipart/form-data（字段名 file），不引入 requests。"""
    boundary = "----CampusBuddyCover" + uuid_hex()
    if content_type is None:
        content_type = "application/octet-stream"
    body = bytearray()
    body += ("--" + boundary + "\r\n").encode()
    body += ('Content-Disposition: form-data; name="file"; filename="%s"\r\n'
             % filename).encode()
    body += ("Content-Type: " + content_type + "\r\n\r\n").encode()
    body += content
    body += ("\r\n--" + boundary + "--\r\n").encode()
    hdrs = {"Content-Type": "multipart/form-data; boundary=" + boundary}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    r = urllib.request.Request(BASE + path, method="POST", data=bytes(body), headers=hdrs)
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
        return 0, {"success": False, "code": "NETWORK_ERROR",
                   "message": str(e), "data": None}


def uuid_hex():
    return "%08x%08x" % (random.getrandbits(32), random.getrandbits(32))


def make_png(width=2, height=2):
    """现场生成最小合法 PNG（truecolor，8 bit），返回 bytes。"""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        for x in range(width):
            raw += bytes(((x * 37 + y * 59) % 256,
                          (x * 17 + y * 29) % 256,
                          (x * 11 + y * 71) % 256))

    def chunk(tag, data):
        payload = tag + data
        return (struct.pack(">I", len(data)) + payload
                + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))


def ok_data(env):
    assert env.get("success") is True, f"expected success envelope: {env}"
    return env.get("data")


def message_of(env):
    return str((env or {}).get("message") or "")


def register(acc, pwd="12345678"):
    return req("POST", "/register", body={"account": acc, "password": pwd, "nickname": acc[:12]})


def login(acc, pwd="12345678"):
    s, env = req("POST", "/login", body={"account": acc, "password": pwd})
    assert env.get("success"), f"login {acc} failed: {s} {env}"
    return ok_data(env)["token"]


def authed_reset():
    """演示重置需要登录；空库时先注册引导账号。"""
    try:
        tok = login("organizer")
    except AssertionError:
        req("POST", "/register",
            body={"account": "coverboot", "password": "12345678", "nickname": "封面审计"})
        tok = login("coverboot", "12345678")
    s, env = req("POST", "/demo/reset", token=tok)
    assert env.get("success"), f"reset failed: {s} {env}"


def create_activity(token, title, **extra):
    body = {
        "title": title, "category": "其他", "description": "封面功能测试",
        "conditions": "", "location": "线上", "capacity": 4,
        "deadline": DEADLINE, "start_time": START, "end_time": END,
    }
    body.update(extra)
    return req("POST", "/activities", token=token, body=body)


def activity_detail(token, aid):
    s, env = req("GET", f"/activities/{aid}", token=token)
    assert env.get("success"), f"detail {aid} failed: {s} {env}"
    return ok_data(env)


def hall_items(token):
    s, env = req("GET", "/activities?pageSize=100", token=token)
    assert env.get("success"), f"hall failed: {s} {env}"
    return ok_data(env)["items"]


def main():
    authed_reset()

    # 全新账号做操作者，避免与种子账号/其他套件冲突。
    acc = "cov" + str(int(time.time()))[-7:] + str(random.randint(10, 99))
    s, env = register(acc)
    assert env.get("success"), f"register {acc} failed: {s} {env}"
    tok = login(acc)

    png = make_png()

    # ---- 1. 上传成功 + 静态访问字节一致 ----
    su, eu = multipart_upload("/uploads/image", "cover.png", png, token=tok,
                              content_type="image/png")
    du = eu.get("data") if isinstance(eu.get("data"), dict) else {}
    url = du.get("url") if isinstance(du, dict) else None
    check("上传合法 PNG：200 且 data.url 以 /uploads/ 开头",
          su == 200 and eu.get("success") is True and isinstance(url, str)
          and url.startswith("/uploads/"), f"{su} {eu}")
    fetched = None
    if url:
        try:
            with urllib.request.urlopen(ROOT + url) as resp:
                fetched = (resp.status, resp.read())
        except Exception as e:
            fetched = (0, str(e).encode())
    check("上传后的 /uploads/... 未登录也可访问且字节一致",
          bool(fetched) and fetched[0] == 200 and fetched[1] == png,
          f"status={fetched[0] if fetched else None} bytes="
          f"{len(fetched[1]) if fetched else 0}")

    # ---- 2. 超过 5MB 拒绝 ----
    big = png + b"\x00" * (MAX_BYTES + 1 - len(png))
    sb, eb = multipart_upload("/uploads/image", "big.png", big, token=tok,
                              content_type="image/png")
    check("超过 5MB：拒绝（400）且文案含 5MB",
          sb == 400 and eb.get("success") is False and "5MB" in message_of(eb),
          f"{sb} {message_of(eb)}")

    # ---- 3. 非图片拒绝（按文件头，不看扩展名 / Content-Type） ----
    st, et = multipart_upload("/uploads/image", "pic.png", b"this is not an image",
                              token=tok, content_type="image/png")
    check("文本改名 pic.png：拒绝（400）且文案提示图片类型",
          st == 400 and et.get("success") is False
          and ("仅支持" in message_of(et) or "图片" in message_of(et)),
          f"{st} {message_of(et)}")

    # ---- 4. 未登录上传 → 401 ----
    sn, en = multipart_upload("/uploads/image", "cover.png", png, token=None,
                              content_type="image/png")
    check("未登录上传：401", sn == 401, f"{sn} {en}")

    # ---- 5. 带封面建活动：详情与大厅返回 cover_url；不带封面为空 ----
    sc, ec = create_activity(tok, "封面活动-带图库", cover_url="/img/cover-2.webp")
    aid = ok_data(ec)["id"] if ec.get("success") else None
    d = activity_detail(tok, aid) if aid else {}
    check("建活动带 cover_url=/img/cover-2.webp：详情返回该值",
          sc == 200 and d.get("cover_url") == "/img/cover-2.webp",
          f"{sc} detail.cover_url={d.get('cover_url')!r}")
    hall_row = next((x for x in hall_items(tok) if str(x.get("id")) == str(aid)), None)
    check("大厅列表同样返回 cover_url",
          bool(hall_row) and hall_row.get("cover_url") == "/img/cover-2.webp",
          str(hall_row.get("cover_url") if hall_row else None))

    sc2, ec2 = create_activity(tok, "封面活动-不带图")
    aid2 = ok_data(ec2)["id"] if ec2.get("success") else None
    d2 = activity_detail(tok, aid2) if aid2 else {}
    check("不带封面的活动：cover_url 为 null/空",
          sc2 == 200 and not d2.get("cover_url"),
          f"{sc2} detail.cover_url={d2.get('cover_url')!r}")

    # ---- 6. 改封面（用上传图）与清除 ----
    sp, ep = req("PUT", f"/activities/{aid}/cover", token=tok, body={"cover_url": url})
    d3 = activity_detail(tok, aid)
    check("PUT 改封面为上传图：详情返回该 url",
          sp == 200 and ep.get("success") is True and bool(url)
          and d3.get("cover_url") == url,
          f"{sp} detail.cover_url={d3.get('cover_url')!r}")
    sclear, eclear = req("PUT", f"/activities/{aid}/cover", token=tok,
                         body={"cover_url": ""})
    d4 = activity_detail(tok, aid)
    check("PUT 传空串清除：详情 cover_url 为 null/空",
          sclear == 200 and eclear.get("success") is True and not d4.get("cover_url"),
          f"{sclear} detail.cover_url={d4.get('cover_url')!r}")

    # ---- 7. 外链 cover_url 拒绝 ----
    se, ee = create_activity(tok, "封面活动-外链", cover_url="http://evil.example/x.png")
    check("建活动传外链 cover_url：拒绝（400）",
          se == 400 and ee.get("success") is False,
          f"{se} {message_of(ee)}")

    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
