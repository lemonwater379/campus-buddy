package com.campusbuddy.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.sql.PreparedStatement;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * 核心业务：报名 / 退出 / 递补确认 / 超时顺延，全部在事务内完成。
 * 并发控制：先 SELECT ... FOR UPDATE 锁定活动行，串行化同一活动的容量核算，
 * 等价于 SRS 要求的行锁；邀请终态用 WHERE status='PENDING' 条件更新，
 * 影响行数 != 1 即说明已被另一方抢先处理。
 * 有效占用 = 正式人数 + 未过期待确认邀请数，必须 <= capacity。
 */
@Service
public class BuddyService {
    private final JdbcTemplate jdbc;
    private final int inviteTtlSeconds;
    /** 任务 8（2026-11-08 补丁）：递补邀请只在白天时段发出，默认 8:00–22:00（服务器时间 Asia/Shanghai），
     *  可配：app.invite-day-start-hour / app.invite-day-end-hour。 */
    private final int dayStartHour;
    private final int dayEndHour;
    /** 启动时从 DataSource 取数据库产品名判断一次并缓存：MySQL 用 INSERT IGNORE，
     *  PostgreSQL 保持 ON CONFLICT DO NOTHING。两分支语义相同：event_key 冲突时静默跳过。 */
    private final boolean mysql;
    /** E2-9：批处理失败留痕；只记录任务名与异常类，不带 SQL、绑定值或用户信息。 */
    private static final Logger log = LoggerFactory.getLogger(BuddyService.class);

    public BuddyService(JdbcTemplate jdbc, @Value("${app.invite-ttl-seconds:120}") int inviteTtlSeconds,
                        @Value("${app.invite-day-start-hour:8}") int dayStartHour,
                        @Value("${app.invite-day-end-hour:22}") int dayEndHour) {
        this.jdbc = jdbc;
        this.inviteTtlSeconds = inviteTtlSeconds;
        this.dayStartHour = dayStartHour;
        this.dayEndHour = dayEndHour;
        this.mysql = detectMysql(jdbc);
    }

    /** 任务 8：白天时段判断。时段为 [start, end)，默认 8:00–22:00；22:00 整算夜间。 */
    public boolean isDaytime(LocalDateTime now) {
        int h = now.getHour();
        return h >= dayStartHour && h < dayEndHour;
    }

    private static boolean detectMysql(JdbcTemplate jdbc) {
        try (var con = jdbc.getDataSource().getConnection()) {
            return con.getMetaData().getDatabaseProductName().toLowerCase().contains("mysql");
        } catch (Exception e) {
            throw new IllegalStateException("无法识别数据库产品", e);
        }
    }

    public int inviteTtlSeconds() { return inviteTtlSeconds; }

    /** 全站时间约定（2026-11-06 时区统一改造：全系统东八区直通）：
     *  所有时间字段均为东八区（Asia/Shanghai）墙钟，直接存取，不做任何时区转换。
     *  JVM 以 -Duser.timezone=Asia/Shanghai 启动，LocalDateTime.now() 即东八区墙钟；
     *  数据库服务器时区同样为 Asia/Shanghai，SQL now()/NOW() 默认值与 Java 写入一致。
     *  Timestamp.valueOf / asLocalDateTime 只按 JVM 默认时区在墙钟与毫秒之间换算，
     *  不改变时刻值。Jackson 仍配 spring.jackson.time-zone=Asia/Shanghai：
     *  PostgreSQL 驱动把 TIMESTAMP 列返回为 Timestamp（Date 子类），Jackson 按该
     *  时区序列化才是墙钟原值；MySQL 驱动返回 LocalDateTime，按原值序列化。 */
    private static final DateTimeFormatter MINUTE_FMT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    /** 东八区墙钟 → "yyyy-MM-dd HH:mm"（通知文案用，无 T、无纳秒）。
     *  直通格式化：入参已是东八区墙钟，不做任何时区转换（2026-11-06 时区统一改造，
     *  旧实现经 utcWallToShanghai 换算已删除）。 */
    public static String fmtShanghaiMinute(LocalDateTime wall) {
        return wall.format(MINUTE_FMT);
    }

    /** 任务 6 + 19（2026-11-09）：通知时间全格式 "yyyy-MM-dd 周X 时段 HH:mm"，
     *  时段词统一四段（凌晨 0–6 / 上午 6–12 / 下午 12–18 / 晚上 18–24，与
     *  大厅时段筛选口径一致；不再用「中午」）。 */
    private static final String[] WEEK = {"周日", "周一", "周二", "周三", "周四", "周五", "周六"};

    private static String periodOf(int hour) {
        if (hour < 6) return "凌晨";
        if (hour < 12) return "上午";
        if (hour < 18) return "下午";
        return "晚上";
    }

    public static String fmtFullMinute(LocalDateTime t) {
        return String.format("%04d-%02d-%02d %s %s %02d:%02d",
                t.getYear(), t.getMonthValue(), t.getDayOfMonth(),
                WEEK[t.getDayOfWeek().getValue() % 7], periodOf(t.getHour()),
                t.getHour(), t.getMinute());
    }

    /** 起止全格式：同日只写一次日期与星期，时段词相同时结束只写时间，
     *  如 "2026-11-10 周二 上午 10:41–下午 12:41"；跨日两边写全。 */
    public static String fmtFullRange(LocalDateTime start, LocalDateTime end) {
        if (start.toLocalDate().equals(end.toLocalDate())) {
            String p1 = periodOf(start.getHour()), p2 = periodOf(end.getHour());
            String endPart = p1.equals(p2)
                    ? String.format("%02d:%02d", end.getHour(), end.getMinute())
                    : p2 + " " + String.format("%02d:%02d", end.getHour(), end.getMinute());
            return fmtFullMinute(start) + "–" + endPart;
        }
        return fmtFullMinute(start) + "–" + fmtFullMinute(end);
    }

    private static Timestamp ts(LocalDateTime t) { return Timestamp.valueOf(t); }

    /** 数据库时间列转 LocalDateTime：MySQL 驱动把 DATETIME/TIMESTAMP 列返回为
     *  LocalDateTime，PostgreSQL 驱动返回为 Timestamp；两者都归一化，避免
     *  (Timestamp) 强转在 MySQL 上抛 ClassCastException。
     *  同时统一 toString() 的输出格式（ISO），两库返回的 JSON 时间格式一致。
     *  只做类型归一化，不做时区转换：Timestamp 按 JVM 默认时区（东八区）解读，
     *  得到的即库里存的东八区墙钟原值。 */
    private static LocalDateTime asLocalDateTime(Object v) {
        if (v instanceof LocalDateTime ldt) return ldt;
        if (v instanceof Timestamp t) return t.toLocalDateTime();
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime();
        throw new IllegalStateException("无法识别的时间类型: " + v);
    }

    /** 业务时间：锁内重新取服务器时间，纳秒截到秒。
     *  截秒是为了版本令牌双库一致——MySQL DATETIME(0) 只存到秒，若 Java 侧写纳秒，
     *  响应里返回的令牌与下一次从库里读出的 updated_at 会不相等。 */
    private static LocalDateTime nowSeconds() {
        return LocalDateTime.now().withNano(0);
    }

    /** 版本令牌：行的 updated_at 渲染值，统一用 LocalDateTime.toString()（ISO-8601 墙钟），
     *  与详情响应里 my_queued_at / invitation_expires_at 的既有渲染口径一致。
     *  A/B 两路及前端均按此字符串原样回传比较，不另做时区或格式转换。 */
    private static String versionOf(Object updatedAt) {
        return asLocalDateTime(updatedAt).toString();
    }

    /** 乐观并发校验：expected 为空表示不校验（旧客户端兼容）；不符返回 409（ConflictException）。 */
    private void requireVersion(String expected, Object actualUpdatedAt, String message) {
        if (expected == null || expected.isBlank()) return;
        String actual = versionOf(actualUpdatedAt);
        if (!expected.equals(actual))
            throw new ConflictException(message, Map.of("current_version", actual));
    }

    /** R2 候补名次：有效 WAITING 队列按 (queued_at, id) 升序，1 起算；不在队列中返回 null。 */
    private Integer waitingRank(long activityId, Object participationId) {
        var queue = jdbc.queryForList(
                "SELECT id FROM participation WHERE activity_id=? AND status='WAITING' " +
                        "ORDER BY queued_at, id", activityId);
        for (int i = 0; i < queue.size(); i++) {
            if (Objects.equals(((Number) queue.get(i).get("id")).longValue(),
                    ((Number) participationId).longValue())) return i + 1;
        }
        return null;
    }

    /** B7：候补通知里的确认窗口文案按实际配置生成（不再写死“2 分钟”）。
     *  ≥60 秒显示分钟（整分钟不带小数，否则保留 1 位），否则显示秒。 */
    private String inviteWindowText() {
        int s = inviteTtlSeconds;
        if (s >= 60) {
            if (s % 60 == 0) return (s / 60) + " 分钟";
            return String.format(Locale.ROOT, "%.1f 分钟", s / 60.0);
        }
        return s + " 秒";
    }

    /** B2：容量严格整数解析：接受整数型 Number / 整数值的 BigDecimal / 纯数字字符串；
     *  小数与 int 溢出返回 null（由调用方按字段错误拒绝），不做截断。 */
    private static Integer parseStrictInt(Object raw) {
        if (raw == null) return null;
        if (raw instanceof Integer i) return i;
        if (raw instanceof Short s) return (int) s;
        if (raw instanceof Byte b) return (int) b;
        if (raw instanceof Long l)
            return (l >= Integer.MIN_VALUE && l <= Integer.MAX_VALUE) ? l.intValue() : null;
        if (raw instanceof BigDecimal bd) {
            try { return bd.stripTrailingZeros().scale() <= 0 ? bd.intValueExact() : null; }
            catch (ArithmeticException e) { return null; }
        }
        if (raw instanceof Number n) {
            double d = n.doubleValue();
            if (!Double.isFinite(d) || d != Math.rint(d) || d < Integer.MIN_VALUE || d > Integer.MAX_VALUE)
                return null;
            return (int) d;
        }
        if (raw instanceof String str) {
            String t = str.trim();
            if (!t.matches("[+-]?\\d+")) return null;
            try { return Integer.parseInt(t); } catch (NumberFormatException e) { return null; }
        }
        return null;
    }

    /** B2：时间字段解析（String ISO / 已是 LocalDateTime / Timestamp）；无法解析返回 null。 */
    private static LocalDateTime parseTimeValue(Object raw) {
        if (raw instanceof LocalDateTime ldt) return ldt;
        if (raw instanceof Timestamp t) return t.toLocalDateTime();
        if (raw instanceof String s) {
            try { return LocalDateTime.parse(s.trim()); } catch (Exception e) { return null; }
        }
        return null;
    }

    private void notify(Long userId, Long activityId, Long invitationId,
                        String type, String content, String eventKey) {
        notifyWithSender(userId, activityId, invitationId, type, content, eventKey, null);
    }

    /** 带发送人的通知写入（任务 9 留言/回复用 sender_id；其余通知 sender 为空）。
     *  sender_id 列由 2026-11-09 迁移 001 加入，双库 schema 已同步。
     *  阶段一 A1（2026-11-15）：通知改走 outbox——写入时显式 status='PENDING'，
     *  publish_at 取当前时间，由 SweepService.publishOutbox() 翻为 PUBLISHED；
     *  event_key 去重口径保持不变。 */
    private void notifyWithSender(Long userId, Long activityId, Long invitationId,
                        String type, String content, String eventKey, Long senderId) {
        String sql = mysql
                ? "INSERT IGNORE INTO notification(user_id, activity_id, invitation_id, type, content, event_key, sender_id, status, publish_at) " +
                        "VALUES (?,?,?,?,?,?,?, 'PENDING', ?)"
                : "INSERT INTO notification(user_id, activity_id, invitation_id, type, content, event_key, sender_id, status, publish_at) " +
                        "VALUES (?,?,?,?,?,?,?, 'PENDING', ?) ON CONFLICT (user_id, event_key) DO NOTHING";
        jdbc.update(sql, userId, activityId, invitationId, type, content, eventKey, senderId,
                ts(LocalDateTime.now()));
    }

    /** 阶段一 A1：参与状态变迁流水。detail 可空；reschedule / removeMember 必须带。
     *  只做审计记录，不参与容量与状态计算。 */
    private void logEvent(long pid, long aid, long uid,
                          String type, String from, String to, String detail) {
        jdbc.update("INSERT INTO participation_events(participation_id, activity_id, user_id, " +
                        "event_type, from_status, to_status, detail, created_at) VALUES (?,?,?,?,?,?,?,?)",
                pid, aid, uid, type, from, to, detail, ts(LocalDateTime.now()));
    }

    /** DG-BE-06：活动字段级变更日志（activity_change_log，一行一字段）。old/new 统一字符串化，时间用既有全格式。 */
    private void logActivityChange(long activityId, long actorId, String changeType, String field,
                                   Object oldValue, Object newValue, String reason) {
        jdbc.update("INSERT INTO activity_change_log(activity_id, actor_id, change_type, field, " +
                        "old_value, new_value, reason, created_at) VALUES (?,?,?,?,?,?,?,?)",
                activityId, actorId, changeType, field,
                oldValue == null ? null : String.valueOf(oldValue),
                newValue == null ? null : String.valueOf(newValue),
                reason, ts(LocalDateTime.now()));
    }
    /** 字段未变时不写日志行。 */
    private void logFieldChange(long activityId, long actorId, String changeType, String field,
                                Object oldValue, Object newValue, String reason) {
        if (!Objects.equals(oldValue, newValue))
            logActivityChange(activityId, actorId, changeType, field, oldValue, newValue, reason);
    }

    /** 组织者通知（任务 2，2026-11-07）：报名 / 进候补 / 退出 / 递补确认时通知组织者。
     *  SDD §6.8 矩阵：正式报名、退出、递补确认通知本人和组织者；DECISIONS.md 决定 1
     *  另定进候补也通知组织者。组织者本人操作时不重复发（报名人与组织者同一人时
     *  只保留本人那条通知）。内容含报名人昵称 + 活动名 + 时间地点（REQUIREMENTS 硬约束 4）。 */
    private void notifyOrganizer(long organizerId, long actorUserId, long activityId,
                                 String type, String content, String eventKey) {
        if (organizerId == actorUserId) return;
        notify(organizerId, activityId, null, type, content, eventKey);
    }

    private String nickname(long userId) {
        return jdbc.queryForObject("SELECT nickname FROM app_user WHERE id=?", String.class, userId);
    }

    /** 活动时间地点后缀（任务 6，2026-11-09）：时间写全
     *  "时间 2026-11-10 周二 上午 10:41–下午 12:41，地点 xxx"（开始 + 结束、
     *  星期、时段词）。调用方查活动时须同时取 start_time 与 end_time。 */
    private String activityWhenWhere(Map<String, Object> act) {
        return "时间 " + fmtFullRange(asLocalDateTime(act.get("start_time")), asLocalDateTime(act.get("end_time")))
                + "，地点 " + act.get("location");
    }

    private int formalCount(long activityId) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM participation WHERE activity_id=? AND status='FORMAL'",
                Integer.class, activityId);
    }

    private int reservedCount(long activityId, LocalDateTime now) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                "WHERE p.activity_id=? AND i.status='PENDING' AND i.expires_at > ?",
                Integer.class, activityId, ts(now));
    }

    private int waitingCount(long activityId) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM participation WHERE activity_id=? AND status='WAITING'",
                Integer.class, activityId);
    }

    /** 在同一事务内：只要还有空位且有候补，就按入队时间依次发邀请。 */
    private void promote(long activityId, LocalDateTime now) {
        while (true) {
            // 先锁活动行：退出/报名/超时三条路都在同一把锁下核算容量，避免超时顺延与报名并发超员
            var act = jdbc.queryForMap("SELECT capacity, deadline, status FROM activity WHERE id=? FOR UPDATE", activityId);
            if (!"OPEN".equals(act.get("status"))) return;
            LocalDateTime deadline = asLocalDateTime(act.get("deadline"));
            if (!now.isBefore(deadline)) return;
            int vacancy = ((Number) act.get("capacity")).intValue()
                    - formalCount(activityId) - reservedCount(activityId, now);
            if (vacancy <= 0) return;
            // E2-11：按 R2 顺序跳过当前停用或封禁中的账号，保持其 WAITING、不消耗名次，
            // 待账号恢复后由下一轮补发；账号口径与 AuthService.login 一致。
            var waiting = jdbc.queryForList(
                    "SELECT p.id, p.user_id FROM participation p JOIN app_user u ON u.id=p.user_id " +
                            "WHERE p.activity_id=? AND p.status='WAITING' AND u.status='ACTIVE' " +
                            "AND NOT EXISTS (SELECT 1 FROM user_ban b " +
                            "WHERE b.user_id=p.user_id AND b.lifted_at IS NULL) " +
                            "ORDER BY p.queued_at, p.id LIMIT 1", activityId);
            if (waiting.isEmpty()) return;
            long partId = ((Number) waiting.get(0).get("id")).longValue();
            long userId = ((Number) waiting.get(0).get("user_id")).longValue();
            String title = jdbc.queryForObject(
                    "SELECT title FROM activity WHERE id=?", String.class, activityId);
            if (!isDaytime(now)) {
                // 任务 8（补丁，文档不改）：夜间不发正式邀请，只给候补第 1 名发一条提示；
                // 邀请等白天由 SweepService.backfillDaytimeInvites 补发。event_key 按
                // (活动, 参与记录) 去重：同一空缺反复触发只提示一次；候补第 1 名换人时
                // （partId 不同）会给新第 1 名再提示一次。窗口、期限、顺延规则都不变。
                notify(userId, activityId, null, "邀请",
                        "活动「" + title + "」已有空缺，将于白天 " + dayStartHour + ":00 后发出邀请，请留意通知。",
                        "notify:night-hint:" + activityId + ":" + partId);
                return;
            }
            LocalDateTime expires = now.plusSeconds(inviteTtlSeconds);
            if (expires.isAfter(deadline)) expires = deadline;
            jdbc.update("UPDATE participation SET status='INVITED', updated_at=? WHERE id=?", ts(now), partId);
            String eventKey = "invite:" + partId + ":" + now;
            jdbc.update("INSERT INTO invitation(participation_id, status, issued_at, expires_at, event_key) " +
                            "VALUES (?,'PENDING',?,?,?)", partId, ts(now), ts(expires), eventKey);
            Long invId = jdbc.queryForObject(
                    "SELECT id FROM invitation WHERE event_key=?", Long.class, eventKey);
            logEvent(partId, activityId, userId, "INVITE_ISSUED", "WAITING", "INVITED", null);
            notify(userId, activityId, invId, "邀请",
                    "活动「" + title + "」已有空缺，请在 " + fmtFullMinute(expires) + " 前确认是否参加。",
                    "notify:" + eventKey);
        }
    }

    /** 任务 8：白天补发夜间暂缓的递补邀请。由 SweepService 每轮调用；夜间直接返回。
     *  只扫有候补的 OPEN 活动，实际发邀请仍走 promote()（容量 / 截止 / 白天三重门都在里面），
     *  所以不会多发、不会在截止后发。 */
    @Transactional(isolation = Isolation.READ_COMMITTED)
    public void backfillDaytimeInvites(LocalDateTime now) {
        if (!isDaytime(now)) return;
        var ids = jdbc.queryForList(
                "SELECT DISTINCT a.id FROM activity a JOIN participation p ON p.activity_id=a.id AND p.status='WAITING' " +
                "WHERE a.status='OPEN' AND a.deadline > ? ORDER BY a.id",
                Long.class, ts(now));
        for (Long id : ids) {
            // E2-9：原空 catch 会吞掉异常并继续使用可能已被 PG 标记失败的事务。
            // 记录任务名 + 异常类后向上抛出，由 Sweep / Governance 的调用方决定整轮处理。
            try {
                // 逐活动在调用前刷新业务时间，避免整批共用扫描时刻、排队等待跨过截止后仍按旧时间发邀请（E2-9 取时口径）。
                promote(id, nowSeconds());
            } catch (RuntimeException e) {
                log.warn("backfillDaytimeInvites promote failed, activityId={}, exception={}",
                        id, e.getClass().getSimpleName());
                throw e;
            }
        }
    }

    /** 阶段一 B-CEM-04：本人其他有效正式参与中，与本活动时间重叠的活动。
     *  重叠口径：other.start_time < 本.end_time AND 本.start_time < other.end_time；
     *  已取消 / 已结束的活动不再参与冲突判断。 */
    private List<Map<String, Object>> findTimeConflicts(long userId, long activityId,
                                                        LocalDateTime start, LocalDateTime end) {
        return jdbc.queryForList(
                "SELECT a.id AS activity_id, a.title, a.start_time, a.end_time " +
                        "FROM participation p JOIN activity a ON a.id=p.activity_id " +
                        "WHERE p.user_id=? AND p.status='FORMAL' AND p.activity_id<>? " +
                        "AND a.status NOT IN ('CANCELLED','ENDED') " +
                        "AND a.start_time < ? AND ? < a.end_time " +
                        "ORDER BY a.start_time, a.id",
                userId, activityId, ts(end), ts(start));
    }

    /** confirmConflict=false 时检查时间冲突；有冲突抛 ConflictException（HTTP 409）。
     *  时间字段给 ISO 字符串，与详情接口口径一致。 */
    private void checkTimeConflict(long userId, long activityId,
                                   LocalDateTime start, LocalDateTime end, boolean confirmConflict) {
        if (confirmConflict) return;
        var conflicts = findTimeConflicts(userId, activityId, start, end);
        if (conflicts.isEmpty()) return;
        List<Map<String, Object>> data = new ArrayList<>();
        for (var row : conflicts) {
            Map<String, Object> c = new LinkedHashMap<>();
            c.put("activity_id", ((Number) row.get("activity_id")).longValue());
            c.put("title", row.get("title"));
            c.put("start_time", asLocalDateTime(row.get("start_time")).toString());
            c.put("end_time", asLocalDateTime(row.get("end_time")).toString());
            data.add(c);
        }
        throw new ConflictException("报名时间与已有活动冲突", Map.of("conflicts", data));
    }

    @Transactional
    public Map<String, Object> signup(long activityId, long userId, boolean confirmConflict) {
        return signup(activityId, userId, confirmConflict, false);
    }

    /**
     * G16（2026-11-21）：活动 conditions 非空白时，新报名（无有效参与）必须显式确认已阅读参与条件——
     * conditionsConfirmed=false/缺省抛 ValidationException 拒绝（字段 conditions_confirmed）；
     * 已有有效参与（FORMAL/WAITING/INVITED）的幂等早返回不受门禁影响；
     * 确认时仍写 CONDITIONS_CONFIRMED 留痕（detail 含确认时刻）。
     */
    @Transactional
    public Map<String, Object> signup(long activityId, long userId, boolean confirmConflict,
                                      boolean conditionsConfirmed) {
        // P417：先锁活动，再以锁后的服务器时间完成全部边界判断；不能使用锁前读取的 now。
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        LocalDateTime now = nowSeconds();
        // P419：清理同一活动已到期的待确认邀请，再计算有效占用与本人申请状态。
        // 活动行已锁住，清理与后续报名/递补在同一串行边界内；只补发一次，避免每条
        // 过期邀请都重复计算/锁行。通知与流水沿用 expireOne 的口径。
        var expired = jdbc.queryForList(
                "SELECT i.id FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                        "WHERE p.activity_id=? AND p.status='INVITED' AND i.status='PENDING' " +
                        "AND i.expires_at <= ? ORDER BY i.expires_at, i.id",
                activityId, ts(now));
        for (var row : expired) {
            expireInvitationLocked(((Number) row.get("id")).longValue(), now, false);
        }
        if (!expired.isEmpty()) promote(activityId, now);
        // 活动锁仍持有；重新读取活动，清理/递补后容量和状态以当前值为准。
        act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        if (!"OPEN".equals(act.get("status"))) {
            // 任务 21（2026-11-11）：已取消活动给出明确文案；READY/RUNNING/ENDED 仍用通用提示。
            if ("CANCELLED".equals(act.get("status")))
                throw new CodedException("ACTIVITY_CANCELLED", "活动已取消，无法报名");
            throw new CodedException("ACTIVITY_NOT_OPEN", "活动不在报名期");
        }
        if (!now.isBefore(asLocalDateTime(act.get("deadline"))))
            throw new CodedException("SIGNUP_DEADLINE_PASSED", "已过报名截止时间");
        // DG-BE-05：被组织者移出且限制未解除者不得重报（复用/新建记录前判定）
        checkRemovedRestriction(activityId, userId);
        var existing = jdbc.queryForList(
                "SELECT * FROM participation WHERE activity_id=? AND user_id=?", activityId, userId);
        if (!existing.isEmpty()) {
            String st = (String) existing.get(0).get("status");
            if (st.equals("FORMAL") || st.equals("WAITING") || st.equals("INVITED")) {
                // 幂等：重试返回原结果，不产生第二条记录
                return detail(activityId, userId);
            }
            // 退出/过期后重新报名：复用同一条记录，候补时间重置（SRS 3.3.5.2）
        }
        // G16（2026-11-21）：条件确认服务端强制。上方已有有效参与的早返回不受影响（豁免）；
        // 无条件活动不拦；确认留痕逻辑（下方 if (conditionsConfirmed)）保持不动。
        Object conditionsRaw = act.get("conditions");
        if (conditionsRaw instanceof String condText && !condText.isBlank() && !conditionsConfirmed)
            throw new ValidationException("conditions_confirmed", "请先确认已阅读参与条件");
        int capacity = ((Number) act.get("capacity")).intValue();
        // E2-4 复核结论：已有候补队列时，新报名一律排队，不因瞬时空位越队。
        // 空位由 promote 按 R2 顺序发邀请消化：队首账号停用时跳过，夜间暂缓发邀。
        // 候补名次以 waitingRank 按 (queued_at, id) 实时计算的结果为准。
        boolean hasQueue = waitingCount(activityId) > 0;
        int occupied = formalCount(activityId) + reservedCount(activityId, now);
        String status = (!hasQueue && occupied < capacity) ? "FORMAL" : "WAITING";
        // 阶段一 B-CEM-04：将成为正式成员时才检查时间冲突（候补不占时间，不拦）。
        if (status.equals("FORMAL")) {
            checkTimeConflict(userId, activityId,
                    asLocalDateTime(act.get("start_time")), asLocalDateTime(act.get("end_time")),
                    confirmConflict);
        }
        if (existing.isEmpty()) {
            jdbc.update("INSERT INTO participation(activity_id, user_id, status, queued_at, joined_at, updated_at) " +
                            "VALUES (?,?,?, ?, ?, ?)",
                    activityId, userId, status,
                    status.equals("WAITING") ? ts(now) : null,
                    status.equals("FORMAL") ? ts(now) : null, ts(now));
        } else {
            jdbc.update("UPDATE participation SET status=?, queued_at=?, joined_at=?, updated_at=? " +
                            "WHERE activity_id=? AND user_id=?",
                    status, status.equals("WAITING") ? ts(now) : null,
                    status.equals("FORMAL") ? ts(now) : null, ts(now), activityId, userId);
        }
        long pid = jdbc.queryForObject(
                "SELECT id FROM participation WHERE activity_id=? AND user_id=?",
                Long.class, activityId, userId);
        logEvent(pid, activityId, userId,
                status.equals("FORMAL") ? "SIGNUP_FORMAL" : "SIGNUP_WAITING",
                existing.isEmpty() ? null : (String) existing.get(0).get("status"),
                status, null);
        if (conditionsConfirmed) {
            logEvent(pid, activityId, userId, "CONDITIONS_CONFIRMED",
                    null, status, "conditions_confirmed=true; confirmed_at=" + now);
        }
        String title = (String) act.get("title");
        long organizerId = ((Number) act.get("organizer_id")).longValue();
        String whenWhere = activityWhenWhere(act);
        if (status.equals("FORMAL")) {
            // 报名成功通知内容含活动名称及时间地点（REQUIREMENTS 硬约束 4）。
            // 组织者本人报名时不追加“联系组织者”提示，仅他人报名时追加。
            String formalContent = userId == organizerId
                    ? "你已成功报名活动「" + title + "」，" + whenWhere + "。"
                    : "你已成功报名活动「" + title + "」，" + whenWhere + "。出发前如需联系组织者，请在活动详情页留言，组织者回复后会在通知里提醒你。";
            notify(userId, activityId, null, "报名", formalContent,
                    "notify:formal:" + activityId + ":" + userId + ":" + now);
            notifyOrganizer(organizerId, userId, activityId, "报名",
                    "「" + nickname(userId) + "」已报名活动「" + title + "」，" + whenWhere + "。",
                    "notify:org:formal:" + activityId + ":" + userId + ":" + now);
        } else {
            // 按 R2 (queued_at, id) 计算真实排名：并发报名或重入队可能让本人不是最后一名。
            Integer rankValue = waitingRank(activityId, pid);
            int rank = rankValue == null ? waitingCount(activityId) : rankValue;
            notify(userId, activityId, null, "候补",
                    "活动「" + title + "」已满员，你已进入候补队列，第 " + rank + " 名，" + whenWhere + "。收到递补邀请后须在 " + inviteWindowText() + " 内确认，超时顺延给下一位。",
                    "notify:waiting:" + activityId + ":" + userId + ":" + now);
            notifyOrganizer(organizerId, userId, activityId, "候补",
                    "「" + nickname(userId) + "」已进入活动「" + title + "」的候补队列，" + whenWhere + "。",
                    "notify:org:waiting:" + activityId + ":" + userId + ":" + now);
        }
        return detail(activityId, userId);
    }

    /** 候补顺序由 queued_at, id 实时排序计算，移除候补后无需改写数据；
     *  保留方法名以表达“候补队列已重排”的语义（阶段一 abandon / removeMember 调用）。 */
    private void resequence(long activityId) { /* 排序即状态，无持久化序号可改 */ }

    /** 阶段一 A7：withdraw 仅正式成员可调；候补 / 待确认者走 abandon。
     *  其余状态流转、通知矩阵与文案保持原口径。 */
    public Map<String, Object> withdraw(long participationId, long userId) {
        return withdraw(participationId, userId, null, null);
    }

    @Transactional
    public Map<String, Object> withdraw(long participationId, long userId, Boolean confirmed, String version) {
        // 统一锁序：先无锁定位 activity_id，再锁活动、再锁参与记录；锁后再取 now。
        var before = jdbc.queryForMap("SELECT activity_id FROM participation WHERE id=?", participationId);
        long activityId = ((Number) before.get("activity_id")).longValue();
        jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        var part = jdbc.queryForMap(
                "SELECT * FROM participation WHERE id=? FOR UPDATE", participationId);
        if (!Objects.equals(((Number) part.get("user_id")).longValue(), userId))
            throw new IllegalStateException("只能操作自己的参与记录");
        requireVersion(version, part.get("updated_at"), "记录已变化，请刷新");
        String st = (String) part.get("status");
        if ("WITHDRAWN".equals(st))
            return participationResult(participationId, "WITHDRAWN", true, part.get("updated_at"));
        if (Boolean.FALSE.equals(confirmed)) throw new IllegalStateException("退出活动需二次确认");
        if (st.equals("WAITING") || st.equals("INVITED"))
            throw new IllegalStateException("候补状态请使用「放弃候补」");
        if (!st.equals("FORMAL"))
            throw new IllegalStateException("当前状态不可退出：" + st);
        // 锁后取业务时间：活动已开始时正式成员不得退出（设计 P428）。
        LocalDateTime now = nowSeconds();
        var actRow = jdbc.queryForMap("SELECT start_time FROM activity WHERE id=?", activityId);
        if (!now.isBefore(asLocalDateTime(actRow.get("start_time"))))
            throw new IllegalStateException("活动已开始，不能退出");
        jdbc.update("UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=?", ts(now), participationId);
        logEvent(participationId, activityId, userId, "WITHDRAW", "FORMAL", "WITHDRAWN", null);
        promote(activityId, now);
        // 任务 3-2：退出产生一条通知，否则退出前后两条「报名成功」无法分辨。
        // 类型存 '退出'（2026-11-08 任务 3：notification 表 CHECK 已放开 '退出'，
        // 见 runs/2026-11-08/migrations/001-*；历史 '变更' 退出通知由迁移一并改掉，
        // 前端按 '变更'→'退出' 的映射可保留作兼容，也可去掉）。
        var actW = jdbc.queryForMap(
                "SELECT organizer_id, title, location, start_time, end_time FROM activity WHERE id=?", activityId);
        String title = (String) actW.get("title");
        notify(userId, activityId, null, "退出",
                "你已退出活动「" + title + "」。",
                "notify:withdraw:" + participationId + ":" + now);
        // 任务 2：退出也通知组织者（SDD §6.8 矩阵；之前只通知本人是漏发）。
        notifyOrganizer(((Number) actW.get("organizer_id")).longValue(), userId, activityId, "退出",
                "「" + nickname(userId) + "」已退出活动「" + title + "」，" + activityWhenWhere(actW) + "。",
                "notify:org:withdraw:" + participationId + ":" + now);
        return participationResult(participationId, "WITHDRAWN", false, ts(now));
    }

    /** 阶段一 A7：放弃候补。WAITING → WITHDRAWN（重排候补顺序）；
     *  INVITED → 邀请 REJECTED + WITHDRAWN，并立即顺延下一位。
     *  通知文案按“放弃候补”口径，与正式退出的「已退出活动」区分。 */
    public Map<String, Object> abandon(long participationId, long userId) {
        return abandon(participationId, userId, null, null);
    }

    @Transactional
    public Map<String, Object> abandon(long participationId, long userId, Boolean confirmed, String version) {
        var before = jdbc.queryForMap("SELECT activity_id FROM participation WHERE id=?", participationId);
        long activityId = ((Number) before.get("activity_id")).longValue();
        jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        var part = jdbc.queryForMap(
                "SELECT * FROM participation WHERE id=? FOR UPDATE", participationId);
        if (!Objects.equals(((Number) part.get("user_id")).longValue(), userId))
            throw new IllegalStateException("只能操作自己的参与记录");
        requireVersion(version, part.get("updated_at"), "记录已变化，请刷新");
        String st = (String) part.get("status");
        if ("WITHDRAWN".equals(st))
            return participationResult(participationId, "WITHDRAWN", true, part.get("updated_at"));
        if (Boolean.FALSE.equals(confirmed)) throw new IllegalStateException("放弃候补需二次确认");
        if (!st.equals("WAITING") && !st.equals("INVITED"))
            throw new IllegalStateException("当前状态不可放弃候补：" + st);
        LocalDateTime now = nowSeconds();
        if (st.equals("INVITED")) {
            var invRows = jdbc.queryForList(
                    "SELECT * FROM invitation WHERE participation_id=? ORDER BY id DESC LIMIT 1 FOR UPDATE", participationId);
            if (invRows.isEmpty()) throw new IllegalStateException("邀请记录不存在");
            var inv = invRows.get(0);
            String invStatus = (String) inv.get("status");
            if ("PENDING".equals(invStatus) && !asLocalDateTime(inv.get("expires_at")).isAfter(now)) {
                expireInvitationLocked(((Number) inv.get("id")).longValue(), now, true);
                return participationResult(participationId, "EXPIRED", false, ts(now));
            }
            if ("EXPIRED".equals(invStatus))
                return participationResult(participationId, "EXPIRED", false, part.get("updated_at"));
            if (!"PENDING".equals(invStatus)) throw new IllegalStateException("邀请已失效：" + invStatus);
            // 未过期待确认者放弃 = 拒绝邀请，释放预留并顺延。
            jdbc.update("UPDATE invitation SET status='REJECTED', responded_at=? WHERE id=? AND status='PENDING'",
                    ts(now), inv.get("id"));
        }
        jdbc.update("UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=?", ts(now), participationId);
        if (st.equals("WAITING")) resequence(activityId);
        logEvent(participationId, activityId, userId, "ABANDON", st, "WITHDRAWN", null);
        var actW = jdbc.queryForMap(
                "SELECT organizer_id, title, location, start_time, end_time FROM activity WHERE id=?", activityId);
        String title = (String) actW.get("title");
        notify(userId, activityId, null, "退出",
                "你已放弃活动「" + title + "」的候补。",
                "notify:abandon:" + participationId + ":" + now);
        notifyOrganizer(((Number) actW.get("organizer_id")).longValue(), userId, activityId, "退出",
                "「" + nickname(userId) + "」已放弃活动「" + title + "」的候补，" + activityWhenWhere(actW) + "。",
                "notify:org:abandon:" + participationId + ":" + now);
        if (st.equals("INVITED")) promote(activityId, now);
        return participationResult(participationId, "WITHDRAWN", false, ts(now));
    }

    /** B4/B5 共用返回：状态 + 版本令牌（updated_at 渲染值）+ 幂等标志（加法字段）。 */
    private Map<String, Object> participationResult(long participationId, String status,
                                                    boolean already, Object updatedAt) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("participation_id", participationId);
        out.put("status", status);
        out.put("my_status", status);
        out.put("participation_version", versionOf(updatedAt));
        if (already) out.put("already", true);
        return out;
    }

    /** B5：事务内的邀请过期收尾（调用方已持有活动行与参与行锁）：
     *  邀请 EXPIRED、参与 EXPIRED、流水 INVITED→EXPIRED、发过期通知，
     *  并在 markPromote=true 时立即递补下一位。无条件推进，不再依赖「先改后抛」的那条路径。
     *  NC-12：系统过期收尾不写 read_at，未读语义只由用户操作产生。 */
    private boolean expireInvitationLocked(long invitationId, LocalDateTime now, boolean markPromote) {
        var invRows = jdbc.queryForList("SELECT * FROM invitation WHERE id=? FOR UPDATE", invitationId);
        if (invRows.isEmpty()) return false;
        var inv = invRows.get(0);
        if (!"PENDING".equals(inv.get("status"))) return false;
        long partId = ((Number) inv.get("participation_id")).longValue();
        var partRow = jdbc.queryForMap("SELECT activity_id, user_id FROM participation WHERE id=?", partId);
        long activityId = ((Number) partRow.get("activity_id")).longValue();
        long userId = ((Number) partRow.get("user_id")).longValue();
        int changed = jdbc.update(
                "UPDATE invitation SET status='EXPIRED' WHERE id=? AND status='PENDING' AND expires_at <= ?",
                invitationId, ts(now));
        if (changed != 1) return false;
        jdbc.update("UPDATE participation SET status='EXPIRED', updated_at=? WHERE id=?", ts(now), partId);
        logEvent(partId, activityId, userId, "INVITE_EXPIRED", "INVITED", "EXPIRED", null);
        String title = jdbc.queryForObject("SELECT title FROM activity WHERE id=?", String.class, activityId);
        boolean hasNext = waitingCount(activityId) > 0;
        notify(userId, activityId, invitationId, "邀请",
                hasNext ? "活动「" + title + "」的递补邀请已过期，名额已顺延至下一位候补。"
                        : "活动「" + title + "」的递补邀请已过期，名额已空出，可重新报名。",
                "notify:expired:" + invitationId);
        if (markPromote) promote(activityId, now);
        return true;
    }

    /** E1：事务内按“邀请失效”收尾（调用方已持参与 / 邀请 / 活动锁）：
     *  邀请 PENDING→EXPIRED、参与 INVITED→EXPIRED（条件更新，不覆盖新状态）、流水带原因、
     *  不写原邀请通知的 read_at（NC-12），仍发失效通知；markPromote=true 时立即递补下一位。
     *  不改 expires_at，也不走“只有真过期才可收尾”的过期 SQL。 */
    private boolean closeInvitationLocked(long invitationId, LocalDateTime now, boolean markPromote, String reason) {
        var invRows = jdbc.queryForList("SELECT * FROM invitation WHERE id=? FOR UPDATE", invitationId);
        if (invRows.isEmpty()) return false;
        var inv = invRows.get(0);
        if (!"PENDING".equals(inv.get("status"))) return false;
        long partId = ((Number) inv.get("participation_id")).longValue();
        var partRow = jdbc.queryForMap("SELECT activity_id, user_id FROM participation WHERE id=?", partId);
        long activityId = ((Number) partRow.get("activity_id")).longValue();
        long userId = ((Number) partRow.get("user_id")).longValue();
        int changed = jdbc.update(
                "UPDATE invitation SET status='EXPIRED', responded_at=? WHERE id=? AND status='PENDING'",
                ts(now), invitationId);
        if (changed != 1) return false;
        changed = jdbc.update(
                "UPDATE participation SET status='EXPIRED', updated_at=? WHERE id=? AND status='INVITED'",
                ts(now), partId);
        if (changed != 1) return false;
        logEvent(partId, activityId, userId, "INVITE_EXPIRED", "INVITED", "EXPIRED", reason);
        String title = jdbc.queryForObject("SELECT title FROM activity WHERE id=?", String.class, activityId);
        notify(userId, activityId, invitationId, "邀请",
                "活动「" + title + "」的递补邀请已失效：" + reason + "。",
                "notify:invalidated:" + invitationId);
        if (markPromote) promote(activityId, now);
        return true;
    }

    /** E1：respondInvitation 的业务错误结果。在事务内正常返回、随事务提交，
     *  由控制器在提交后按 _respond_error 标记映射为 400（不要删除该标记）。 */
    private Map<String, Object> respondError(String message, long activityId,
                                             long participationId, long invitationId) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("_respond_error", true);
        out.put("code", "ERROR");
        out.put("message", message);
        out.put("activity_id", activityId);
        out.put("activity_status", jdbc.queryForObject(
                "SELECT status FROM activity WHERE id=?", String.class, activityId));
        out.put("participation_id", participationId);
        out.put("my_status", jdbc.queryForObject(
                "SELECT status FROM participation WHERE id=?", String.class, participationId));
        out.put("invitation_id", invitationId);
        out.put("invitation_status", jdbc.queryForObject(
                "SELECT status FROM invitation WHERE id=?", String.class, invitationId));
        return out;
    }

    @Transactional(isolation = org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    public Map<String, Object> respondInvitation(long invitationId, long userId,
                                                 boolean accept, boolean confirmConflict) {
        // 遵循全局锁序：activity → participation → invitation。
        // 无锁读取 participation_id 和 activity_id 仅用于定位待加锁的行，
        // 后续业务判断以锁后读数为准。
        var inv0 = jdbc.queryForMap("SELECT participation_id FROM invitation WHERE id=?", invitationId);
        long partId0 = ((Number) inv0.get("participation_id")).longValue();
        var part0 = jdbc.queryForMap("SELECT activity_id FROM participation WHERE id=?", partId0);
        long activityId0 = ((Number) part0.get("activity_id")).longValue();
        // E1：活动行在锁内取全字段，accept 分支的状态 / 截止 / 容量复核都以锁后读数为准。
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId0);
        var part = jdbc.queryForMap("SELECT * FROM participation WHERE id=? FOR UPDATE", partId0);
        var inv = jdbc.queryForMap("SELECT * FROM invitation WHERE id=? FOR UPDATE", invitationId);
        if (!Objects.equals(((Number) part.get("user_id")).longValue(), userId))
            throw new IllegalStateException("只能操作自己的邀请");
        long activityId = ((Number) part.get("activity_id")).longValue();
        // E1（NC-01/NC-02 同根）：三把锁全部取得后再取业务时间；MySQL 默认 RR 下锁前的
        // 普通读取会固定旧计数快照，显式 READ_COMMITTED 保证复核读到最新已提交状态。
        LocalDateTime now = nowSeconds();
        String invStatus = (String) inv.get("status");
        if (!"PENDING".equals(invStatus)) {
            // E1（B5 扩展）：终态邀请一律 4xx + 当前真实状态，不再返回 200 旧结果。
            String prefix = "EXPIRED".equals(invStatus) ? "邀请已过期" : "邀请已不可应答";
            throw new IllegalStateException(prefix + "，当前状态：" + invStatus);
        }
        // E1：旧邀请不得覆盖新周期——只允许该参与记录最新一条邀请被应答。
        Long latestInvId = jdbc.queryForObject(
                "SELECT MAX(id) FROM invitation WHERE participation_id=?", Long.class, partId0);
        if (latestInvId == null || latestInvId.longValue() != invitationId)
            return respondError("邀请已失效，请刷新后重试", activityId, partId0, invitationId);
        // E1：先确认参与行仍为 INVITED，再做过期收尾——旧 PENDING 邀请挂在
        // FORMAL/WITHDRAWN/WAITING 参与行时，不得由过期分支无条件覆盖新状态。
        String st = (String) part.get("status");
        if (!"INVITED".equals(st))
            return respondError("参与状态已变化：" + st, activityId, partId0, invitationId);
        if (!now.isBefore(asLocalDateTime(inv.get("expires_at")))) {
            // E1（NC-03/NC-13）：等号即过期。先在同一事务内做真实收尾（邀请/参与 EXPIRED、
            // 流水、通知、递补），再正常返回错误结果让事务提交；绝不在此抛异常回滚收尾。
            expireInvitationLocked(invitationId, now, true);
            return respondError("邀请已过期，无法接受", activityId, partId0, invitationId);
        }
        if (accept) {
            // E1：活动门禁复核（防御分支；通常过期分支已先命中）。
            if (!"OPEN".equals(act.get("status"))
                    || !now.isBefore(asLocalDateTime(act.get("deadline")))) {
                closeInvitationLocked(invitationId, now, false, "活动已不可报名");
                return respondError("活动已不可报名，邀请已失效", activityId, partId0, invitationId);
            }
            // E1（NC-01）：活动锁内、转 FORMAL 前重核容量——同一名额不得被重复占用。
            // 本人邀请已确认是当前活动的有效预留，reservedCount 减 1 恰好排除这条将被消费的邀请。
            int capacity = ((Number) act.get("capacity")).intValue();
            int occupied = formalCount(activityId) + (reservedCount(activityId, now) - 1);
            if (occupied >= capacity) {
                closeInvitationLocked(invitationId, now, false, "名额已被占用");
                return respondError("名额已满，邀请已失效", activityId, partId0, invitationId);
            }
            // 阶段一 B-CEM-04：接受递补将转为正式成员，同样检测时间冲突；
            // 冲突时抛 409，邀请保持 PENDING（事务回滚，不落任何变更）。
            checkTimeConflict(userId, activityId,
                    asLocalDateTime(act.get("start_time")), asLocalDateTime(act.get("end_time")),
                    confirmConflict);
            int changed = jdbc.update(
                    "UPDATE invitation SET status='ACCEPTED', responded_at=? WHERE id=? AND status='PENDING'",
                    ts(now), invitationId);
            if (changed != 1) throw new IllegalStateException("邀请已被另一方处理");
            int partChanged = jdbc.update(
                    "UPDATE participation SET status='FORMAL', joined_at=?, updated_at=? WHERE id=? AND status='INVITED'",
                    ts(now), ts(now), partId0);
            if (partChanged != 1) throw new IllegalStateException("参与状态已变化");
            logEvent(partId0, activityId, userId, "INVITE_ACCEPTED", "INVITED", "FORMAL", null);
            // 任务 4：接受递补邀请后，原邀请通知标已读（与过期情形 expireOne 一致）。
            jdbc.update("UPDATE notification SET read_at=? WHERE invitation_id=? AND type='邀请' AND read_at IS NULL",
                    ts(now), invitationId);
            // 任务 2：递补确认通知组织者（SDD §6.8 矩阵）。
            notifyOrganizer(((Number) act.get("organizer_id")).longValue(), userId, activityId, "报名",
                    "「" + nickname(userId) + "」已确认参加活动「" + act.get("title") + "」，" + activityWhenWhere(act) + "。",
                    "notify:org:accept:" + invitationId);
            // 2026-11-18 批次1 F1：REQUIREMENTS 硬约束 4「递补确认——通知本人和组织者」，
            // 原实现只调用了 notifyOrganizer，本人侧缺一条确认通知（探针 P7-A7-05）。
            notify(userId, activityId, invitationId, "报名",
                    "你已确认参加活动「" + act.get("title") + "」，" + activityWhenWhere(act) + "。",
                    "notify:accept:" + invitationId);
        } else {
            int changed = jdbc.update(
                    "UPDATE invitation SET status='REJECTED', responded_at=? WHERE id=? AND status='PENDING'",
                    ts(now), invitationId);
            if (changed != 1) throw new IllegalStateException("邀请已被另一方处理");
            int partChanged = jdbc.update(
                    "UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=? AND status='INVITED'",
                    ts(now), partId0);
            if (partChanged != 1) throw new IllegalStateException("参与状态已变化");
            logEvent(partId0, activityId, userId, "INVITE_REJECTED", "INVITED", "WITHDRAWN", null);
            promote(activityId, now);
        }
        return detail(activityId, userId);
    }

    /** 超时顺延：仅成功抢占邀请状态的任务可处理一次（条件更新 + 事务）。 */
    @Transactional
    public boolean expireOne(long invitationId) {
        // E2-8：全局锁序为 activity → participation → invitation（条件更新）；无锁读取仅用于定位。
        var inv0 = jdbc.queryForMap("SELECT participation_id FROM invitation WHERE id=?", invitationId);
        long partId = ((Number) inv0.get("participation_id")).longValue();
        var part0 = jdbc.queryForMap("SELECT activity_id FROM participation WHERE id=?", partId);
        long activityId0 = ((Number) part0.get("activity_id")).longValue();
        jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId0);
        var part = jdbc.queryForMap("SELECT activity_id, user_id FROM participation WHERE id=? FOR UPDATE", partId);
        long activityId = ((Number) part.get("activity_id")).longValue();
        long userId = ((Number) part.get("user_id")).longValue();
        LocalDateTime now = nowSeconds();
        int changed = jdbc.update(
                "UPDATE invitation SET status='EXPIRED' WHERE id=? AND status='PENDING' AND expires_at <= ?",
                invitationId, ts(now));
        if (changed != 1) return false;
        jdbc.update("UPDATE participation SET status='EXPIRED', updated_at=? WHERE id=?", ts(now), partId);
        // E1（B8）：过期流水与参与真实终态一致：INVITED→EXPIRED。
        logEvent(partId, activityId, userId, "INVITE_EXPIRED", "INVITED", "EXPIRED", null);
        // 任务 3-3：邀请过期要让被邀请人知道。不再标已读（NC-12：系统收尾不写 read_at），
        // 只发过期通知。类型用 '邀请'（notification 表 CHECK 允许，不改表）。
        String title = jdbc.queryForObject("SELECT title FROM activity WHERE id=?", String.class, activityId);
        // 任务 11（2026-11-10）：按当时有无下一位有效候补区分文案——有下一位才写顺延，
        // 无人写「名额已空出，可重新报名」（参与记录已置 EXPIRED，不计入 waitingCount）。
        boolean hasNext = waitingCount(activityId) > 0;
        notify(userId, activityId, invitationId, "邀请",
                hasNext
                        ? "活动「" + title + "」的递补邀请已过期，名额已顺延至下一位候补。"
                        : "活动「" + title + "」的递补邀请已过期，名额已空出，可重新报名。",
                "notify:expired:" + invitationId);
        promote(activityId, now);
        return true;
    }

    /** 截止收尾不推进活动生命周期；活动已开始/结束时也可清理错过扫描的队列。
     *  G06（2026-11-21）：守卫口径仅拒绝 ENDED/CANCELLED，OPEN/READY/RUNNING 均可收尾，
     *  避免活动在截止后被推进到 RUNNING 时，WAITING/INVITED 队列永远清不掉。 */
    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Map<String, Object> closeOutActivity(long activityId, LocalDateTime scanTime) {
        var acts = jdbc.queryForList("SELECT status, deadline FROM activity WHERE id=? FOR UPDATE", activityId);
        // 扫描时间只用于调用方选取候选；以实际取得活动锁后的时间为准。
        LocalDateTime now = nowSeconds();
        if (acts.isEmpty() || Set.of("ENDED", "CANCELLED").contains(acts.get(0).get("status"))
                || now.isBefore(asLocalDateTime(acts.get(0).get("deadline"))))
            return Map.of("waitingClosed", 0, "invitedClosed", 0);

        var pending = jdbc.queryForList("SELECT id, user_id, status FROM participation " +
                "WHERE activity_id=? AND status IN ('WAITING','INVITED') ORDER BY id FOR UPDATE", activityId);
        int waitingClosed = 0;
        int invitedClosed = 0;
        for (var part : pending) {
            long partId = ((Number) part.get("id")).longValue();
            long userId = ((Number) part.get("user_id")).longValue();
            String status = (String) part.get("status");
            boolean invited = "INVITED".equals(status);
            if (invited) invalidatePendingInvitations(partId, now);
            if (jdbc.update("UPDATE participation SET status='EXPIRED', updated_at=? WHERE id=? AND status=?",
                    ts(now), partId, status) != 1)
                throw new IllegalStateException("参与状态已变化");
            logEvent(partId, activityId, userId, "SIGNUP_CLOSED", status, "EXPIRED",
                    invited ? "报名截止，原邀请作废" : "报名截止，未获得名额");
            if (invited) invitedClosed++;
            else waitingClosed++;
        }
        return Map.of("waitingClosed", waitingClosed, "invitedClosed", invitedClosed);
    }

    /** 调用方持有活动行及关联参与行锁；终态邀请不覆盖。 */
    private void invalidatePendingInvitations(long participationId, LocalDateTime now) {
        jdbc.update("UPDATE invitation SET status='INVALID', responded_at=? " +
                "WHERE participation_id=? AND status='PENDING'", ts(now), participationId);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Map<String, Object> cancelActivity(long activityId, long userId) {
        return cancelActivity(activityId, userId, null, null);
    }

    /** 取消前在锁内锁定并保存参与快照；通知和流水与状态改动同一事务。 */
    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Map<String, Object> cancelActivity(long activityId, long userId, String reason, Boolean confirmed) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        if (!Objects.equals(((Number) act.get("organizer_id")).longValue(), userId))
            throw new IllegalStateException("只有组织者可以取消活动");
        // G04（2026-11-21）：已取消的重复请求先走幂等返回，不受下方二次确认/原因/结束边界新校验影响。
        if ("CANCELLED".equals(act.get("status")))
            return Map.of("ok", true, "status", "CANCELLED", "alreadyCancelled", true, "notified", 0);
        // G04（2026-11-21）：confirmed 必须显式为 true，缺省 null 与 false 均拒绝。
        if (!Boolean.TRUE.equals(confirmed))
            throw new ValidationException("confirmed", "取消活动需二次确认");
        // G04（2026-11-21）：取消原因必填（非空白），落库存 trim 后的原因。
        if (reason == null || reason.isBlank())
            throw new ValidationException("reason", "取消原因不能为空");
        // G04（2026-11-21）：锁后提前取业务时间，结束边界同时按状态与实际结束时刻判定。
        LocalDateTime now = nowSeconds();
        if ("ENDED".equals(act.get("status")) || !now.isBefore(asLocalDateTime(act.get("end_time"))))
            throw new IllegalStateException("活动已结束，不能取消");

        String trimmedReason = reason.strip();
        String reasonDetail = "取消原因：" + trimmedReason;
        // participation_events.detail 最多 500 字，须给「取消原因：」留 5 字。
        if (reasonDetail != null && reasonDetail.codePointCount(0, reasonDetail.length()) > 500)
            throw new ValidationException("reason", "取消原因不能超过 495 字");
        // 一并锁定可能关联残留 PENDING 邀请的终态参与，但不改这些参与、不通知它们。
        var parts = jdbc.queryForList("SELECT id, user_id, status FROM participation " +
                "WHERE activity_id=? ORDER BY id FOR UPDATE", activityId);
        var recipients = parts.stream()
                .filter(p -> Set.of("FORMAL", "WAITING", "INVITED").contains(p.get("status"))).toList();
        // G04（2026-11-21）：now 已在校验区提前取得，这里直接复用。
        jdbc.update("UPDATE activity SET status='CANCELLED', updated_at=? WHERE id=?", ts(now), activityId);
        // G04（2026-11-21）：变更日志与流水一致，落库存 trim 后的原因。
        logActivityChange(activityId, userId, "CANCEL", "status", act.get("status"), "CANCELLED", trimmedReason);
        jdbc.update("UPDATE invitation SET status='INVALID', responded_at=? WHERE participation_id IN " +
                "(SELECT id FROM participation WHERE activity_id=?) AND status='PENDING'", ts(now), activityId);
        jdbc.update("UPDATE participation SET status='CANCELLED', updated_at=? " +
                "WHERE activity_id=? AND status IN ('FORMAL','WAITING','INVITED')", ts(now), activityId);
        String range = fmtFullRange(asLocalDateTime(act.get("start_time")), asLocalDateTime(act.get("end_time")));
        for (var part : recipients) {
            long pid = ((Number) part.get("id")).longValue();
            long uid = ((Number) part.get("user_id")).longValue();
            String status = (String) part.get("status");
            logEvent(pid, activityId, uid, "ACTIVITY_CANCELLED", status, "CANCELLED", reasonDetail);
            notify(uid, activityId, null, "取消",
                    "活动「" + act.get("title") + "」已取消，原定时间 " + range + "，地点 " + act.get("location") + "。"
                            + ("INVITED".equals(status) ? "原邀请作废。" : "")
                            + (reasonDetail == null ? "" : reasonDetail + "。"),
                    "notify:cancel:" + activityId + ":" + uid);
        }
        return Map.of("ok", true, "status", "CANCELLED", "alreadyCancelled", false, "notified", recipients.size());
    }

    private static final Set<String> EDIT_FIELDS = Set.of("title", "category", "description", "conditions",
            "location", "capacity", "deadline", "start_time", "end_time", "startTime", "endTime");
    private static final Set<String> ACTIVITY_CATEGORIES = Set.of("羽毛球", "桌游", "学习组", "其他");
    private static final String EFFECTIVE_RESERVATIONS =
            " FROM invitation i JOIN participation p ON p.id=i.participation_id "
            + "WHERE p.activity_id=? AND i.status='PENDING' AND i.expires_at > ?";

    /** 仅在报名期内编辑既有字段；保留参与、活动标识和已发出邀请的期限。 */
    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Map<String, Object> editActivity(long organizerId, long activityId,
                                            Map<String, Object> fields, String expectedVersion) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        LocalDateTime now = nowSeconds();
        if (((Number) act.get("organizer_id")).longValue() != organizerId)
            throw new IllegalStateException("只有组织者可以修改活动");
        // G03（2026-11-21）：活动编辑链强制要求版本令牌，缺失直接拒绝；withdraw/abandon 的可选版本口径不变。
        if (expectedVersion == null || expectedVersion.isBlank())
            throw new ValidationException("expectedVersion", "缺少版本号，请刷新后重试");
        requireVersion(expectedVersion, act.get("updated_at"), "活动已变化，请刷新");
        if (!"OPEN".equals(act.get("status"))) throw new IllegalStateException("活动不在报名期，不可修改");
        LocalDateTime oldDeadline = asLocalDateTime(act.get("deadline"));
        if (!now.isBefore(oldDeadline)) throw new IllegalStateException("报名已截止，不可修改");

        Map<String, Object> edits = fields == null ? Map.of() : fields;
        for (String field : edits.keySet()) {
            if (field == null || !EDIT_FIELDS.contains(field))
                throw new ValidationException("fields", "包含不可修改的活动字段");
        }
        Map<String, String> errors = new LinkedHashMap<>();
        String title = editText(edits.getOrDefault("title", act.get("title")), "title", "标题", 50, true, errors);
        String location = editText(edits.getOrDefault("location", act.get("location")), "location", "地点", 100, true, errors);
        String description = editText(edits.getOrDefault("description", act.get("description")),
                "description", "介绍", 2000, false, errors);
        String conditions = editText(edits.getOrDefault("conditions", act.get("conditions")),
                "conditions", "参与条件", 500, false, errors);
        Object category = edits.getOrDefault("category", act.get("category"));
        if (!(category instanceof String s) || !ACTIVITY_CATEGORIES.contains(s))
            errors.put("category", "类别不合法");
        int oldCapacity = ((Number) act.get("capacity")).intValue();
        Integer capacity = parseStrictInt(edits.getOrDefault("capacity", oldCapacity));
        if (capacity == null || capacity < 1 || capacity > 100)
            errors.put("capacity", "人数上限需为 1-100 的整数");

        LocalDateTime oldStart = asLocalDateTime(act.get("start_time"));
        LocalDateTime oldEnd = asLocalDateTime(act.get("end_time"));
        LocalDateTime deadline = editTime(edits, "deadline", null, oldDeadline, errors);
        LocalDateTime start = editTime(edits, "start_time", "startTime", oldStart, errors);
        LocalDateTime end = editTime(edits, "end_time", "endTime", oldEnd, errors);
        // G02（2026-11-21）：报名截止允许等于开始时刻，与创建校验和 reschedule 的 !deadline.isAfter(start) 口径一致。
        if (deadline != null && start != null && end != null
                && !(now.isBefore(deadline) && !deadline.isAfter(start) && start.isBefore(end)))
            errors.put("start_time", "时间需满足：现在 < 报名截止 ≤ 开始 < 结束");
        if (!errors.isEmpty()) throw new ValidationException(errors, errors.values().iterator().next());

        var reservation = jdbc.queryForMap("SELECT COUNT(*) AS reserved, MAX(i.expires_at) AS latest_expiry"
                + EFFECTIVE_RESERVATIONS, activityId, ts(now));
        Object lastExpiry = reservation.get("latest_expiry");
        if (lastExpiry != null && deadline.isBefore(asLocalDateTime(lastExpiry)))
            throw new ValidationException("deadline", "新报名截止早于已有待确认邀请的过期时间，无法修改");
        if (capacity < formalCount(activityId) + ((Number) reservation.get("reserved")).intValue())
            throw new ValidationException("capacity", "人数上限不能低于正式人数与有效预留之和");

        List<String> changes = new ArrayList<>();
        addEditChange(changes, "名称", act.get("title"), title);
        addEditChange(changes, "类别", act.get("category"), category);
        addEditChange(changes, "地点", act.get("location"), location);
        addEditChange(changes, "人数上限", oldCapacity, capacity);
        addEditChange(changes, "报名截止", formatChangeTime(oldDeadline), formatChangeTime(deadline));
        addEditChange(changes, "开始时间", formatChangeTime(oldStart), formatChangeTime(start));
        addEditChange(changes, "结束时间", formatChangeTime(oldEnd), formatChangeTime(end));
        // 长文本仅提示已变更，避免长介绍/条件使通知超出表约束。
        if (!Objects.equals(act.get("description"), description)) changes.add("活动介绍已更新");
        if (!Objects.equals(act.get("conditions"), conditions)) changes.add("参与条件已更新");

        int notifiedCount = 0;
        Object updatedAt = act.get("updated_at");
        if (!changes.isEmpty()) {
            // G03（2026-11-21）：同秒编辑令牌必变——新 updated_at 取 max(now, 当前 updated_at + 1 秒)。
            LocalDateTime currentUpdated = asLocalDateTime(act.get("updated_at"));
            LocalDateTime floor = currentUpdated.plusSeconds(1);
            LocalDateTime newUpdatedAt = now.isAfter(floor) ? now : floor;
            var recipients = jdbc.queryForList("SELECT user_id FROM participation " +
                    "WHERE activity_id=? AND status IN ('FORMAL','WAITING','INVITED') ORDER BY id", activityId);
            jdbc.update("UPDATE activity SET title=?, category=?, description=?, conditions=?, location=?, " +
                            "capacity=?, deadline=?, start_time=?, end_time=?, updated_at=? WHERE id=?",
                    title, category, description, conditions, location, capacity, ts(deadline), ts(start), ts(end), ts(newUpdatedAt), activityId);
            logFieldChange(activityId, organizerId, "EDIT", "title", act.get("title"), title, null);
            logFieldChange(activityId, organizerId, "EDIT", "category", act.get("category"), category, null);
            logFieldChange(activityId, organizerId, "EDIT", "location", act.get("location"), location, null);
            logFieldChange(activityId, organizerId, "EDIT", "capacity", oldCapacity, capacity, null);
            logFieldChange(activityId, organizerId, "EDIT", "deadline", formatChangeTime(oldDeadline), formatChangeTime(deadline), null);
            logFieldChange(activityId, organizerId, "EDIT", "start_time", formatChangeTime(oldStart), formatChangeTime(start), null);
            logFieldChange(activityId, organizerId, "EDIT", "end_time", formatChangeTime(oldEnd), formatChangeTime(end), null);
            logFieldChange(activityId, organizerId, "EDIT", "description", act.get("description"), description, null);
            logFieldChange(activityId, organizerId, "EDIT", "conditions", act.get("conditions"), conditions, null);
            if (capacity > oldCapacity) promote(activityId, now);
            String content = "活动「" + title + "」资料已变更：" + String.join("；", changes) + "。";
            // 不以秒精度版本去重不同编辑；同次变更的通知继续使用既有 outbox 去重键。
            String eventKey = "notify:edit:" + activityId + ":" + UUID.randomUUID();
            for (var recipient : recipients) {
                long uid = ((Number) recipient.get("user_id")).longValue();
                notify(uid, activityId, null, "变更", content, eventKey);
            }
            notifiedCount = recipients.size();
            updatedAt = ts(newUpdatedAt);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", activityId);
        result.put("activity_id", activityId);
        result.put("status", act.get("status"));
        result.put("title", title);
        result.put("category", category);
        result.put("description", description);
        result.put("conditions", conditions);
        result.put("location", location);
        result.put("capacity", capacity);
        result.put("deadline", deadline.toString());
        result.put("start_time", start.toString());
        result.put("end_time", end.toString());
        result.put("activity_version", versionOf(updatedAt));
        result.put("notifiedCount", notifiedCount);
        result.put("changes", changes);
        result.put("affected_count", notifiedCount);
        result.put("capacity_increased", capacity > oldCapacity);
        return result;
    }

    private static String editText(Object raw, String field, String label, int max, boolean required,
                                   Map<String, String> errors) {
        if (raw == null && !required) return "";
        if (!(raw instanceof String text)) {
            errors.put(field, required ? label + "需为 1-" + max + " 字" : label + "格式不正确");
            return null;
        }
        if ((required && text.isBlank()) || text.codePointCount(0, text.length()) > max)
            errors.put(field, required ? label + "需为 1-" + max + " 字" : label + "不能超过 " + max + " 字");
        return text;
    }

    private static LocalDateTime editTime(Map<String, Object> edits, String field, String alias,
                                          LocalDateTime current, Map<String, String> errors) {
        boolean hasAlias = alias != null && edits.containsKey(alias);
        if (hasAlias && edits.containsKey(field)) {
            errors.put(field, "请勿同时提交同一时间字段的两种写法");
            return null;
        }
        LocalDateTime value = parseTimeValue(edits.getOrDefault(hasAlias ? alias : field, current));
        if (value == null) errors.put(field, "时间格式不正确");
        return value;
    }

    private static String formatChangeTime(LocalDateTime time) {
        return time.getSecond() == 0 && time.getNano() == 0
                ? fmtFullMinute(time) : time.toString().replace('T', ' ');
    }

    private static void addEditChange(List<String> changes, String field, Object oldValue, Object newValue) {
        if (!Objects.equals(oldValue, newValue)) changes.add(field + "由「" + oldValue + "」改为「" + newValue + "」");
    }

    /** 任务 2（2026-11-09，P0）：组织者报名截止前改活动时间（开始 / 结束 / 截止）。
     *  SRS 表 3.3-1 R5：活动信息、容量、时间仅在报名截止前可改；修改后仍须满足
     *  “发出时间早于过期时间，且过期时间不晚于报名截止”，否则拒绝修改。
     *  本次只做时间，不扩容量与活动信息；不产生新活动、不迁移报名（原 id 与原
     *  报名记录不变）。改后给全部正式成员与候补成员（含待确认邀请者、含组织者
     *  本人作为参与者时）发「变更」通知，内容写清旧时间 → 新时间。
     *  R5 细则（SRS §3.3.3.3）：新报名截止早于已有待确认邀请的过期时间时
     *  拒绝修改并提示；延后截止不延长已有邀请的过期时间（本方法不动 invitation）。 */
    @Transactional
    public Map<String, Object> reschedule(long activityId, long organizerId,
                                          LocalDateTime deadline, LocalDateTime start, LocalDateTime end) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        LocalDateTime now = nowSeconds();
        if (!Objects.equals(((Number) act.get("organizer_id")).longValue(), organizerId))
            throw new IllegalStateException("只有组织者可以修改活动时间");
        if (!"OPEN".equals(act.get("status")))
            throw new IllegalStateException("活动不在报名期，不可改时间");
        if (!now.isBefore(asLocalDateTime(act.get("deadline"))))
            throw new IllegalStateException("报名已截止，不可改时间");
        if (!(now.isBefore(deadline) && !deadline.isAfter(start) && start.isBefore(end)))
            throw new IllegalStateException("时间需满足：现在 < 报名截止 ≤ 开始 < 结束");
        var pending = jdbc.queryForList(
                "SELECT i.expires_at FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                "WHERE p.activity_id=? AND i.status='PENDING'", activityId);
        for (var row : pending) {
            if (deadline.isBefore(asLocalDateTime(row.get("expires_at"))))
                throw new IllegalStateException("新报名截止早于已有待确认邀请的过期时间，无法修改");
        }
        LocalDateTime oldDeadline = asLocalDateTime(act.get("deadline"));
        LocalDateTime oldStart = asLocalDateTime(act.get("start_time"));
        LocalDateTime oldEnd = asLocalDateTime(act.get("end_time"));
        String oldRange = fmtFullRange(oldStart, asLocalDateTime(act.get("end_time")));
        var recipients = jdbc.queryForList(
                "SELECT id, user_id, status FROM participation " +
                "WHERE activity_id=? AND status IN ('FORMAL','WAITING','INVITED')",
                activityId);
        jdbc.update("UPDATE activity SET deadline=?, start_time=?, end_time=?, updated_at=? WHERE id=?",
                ts(deadline), ts(start), ts(end), ts(now), activityId);
        logFieldChange(activityId, organizerId, "RESCHEDULE", "deadline", formatChangeTime(oldDeadline), formatChangeTime(deadline), null);
        logFieldChange(activityId, organizerId, "RESCHEDULE", "start_time", formatChangeTime(oldStart), formatChangeTime(start), null);
        logFieldChange(activityId, organizerId, "RESCHEDULE", "end_time", formatChangeTime(oldEnd), formatChangeTime(end), null);
        String newRange = fmtFullRange(start, end);
        String title = (String) act.get("title");
        String eventDetail = "开始时间由 " + fmtFullMinute(oldStart) + " 改为 " + fmtFullMinute(start);
        for (var p : recipients) {
            long pid = ((Number) p.get("id")).longValue();
            long uid = ((Number) p.get("user_id")).longValue();
            String st = (String) p.get("status");
            logEvent(pid, activityId, uid, "RESCHEDULED", st, st, eventDetail);
            notify(uid, activityId, null, "变更",
                    "活动「" + title + "」时间已变更：原定 " + oldRange + "，现为 " + newRange + "，地点 " + act.get("location") + "。",
                    "notify:reschedule:" + activityId + ":" + uid + ":" + now);
        }
        return Map.of("ok", true, "activity_id", activityId,
                "deadline", deadline.toString(), "start_time", start.toString(), "end_time", end.toString());
    }

    /** 任务 9（2026-11-09，P1）：站内留言——详情页「给组织者留言」。
     *  存储复用 notification 表（type='留言'，sender_id=留言人，不新增表；
     *  type 值与 sender_id 列由当日迁移 001 加入）。登录用户报名前后均可留言，
     *  纯文本一句话，上限 200 字（超长拒绝并提示，不截断）。已取消/已结束活动不可留言。
     *  留言行 user_id=组织者（组织者在通知列表里也能看到），仅组织者可见：
     *  公开详情不返回 messages，只有组织者调详情时 listMessages() 才返回。 */
    @Transactional
    public Map<String, Object> postMessage(long activityId, long userId, String content) {
        var act = jdbc.queryForMap("SELECT organizer_id, title, status FROM activity WHERE id=?", activityId);
        if ("CANCELLED".equals(act.get("status")))
            throw new IllegalStateException("活动已取消，无法留言");
        if ("ENDED".equals(act.get("status")))
            throw new IllegalStateException("活动已结束，无法留言");
        if (content == null || content.isBlank())
            throw new IllegalStateException("留言内容不能为空");
        if (content.codePointCount(0, content.length()) > 200)
            throw new IllegalStateException("留言最多 200 字");
        long organizerId = ((Number) act.get("organizer_id")).longValue();
        // 任务 2（2026-11-12）：组织者不能给自己的活动留言，否则会给自己写一条
        // type='留言' 的通知；由 ApiController 的 IllegalStateException handler 映射为 400。
        // 仅拦 postMessage，组织者回复他人留言的 replyMessage 链路不受影响。
        if (userId == organizerId)
            throw new IllegalStateException("组织者不能给自己的活动留言");
        LocalDateTime now = LocalDateTime.now();
        KeyHolder keyHolder = new GeneratedKeyHolder();
        // 任务 5（2026-11-10）：留言通知带活动标题，如「留言（羽毛球双打）：……」，
        // 组织者名下多个活动的留言通知能凭标题区分；listMessages 展示时再剥掉此前缀。
        final String text = "留言（" + act.get("title") + "）：" + content.trim();
        final String eventKey = "msg:" + activityId + ":" + userId + ":" + now;
        jdbc.update(con -> {
            // 留言同样走通知 outbox：显式 PENDING，由发布任务翻 PUBLISHED。
            PreparedStatement ps = con.prepareStatement(
                    "INSERT INTO notification(user_id, activity_id, type, content, event_key, sender_id, status, publish_at) " +
                    "VALUES (?,?,?,?,?,?, 'PENDING', ?)", new String[]{"id"});
            ps.setLong(1, organizerId);
            ps.setLong(2, activityId);
            ps.setString(3, "留言");
            ps.setString(4, text);
            ps.setString(5, eventKey);
            ps.setLong(6, userId);
            ps.setTimestamp(7, ts(now));
            return ps;
        }, keyHolder);
        return Map.of("ok", true, "id", keyHolder.getKey().longValue());
    }

    /** 任务 9：组织者名单视图的留言列表（带留言人昵称与时间，每条附其唯一回复）。
     *  回复行本身也是 type='留言' 的 notification 行（event_key 以 msg-reply: 开头），
     *  在此排除，只作为 reply 附在原留言下。 */
    public List<Map<String, Object>> listMessages(long activityId) {
        return queryMessages(activityId, null);
    }

    /** 任务 17（2026-11-10，P2）：留言者本人查自己发过的留言及组织者回复。
     *  只返回 sender_id = 本人的留言行，他人留言不可见；组织者走 listMessages() 看全部。 */
    public List<Map<String, Object>> listMyMessages(long activityId, long userId) {
        return queryMessages(activityId, userId);
    }

    /** 任务 9 / 17 公共查询：留言行（排除回复行本身，每条附唯一回复）。
     *  senderId 为 null 时返回全部留言（组织者视角），否则只返回该 sender 的留言。
     *  展示时剥掉任务 5（2026-11-10）写入通知的「留言（<标题>）：」前缀——
     *  名单视图 / 本人留言区已在当活动语境下，标题是多余的；通知列表仍显示带标题的原文。 */
    private List<Map<String, Object>> queryMessages(long activityId, Long senderId) {
        String title = jdbc.queryForObject("SELECT title FROM activity WHERE id=?", String.class, activityId);
        String prefix = "留言（" + title + "）：";
        String sql = "SELECT n.*, u.nickname AS sender_nickname FROM notification n JOIN app_user u ON u.id=n.sender_id " +
                "WHERE n.activity_id=? AND n.type='留言' AND n.status='PUBLISHED' AND n.event_key NOT LIKE 'msg-reply:%' ";
        var rows = senderId == null
                ? jdbc.queryForList(sql + "ORDER BY n.created_at, n.id", activityId)
                : jdbc.queryForList(sql + "AND n.sender_id=? ORDER BY n.created_at, n.id", activityId, senderId);
        for (var row : rows) {
            String content = (String) row.get("content");
            if (content != null && content.startsWith(prefix)) {
                row.put("content", content.substring(prefix.length()));
            }
            long mid = ((Number) row.get("id")).longValue();
            var replies = jdbc.queryForList(
                    "SELECT content, created_at FROM notification WHERE event_key LIKE ? AND status='PUBLISHED' " +
                            "ORDER BY id LIMIT 1",
                    "msg-reply:" + mid + ":%");
            if (!replies.isEmpty()) {
                // 任务 7（2026-11-11）：回复通知内容带「回复（<标题>）：」前缀，展示时剥掉，
                // 与上面剥「留言（<标题>）：」同理，让当活动语境下的回复保持干净。
                String replyPrefix = "回复（" + title + "）：";
                var reply = replies.get(0);
                String replyContent = (String) reply.get("content");
                if (replyContent != null && replyContent.startsWith(replyPrefix)) {
                    reply.put("content", replyContent.substring(replyPrefix.length()));
                }
            }
            row.put("reply", replies.isEmpty() ? null : replies.get(0));
        }
        return rows;
    }

    /** 任务 9：组织者在名单视图回一条（走站内通知，留言人收到回复通知）。
     *  每条留言只能回一条（防聊起来变聊天串）；回复内容同样 ≤200 字；
     *  只有组织者可回，回复对象是原留言人。 */
    @Transactional
    public Map<String, Object> replyMessage(long activityId, long organizerId, long messageId, String content) {
        var act = jdbc.queryForMap("SELECT organizer_id, title FROM activity WHERE id=?", activityId);
        if (!Objects.equals(((Number) act.get("organizer_id")).longValue(), organizerId))
            throw new IllegalStateException("只有组织者可以回复留言");
        var msg = jdbc.queryForMap(
                "SELECT * FROM notification WHERE id=? AND activity_id=? AND type='留言' AND status='PUBLISHED'",
                messageId, activityId);
        if (((String) msg.get("event_key")).startsWith("msg-reply:"))
            throw new IllegalStateException("不能回复一条回复");
        if (msg.get("sender_id") == null)
            throw new IllegalStateException("留言记录异常，无留言人");
        long senderId = ((Number) msg.get("sender_id")).longValue();
        Integer n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM notification WHERE event_key LIKE ?", Integer.class,
                "msg-reply:" + messageId + ":%");
        if (n != null && n > 0)
            throw new IllegalStateException("该留言已回复过");
        if (content == null || content.isBlank())
            throw new IllegalStateException("回复内容不能为空");
        if (content.codePointCount(0, content.length()) > 200)
            throw new IllegalStateException("回复最多 200 字");
        // 任务 7（2026-11-11）：回复通知与任务 5 的留言通知同样带活动标题，如
        // 「回复（羽毛球双打）：……」，通知列表可按标题区分；queryMessages 展示时剥掉此前缀。
        final String text = "回复（" + act.get("title") + "）：" + content.trim();
        notifyWithSender(senderId, activityId, null, "留言", text,
                "msg-reply:" + messageId + ":" + LocalDateTime.now(), organizerId);
        return Map.of("ok", true);
    }

    /** 任务 3（2026-11-10，P1）：详情人数公开计数——未登录也能看 formal/reserved/waiting
     *  （SRS §3.3.2.2 详情字段清单本就含正式/候补人数）；不含名单、联系方式与本人状态。 */
    public Map<String, Object> publicCounts(long activityId) {
        LocalDateTime now = LocalDateTime.now();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("formal", formalCount(activityId));
        out.put("reserved", reservedCount(activityId, now));
        out.put("waiting", waitingCount(activityId));
        return out;
    }

    public Map<String, Object> detail(long activityId, long userId) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        LocalDateTime now = LocalDateTime.now();
        var mine = jdbc.queryForList(
                "SELECT * FROM participation WHERE activity_id=? AND user_id=?", activityId, userId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("activity_id", activityId);
        out.put("title", act.get("title"));
        // 任务 1：报名接口返回补齐介绍与条件，否则前端用返回体覆盖详情时会变空白
        out.put("description", act.get("description"));
        out.put("conditions", act.get("conditions"));
        out.put("capacity", act.get("capacity"));
        out.put("formal", formalCount(activityId));
        out.put("reserved", reservedCount(activityId, now));
        out.put("waiting", waitingCount(activityId));
        out.put("status", act.get("status"));
        if (!mine.isEmpty()) {
            var m = mine.get(0);
            out.put("my_status", m.get("status"));
            out.put("participation_id", m.get("id"));
            out.put("participation_version", versionOf(m.get("updated_at")));
            // 任务 5（2026-11-12）：joined_at 非空表示曾经成为过正式成员（候补 / 待确认者
            // 从未被写入 joined_at），供前端区分 WITHDRAWN 的显示口径：曾正式 →「已退出」，
            // 从未正式 →「已放弃候补」。
            out.put("my_had_joined", m.get("joined_at") != null);
            out.put("my_queued_at", m.get("queued_at") == null ? null : asLocalDateTime(m.get("queued_at")).toString());
            var inv = jdbc.queryForList(
                    "SELECT * FROM invitation WHERE participation_id=? AND status='PENDING' ORDER BY id DESC LIMIT 1",
                    m.get("id"));
            if (!inv.isEmpty()) {
                var invitation = inv.get(0);
                LocalDateTime expiresAt = asLocalDateTime(invitation.get("expires_at"));
                if (expiresAt.isAfter(now)) {
                    out.put("invitation_id", invitation.get("id"));
                    // 库里存的就是东八区墙钟，直接返回，不再换算。
                    out.put("invitation_expires_at", expiresAt.toString());
                }
            }
            // 候补排名：排队中按 queued_at, id 排序
            if ("WAITING".equals(m.get("status")) && now.isBefore(asLocalDateTime(act.get("deadline")))) {
                var queue = jdbc.queryForList(
                        "SELECT id FROM participation WHERE activity_id=? AND status='WAITING' " +
                        "ORDER BY queued_at, id", activityId);
                for (int i = 0; i < queue.size(); i++) {
                    if (Objects.equals(queue.get(i).get("id"), m.get("id"))) { out.put("my_rank", i + 1); break; }
                }
            }
        }
        return out;
    }

    /** 阶段一：活动详情（原 ApiController 的组装逻辑下沉，供 GET 详情与移出成员复用）。
     *  userId 为 null 表示未登录：只返回公开计数，不含名单与本人状态。 */
    public Map<String, Object> activityDetail(long activityId, Long userId) {
        return activityDetail(activityId, userId, null, null, null, null, null, null);
    }

    public Map<String, Object> activityDetail(long activityId, Long userId,
                                              Integer confirmedPage, Integer confirmedPageSize,
                                              Integer pendingPage, Integer pendingPageSize,
                                              Integer waitingPage, Integer waitingPageSize) {
        var act = jdbc.queryForMap("SELECT a.*, u.nickname AS organizer_name FROM activity a " +
                "JOIN app_user u ON u.id=a.organizer_id WHERE a.id=?", activityId);
        Map<String, Object> out = new LinkedHashMap<>(act);
        if (userId == null) {
            out.putAll(publicCounts(activityId));
            return out;
        }
        out.putAll(detail(activityId, userId));
        // 组织者可见名单与候补队列；其他人只能看到人数
        if (Objects.equals(((Number) act.get("organizer_id")).longValue(), userId.longValue())) {
            out.put("roster", jdbc.queryForList(
                    "SELECT p.*, u.nickname FROM participation p JOIN app_user u ON u.id=p.user_id " +
                    "WHERE p.activity_id=? AND p.status IN ('FORMAL','WAITING','INVITED') " +
                    "ORDER BY CASE p.status WHEN 'FORMAL' THEN 0 WHEN 'INVITED' THEN 1 ELSE 2 END, p.queued_at, p.id", activityId));
            out.put("pending_invitations", jdbc.queryForList(
                    "SELECT i.*, u.nickname FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                    "JOIN app_user u ON u.id=p.user_id WHERE p.activity_id=? AND i.status='PENDING' ORDER BY i.expires_at", activityId));
            // 任务 9（2026-11-09）：站内留言只在组织者视角返回，不上公开详情页。
            out.put("messages", listMessages(activityId));

            var confirmed = jdbc.queryForList(
                    "SELECT p.*, u.nickname FROM participation p JOIN app_user u ON u.id=p.user_id " +
                    "WHERE p.activity_id=? AND p.status='FORMAL' ORDER BY p.joined_at, p.id", activityId);
            LocalDateTime now = LocalDateTime.now();
            var pending = jdbc.queryForList(
                    "SELECT p.*, u.nickname, i.id AS invitation_id, i.expires_at AS invitation_expires_at " +
                    "FROM participation p JOIN app_user u ON u.id=p.user_id " +
                    "JOIN invitation i ON i.participation_id=p.id AND i.status='PENDING' AND i.expires_at > ? " +
                    "WHERE p.activity_id=? AND p.status='INVITED' ORDER BY i.expires_at, i.id", ts(now), activityId);
            var waiting = jdbc.queryForList(
                    "SELECT p.*, u.nickname FROM participation p JOIN app_user u ON u.id=p.user_id " +
                    "WHERE p.activity_id=? AND p.status='WAITING' ORDER BY p.queued_at, p.id", activityId);
            // G06（2026-11-21）：报名截止后候补队列已失去意义，waiting 段按空返回（仍保留分页骨架）；
            // confirmed/pending 段不受影响。
            boolean signupClosed = !now.isBefore(asLocalDateTime(act.get("deadline")));
            Map<String, Object> sections = new LinkedHashMap<>();
            sections.put("confirmed", rosterSectionPage(confirmed, confirmedPage, confirmedPageSize));
            sections.put("pending", rosterSectionPage(pending, pendingPage, pendingPageSize));
            sections.put("waiting", rosterSectionPage(signupClosed ? List.of() : waiting, waitingPage, waitingPageSize));
            out.put("roster_sections", sections);
        }
        return out;
    }

    private static Map<String, Object> rosterSectionPage(List<?> rows, Integer page, Integer pageSize) {
        int p = page == null ? 1 : Math.max(1, page);
        int size = pageSize == null ? 10 : Math.max(1, Math.min(50, pageSize));
        int total = rows.size();
        long offset = (long) (p - 1) * size;
        int start = (int) Math.min(offset, total);
        int end = (int) Math.min(offset + size, total);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", new ArrayList<>(rows.subList(start, end)));
        out.put("page", p);
        out.put("pageSize", size);
        out.put("total", total);
        return out;
    }

    /** DG-BE-05：移出限制判定。依据 participation_events 中该用户该活动最近一条关键事件：
     *  MEMBER_REMOVED 为最近且其后无 MEMBER_REMOVAL_LIFTED（限制解除标记）/ 无新的 SIGNUP_* 事件时，限制生效。
     *  普通 withdraw/abandon 只写 WITHDRAW/ABANDON 事件、不写 MEMBER_REMOVED，故不受影响。 */
    private void checkRemovedRestriction(long activityId, long userId) {
        var rows = jdbc.queryForList(
                "SELECT event_type FROM participation_events WHERE activity_id=? AND user_id=? " +
                        "AND event_type IN ('MEMBER_REMOVED','MEMBER_REMOVAL_LIFTED','SIGNUP_FORMAL','SIGNUP_WAITING') " +
                        "ORDER BY id DESC LIMIT 1", activityId, userId);
        if (rows.isEmpty()) return;
        if ("MEMBER_REMOVED".equals(rows.get(0).get("event_type")))
            throw new CodedException("MEMBER_REMOVED_RESTRICTED", "你已被组织者移出该活动，限制未解除前不能重新报名");
    }

    /** DG-BE-05（2026-11-21）：移出治理决定留痕。decision_type='REMOVAL' 已同步放宽 schema 双份
     *  CHECK；存量库的 CHECK 不随建表脚本更新，部署时须另行 ALTER 放宽（见 merge 报告部署顺序）。
     *  被移出者可凭本决定走申诉，复核撤销后由 GovernanceService 写 MEMBER_REMOVAL_LIFTED 解除限制。 */
    private long insertRemovalDecision(long organizerId, long targetUserId, long activityId,
                                       long participationId, String reason, LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                    "INSERT INTO governance_decision(actor_id, previous_decision_id, decision_type, " +
                            "subject_user_id, activity_id, participation_id, attendance_revision_id, " +
                            "reason, result, decided_at, expires_at, available_at, appeal_until, " +
                            "execution_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    new String[]{"id"});
            ps.setLong(1, organizerId);
            ps.setNull(2, java.sql.Types.BIGINT);
            ps.setString(3, "REMOVAL");
            ps.setLong(4, targetUserId);
            ps.setLong(5, activityId);
            ps.setLong(6, participationId);
            ps.setNull(7, java.sql.Types.BIGINT);
            ps.setString(8, reason);
            ps.setString(9, "组织者移出成员");
            ps.setTimestamp(10, ts(now));
            ps.setNull(11, java.sql.Types.TIMESTAMP);
            ps.setNull(12, java.sql.Types.TIMESTAMP);
            ps.setNull(13, java.sql.Types.TIMESTAMP);
            ps.setNull(14, java.sql.Types.VARCHAR);
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    /** 阶段一 B-CEM-03：组织者有据移出成员。
     *  校验组织者身份、原因（非空且 ≤200 字）与目标参与状态；INVITED 先作废邀请，
     *  WAITING 仅重排候补，FORMAL / INVITED 移出后立即 promote 递补。
     *  被移出者收到「变更」通知；组织者本人操作不另通知。
     *  移出同时落 DG-BE-05 重报限制（以 MEMBER_REMOVED 事件为据，signup 时判定）与 governance_action 审计留痕。 */
    @Transactional
    public Map<String, Object> removeMember(long activityId, long organizerId,
                                            long targetUserId, String reason) {
        // E2-8：遵循 activity → participation 锁序，先锁活动行，再锁参与行。
        var act = jdbc.queryForMap(
                "SELECT organizer_id, title FROM activity WHERE id=? FOR UPDATE", activityId);
        if (!Objects.equals(((Number) act.get("organizer_id")).longValue(), organizerId))
            throw new IllegalStateException("只有组织者可以移出成员");
        if (reason == null || reason.isBlank())
            throw new ValidationException("reason", "移出原因不能为空");
        if (reason.codePointCount(0, reason.length()) > 200)
            throw new ValidationException("reason", "移出原因不能超过 200 字");
        if (targetUserId == organizerId)
            throw new IllegalStateException("不能移出组织者本人，如需终止活动请取消活动");
        var parts = jdbc.queryForList(
                "SELECT * FROM participation WHERE activity_id=? AND user_id=? " +
                        "AND status IN ('FORMAL','WAITING','INVITED') ORDER BY id DESC LIMIT 1 FOR UPDATE",
                activityId, targetUserId);
        if (parts.isEmpty())
            throw new IllegalStateException("该用户不在活动名单中");
        var part = parts.get(0);
        long pid = ((Number) part.get("id")).longValue();
        String st = (String) part.get("status");
        LocalDateTime now = nowSeconds();
        if (st.equals("INVITED")) {
            jdbc.update("UPDATE invitation SET status='INVALID' WHERE participation_id=? AND status='PENDING'", pid);
        }
        jdbc.update("UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=?", ts(now), pid);
        if (st.equals("WAITING")) resequence(activityId);
        logEvent(pid, activityId, targetUserId, "MEMBER_REMOVED", st, "WITHDRAWN", reason);
        // DG-BE-05 决定留痕（2026-11-21 修订）：写入 governance_decision（REMOVAL）作为申诉
        // 解除通道的原决定，governance_action 审计行同步挂该决定 id（原口径只写审计行、无决定，
        // 被移出者无从申诉；schema 双份 CHECK 已放宽含 REMOVAL，存量库部署时另行 ALTER）。
        long removalDecisionId = insertRemovalDecision(
                organizerId, targetUserId, activityId, pid, reason, now);
        jdbc.update("INSERT INTO governance_action(actor_id, action, target_type, target_id, " +
                        "decision_id, reason, detail, request_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                organizerId, "MEMBER_REMOVED", "PARTICIPATION", pid, removalDecisionId,
                reason, "activity_id=" + activityId + ", target_user_id=" + targetUserId,
                null, ts(now));
        notify(targetUserId, activityId, null, "变更",
                "组织者将你移出活动「" + act.get("title") + "」：" + reason,
                "notify:remove:" + pid + ":" + now);
        if (st.equals("FORMAL") || st.equals("INVITED")) promote(activityId, now);
        return activityDetail(activityId, organizerId);
    }

    /** 阶段一 A1：参与事件流。参与本人或该活动组织者可见（id 升序）。 */
    public List<Map<String, Object>> listEvents(long participationId, long userId) {
        var part = jdbc.queryForMap(
                "SELECT activity_id, user_id FROM participation WHERE id=?", participationId);
        long activityId = ((Number) part.get("activity_id")).longValue();
        long ownerId = ((Number) part.get("user_id")).longValue();
        boolean organizer = jdbc.queryForObject(
                "SELECT COUNT(*) FROM activity WHERE id=? AND organizer_id=?",
                Integer.class, activityId, userId) > 0;
        if (ownerId != userId && !organizer)
            throw new IllegalStateException("无权查看该参与记录");
        return jdbc.queryForList(
                "SELECT id, participation_id, activity_id, user_id, event_type, " +
                        "from_status, to_status, detail, created_at " +
                        "FROM participation_events WHERE participation_id=? ORDER BY id",
                participationId);
    }

    /** DG-BE-06：活动变更日志查询。仅组织者本人或管理员（admin 由控制器按治理口径传入）可见，其余 403。 */
    public List<Map<String, Object>> listActivityChanges(long activityId, long requesterId, boolean admin) {
        var act = jdbc.queryForMap("SELECT organizer_id FROM activity WHERE id=?", activityId);
        if (!admin && ((Number) act.get("organizer_id")).longValue() != requesterId)
            throw new ForbiddenException("只有组织者或管理员可以查看变更日志");
        return jdbc.queryForList("SELECT id, activity_id, actor_id, change_type, field, old_value, new_value, reason, created_at " +
                "FROM activity_change_log WHERE activity_id=? ORDER BY id DESC", activityId);
    }

    /** 阶段一 A6 / outbox：通知列表只返回已发布的通知（全量，controller 分页）。 */
    public List<Map<String, Object>> listNotifications(long userId) {
        return listNotifications(userId, false);
    }

    public List<Map<String, Object>> listNotifications(long userId, boolean unreadOnly) {
        // G19（2026-11-21）：同时返回本条通知所关联邀请自身的状态（无 invitation_id 时为 null），
        // 前端据此按本条邀请判状态，不再误用该活动「最近一条」邀请的状态。
        return jdbc.queryForList(
                "SELECT n.*, i.expires_at AS expires_at, i.status AS invitation_status FROM notification n " +
                        "LEFT JOIN invitation i ON i.id=n.invitation_id " +
                        "WHERE n.user_id=? AND n.status='PUBLISHED' " +
                        (unreadOnly ? "AND n.read_at IS NULL " : "") +
                        "ORDER BY n.created_at DESC, n.id DESC", userId);
    }

    public String latestInvitationStatus(long userId, long activityId) {
        var statuses = jdbc.queryForList(
                "SELECT i.status FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                        "WHERE p.activity_id=? AND p.user_id=? ORDER BY i.id DESC LIMIT 1",
                String.class, activityId, userId);
        return statuses.isEmpty() ? null : statuses.get(0);
    }

    public int unreadCount(long userId) {
        Integer n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM notification WHERE user_id=? AND read_at IS NULL AND status='PUBLISHED'",
                Integer.class, userId);
        return n == null ? 0 : n;
    }

    /** 阶段一 A6：单条已读。只能标记自己的、已发布的通知；否则按业务错误处理。 */
    @Transactional
    public Map<String, Object> readNotification(long userId, long notificationId) {
        int changed = jdbc.update(
                "UPDATE notification SET read_at=COALESCE(read_at, ?) " +
                        "WHERE id=? AND user_id=? AND status='PUBLISHED'",
                ts(LocalDateTime.now()), notificationId, userId);
        if (changed == 0) throw new IllegalStateException("通知不存在");
        return Map.of("id", notificationId, "read", true);
    }
}
