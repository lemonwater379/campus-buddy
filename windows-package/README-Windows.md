# 找个搭子 · Windows 运行说明

## 前置条件（各装一次）
1. **JDK 17**（如 Temurin 17）：命令行输入 `java -version` 能看到 17.x。
2. **PostgreSQL 16**：安装时记住 postgres 用户的密码；安装后新建数据库（只做一次）：
   ```
   psql -U postgres -c "CREATE DATABASE campus_buddy ENCODING 'UTF8';"
   ```
   如果本机 PostgreSQL 装在非默认端口，启动前按下面“改配置”改 `DB_URL`。

## 启动（每次演示）
双击 `run.bat`，看到 Spring Boot 启动日志后，浏览器打开：

**http://localhost:8080**

前端已打包在 Jar 里，不需要另外装 Node 或启动前端。

## 演示账号（密码都是 Dazi@2026!）
- 组织者：`organizer`
- 同学：`demo01` … `demo20`

页面右上角有“快速登录”按钮（组织者 / 同学1 / 同学5），
也可以用“恢复演示数据”回到初始状态（3 个种子活动：羽毛球、桌游、学习组）。

## 建议的演示顺序（对应 PPT 第 7 页）
1. 用同学账号打开“周六羽毛球双打”（上限 4，已有 3 正式）：第 4 人报名转正式，第 5 人候补第 1。
2. 第 4 人退出 → 候补第 1 收到限时邀请（正式 3 + 预留 1 = 上限）。
3. 接受邀请 → 转正式；或等 120 秒超时 → 自动顺延到下一候补。
   想现场快一点看超时顺延：先关掉程序，设 `INVITE_TTL=10` 再启动（见下）。

## 改配置（不改代码）
在启动 `run.bat` 之前，在命令行设置环境变量再运行它，例如：
```
set DB_URL=jdbc:postgresql://127.0.0.1:5433/campus_buddy
set DB_PASSWORD=你的密码
set INVITE_TTL=10
set SWEEP_SECONDS=2
run.bat
```
- `DB_URL`：默认 `jdbc:postgresql://127.0.0.1:5432/campus_buddy`
- `DB_USER`：默认 `postgres`；`DB_PASSWORD`：默认空
- `PORT`：默认 `8080`；`INVITE_TTL`：默认 120 秒；`SWEEP_SECONDS`：默认 10 秒

## 常见问题
- **启动后报数据库连接失败**：先确认 PostgreSQL 在运行、数据库 `campus_buddy` 已建、密码对得上。
- **中文显示乱码**：不要删 `run.bat` 里的 `-Dfile.encoding=UTF-8`，建表脚本含中文分类名，缺了它会建表失败。
- **端口被占**：设 `PORT=8081` 再启动，浏览器改打开 `http://localhost:8081`。

## 技术路线
Vue 3（已打包进 Jar）+ Spring Boot 3.3.5 + PostgreSQL；核心规则：有效占用 = 正式人数 + 未过期邀请数 ≤ 上限；同一活动同一用户一条当前记录；邀请终态唯一；候补按入队时间排。
