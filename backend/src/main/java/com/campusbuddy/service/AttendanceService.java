package com.campusbuddy.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.*;

/**
 * 阶段二 CEM-08（2026-11-15）：签到、出勤快照 / 核对 / 定版、活动评价。
 *
 * 口径（见 phase2/specs/spec-backend.md）：
 * - 全系统东八区墙钟 LocalDateTime 直存直取，不做时区换算；ZONE 只用于把墙钟
 *   映射到签到轮换窗（windowIndex / window_start / window_end），不改变存储值。
 * - 双库：构造时检测数据库产品名并缓存，冲突忽略 / upsert 按 MySQL 与 PostgreSQL
 *   两种方言分别写入（与 BuddyService 同做法）。
 * - 签到码只按 HMAC-SHA256 实时派生，不落库、不写日志，密钥也不写日志。
 * - 通知沿用阶段一 outbox：显式 PENDING + publish_at=now + event_key 去重。
 */
@Service
public class AttendanceService {
    /** 全站东八区墙钟（与 BuddyService 时区口径一致）。 */
    private static final ZoneOffset ZONE = ZoneOffset.ofHours(8);
    /** 签到窗前置 15 分钟；截止为开始后 30 分钟（且不晚于活动结束）。 */
    private static final int CHECKIN_OPEN_MINUTES_BEFORE = 15;
    private static final int CHECKIN_CLOSE_MINUTES_AFTER_START = 30;
    /** 评价可改期限 7 日；出勤结论申诉期 7 日（SDD，按代码常量固定）。 */
    private static final int EVALUATION_DAYS = 7;
    private static final int APPEAL_DAYS = 7;
    private static final Set<String> RESULTS =
            Set.of("PRESENT", "ABSENT_VERIFIED", "EXEMPT", "UNVERIFIED");

    private final JdbcTemplate jdbc;
    private final String secret;
    private final int windowSeconds;
    private final int maxFails;
    private final int lockMinutes;
    private final int verifyWindowMinutes;
    /** 双库分支：与 BuddyService.detectMysql 同口径，启动时判定一次并缓存。 */
    private final boolean mysql;

    public AttendanceService(JdbcTemplate jdbc,
                             @Value("${app.checkin.secret}") String secret,
                             @Value("${app.checkin.window-seconds}") int windowSeconds,
                             @Value("${app.checkin.max-fails}") int maxFails,
                             @Value("${app.checkin.lock-minutes}") int lockMinutes,
                             @Value("${app.attendance.verify-window-minutes}") int verifyWindowMinutes) {
        this.jdbc = jdbc;
        this.secret = secret;
        this.windowSeconds = windowSeconds;
        this.maxFails = maxFails;
        this.lockMinutes = lockMinutes;
        this.verifyWindowMinutes = verifyWindowMinutes;
        this.mysql = detectMysql(jdbc);
    }

    /** 与 BuddyService.detectMysql 同实现（规格要求照抄该私有静态方法）。 */
    private static boolean detectMysql(JdbcTemplate jdbc) {
        try (var con = jdbc.getDataSource().getConnection()) {
            return con.getMetaData().getDatabaseProductName().toLowerCase().contains("mysql");
        } catch (Exception e) {
            throw new IllegalStateException("无法识别数据库产品", e);
        }
    }

    /** 东八区墙钟 → JDBC Timestamp，不做时区换算（与 BuddyService.ts 同口径）。 */
    private static Timestamp ts(LocalDateTime t) { return Timestamp.valueOf(t); }

    /** 与 BuddyService.asLocalDateTime 同实现（规格要求复制一份）：MySQL 驱动返回
     *  LocalDateTime、PostgreSQL 驱动返回 Timestamp，统一归一化，只做类型转换。 */
    private static LocalDateTime asLocalDateTime(Object v) {
        if (v instanceof LocalDateTime ldt) return ldt;
        if (v instanceof Timestamp t) return t.toLocalDateTime();
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime();
        throw new IllegalStateException("无法识别的时间类型: " + v);
    }

    /** 时间字段统一输出 ISO 字符串（与 BuddyService.detail 的 my_queued_at 口径一致）。 */
    private static String iso(Object v) { return v == null ? null : asLocalDateTime(v).toString(); }

    /** 与 BuddyService.notify 同口径的 outbox 写入：显式 status='PENDING'、
     *  publish_at=now、event_key 去重，MySQL 用 INSERT IGNORE、PostgreSQL 用
     *  ON CONFLICT DO NOTHING。通知 type 仅使用现有 CHECK 允许值，出勤用「变更」。 */
    private void notify(Long userId, Long activityId, String type, String content, String eventKey) {
        String sql = mysql
                ? "INSERT IGNORE INTO notification(user_id, activity_id, invitation_id, type, content, " +
                        "event_key, sender_id, status, publish_at) VALUES (?,?,?,?,?,?,?, 'PENDING', ?)"
                : "INSERT INTO notification(user_id, activity_id, invitation_id, type, content, " +
                        "event_key, sender_id, status, publish_at) VALUES (?,?,?,?,?,?,?, 'PENDING', ?) " +
                        "ON CONFLICT (user_id, event_key) DO NOTHING";
        jdbc.update(sql, userId, activityId, null, type, content, eventKey, null,
                ts(LocalDateTime.now()));
    }

    // ---- 签到码派生（4.1） ----

    private long windowIndex(LocalDateTime now) {
        return now.toEpochSecond(ZONE) / windowSeconds;
    }

    private String codeFor(long activityId, long widx) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] digest = mac.doFinal((activityId + ":" + widx).getBytes(StandardCharsets.UTF_8));
            int v = ((digest[0] & 0xff) << 24)
                    | ((digest[1] & 0xff) << 16)
                    | ((digest[2] & 0xff) << 8)
                    | (digest[3] & 0xff);
            v &= 0x7fffffff;
            v %= 1000000;
            return String.format("%06d", v);
        } catch (Exception e) {
            // 只报派生失败，不带 secret / 码值。
            throw new IllegalStateException("签到码派生失败", e);
        }
    }

    private boolean codeMatches(long activityId, String code, LocalDateTime now) {
        if (code == null) return false;
        String trimmed = code.trim();
        if (trimmed.isEmpty()) return false;
        long widx = windowIndex(now);
        return sameCode(trimmed, codeFor(activityId, widx))
                || sameCode(trimmed, codeFor(activityId, widx - 1));
    }

    /** 定长比较，避免按字节短路（MessageDigest.isEqual）。 */
    private static boolean sameCode(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8),
                b.getBytes(StandardCharsets.UTF_8));
    }

    /** 签到窗 [start-15min, min(start+30min, end))；status 必须 RUNNING。 */
    private static boolean inCheckinWindow(Map<String, Object> act, LocalDateTime now) {
        if (!"RUNNING".equals(act.get("status"))) return false;
        LocalDateTime start = asLocalDateTime(act.get("start_time"));
        LocalDateTime end = asLocalDateTime(act.get("end_time"));
        LocalDateTime open = start.minusMinutes(CHECKIN_OPEN_MINUTES_BEFORE);
        LocalDateTime close = start.plusMinutes(CHECKIN_CLOSE_MINUTES_AFTER_START);
        if (close.isAfter(end)) close = end;
        return !now.isBefore(open) && now.isBefore(close);
    }

    // ---- 4.2 组织者读码 ----

    public Map<String, Object> checkinCode(long activityId, long organizerId) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        if (!Objects.equals(((Number) act.get("organizer_id")).longValue(), organizerId))
            throw new IllegalStateException("只有组织者可以查看签到码");
        LocalDateTime now = LocalDateTime.now();
        if (!inCheckinWindow(act, now))
            throw new IllegalStateException("当前不在签到时间内");
        long widx = windowIndex(now);
        LocalDateTime windowStart = LocalDateTime.ofEpochSecond(widx * windowSeconds, 0, ZONE);
        LocalDateTime windowEnd = windowStart.plusSeconds(windowSeconds);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", codeFor(activityId, widx));
        out.put("window_start", windowStart.toString());
        out.put("window_end", windowEnd.toString());
        out.put("seconds_left", windowEnd.toEpochSecond(ZONE) - now.toEpochSecond(ZONE));
        return out;
    }

    // ---- 4.3 / 4.4 签到与错码限流 ----

    // 错码路径按规格是“先记失败再 throw IllegalStateException”；默认事务规则会在
    // 异常穿出代理时回滚，导致限流计数永远不落库。业务拒绝（400）不应回滚这次记账，
    // 故显式 noRollbackFor；真正改变签到事实的写入都在成功路径。
    @Transactional(noRollbackFor = IllegalStateException.class)
    public Map<String, Object> checkin(long activityId, long userId, String code) {
        LocalDateTime now = LocalDateTime.now();
        // 1. 锁活动行：同一活动的签到串行，签到事实唯一约束不会在并发下报错。
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        // 2. 已有签到事实先行返回（不校验码、不计限流；重复请求返回原签到时间）。
        var existing = jdbc.queryForList(
                "SELECT * FROM checkin WHERE activity_id=? AND user_id=?", activityId, userId);
        if (!existing.isEmpty()) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("activity_id", activityId);
            out.put("user_id", userId);
            out.put("checkin_at", iso(existing.get(0).get("checkin_at")));
            out.put("already_checked_in", true);
            return out;
        }
        // 3. 状态 / 窗口。
        if (!inCheckinWindow(act, now))
            throw new IllegalStateException("当前不在签到时间内");
        // 4. 资格：只有正式成员。
        var parts = jdbc.queryForList(
                "SELECT * FROM participation WHERE activity_id=? AND user_id=? AND status='FORMAL'",
                activityId, userId);
        if (parts.isEmpty())
            throw new IllegalStateException("只有正式成员可以签到");
        long participationId = ((Number) parts.get(0).get("id")).longValue();
        // 5. 限流：锁定截止未到则 429。
        var attempts = jdbc.queryForList(
                "SELECT * FROM checkin_attempt WHERE activity_id=? AND user_id=?", activityId, userId);
        if (!attempts.isEmpty() && attempts.get(0).get("locked_until") != null) {
            LocalDateTime lockedUntil = asLocalDateTime(attempts.get(0).get("locked_until"));
            if (lockedUntil.isAfter(now)) {
                // 剩余分钟数向上取整：先按秒向上取整，再按 60 秒进位。
                Duration remaining = Duration.between(now, lockedUntil);
                long seconds = remaining.getSeconds() + (remaining.getNano() > 0 ? 1 : 0);
                long minutes = (seconds + 59) / 60;
                if (minutes < 1) minutes = 1;
                throw new RateLimitException("签到尝试过于频繁，请 " + minutes + " 分钟后再试");
            }
        }
        // 6. 错码：记一次失败后拒绝。
        if (!codeMatches(activityId, code, now)) {
            recordFailure(activityId, userId, now);
            throw new IllegalStateException("签到码不正确，请核对后重试");
        }
        // 7. 正确：清零限流、写签到事实、补建出勤快照。
        jdbc.update("DELETE FROM checkin_attempt WHERE activity_id=? AND user_id=?", activityId, userId);
        jdbc.update("INSERT INTO checkin(activity_id, user_id, participation_id, checkin_at) VALUES (?,?,?,?)",
                activityId, userId, participationId, ts(now));
        ensureSnapshotForActivity(act);
        // 从库里读回签到时间再输出：两库对时间精度的截断不同，直接返回 now 会与
        // 重复签到（读库）返回的时间字符串不一致（SDD §6.9 要求重复请求返回原时间）。
        var stored = jdbc.queryForList(
                "SELECT checkin_at FROM checkin WHERE activity_id=? AND user_id=?", activityId, userId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("activity_id", activityId);
        out.put("user_id", userId);
        out.put("checkin_at", iso(stored.get(0).get("checkin_at")));
        out.put("already_checked_in", false);
        return out;
    }

    /** 4.4 限流记账：连续错误计数；10 分钟内未再错则从 1 重新计；
     *  达到 maxFails 时锁定 lockMinutes 分钟并把 fail_count 清零。 */
    private void recordFailure(long activityId, long userId, LocalDateTime now) {
        String insert = mysql
                ? "INSERT IGNORE INTO checkin_attempt(activity_id, user_id, fail_count, updated_at) VALUES (?,?,0,?)"
                : "INSERT INTO checkin_attempt(activity_id, user_id, fail_count, updated_at) VALUES (?,?,0,?) " +
                        "ON CONFLICT (activity_id, user_id) DO NOTHING";
        jdbc.update(insert, activityId, userId, ts(now));
        var rows = jdbc.queryForList(
                "SELECT fail_count, last_fail_at FROM checkin_attempt WHERE activity_id=? AND user_id=?",
                activityId, userId);
        int oldFails = ((Number) rows.get(0).get("fail_count")).intValue();
        Object lastFailRaw = rows.get(0).get("last_fail_at");
        boolean stale = lastFailRaw == null
                || asLocalDateTime(lastFailRaw).isBefore(now.minusMinutes(10));
        int newFails = stale ? 1 : oldFails + 1;
        if (newFails >= maxFails) {
            jdbc.update("UPDATE checkin_attempt SET fail_count=0, locked_until=?, last_fail_at=?, updated_at=? " +
                            "WHERE activity_id=? AND user_id=?",
                    ts(now.plusMinutes(lockMinutes)), ts(now), ts(now), activityId, userId);
        } else {
            jdbc.update("UPDATE checkin_attempt SET fail_count=?, last_fail_at=?, updated_at=? " +
                            "WHERE activity_id=? AND user_id=?",
                    newFails, ts(now), ts(now), activityId, userId);
        }
    }

    // ---- 4.5 出勤快照 ----

    /** 活动开始时正式资格快照。public 供 SweepService 与本服务调用；
     *  自身不开新事务，靠调用方事务。 */
    public void ensureSnapshotForActivity(Map<String, Object> act) {
        long activityId = ((Number) act.get("id")).longValue();
        LocalDateTime start = asLocalDateTime(act.get("start_time"));
        var parts = jdbc.queryForList("SELECT * FROM participation WHERE activity_id=?", activityId);
        for (var part : parts) {
            long participationId = ((Number) part.get("id")).longValue();
            long userId = ((Number) part.get("user_id")).longValue();
            if (!formalAtStart(participationId, (String) part.get("status"), part.get("joined_at"), start))
                continue;
            String insert = mysql
                    ? "INSERT IGNORE INTO attendance(participation_id, activity_id, user_id, result, version, decided_by) " +
                            "VALUES (?,?,?,'UNVERIFIED',1,NULL)"
                    : "INSERT INTO attendance(participation_id, activity_id, user_id, result, version, decided_by) " +
                            "VALUES (?,?,?,'UNVERIFIED',1,NULL) ON CONFLICT (participation_id) DO NOTHING";
            int inserted = jdbc.update(insert, participationId, activityId, userId);
            if (inserted != 1) continue;
            Long attendanceId = jdbc.queryForObject(
                    "SELECT id FROM attendance WHERE participation_id=?", Long.class, participationId);
            jdbc.update("INSERT INTO attendance_revision(attendance_id, version, actor_id, result, reason, " +
                            "available_at, appeal_until) VALUES (?,?,NULL,?,'活动开始资格快照',NULL,NULL)",
                    attendanceId, 1L, "UNVERIFIED");
        }
    }

    /** 活动开始时的正式资格：取开始前最后一条参与事件（有则以其 to_status 为准）；
     *  无事件则看当前状态与 joined_at。 */
    private boolean formalAtStart(long participationId, String status, Object joinedAt,
                                  LocalDateTime start) {
        var events = jdbc.queryForList(
                "SELECT to_status FROM participation_events WHERE participation_id=? AND created_at<=? " +
                        "ORDER BY id DESC LIMIT 1",
                participationId, ts(start));
        if (!events.isEmpty())
            return "FORMAL".equals(events.get(0).get("to_status"));
        return "FORMAL".equals(status)
                && (joinedAt == null || !asLocalDateTime(joinedAt).isAfter(start));
    }

    // ---- 4.6 出勤列表 ----

    @Transactional
    public List<Map<String, Object>> listAttendance(long activityId, long requesterId) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        String status = (String) act.get("status");
        if ("RUNNING".equals(status) || "ENDED".equals(status))
            ensureSnapshotForActivity(act);
        boolean organizer = Objects.equals(
                ((Number) act.get("organizer_id")).longValue(), requesterId);
        return queryAttendance(activityId, organizer ? null : Long.valueOf(requesterId));
    }

    /** 管理员查看全量出勤名单；与 listAttendance 一样在事务内补建已开始活动的快照。 */
    @Transactional
    public List<Map<String, Object>> listAttendanceForAdmin(long activityId) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        String status = (String) act.get("status");
        if ("RUNNING".equals(status) || "ENDED".equals(status))
            ensureSnapshotForActivity(act);
        return queryAttendance(activityId, null);
    }

    private List<Map<String, Object>> queryAttendance(long activityId, Long userId) {
        String base = "SELECT att.*, u.nickname AS nickname, c.checkin_at AS checkin_at " +
                "FROM attendance att JOIN app_user u ON u.id=att.user_id " +
                "LEFT JOIN checkin c ON c.activity_id=att.activity_id AND c.user_id=att.user_id " +
                "WHERE att.activity_id=?";
        var rows = userId == null
                ? jdbc.queryForList(base + " ORDER BY att.user_id", activityId)
                : jdbc.queryForList(base + " AND att.user_id=? ORDER BY att.user_id", activityId, userId);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) out.add(toAttendanceMap(row));
        return out;
    }

    /** 出勤单行输出口径（4.6）：时间统一 ISO 字符串，id 类保持 Number。 */
    private Map<String, Object> toAttendanceMap(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("participation_id", row.get("participation_id"));
        out.put("activity_id", row.get("activity_id"));
        out.put("user_id", row.get("user_id"));
        out.put("nickname", row.get("nickname"));
        out.put("result", row.get("result"));
        out.put("version", row.get("version"));
        out.put("decided_by", row.get("decided_by"));
        out.put("finalized_at", iso(row.get("finalized_at")));
        out.put("checkin_at", iso(row.get("checkin_at")));
        out.put("created_at", iso(row.get("created_at")));
        out.put("updated_at", iso(row.get("updated_at")));
        return out;
    }

    private Map<String, Object> attendanceRow(long activityId, long userId) {
        var rows = queryAttendance(activityId, Long.valueOf(userId));
        return rows.isEmpty() ? null : rows.get(0);
    }

    // ---- 4.7 核对 ----

    @Transactional
    public Map<String, Object> verify(long activityId, long organizerId, long targetUserId,
                                      String result, String evidence, Long version) {
        // 1. 锁活动行并校验组织者。
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        if (!Objects.equals(((Number) act.get("organizer_id")).longValue(), organizerId))
            throw new IllegalStateException("只有组织者可以核对出勤");
        // 2. 组织者本人由管理员处理。
        if (targetUserId == organizerId)
            throw new IllegalStateException("组织者本人的出勤由管理员处理");
        // 3. 仅活动结束后可核对。
        if (!"ENDED".equals(act.get("status")))
            throw new IllegalStateException("活动结束后才可核对出勤");
        // 4. 查询入口补建快照后取出目标出勤行。
        ensureSnapshotForActivity(act);
        var rows = jdbc.queryForList(
                "SELECT * FROM attendance WHERE activity_id=? AND user_id=?",
                activityId, targetUserId);
        if (rows.isEmpty())
            throw new IllegalStateException("该成员不在出勤名单中");
        var att = rows.get(0);
        long attendanceId = ((Number) att.get("id")).longValue();
        long currentVersion = ((Number) att.get("version")).longValue();
        LocalDateTime now = LocalDateTime.now();
        // 5. 已定版或核对期届满都拒绝（定版可能尚未被 sweep 执行，口径一致）。
        if (att.get("finalized_at") != null)
            throw new IllegalStateException("核对期已结束，出勤已定版，更正请走申诉复核");
        LocalDateTime end = asLocalDateTime(act.get("end_time"));
        if (now.isAfter(end.plusMinutes(verifyWindowMinutes)))
            throw new IllegalStateException("核对期已结束，更正请走申诉复核");
        // 6. result 枚举校验。
        if (result == null || !RESULTS.contains(result))
            throw new ValidationException("result", "出勤结果不合法");
        // 7. 乐观并发：版本不一致返回 409。
        if (version != null && version.longValue() != currentVersion)
            throw new ConflictException("出勤记录已被更新，请刷新后重试", Map.of());
        // 8. 覆盖签到事实 / 更正已有结论必须填写依据。
        boolean hasConclusion = currentVersion > 1 || att.get("decided_by") != null;
        Integer checkinCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM checkin WHERE activity_id=? AND user_id=?",
                Integer.class, activityId, targetUserId);
        boolean hasCheckin = checkinCount != null && checkinCount > 0;
        boolean needEvidence = hasConclusion
                || ("PRESENT".equals(result) && !hasCheckin)
                || ("ABSENT_VERIFIED".equals(result) && hasCheckin);
        if (needEvidence && (evidence == null || evidence.isBlank()))
            throw new ValidationException("evidence", "覆盖签到或更正出勤结论须填写依据");
        // 9. 更新出勤并追加只增不改的修订行。
        long newVersion = currentVersion + 1;
        jdbc.update("UPDATE attendance SET result=?, version=?, decided_by=?, updated_at=? WHERE id=?",
                result, newVersion, organizerId, ts(now), attendanceId);
        String reason = (evidence != null && !evidence.isBlank()) ? evidence.trim() : "组织者核对";
        jdbc.update("INSERT INTO attendance_revision(attendance_id, version, actor_id, result, reason, " +
                        "available_at, appeal_until) VALUES (?,?,?,?,?,?,?)",
                attendanceId, newVersion, organizerId, result, reason,
                ts(now), ts(now.plusDays(APPEAL_DAYS)));
        // 10. 通知被核对者（与 BuddyService.notify 同口径的 outbox，type 用「变更」）。
        notify(targetUserId, activityId, "变更",
                "活动「" + act.get("title") + "」出勤结果：" + resultLabel(result) + "。",
                "notify:attendance:" + attendanceId + ":v" + newVersion);
        // 11. 返回更新后的单行（附昵称与签到时间）。
        return attendanceRow(activityId, targetUserId);
    }

    /** 管理员仅在核对窗内代核组织者本人；已定版更正仍走申诉复核 / adminCorrect。 */
    @Transactional
    public Map<String, Object> adminVerifyOrganizer(long activityId, long adminId,
                                                   String result, String evidence) {
        // 先锁活动，再补建快照并锁出勤行，保持活动在先的核对写入顺序。
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=? FOR UPDATE", activityId);
        long organizerId = ((Number) act.get("organizer_id")).longValue();
        if (!"ENDED".equals(act.get("status")))
            throw new IllegalStateException("活动结束后才可核对出勤");
        ensureSnapshotForActivity(act);
        var rows = jdbc.queryForList(
                "SELECT * FROM attendance WHERE activity_id=? AND user_id=? FOR UPDATE",
                activityId, organizerId);
        if (rows.isEmpty())
            throw new IllegalStateException("组织者不在出勤名单中");
        var att = rows.get(0);
        long attendanceId = ((Number) att.get("id")).longValue();
        long currentVersion = ((Number) att.get("version")).longValue();
        LocalDateTime now = LocalDateTime.now();
        if (att.get("finalized_at") != null)
            throw new IllegalStateException("出勤已定版，管理员更正请走申诉复核");
        // 沿用 verify 的独立核对窗与边界，不能因 sweep 尚未定版而允许窗外代核。
        LocalDateTime end = asLocalDateTime(act.get("end_time"));
        if (now.isAfter(end.plusMinutes(verifyWindowMinutes)))
            throw new IllegalStateException("核对期已结束，更正请走申诉复核");
        if (result == null || !RESULTS.contains(result))
            throw new ValidationException("result", "出勤结果不合法");
        // 严格对照 verify 第 8 步：已有结论（version>1 或 decided_by 非空）必填；
        // 首次核对仅 PRESENT 无签到或 ABSENT_VERIFIED 有签到必填，
        // EXEMPT / UNVERIFIED 不因存在签到事实就单独要求依据。
        boolean hasConclusion = currentVersion > 1 || att.get("decided_by") != null;
        Integer checkinCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM checkin WHERE activity_id=? AND user_id=?",
                Integer.class, activityId, organizerId);
        boolean hasCheckin = checkinCount != null && checkinCount > 0;
        boolean needEvidence = hasConclusion
                || ("PRESENT".equals(result) && !hasCheckin)
                || ("ABSENT_VERIFIED".equals(result) && hasCheckin);
        if (needEvidence && (evidence == null || evidence.isBlank()))
            throw new ValidationException("evidence", "覆盖签到事实或更正已有结论须填写依据");
        long newVersion = currentVersion + 1;
        jdbc.update("UPDATE attendance SET result=?, version=?, decided_by=?, updated_at=? WHERE id=?",
                result, newVersion, adminId, ts(now), attendanceId);
        String reason = (evidence != null && !evidence.isBlank())
                ? evidence.trim() : "管理员代组织者本人核对";
        jdbc.update("INSERT INTO attendance_revision(attendance_id, version, actor_id, result, reason, " +
                        "available_at, appeal_until) VALUES (?,?,?,?,?,?,?)",
                attendanceId, newVersion, adminId, result, reason,
                ts(now), ts(now.plusDays(APPEAL_DAYS)));
        notify(organizerId, activityId, "变更",
                "活动「" + act.get("title") + "」你的出勤（组织者本人）已由管理员核对为：" + resultLabel(result) + "。",
                "notify:attendance:" + attendanceId + ":v" + newVersion);
        Map<String, Object> out = attendanceRow(activityId, organizerId);
        out.put("new_version", newVersion);
        return out;
    }

    private static String resultLabel(String result) {
        return switch (result) {
            case "PRESENT" -> "到场";
            case "ABSENT_VERIFIED" -> "核实缺席";
            case "EXEMPT" -> "豁免";
            default -> "未核实";
        };
    }

    // ---- 阶段四 CEM-09（2026-11-15）：管理员改判通道 ----

    /** 管理员复核更正已定版出勤：结果枚举与理由必填，出勤行锁内追加新版本并通知本人。
     *  供申诉复核（GovernanceService.reviewAppeal）调用；不改信用分——阶段三重算扫描
     *  会按版本落后自动跟进。 */
    @Transactional
    public Map<String, Object> adminCorrect(long attendanceId, long adminId, String result, String reason) {
        if (result == null || !RESULTS.contains(result))
            throw new ValidationException("result", "出勤结果不合法");
        if (reason == null || reason.isBlank())
            throw new ValidationException("reason", "更正须填写理由");
        var rows = jdbc.queryForList("SELECT * FROM attendance WHERE id=? FOR UPDATE", attendanceId);
        if (rows.isEmpty())
            throw new IllegalStateException("出勤记录不存在");
        var att = rows.get(0);
        if (att.get("finalized_at") == null)
            throw new IllegalStateException("出勤尚未定版，改判请走组织者核对");
        long activityId = ((Number) att.get("activity_id")).longValue();
        long userId = ((Number) att.get("user_id")).longValue();
        long currentVersion = ((Number) att.get("version")).longValue();
        long newVersion = currentVersion + 1;
        LocalDateTime now = LocalDateTime.now();
        jdbc.update("UPDATE attendance SET result=?, version=?, decided_by=?, updated_at=? WHERE id=?",
                result, newVersion, adminId, ts(now), attendanceId);
        jdbc.update("INSERT INTO attendance_revision(attendance_id, version, actor_id, result, reason, " +
                        "available_at, appeal_until) VALUES (?,?,?,?,?,?,?)",
                attendanceId, newVersion, adminId, result, reason,
                ts(now), ts(now.plusDays(APPEAL_DAYS)));
        Long revisionId = jdbc.queryForObject(
                "SELECT id FROM attendance_revision WHERE attendance_id=? AND version=?",
                Long.class, attendanceId, newVersion);
        String title = jdbc.queryForObject(
                "SELECT title FROM activity WHERE id=?", String.class, activityId);
        notify(userId, activityId, "变更",
                "活动「" + title + "」出勤结果已由管理员复核更正为：" + resultLabel(result) + "。",
                "notify:attendance:" + attendanceId + ":v" + newVersion);
        Map<String, Object> out = attendanceRow(activityId, userId);
        if (out == null) out = new LinkedHashMap<>();
        out.put("new_revision_id", revisionId);
        out.put("new_version", newVersion);
        return out;
    }

    // ---- 4.8 定版 ----

    /** 核对期届满定版：无结论者按签到事实形成结论并通知；有结论者只封存。
     *  @Transactional 保证同一活动的定版与 revision / 通知写入原子完成。 */
    @Transactional
    public int finalizeActivity(long activityId, LocalDateTime now) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        ensureSnapshotForActivity(act);
        String title = (String) act.get("title");
        var rows = jdbc.queryForList(
                "SELECT * FROM attendance WHERE activity_id=? AND finalized_at IS NULL ORDER BY id",
                activityId);
        int processed = 0;
        for (var row : rows) {
            processed++;
            long attendanceId = ((Number) row.get("id")).longValue();
            long userId = ((Number) row.get("user_id")).longValue();
            long version = ((Number) row.get("version")).longValue();
            boolean hasConclusion = version > 1 || row.get("decided_by") != null;
            if (!hasConclusion) {
                Integer checkinCount = jdbc.queryForObject(
                        "SELECT COUNT(*) FROM checkin WHERE activity_id=? AND user_id=?",
                        Integer.class, activityId, userId);
                boolean hasCheckin = checkinCount != null && checkinCount > 0;
                String newResult = hasCheckin ? "PRESENT" : "UNVERIFIED";
                long newVersion = version + 1;
                String reason = hasCheckin
                        ? "核对期届满，系统按签到事实形成到场结果"
                        : "核对期届满，系统形成未核实结果";
                jdbc.update("UPDATE attendance SET result=?, version=?, updated_at=?, finalized_at=? WHERE id=?",
                        newResult, newVersion, ts(now), ts(now), attendanceId);
                jdbc.update("INSERT INTO attendance_revision(attendance_id, version, actor_id, result, reason, " +
                                "available_at, appeal_until) VALUES (?,?,NULL,?,?,?,?)",
                        attendanceId, newVersion, newResult, reason,
                        ts(now), ts(now.plusDays(APPEAL_DAYS)));
                notify(userId, activityId, "变更",
                        "活动「" + title + "」出勤结果：" + resultLabel(newResult) + "。",
                        "notify:attendance:" + attendanceId + ":v" + newVersion);
            } else {
                jdbc.update("UPDATE attendance SET finalized_at=? WHERE id=?", ts(now), attendanceId);
            }
        }
        return processed;
    }

    // ---- 4.9 定时扫描挂钩 ----

    /** SweepService 每轮调用：先补建缺失的出勤快照，再对核对期届满的活动定版。
     *  逐活动失败由 SweepService 的 try/catch 兜住，下一轮重试。 */
    @Transactional
    public void sweepAttendance(LocalDateTime now) {
        // 补建候选：已开始 / 已结束且还没有任何出勤行的活动。
        var snapshotIds = jdbc.queryForList(
                "SELECT id FROM activity WHERE status IN ('RUNNING','ENDED') AND start_time <= ? " +
                        "AND id NOT IN (SELECT activity_id FROM attendance) " +
                        "AND EXISTS (SELECT 1 FROM participation WHERE participation.activity_id=activity.id) " +
                        "ORDER BY id",
                Long.class, ts(now));
        for (Long activityId : snapshotIds) {
            var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
            ensureSnapshotForActivity(act);
        }
        // 定版候选：ENDED 且 end_time + 核对期 <= now 仍有未定版出勤的活动。
        var finalizeIds = jdbc.queryForList(
                "SELECT DISTINCT a.id FROM activity a JOIN attendance att ON att.activity_id=a.id " +
                        "WHERE a.status='ENDED' AND att.finalized_at IS NULL AND a.end_time <= ? " +
                        "ORDER BY a.id",
                Long.class, ts(now.minusMinutes(verifyWindowMinutes)));
        for (Long activityId : finalizeIds) {
            finalizeActivity(activityId, now);
        }
    }

    // ---- 4.10 评价 ----

    @Transactional
    public Map<String, Object> upsertEvaluation(long activityId, long userId,
                                                Integer rating, String content) {
        var act = jdbc.queryForMap("SELECT * FROM activity WHERE id=?", activityId);
        LocalDateTime now = LocalDateTime.now();
        if (!"ENDED".equals(act.get("status")))
            throw new IllegalStateException("活动结束后才可评价");
        LocalDateTime end = asLocalDateTime(act.get("end_time"));
        if (now.isAfter(end.plusDays(EVALUATION_DAYS)))
            throw new IllegalStateException("评价期已结束（活动结束后 7 日内可评价）");
        var attRows = jdbc.queryForList(
                "SELECT * FROM attendance WHERE activity_id=? AND user_id=? AND result='PRESENT'",
                activityId, userId);
        if (attRows.isEmpty())
            throw new IllegalStateException("出勤结果为到场时才可评价");
        long participationId = ((Number) attRows.get(0).get("participation_id")).longValue();
        if (rating == null || rating < 1 || rating > 5)
            throw new ValidationException("rating", "评分需为 1-5 分");
        if (content == null) content = "";
        if (content.codePointCount(0, content.length()) > 500)
            throw new ValidationException("content", "评价不能超过 500 字");
        // 双库 upsert：created_at 只在首次插入时写，updated_at 每次更新。
        String sql = mysql
                ? "INSERT INTO evaluation(activity_id, user_id, participation_id, rating, content, " +
                        "created_at, updated_at) VALUES (?,?,?,?,?,?,?) " +
                        "ON DUPLICATE KEY UPDATE participation_id=VALUES(participation_id), " +
                        "rating=VALUES(rating), content=VALUES(content), updated_at=VALUES(updated_at)"
                : "INSERT INTO evaluation(activity_id, user_id, participation_id, rating, content, " +
                        "created_at, updated_at) VALUES (?,?,?,?,?,?,?) " +
                        "ON CONFLICT (activity_id, user_id) DO UPDATE SET " +
                        "participation_id=EXCLUDED.participation_id, rating=EXCLUDED.rating, " +
                        "content=EXCLUDED.content, updated_at=EXCLUDED.updated_at";
        jdbc.update(sql, activityId, userId, participationId, rating, content, ts(now), ts(now));
        return evaluationRow(activityId, userId);
    }

    /** 组织者看全部评价；出勤名单内的本人看自己那份（0/1 条）；名单外登录用户拒绝。
     *  规格未明确“本人”的判定，这里以出勤名单成员为本人（按 4.6 的可见范围类推）。 */
    public List<Map<String, Object>> listEvaluations(long activityId, long requesterId) {
        var act = jdbc.queryForMap("SELECT organizer_id FROM activity WHERE id=?", activityId);
        boolean organizer = Objects.equals(
                ((Number) act.get("organizer_id")).longValue(), requesterId);
        if (organizer) {
            var rows = jdbc.queryForList(
                    "SELECT e.*, u.nickname AS nickname FROM evaluation e " +
                            "JOIN app_user u ON u.id=e.user_id WHERE e.activity_id=? " +
                            "ORDER BY e.updated_at DESC, e.id DESC",
                    activityId);
            List<Map<String, Object>> out = new ArrayList<>(rows.size());
            for (var row : rows) out.add(toEvaluationListMap(row));
            return out;
        }
        Integer inRoster = jdbc.queryForObject(
                "SELECT COUNT(*) FROM attendance WHERE activity_id=? AND user_id=?",
                Integer.class, activityId, requesterId);
        if (inRoster == null || inRoster == 0)
            throw new IllegalStateException("评价正文仅本人和组织者可见");
        var own = evaluationRow(activityId, requesterId);
        if (own == null) return List.of();
        return List.of(own);
    }

    public Map<String, Object> evaluationSummary(long activityId) {
        var row = jdbc.queryForMap(
                "SELECT COUNT(*) c, AVG(rating) a FROM evaluation WHERE activity_id=?", activityId);
        long count = ((Number) row.get("c")).longValue();
        Object avg = row.get("a");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("count", count);
        out.put("avg_score", (count == 0 || avg == null)
                ? null : Math.round(((Number) avg).doubleValue() * 10) / 10.0);
        return out;
    }

    /** 本人评价单行；无则 null。字段口径同 upsertEvaluation 的返回。 */
    public Map<String, Object> myEvaluation(long activityId, long userId) {
        return evaluationRow(activityId, userId);
    }

    /** 本人签到单行；无则 null。 */
    public Map<String, Object> myCheckin(long activityId, long userId) {
        var rows = jdbc.queryForList(
                "SELECT * FROM checkin WHERE activity_id=? AND user_id=?", activityId, userId);
        if (rows.isEmpty()) return null;
        var row = rows.get(0);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("activity_id", row.get("activity_id"));
        out.put("user_id", row.get("user_id"));
        out.put("participation_id", row.get("participation_id"));
        out.put("checkin_at", iso(row.get("checkin_at")));
        return out;
    }

    /** 本人出勤单行；无则 null。字段口径同 4.6（含 nickname / checkin_at）。 */
    public Map<String, Object> myAttendance(long activityId, long userId) {
        return attendanceRow(activityId, userId);
    }

    private Map<String, Object> evaluationRow(long activityId, long userId) {
        var rows = jdbc.queryForList(
                "SELECT * FROM evaluation WHERE activity_id=? AND user_id=?", activityId, userId);
        if (rows.isEmpty()) return null;
        var row = rows.get(0);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("activity_id", row.get("activity_id"));
        out.put("user_id", row.get("user_id"));
        out.put("rating", row.get("rating"));
        out.put("content", row.get("content"));
        out.put("created_at", iso(row.get("created_at")));
        out.put("updated_at", iso(row.get("updated_at")));
        return out;
    }

    private Map<String, Object> toEvaluationListMap(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("activity_id", row.get("activity_id"));
        out.put("user_id", row.get("user_id"));
        out.put("participation_id", row.get("participation_id"));
        out.put("nickname", row.get("nickname"));
        out.put("rating", row.get("rating"));
        out.put("content", row.get("content"));
        out.put("created_at", iso(row.get("created_at")));
        out.put("updated_at", iso(row.get("updated_at")));
        return out;
    }
}
