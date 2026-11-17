"""jar 置换法（2026-11-13/11-14 同法，/tmp 被 VM 重置清空后重建）：
完整 Maven 打包不可行（阿里云镜像被出口代理重置，~/.m2 为空），故只替换
jar 内 BOOT-INF/classes/static/ 整棵静态树为 frontend/dist 的内容，
后端 class 一个字节不动。
用法：python3 jarswap.py <jar路径> <dist目录>
"""
import hashlib, os, shutil, sys, zipfile

JAR, DIST = sys.argv[1], sys.argv[2]
PREFIX = "BOOT-INF/classes/static/"
tmp = JAR + ".tmp"

def md5(b):
    return hashlib.md5(b).hexdigest()

# 置换前先取后端关键 class 的 md5（事后核对未动）
zin = zipfile.ZipFile(JAR)
cls_before = {}
for name in ["BOOT-INF/classes/com/campusbuddy/service/BuddyService.class",
             "BOOT-INF/classes/com/campusbuddy/CampusBuddyApplication.class"]:
    try:
        cls_before[name] = md5(zin.read(name))
    except KeyError:
        cls_before[name] = "MISSING"
print("class md5 before:", cls_before, flush=True)

dist_files = {}
for root, _, files in os.walk(DIST):
    for f in files:
        p = os.path.join(root, f)
        rel = os.path.relpath(p, DIST).replace(os.sep, "/")
        dist_files[PREFIX + rel] = p

kept, dropped = 0, 0
with zipfile.ZipFile(JAR) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename.startswith(PREFIX):
            dropped += 1
            continue
        zout.writestr(item, zin.read(item.filename))
        kept += 1
    # 目录条目必须保留（BUILD-NOTES：缺目录条目会让 Spring 扫不到类；
    # static 树虽不含类，也按同一规则补齐，避免目录条目数与原 jar 不一致）。
    dist_dirs = sorted({os.path.dirname(PREFIX + rel) for rel in
                        (os.path.relpath(os.path.join(r, f), DIST).replace(os.sep, "/")
                         for r, _, fs in os.walk(DIST) for f in fs)} | {PREFIX.rstrip("/")})
    for d in dist_dirs:
        zout.writestr(zipfile.ZipInfo(d + "/"), b"")
    for name, path in sorted(dist_files.items()):
        zout.write(path, name)
print(f"kept={kept} dropped_static={dropped} added_static={len(dist_files)}", flush=True)
shutil.move(tmp, JAR)

# 置换后核对
z = zipfile.ZipFile(JAR)
cls_after = {n: md5(z.read(n)) for n in cls_before}
print("class md5 after: ", cls_after, flush=True)
assert cls_before == cls_after, "后端 class 被改动！置换失败"
names = z.namelist()
static = sorted(n for n in names if n.startswith(PREFIX))
print("static now:", static, flush=True)
assert "BOOT-INF/classes/static/assets/index-Bfigc0ZP.js" not in names, "旧 JS 未删掉"
new_js = [n for n in names if n.startswith(PREFIX + "assets/index-") and n.endswith(".js")]
print("new js entries:", new_js, flush=True)
print("jar md5:", md5(open(JAR, "rb").read()), flush=True)
print("JARSWAP OK")
