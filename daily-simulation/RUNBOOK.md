# 每日运行手册（cron 代理按此执行）

运行目录：`~/workspace/campus-buddy/daily-simulation/`，
当日输出：`runs/YYYY-MM-DD/`（users/、digest.md、changes.md、report.md）。

## 0. 环境恢复（虚拟机随时可能被重置，先做这步）

双库说明见 `DUAL-DB.md`。A 版（PostgreSQL，8080）是默认；B 版
（MySQL 8.0.28，8081）按当日抽签决定是否启用（见下）。

1. 查后端健康：`curl -s http://127.0.0.1:8080/api/health`，正常返回 ok 且
   users=21、activities=4 即通过。
2. 不通就重建：`useradd -m pgdemo`（如不存在）→ 复制
   `~/workspace/.portable/pgsql` 到 `/tmp/pgsql` 并 `chmod -R a+rX` →
   `LD_LIBRARY_PATH=/tmp/pgsql/usr/lib/x86_64-linux-gnu:/tmp/pgsql/usr/lib/postgresql/16/lib`
   下用 pgdemo 身份 initdb（`/tmp/pgdata2`，UTF8，C.utf8）→ postgresql.conf
   追加 port=5433、listen 127.0.0.1、socket /tmp/pgrun、**timezone='Asia/Shanghai'**
   （时区统一，2026-11-06 起必带；漏了它 PG `now()` 产 UTC 墙钟，
   `reserved_count` 与 `created_at` 默认值全错 8 小时）→ pg_ctl 启动 →
   建 postgres 超级用户 → createdb campus_buddy → 从
   `~/workspace/campus-buddy/database/backup-2026-11-04.sql` 恢复 →
   核对计数 21/4/10（A 版；2026-11-06 晚用户定种子改动后，demo01 退出
   周末学习组，活动参与由 11 变 10；2026-11-08 加第 4 个种子活动「周日羽毛球
   友谊赛」，demo01 未预报名，活动数 3→4；B 版为 21/4/11）。重建后验时区：`SHOW timezone;` 应为 Asia/Shanghai，
   `SELECT now();` 应带 `+08`；系统时区也应为 Asia/Shanghai
   （`/etc/localtime` → Asia/Shanghai，`date` 应显示 CST）。
3. 启动 A 版后端：`DB_URL=jdbc:postgresql://127.0.0.1:5433/campus_buddy
   DB_USER=postgres INVITE_TTL=120 SWEEP_SECONDS=10 PORT=8080`，
   `~/workspace/.portable/jdk-17.0.21+9/bin/java -Dfile.encoding=UTF-8
   -Djava.net.preferIPv4Stack=true -Duser.timezone=Asia/Shanghai -jar
   ~/workspace/campus-buddy/backend/target/campus-buddy-1.0.0.jar`，
   再验健康。启动约需 14–16 秒，健康检查至少等 20 秒。**JVM 时区参数
   `-Duser.timezone=Asia/Shanghai` 必带（时区统一，2026-11-06 起）；漏了它
   `LocalDateTime.now()` 产 UTC 墙钟，活动时间整体晚 8 小时（2026-11-06 P0
   的根因）。**B 版同理（8081，见 DUAL-DB.md，启动前先轮换 cb_app 密码）。
4. **A/B 抽签（每天一次，步骤 1 之前做）**：抛一次硬币决定当天
   **移动端测试**跑本地 A 还是 B（按天随机，不按人随机；2026-11-13 起
   用户体验固定走线上服务器版，见第 0 步第 7 条与第 2 步，抽签不再决定
   体验版本）。结果与种子记入
   `runs/<日期>/ab-assignment.md` 与当日 digest。抽中 B 时：先确认
   MySQL 在跑（`mysqladmin --defaults-file=~/workspace/.portable/mysql-8.0.28/my.cnf ping`），
   不在就用 DUAL-DB.md 的命令启动（数据目录
   `~/workspace/.portable/mysql-data` 还在，原地启动即可）；再按
   DUAL-DB.md 先轮换 cb_app 密码再启动 B 版应用实例（8081，密码不存文件、
   每次启动现生成，见 DUAL-DB.md“启动 B 版”）。
   MySQL 没就绪时，循环照常只跑 PostgreSQL 并在报告里注明。MySQL 时区
   由 `~/workspace/.portable/mysql-8.0.28/my.cnf` 里的
   `default-time-zone=+08:00` 固定（不要写成 `time_zone=`，mysqld 会报
   unknown variable 而启动失败）；验活时顺带查
   `SELECT @@global.time_zone, NOW();` 应为 `+08:00`。
   **停应用时按端口逐个 kill（见 DUAL-DB.md）；`kill_backend.py`
   会杀掉所有 campus-buddy 的 Java 进程，双实例运行时绝不能用。**
5. **Maven 构建环境（虚拟机重置后必做，2026-11-09 补）**：重置会丢
   `/tmp/maven-settings.xml`、`/tmp/egress-truststore.jks` 与 `~/.m2`；
   `mvn package` 前先跑 `bash daily-simulation/gen-maven-settings.sh`
   重生成这两份 /tmp 文件（脚本只从环境变量读代理凭据，只写 /tmp，
   不进仓库）；依赖会重新下载，构建成功后再继续。
6. **magpie 网关（2026-11-10 起，Claude Code 必经）**：开发团队编程任务
   走 `claude -p --permission-mode acceptEdits`，经 yetone/magpie 本地网关（http://127.0.0.1:3425）到
   用户 OpenCode Go 额度的 DeepSeek V4.1 Flash。网关由 systemd 服务
   `magpie.service` 跑 `magpie serve`；虚拟机重置会丢 /etc 下的 unit，
   先跑 `bash ~/workspace/magpie/ensure-magpie.sh`（从当前环境重建
   unit 并拉起，30 秒内验活），再验 `curl -s
   http://127.0.0.1:3425/v1/models` 应只列出
   `opencode-go/deepseek-v4.1-flash` 一个模型。网关不通时不要直接改
   `~/.claude/settings.json` 绕回直连，先修网关；密钥只在
   `~/.config/magpie` 里，不读不传。
7. **线上服务器体验环境（2026-11-13 用户指令）**：用户体验固定走 Azure
   线上服务器版。开跑前建 SSH 隧道并验活（直连 22 口会被出口代理重置，
   必须走 ProxyCommand；proxyauth 从 `$https_proxy` 运行时提取，不硬编码）：
   `PROXY_AUTH=$(python3 -c "import os;u=os.environ['https_proxy'];print(u.split('://',1)[1].split('@')[0])")`，
   然后 `ssh -fN -o UserKnownHostsFile=/home/hatch/.ssh/known_hosts
   -o ProxyCommand="socat - PROXY:hatch-egress-proxy:%h:%p,proxyport=3128,proxyauth=$PROXY_AUTH"
   -i ~/.ssh/campusbuddy_key993.pem -L 18080:127.0.0.1:8080 azureuser@40.74.66.63`，
   再验 `curl -s http://127.0.0.1:18080/api/health` 应 ok；users/activities
   以服务器当日快照基线为准（2026-11-13 基线 22 用户 / 5 活动，含用户
   自建活动「王者开黑」#5；基线不是本地的 21/4）。虚拟机重置只会断隧道，
   重建隧道即可续跑，服务器上的体验数据不丢；known_hosts 丢失时先按
   AGENTS.md 的办法核对同一台再写回，不要盲目删 key 重认。

## 1. 数据库快照

- A 版：`pg_dump` 当日一份到 `runs/YYYY-MM-DD/db-before.sql`（以 pgdemo 身份连
  127.0.0.1:5433；pg_dump 写 runs 目录会 Permission denied，先 dump 到 /tmp
  再 cp 过去）。
- B 版（当天抽中 B 或 QA 要测 B 时）：`mysqldump` 一份到
  `runs/YYYY-MM-DD/db-before-mysql.sql`（`--single-transaction --no-tablespaces`，
  命令见 DUAL-DB.md）。
- 服务器版（体验用，2026-11-13 起必做）：SSH 到 Azure 执行
  `sudo -u postgres pg_dump campus_buddy` 存到服务器
  `/home/azureuser/snapshots/db-before-YYYY-MM-DD.sql`，并 scp 回
  `runs/YYYY-MM-DD/db-server-before.sql` 留档。恢复见第 5 步；
  **服务器只走 pg_dump 快照恢复，绝不用 /demo/reset**（会把线上真实
  数据清回种子态）。
- 用户体验结束、开发验证完成后，用快照恢复，当天体验数据不留库。

## 2. 用户体验（并行拉起 6 个子代理）

每人一份独立任务，任务里写清：你的人设文件路径、当日场景、
产品地址（**线上服务器版，经第 0 步第 7 条的 SSH 隧道
http://127.0.0.1:18080**；2026-11-13 用户指令，体验不再用本地 A/B 版）、
驱动方式（用 `~/workspace/.portable/venv-mobile/bin/python` + Playwright 写一段
临时脚本操作页面并截图，或直接调后端 API）、报告写到
`runs/YYYY-MM-DD/users/<名字>.md`（格式：试了什么、每步顺不顺、
卡点原话、建议 + 严重度 P0/P1/P2、截图路径；每条反馈标注【功能性】或【合理性】）。

- 长期用户（3 名）：先读自己的 journal 文件，按人设和昨日记录继续体验。
  沈知行：组织一次活动并看报名情况；顾晓：逛大厅并报一个活动；
  陆远：检查通知与「我的活动」，并试一个边界情况（满员/截止/邀请过期）。
- 新用户（3 名）：从 `new-user-angles.md` 取当日 3 个角度并打勾记日期，
  现场生成身份，以首日用户视角完成登录→逛大厅→报名（或发布）全流程。

**合理性评价（2026-11-10 用户指令，硬性要求，写进每个用户代理的任务里）**：
体验时要像第一次用这个产品的普通人一样走正常使用流程、凭生活常识
判断，不只按测试步骤点按钮。功能上能跑通不等于合理——“能用但不对劲、
让人困惑、不符合正常预期”的问题同样要报。合理性问题范例（用户
2026-11-10 晚亲提，均不是功能 bug）：① 游客没登录就能看到大厅内容
（应先登录/注册才能进大厅）；② 点开活动详情不是跳详情页、也不是在
原地展开，而是跳到列表最上方再展开；③ 点开详情后看不到报名按钮
（按钮被埋在页面下方，要翻很久才找得到）。

禁令（写进每个用户代理的任务里）：绝不点「恢复演示数据」、
绝不调 `/demo/reset`（服务器版上这会把线上真实数据清回种子态，
是全场最严重事故）；不报名、不退出、不取消「王者开黑」（#5，
用户自建的真实活动），只浏览；不改他人数据；不直接改代码。

**专属账号（2026-11-09 定，防并行干扰）**：长期用户各固定一个 demo
账号，只用自己的——沈知行用 organizer、顾晓用 demo01、陆远用 demo05
（服务器上同名账号、密码同为 123456）；
任何代理不得用他人专属账号报名/退出/发活动（昨日陆远的 demo05 被沈知行
代报、通知混入他人操作，均由此引起）；新用户在服务器上现场注册新账号，用固定临时池
temp01–temp03（见下），不用 demo 账号。digest 核对基线以当日**服务器**快照为准，不拿用户截图里的中途计数当基线。

**临时账号回收复用（2026-11-10 用户指令）**：新用户账号是临时的、固定池
回收复用，共 3 个——temp01、temp02、temp03（密码均为 123456，与演示账号
一致；种子库里没有这 3 个名，不撞号）。每天 3 名新角色按当日顺序各用一个
（第 1 个角度用 temp01，第 2 个用 temp02，第 3 个用 temp03），注册时昵称写
当天角色名。重置靠第 5 步的快照恢复：临时账号及当天的报名、通知、留言、
发布全部在当日快照之后产生，恢复当日快照即全部清掉，次日重新注册同名即是
干净账号——不需要单独的清理步骤，也不要点「恢复演示数据」（那会连种子与
长期账号数据一起清掉，绝不能用）。长期账号（organizer、demo01、demo05）
在种子与当日快照里，恢复时保留，任何时候都不重置、不删、不改。2026-11-13
起体验在服务器上：temp01–temp03 注册在服务器库里，重置靠第 5 步的**服务器
快照**恢复。开跑前经隧道查服务器健康，users 与服务器快照基线（2026-11-13
为 22）不一致，说明上一轮服务器恢复没跑完（临时账号残留），先用上一轮的
服务器快照恢复再开跑，不要直接登录旧临时账号接着用（数据是脏的）。

## 3. 产品经理汇总（串行，1 个子代理）

开工前先读 TEAM.md「能力配置」里林晚的四个 skill
（meeting-follow-up、documents、teamwork_delivery_guard、planning-task-breakdown），再读
6 份用户报告，按 TEAM.md 的林晚人设去重、归因、定优先级，
写 `runs/YYYY-MM-DD/digest.md`（含当日全部开发任务 +「待用户定」区）。
**UI 人工复核（用户 2026-11-07 指令）：AI 生成的 UI 不一定合理，林晚对每轮
UI 改动逐项人工复核（布局、间距、对比度、字号、文案合理性），不只看测试
通过；觉得不合理的写进 digest，返工到合理为止。**
用户长期规则（2026-11-06）：**反馈里需要修的，当天全部修完，不设数量
上限、不推到明天**（取消原来“每天最多 3 项小改动”的上限）。只有三类
不进当日任务——新功能、需要改 SRS/SDD 文档的需求变更、与 REQUIREMENTS.md
硬约束冲突的事项——注明依据放「待产品经理定」区。用户 2026-11-08 改定
（见 DECISIONS.md）：待定事项不再报给用户，全部由产品经理林晚在轮内
决定，决定记入 DECISIONS.md 后即可排入当日任务；与硬约束冲突的仍不排入，
注明依据放回待定区。**排任务前必读 REQUIREMENTS.md
（SRS v1.4 与 SDD v1.0 的硬约束：类别固定、组织者须自行报名、详情页不含
名单与联系方式、通知矩阵、R1～R5、不新增文档外字段）；与硬约束冲突的
事项不排入任务，注明依据放回待用户定区。**服务器版滞后口径（2026-11-13
起）：体验走的是已部署的服务器版，比本地代码最多落后两轮；反馈若命中
近两轮 changes.md 里已修、但还没部署到服务器的改动，digest 标
「已修待部署」，不重复排任务（部署节奏见第 6 步）。**同步更新长期用户的 journal
（各追加 2–3 行当日体验摘要）。

## 4. 开发优化（串行：后端 + 前端各 1 个子代理，最后测试 1 个）

开工前各先读自己的 skill：沈默读 campus-buddy-backend、
superpowers-systematic-debugging、superpowers-test-driven-development，
苏晴读 claude-rea-design + MOBILE.md、antfu-vue、vue-debug，陈诺读
campus-buddy-qa、superpowers-verification-before-completion、webapp-testing
（路径见 TEAM.md「能力配置」）。

- 后端（沈默）、前端（苏晴）按 digest 的任务改代码。编程任务用 Claude Code
  CLI（`~/.npm-global/bin/claude -p --permission-mode acceptEdits` 非交互模式，
  模型已锁 DeepSeek flash，走用户 OpenCode Go 额度；密钥不读不传，
  见 TEAM.md「能力配置」）。
  **先复现后修复**：
  每个任务动手前先复现问题（写失败测试，或跑一段复现脚本，或留复现
  步骤 + 截图/日志），复现成功再修；修完跑复现验证通过才算做完；
  复现不出来的先写明复现尝试与结论，不凭猜测改代码。改动记入
  `runs/YYYY-MM-DD/changes.md`（复现方法、根因、改了什么、证据）。
- 测试（陈诺）独立复核：后端测试在两个库上都跑（A 版 8080、B 版 8081，
  各 46/46；测试参数 INVITE_TTL=10 SWEEP_SECONDS=2，BASE_URL 换端口）、
  移动端测试 16/16（只跑当天抽中的本地版本——新代码在本地，服务器版是
  已部署的旧 jar，测它验不到当日改动）、数据库不变量复核（容量、
  唯一约束、重复/孤儿全 0，两库各查一遍，MySQL 用 NOW()）；不通过打回。
  **全部测试只对本地双库跑，绝不对服务器版跑：test_audit 会调
  /demo/reset，在服务器上执行等于把线上真实数据清回种子态。**

## 5. 恢复数据库并交付

1. 用步骤 1 的快照恢复，复核计数回到快照时状态。**恢复即临时账号的重置：
   当日新注册的 temp01–temp03 及它们的报名、通知、留言、发布全部清掉，次日
   新角色重新注册同名即是干净账号；长期账号（organizer、demo01、demo05）
   在快照里，恢复保留。**恢复 PG 快照必须先
   dropdb + createdb 再 `psql -f`（pg_dump 不含 DROP，直接恢复会残留
   测试产生的多余行）；快照文件须先 cp 到 /tmp 并 chown pgdemo
   （runs 目录文件 pgdemo 读不了）。**B 版用 DROP/CREATE + `mysql <`
   恢复（命令见 DUAL-DB.md）。两个库的恢复互不影响，但各恢复各的
   快照，不要串。如当日有结构改动（迁移文件在
   `runs/YYYY-MM-DD/migrations/`），恢复后重新执行迁移文件，
   再复核计数与不变量；迁移须同步更新 `schema.sql`（见 DECISIONS.md
   「结构改动规则」）。
2. **恢复服务器数据库（2026-11-13 起）**：SSH 到 Azure，先
   `sudo systemctl stop campus-buddy`，再用第 1 步的服务器快照恢复
   （`sudo -u postgres psql campus_buddy < /home/azureuser/snapshots/db-before-YYYY-MM-DD.sql`，
   恢复前先 DROP/CREATE 或整表清理的口径按服务器快照形式定，恢复后
   计数必须回到快照基线），然后 `sudo systemctl start campus-buddy`，
   经隧道验 /api/health（ok 且计数与基线一致）、demo01 登录通过。
   **只走快照恢复，绝不用 /demo/reset。**
3. 写 `runs/YYYY-MM-DD/report.md`（当天摘要：用户反馈 Top 3、改了什么、
   没改什么及原因、明日关注点）。
4. 把摘要发到用户所在的 side chat（本对话），完整报告留档，不贴长文。

## 6. 同步服务器与 GitHub（每两次更新一次）

用户规则（2026-11-13，取代 2026-11-06 的「每次都自动推」）：每日改动
先攒着，每满两轮（两次更新）同步一次——部署最新 jar 到 Azure 服务器 +
把累计改动推 GitHub（lemonwater379/campus-buddy，main）。授权不变，
只改节奏。2026-11-13 已补同步 11-12、11-13 两轮；计数从 2026-11-14
起算（第 1 轮 11-14、第 2 轮 11-15，11-15 轮末同步），以此类推。

1. **每轮都做**：第 5 步后，把当日改动文件清单（代码、测试、TEAM.md、
   RUNBOOK.md、DECISIONS.md、REQUIREMENTS.md、DUAL-DB.md、
   new-user-angles.md 等 UTF-8 文本；不含 runs/ 报告与截图、日志、jar、
   二进制、node_modules、target/、static 构建产物）追加进持久待同步
   清单 `daily-simulation/pending-sync-paths.txt`（NUL 分隔，放
   workspace，不要放 /tmp——重置会清），并在 report.md 里记明
   「本轮为第 N 次更新，同步轮 / 非同步轮」。
2. **同步轮（第 2 轮）在第 5 步后执行**：
   - 部署：先 `md5sum` 核对本地
     `backend/target/campus-buddy-1.0.0.jar`；SSH（走第 0 步第 7 条的
     ProxyCommand）到 Azure，先备份旧 jar
     （`cp campus-buddy-1.0.0.jar campus-buddy-1.0.0.jar.bak-YYYYMMDD`），
     再 scp 新 jar 到 `/home/azureuser/campus-buddy-1.0.0.jar`，
     `sudo systemctl restart campus-buddy`，等 20 秒以上验
     /api/health（ok 且 users/activities 与部署前一致）、demo01 登录、
     首页可打开。部署只换 jar、不动数据库（SeedRunner 只在空库播种，
     线上有数据时不动；无结构改动时直接换 jar，有迁移时先在本地
     双库验过再部署）。
   - GitHub：按 `/opt/hatch/connectors/github/references/snapshot-push.md`
     走：先用 `list_commits` 核对远端 main 的 head 与同步记录
     `~/workspace/campus-buddy.muse-github-snapshot-sync.json` 最新一条
     一致，再 `github push-files` 推待同步清单里的全部文件，成功后
     把新提交 SHA 与清单追加进同步记录（先写 `.tmp-*` 再原子替换），
     再查一次 head 确认，最后清空 `pending-sync-paths.txt`。
3. GitHub 写操作每次仍会弹出一次审批卡（安全规则，绕不过），由用户点
   一下确认；审批超时、或部署/推送被虚拟机重置打断，记为待同步、
   不阻塞当日交付，**下一轮开跑先补做这次同步，补上后计数重新开始**。
   不要因为等审批而拖延报告交付。

## 7. 失败处理

- 环境重建失败：不硬跑用户体验，先修环境，当日只交付失败说明。
- 某用户代理失败：其余继续，digest 注明缺失的一份，不编造。
- 开发改动导致测试变红：回滚改动，当日重修；重修仍不通过才记入明日队列并说明原因，changes.md 如实记。
