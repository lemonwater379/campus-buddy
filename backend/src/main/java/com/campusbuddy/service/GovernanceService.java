package com.campusbuddy.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.LocalDateTime;
import java.util.*;

/**
 * 阶段四 CEM-09（2026-11-15）：平台治理服务层（见 phase4/specs/spec-backend-service.md）。
 *
 * 口径：
 * - 双库 PostgreSQL / MySQL 同代码，构造时 detectMysql 判定方言，照抄
 *   AttendanceService 的 detectMysql / ts / asLocalDateTime / iso / notify 私有助手写法。
 * - 治理决定（governance_decision）只追加不覆盖，当前封禁态由 user_ban 单独维护；
 *   活动下架标记独立于 activity 生命周期。
 * - 通知一律使用既有 CHECK 允许的「变更」，走 outbox：显式 status='PENDING'、
 *   publish_at=now、event_key 去重。
 * - 取新行 id 一律 GeneratedKeyHolder + new String[]{"id"}（禁止 RETURN_GENERATED_KEYS /
 *   SELECT MAX(id)）。
 */
@Service
public class GovernanceService {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Set<String> COMPLAINT_CATEGORIES =
            Set.of("违规内容", "人身攻击", "虚假信息", "其他");
    private static final Set<String> ATTENDANCE_RESULTS =
            Set.of("PRESENT", "ABSENT_VERIFIED", "EXEMPT", "UNVERIFIED");
    private static final Set<String> REVIEW_APPEAL_OUTCOMES = Set.of("UPHOLD", "CORRECT");
    private static final Set<String> COMPLAINT_OUTCOMES = Set.of("RESOLVED", "DISMISSED");

    private static final String COMPLAINT_SELECT =
            "SELECT c.*, a.title AS activity_title, su.nickname AS subject_nickname, " +
                    "au.nickname AS applicant_nickname " +
                    "FROM complaint c JOIN app_user au ON au.id=c.applicant_id " +
                    "LEFT JOIN activity a ON a.id=c.activity_id " +
                    "LEFT JOIN app_user su ON su.id=c.subject_user_id";

    private static final String APPEAL_SELECT =
            "SELECT ap.*, au.nickname AS applicant_nickname, d.decision_type, d.activity_id, " +
                    "d.subject_user_id, r.attendance_id AS attendance_id " +
                    "FROM appeal ap JOIN app_user au ON au.id=ap.applicant_id " +
                    "JOIN governance_decision d ON d.id=ap.decision_id " +
                    "LEFT JOIN attendance_revision r ON r.id=d.attendance_revision_id";

    private final JdbcTemplate jdbc;
    private final AuthService auth;
    private final BuddyService buddy;
    private final AttendanceService attendanceService;
    private final ObjectMapper mapper;
    private final long resetMinutes;
    /** 双库分支：与 AttendanceService.detectMysql 同口径，启动时判定一次并缓存。 */
    private final boolean mysql;

    public GovernanceService(JdbcTemplate jdbc, AuthService auth, BuddyService buddy,
                             AttendanceService attendanceService, ObjectMapper mapper,
                             @Value("${app.governance.reset-minutes}") long resetMinutes) {
        this.jdbc = jdbc;
        this.auth = auth;
        this.buddy = buddy;
        this.attendanceService = attendanceService;
        this.mapper = mapper;
        this.resetMinutes = resetMinutes;
        this.mysql = detectMysql(jdbc);
    }

    // ---- 通用私有助手（照抄 AttendanceService 口径） ----

    /** 与 AttendanceService.detectMysql 同实现。 */
    private static boolean detectMysql(JdbcTemplate jdbc) {
        try (var con = jdbc.getDataSource().getConnection()) {
            return con.getMetaData().getDatabaseProductName().toLowerCase().contains("mysql");
        } catch (Exception e) {
            throw new IllegalStateException("无法识别数据库产品", e);
        }
    }

    /** 东八区墙钟 → JDBC Timestamp，不做时区换算。 */
    private static Timestamp ts(LocalDateTime t) { return Timestamp.valueOf(t); }

    /** MySQL 驱动返回 LocalDateTime、PostgreSQL 驱动返回 Timestamp，统一归一化。 */
    private static LocalDateTime asLocalDateTime(Object v) {
        if (v instanceof LocalDateTime ldt) return ldt;
        if (v instanceof Timestamp t) return t.toLocalDateTime();
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime();
        throw new IllegalStateException("无法识别的时间类型: " + v);
    }

    /** 时间字段统一输出 ISO 字符串。 */
    private static String iso(Object v) { return v == null ? null : asLocalDateTime(v).toString(); }

    /** 数据库 0/1 整型转 boolean。 */
    private static boolean bool(Object v) {
        if (v == null) return false;
        if (v instanceof Boolean b) return b;
        return ((Number) v).intValue() != 0;
    }

    private static Long nullableLong(Object v) {
        return v == null ? null : ((Number) v).longValue();
    }

    private static String truncate(String s, int max) {
        if (s == null) return null;
        return s.length() <= max ? s : s.substring(0, max);
    }

    private static int clampLimit(int limit) {
        if (limit < 1) return 1;
        return Math.min(limit, 200);
    }

    /** 与 ApiSupport.sha256 相同实现（服务层不依赖 controller 包）。 */
    private static String sha256(String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(text.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    /** 32 位小写十六进制查询 / 重置凭据。 */
    private static String newToken() {
        byte[] bytes = new byte[16];
        RANDOM.nextBytes(bytes);
        return HexFormat.of().formatHex(bytes);
    }

    /** 与 BuddyService.notify 同口径的 outbox 写入，治理通知 type 固定「变更」。 */
    private void notify(Long userId, Long activityId, String content, String eventKey) {
        String sql = mysql
                ? "INSERT IGNORE INTO notification(user_id, activity_id, invitation_id, type, content, " +
                        "event_key, sender_id, status, publish_at) VALUES (?,?,?,?,?,?,?, 'PENDING', ?)"
                : "INSERT INTO notification(user_id, activity_id, invitation_id, type, content, " +
                        "event_key, sender_id, status, publish_at) VALUES (?,?,?,?,?,?,?, 'PENDING', ?) " +
                        "ON CONFLICT (user_id, event_key) DO NOTHING";
        jdbc.update(sql, userId, activityId, null, "变更", truncate(content, 1000), eventKey, null,
                ts(LocalDateTime.now()));
    }

    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("治理明细序列化失败", e);
        }
    }

    private static void setLongOrNull(PreparedStatement ps, int idx, Long v) throws SQLException {
        if (v == null) ps.setNull(idx, Types.BIGINT); else ps.setLong(idx, v);
    }

    private static void setTsOrNull(PreparedStatement ps, int idx, LocalDateTime v) throws SQLException {
        if (v == null) ps.setNull(idx, Types.TIMESTAMP); else ps.setTimestamp(idx, ts(v));
    }

    private static void setStrOrNull(PreparedStatement ps, int idx, String v) throws SQLException {
        if (v == null) ps.setNull(idx, Types.VARCHAR); else ps.setString(idx, v);
    }

    // ---- 通用写入件 ----

    /** INSERT 一条不可变治理决定并返回 id。 */
    private long insertDecision(Long actorId, Long previousDecisionId, String type,
                                Long subjectUserId, Long activityId, Long participationId,
                                Long attendanceRevisionId, String reason, String result,
                                LocalDateTime expiresAt, LocalDateTime availableAt,
                                LocalDateTime appealUntil, String executionState) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                    "INSERT INTO governance_decision(actor_id, previous_decision_id, decision_type, " +
                            "subject_user_id, activity_id, participation_id, attendance_revision_id, " +
                            "reason, result, decided_at, expires_at, available_at, appeal_until, " +
                            "execution_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    new String[]{"id"});
            setLongOrNull(ps, 1, actorId);
            setLongOrNull(ps, 2, previousDecisionId);
            ps.setString(3, type);
            setLongOrNull(ps, 4, subjectUserId);
            setLongOrNull(ps, 5, activityId);
            setLongOrNull(ps, 6, participationId);
            setLongOrNull(ps, 7, attendanceRevisionId);
            ps.setString(8, reason == null ? "" : truncate(reason, 500));
            ps.setString(9, result == null ? "" : truncate(result, 1000));
            ps.setTimestamp(10, ts(LocalDateTime.now()));
            setTsOrNull(ps, 11, expiresAt);
            setTsOrNull(ps, 12, availableAt);
            setTsOrNull(ps, 13, appealUntil);
            setStrOrNull(ps, 14, executionState);
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    /** 治理操作审计；request_id 固定为空。 */
    private void logAction(long actorId, String action, String targetType, Long targetId,
                           Long decisionId, String reason, String detail) {
        jdbc.update("INSERT INTO governance_action(actor_id, action, target_type, target_id, " +
                        "decision_id, reason, detail, request_id, created_at) VALUES (?,?,?,?,?,?,?,NULL,?)",
                actorId, action, targetType, targetId, decisionId,
                reason == null ? "" : truncate(reason, 500), detail, ts(LocalDateTime.now()));
    }

    private long insertComplaint(long applicantId, Long activityId, Long subjectUserId,
                                 String category, String reason, LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                    "INSERT INTO complaint(applicant_id, activity_id, subject_user_id, category, " +
                            "reason, state, submitted_at) VALUES (?,?,?,?,?, 'PENDING', ?)",
                    new String[]{"id"});
            ps.setLong(1, applicantId);
            setLongOrNull(ps, 2, activityId);
            setLongOrNull(ps, 3, subjectUserId);
            ps.setString(4, category);
            ps.setString(5, reason);
            ps.setTimestamp(6, ts(now));
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    private long insertAppeal(long applicantId, long decisionId, Long complaintId,
                              String reason, LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                    "INSERT INTO appeal(applicant_id, decision_id, complaint_id, reason, state, " +
                            "submitted_at) VALUES (?,?,?,?, 'PENDING', ?)",
                    new String[]{"id"});
            ps.setLong(1, applicantId);
            ps.setLong(2, decisionId);
            setLongOrNull(ps, 3, complaintId);
            ps.setString(4, reason);
            ps.setTimestamp(5, ts(now));
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    private long insertRecoveryRequest(long applicantId, int requestType, Long decisionId,
                                       String reason, String contact, String queryHash,
                                       LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                    "INSERT INTO recovery_request(applicant_id, request_type, decision_id, reason, " +
                            "contact, state, query_hash, applied_at) VALUES (?,?,?,?,?, 'PENDING', ?, ?)",
                    new String[]{"id"});
            ps.setLong(1, applicantId);
            ps.setInt(2, requestType);
            setLongOrNull(ps, 3, decisionId);
            ps.setString(4, reason);
            ps.setString(5, contact == null ? "" : contact);
            ps.setString(6, queryHash);
            ps.setTimestamp(7, ts(now));
            return ps;
        }, keyHolder);
        return keyHolder.getKey().longValue();
    }

    private void logParticipationEvent(long pid, long activityId, long userId,
                                       String type, String from, String to, String detail) {
        jdbc.update("INSERT INTO participation_events(participation_id, activity_id, user_id, " +
                        "event_type, from_status, to_status, detail, created_at) VALUES (?,?,?,?,?,?,?,?)",
                pid, activityId, userId, type, from, to, truncate(detail, 500),
                ts(LocalDateTime.now()));
    }

    private static void requireText(String value, int max, String field, String message) {
        if (value == null || value.isBlank()
                || value.codePointCount(0, value.length()) > max)
            throw new ValidationException(field, message);
    }

    private int count(String sql, Object... args) {
        Integer n = jdbc.queryForObject(sql, Integer.class, args);
        return n == null ? 0 : n;
    }

    // ---- 管理员 ----

    public boolean isAdmin(long userId) {
        return count("SELECT COUNT(*) FROM administrator WHERE user_id=? AND enabled=1", userId) > 0;
    }

    public void requireAdmin(long userId) {
        if (!isAdmin(userId)) throw new ForbiddenException("需要管理员权限");
    }

    public List<Map<String, Object>> listAdmins() {
        var rows = jdbc.queryForList(
                "SELECT a.user_id, u.account, u.nickname, a.enabled, a.authorized_at, " +
                        "a.authorization_note FROM administrator a JOIN app_user u ON u.id=a.user_id " +
                        "ORDER BY a.user_id");
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("user_id", row.get("user_id"));
            m.put("account", row.get("account"));
            m.put("nickname", row.get("nickname"));
            m.put("enabled", bool(row.get("enabled")));
            m.put("authorized_at", iso(row.get("authorized_at")));
            m.put("authorization_note", row.get("authorization_note"));
            out.add(m);
        }
        return out;
    }

    @Transactional
    public Map<String, Object> appointAdmin(long actorId, long targetUserId, String note) {
        requireAdmin(actorId);
        if (count("SELECT COUNT(*) FROM app_user WHERE id=?", targetUserId) == 0)
            throw new IllegalStateException("用户不存在");
        String authorizationNote = note == null ? "" : note;
        var rows = jdbc.queryForList(
                "SELECT enabled FROM administrator WHERE user_id=?", targetUserId);
        LocalDateTime now = LocalDateTime.now();
        if (rows.isEmpty()) {
            jdbc.update("INSERT INTO administrator(user_id, enabled, authorized_at, authorization_note) " +
                            "VALUES (?, 1, ?, ?)",
                    targetUserId, ts(now), authorizationNote);
        } else if (bool(rows.get(0).get("enabled"))) {
            throw new IllegalStateException("该用户已是管理员");
        } else {
            jdbc.update("UPDATE administrator SET enabled=1, authorized_at=?, authorization_note=?, " +
                            "updated_at=? WHERE user_id=?",
                    ts(now), authorizationNote, ts(now), targetUserId);
        }
        logAction(actorId, "ADMIN_APPOINT", "USER", targetUserId, null, note, null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("user_id", targetUserId);
        out.put("enabled", true);
        return out;
    }

    @Transactional
    public Map<String, Object> revokeAdmin(long actorId, long targetUserId, String reason) {
        requireAdmin(actorId);
        var rows = jdbc.queryForList(
                "SELECT enabled FROM administrator WHERE user_id=?", targetUserId);
        if (rows.isEmpty() || !bool(rows.get(0).get("enabled")))
            throw new IllegalStateException("该用户不是在任管理员");
        if (enabledAdminCount() <= 1)
            throw new IllegalStateException("不得撤销最后一名管理员");
        jdbc.update("UPDATE administrator SET enabled=0, updated_at=? WHERE user_id=?",
                ts(LocalDateTime.now()), targetUserId);
        logAction(actorId, "ADMIN_REVOKE", "USER", targetUserId, null, reason, null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("user_id", targetUserId);
        out.put("enabled", false);
        return out;
    }

    public int enabledAdminCount() {
        return count("SELECT COUNT(*) FROM administrator WHERE enabled=1");
    }

    // ---- 总览与队列（工作台） ----

    public Map<String, Object> overview() {
        LocalDateTime now = LocalDateTime.now();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("complaints_pending", count("SELECT COUNT(*) FROM complaint WHERE state='PENDING'"));
        out.put("appeals_pending", count("SELECT COUNT(*) FROM appeal WHERE state='PENDING'"));
        out.put("recovery_pending", count("SELECT COUNT(*) FROM recovery_request WHERE state='PENDING'"));
        out.put("credit_reviews_pending", count("SELECT COUNT(*) FROM credit_review WHERE status='PENDING'"));
        out.put("bans_active", count(
                "SELECT COUNT(*) FROM user_ban WHERE lifted_at IS NULL AND expires_at > ?", ts(now)));
        out.put("bans_expired_pending", count(
                "SELECT COUNT(*) FROM user_ban WHERE lifted_at IS NULL AND expires_at <= ?", ts(now)));
        return out;
    }

    public List<Map<String, Object>> listUsers(String q, int limit) {
        String sql = "SELECT u.id, u.account, u.nickname, u.status, " +
                "CASE WHEN ad.user_id IS NULL THEN 0 ELSE 1 END AS is_admin, " +
                "CASE WHEN b.user_id IS NULL THEN 0 ELSE 1 END AS banned, " +
                "COALESCE((SELECT ce.score_after FROM credit_entry ce WHERE ce.user_id=u.id " +
                "ORDER BY ce.fact_end_time DESC, ce.activity_id DESC, ce.participation_id DESC " +
                "LIMIT 1), 100) AS credit_score " +
                "FROM app_user u " +
                "LEFT JOIN administrator ad ON ad.user_id=u.id AND ad.enabled=1 " +
                "LEFT JOIN user_ban b ON b.user_id=u.id AND b.lifted_at IS NULL";
        List<Object> args = new ArrayList<>();
        if (q != null && !q.isBlank()) {
            sql += " WHERE u.account LIKE ? OR u.nickname LIKE ?";
            String like = "%" + q.trim() + "%";
            args.add(like);
            args.add(like);
        }
        sql += " ORDER BY u.id LIMIT ?";
        args.add(clampLimit(limit));
        var rows = jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", row.get("id"));
            m.put("account", row.get("account"));
            m.put("nickname", row.get("nickname"));
            m.put("status", row.get("status"));
            m.put("is_admin", bool(row.get("is_admin")));
            m.put("banned", bool(row.get("banned")));
            m.put("credit_score", row.get("credit_score"));
            out.add(m);
        }
        return out;
    }

    public List<Map<String, Object>> listActivitiesAdmin() {
        var rows = jdbc.queryForList(
                "SELECT a.*, u.nickname AS organizer_name, COALESCE(d.delisted, 0) AS delisted " +
                        "FROM activity a LEFT JOIN app_user u ON u.id=a.organizer_id " +
                        "LEFT JOIN activity_delist d ON d.activity_id=a.id " +
                        "ORDER BY a.id DESC LIMIT 200");
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", row.get("id"));
            m.put("organizer_id", row.get("organizer_id"));
            m.put("title", row.get("title"));
            m.put("category", row.get("category"));
            m.put("description", row.get("description"));
            m.put("conditions", row.get("conditions"));
            m.put("location", row.get("location"));
            m.put("capacity", row.get("capacity"));
            m.put("deadline", iso(row.get("deadline")));
            m.put("start_time", iso(row.get("start_time")));
            m.put("end_time", iso(row.get("end_time")));
            m.put("status", row.get("status"));
            m.put("created_at", iso(row.get("created_at")));
            m.put("updated_at", iso(row.get("updated_at")));
            m.put("organizer_name", row.get("organizer_name"));
            m.put("delisted", bool(row.get("delisted")));
            out.add(m);
        }
        return out;
    }

    public List<Map<String, Object>> listActions(int limit) {
        var rows = jdbc.queryForList(
                "SELECT * FROM governance_action ORDER BY created_at DESC, id DESC LIMIT ?",
                clampLimit(limit));
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", row.get("id"));
            m.put("actor_id", row.get("actor_id"));
            m.put("action", row.get("action"));
            m.put("target_type", row.get("target_type"));
            m.put("target_id", row.get("target_id"));
            m.put("decision_id", row.get("decision_id"));
            m.put("reason", row.get("reason"));
            m.put("detail", row.get("detail"));
            m.put("request_id", row.get("request_id"));
            m.put("created_at", iso(row.get("created_at")));
            out.add(m);
        }
        return out;
    }

    // ---- 封禁 ----

    private boolean isBanned(long userId) {
        return count("SELECT COUNT(*) FROM user_ban WHERE user_id=? AND lifted_at IS NULL", userId) > 0;
    }

    /** 影响面查询的公共 SELECT；organizer_id 供处置组织者通知使用，不对外输出。 */
    private List<Map<String, Object>> impactRows(long userId, String condition, Object... extra) {
        String sql = "SELECT p.id AS participation_id, p.activity_id, a.title, a.start_time, " +
                "a.organizer_id FROM participation p JOIN activity a ON a.id=p.activity_id " +
                "WHERE p.user_id=? AND (" + condition + ") ORDER BY p.id";
        List<Object> args = new ArrayList<>();
        args.add(userId);
        args.addAll(Arrays.asList(extra));
        return jdbc.queryForList(sql, args.toArray());
    }

    private List<Map<String, Object>> impactList(List<Map<String, Object>> rows) {
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("participation_id", row.get("participation_id"));
            m.put("activity_id", row.get("activity_id"));
            m.put("title", row.get("title"));
            m.put("start_time", iso(row.get("start_time")));
            out.add(m);
        }
        return out;
    }

    private List<Map<String, Object>> organizedActive(long userId) {
        var rows = jdbc.queryForList(
                "SELECT id AS activity_id, title, status FROM activity WHERE organizer_id=? " +
                        "AND status NOT IN ('ENDED','CANCELLED') ORDER BY id", userId);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("activity_id", row.get("activity_id"));
            m.put("title", row.get("title"));
            m.put("status", row.get("status"));
            out.add(m);
        }
        return out;
    }

    private Map<String, Object> execItem(String kind, Long participationId, Long activityId,
                                         String action, String result, String note) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("kind", kind);
        if (participationId != null) m.put("participation_id", participationId);
        if (activityId != null) m.put("activity_id", activityId);
        m.put("action", action);
        m.put("result", result);
        if (note != null) m.put("note", note);
        return m;
    }

    public Map<String, Object> banImpact(long actorId, long targetUserId) {
        requireAdmin(actorId);
        var userRows = jdbc.queryForList(
                "SELECT id, account, nickname, status FROM app_user WHERE id=?", targetUserId);
        if (userRows.isEmpty()) throw new IllegalStateException("用户不存在");
        var u = userRows.get(0);
        LocalDateTime now = LocalDateTime.now();
        Map<String, Object> user = new LinkedHashMap<>();
        user.put("id", u.get("id"));
        user.put("account", u.get("account"));
        user.put("nickname", u.get("nickname"));
        user.put("is_admin", isAdmin(targetUserId));
        user.put("banned", isBanned(targetUserId));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("user", user);
        out.put("waiting", impactList(impactRows(targetUserId, "p.status='WAITING'")));
        out.put("invited", impactList(impactRows(targetUserId, "p.status='INVITED'")));
        out.put("future_formal", impactList(impactRows(targetUserId,
                "p.status='FORMAL' AND a.start_time > ? AND a.status NOT IN ('CANCELLED','ENDED')",
                ts(now))));
        out.put("running_formal", impactList(impactRows(targetUserId,
                "p.status='FORMAL' AND (a.status='RUNNING' OR (a.start_time <= ? AND ? < a.end_time))",
                ts(now), ts(now))));
        out.put("organized_active", organizedActive(targetUserId));
        return out;
    }

    @Transactional
    public Map<String, Object> banUser(long actorId, long targetUserId, Integer days,
                                       String reason, String futureFormal, String organized) {
        requireAdmin(actorId);
        requireText(reason, 500, "reason", "封禁理由须为 1-500 字");
        if (days == null || days < 1 || days > 30)
            throw new ValidationException("days", "封禁期限须为 1 至 30 日");
        if (targetUserId == actorId)
            throw new IllegalStateException("不得封禁自己");
        if (count("SELECT COUNT(*) FROM app_user WHERE id=?", targetUserId) == 0)
            throw new IllegalStateException("用户不存在");
        if (isBanned(targetUserId))
            throw new IllegalStateException("该用户已被封禁");
        if (isAdmin(targetUserId) && enabledAdminCount() <= 1)
            throw new IllegalStateException("不得封禁唯一管理员");
        String futureMode = (futureFormal == null || futureFormal.isBlank()) ? "REMOVE" : futureFormal;
        if (!Set.of("REMOVE", "KEEP").contains(futureMode))
            throw new ValidationException("future_formal", "future_formal 须为 REMOVE 或 KEEP");
        String organizedMode = (organized == null || organized.isBlank()) ? "CANCEL" : organized;
        if (!Set.of("CANCEL", "KEEP").contains(organizedMode))
            throw new ValidationException("organized", "organized 须为 CANCEL 或 KEEP");

        LocalDateTime now = LocalDateTime.now();
        LocalDateTime expiresAt = now.plusDays(days);
        String nickname = jdbc.queryForObject(
                "SELECT nickname FROM app_user WHERE id=?", String.class, targetUserId);
        // 1. 先算影响面（与 banImpact 共用查询）。
        var waitingRows = impactRows(targetUserId, "p.status='WAITING'");
        var invitedRows = impactRows(targetUserId, "p.status='INVITED'");
        var futureRows = impactRows(targetUserId,
                "p.status='FORMAL' AND a.start_time > ? AND a.status NOT IN ('CANCELLED','ENDED')",
                ts(now));
        var runningRows = impactRows(targetUserId,
                "p.status='FORMAL' AND (a.status='RUNNING' OR (a.start_time <= ? AND ? < a.end_time))",
                ts(now), ts(now));
        var organizedRows = organizedActive(targetUserId);

        // 2. 决定与当前封禁态。
        long decisionId = insertDecision(actorId, null, "BAN", targetUserId, null, null, null,
                reason, "封禁 " + days + " 日", expiresAt, now, now.plusDays(7), null);
        // user_ban 以 user_id 为主键保存“当前封禁态”：首次封禁 INSERT；曾经解封过的
        // 用户复用同一行（否则主键冲突，且历史行不应当再阻塞再次封禁）。
        if (count("SELECT COUNT(*) FROM user_ban WHERE user_id=?", targetUserId) == 0) {
            jdbc.update("INSERT INTO user_ban(user_id, decision_id, reason, banned_at, expires_at) " +
                            "VALUES (?,?,?,?,?)",
                    targetUserId, decisionId, reason, ts(now), ts(expiresAt));
        } else {
            jdbc.update("UPDATE user_ban SET decision_id=?, reason=?, banned_at=?, expires_at=?, " +
                            "lifted_at=NULL, lifted_by=NULL, lift_decision_id=NULL, updated_at=? " +
                            "WHERE user_id=?",
                    decisionId, reason, ts(now), ts(expiresAt), ts(now), targetUserId);
        }

        // 3. 逐项处置；单项异常记 FAILED 后继续。
        List<Map<String, Object>> execution = new ArrayList<>();
        for (var p : waitingRows) {
            long pid = ((Number) p.get("participation_id")).longValue();
            long aid = ((Number) p.get("activity_id")).longValue();
            String title = (String) p.get("title");
            try {
                jdbc.update("UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=?",
                        ts(now), pid);
                logParticipationEvent(pid, aid, targetUserId, "BAN_DISPOSAL",
                        "WAITING", "WITHDRAWN", reason);
                notify(targetUserId, aid,
                        "你已被移出活动「" + title + "」的候补队列（账号封禁处置）。",
                        "notify:ban-disp:" + decisionId + ":" + pid);
                execution.add(execItem("WAITING", pid, aid, "WITHDRAW", "DONE", null));
            } catch (Exception e) {
                execution.add(execItem("WAITING", pid, aid, "WITHDRAW", "FAILED", e.getMessage()));
            }
        }
        for (var p : invitedRows) {
            long pid = ((Number) p.get("participation_id")).longValue();
            long aid = ((Number) p.get("activity_id")).longValue();
            String title = (String) p.get("title");
            try {
                jdbc.update("UPDATE invitation SET status='INVALID', responded_at=? " +
                                "WHERE participation_id=? AND status='PENDING'", ts(now), pid);
                jdbc.update("UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=?",
                        ts(now), pid);
                logParticipationEvent(pid, aid, targetUserId, "BAN_DISPOSAL",
                        "INVITED", "WITHDRAWN", reason);
                notify(targetUserId, aid,
                        "你在活动「" + title + "」的待确认邀请已作废（账号封禁处置）。",
                        "notify:ban-disp:" + decisionId + ":" + pid);
                execution.add(execItem("INVITED", pid, aid, "INVALIDATE", "DONE", null));
            } catch (Exception e) {
                execution.add(execItem("INVITED", pid, aid, "INVALIDATE", "FAILED", e.getMessage()));
            }
        }
        if ("REMOVE".equals(futureMode)) {
            for (var p : futureRows) {
                long pid = ((Number) p.get("participation_id")).longValue();
                long aid = ((Number) p.get("activity_id")).longValue();
                long organizerId = ((Number) p.get("organizer_id")).longValue();
                String title = (String) p.get("title");
                try {
                    jdbc.update("UPDATE participation SET status='WITHDRAWN', updated_at=? WHERE id=?",
                            ts(now), pid);
                    logParticipationEvent(pid, aid, targetUserId, "BAN_DISPOSAL",
                            "FORMAL", "WITHDRAWN", reason);
                    notify(targetUserId, aid,
                            "你已被移出活动「" + title + "」（账号封禁处置）。",
                            "notify:ban-disp:" + decisionId + ":" + pid);
                    if (organizerId != targetUserId) {
                        notify(organizerId, aid,
                                "「" + nickname + "」因账号封禁退出活动「" + title + "」。",
                                "notify:ban-disp-org:" + decisionId + ":" + pid);
                    }
                    execution.add(execItem("FUTURE_FORMAL", pid, aid, "WITHDRAW", "DONE", null));
                } catch (Exception e) {
                    execution.add(execItem("FUTURE_FORMAL", pid, aid,
                            "WITHDRAW", "FAILED", e.getMessage()));
                }
            }
        } else {
            for (var p : futureRows) {
                execution.add(execItem("FUTURE_FORMAL",
                        ((Number) p.get("participation_id")).longValue(),
                        ((Number) p.get("activity_id")).longValue(), "KEEP", "SKIPPED", null));
            }
        }
        for (var p : runningRows) {
            execution.add(execItem("RUNNING_FORMAL",
                    ((Number) p.get("participation_id")).longValue(),
                    ((Number) p.get("activity_id")).longValue(),
                    "MANUAL", "SKIPPED", "活动进行中，需人工协调"));
        }
        if ("CANCEL".equals(organizedMode)) {
            for (var row : organizedRows) {
                long aid = ((Number) row.get("activity_id")).longValue();
                try {
                    buddy.cancelActivity(aid, targetUserId);
                    execution.add(execItem("ORGANIZED_ACTIVE", null, aid, "CANCEL", "DONE", null));
                } catch (Exception e) {
                    execution.add(execItem("ORGANIZED_ACTIVE", null, aid,
                            "CANCEL", "FAILED", e.getMessage()));
                }
            }
        } else {
            for (var row : organizedRows) {
                execution.add(execItem("ORGANIZED_ACTIVE", null,
                        ((Number) row.get("activity_id")).longValue(),
                        "KEEP", "SKIPPED", null));
            }
        }
        // 4. 回写执行明细。
        jdbc.update("UPDATE governance_decision SET execution_state=? WHERE id=?",
                json(execution), decisionId);
        // 5. 撤销会话、通知本人、审计、事务尾释放名额递补。
        auth.revokeSessionsForUser(targetUserId);
        notify(targetUserId, null,
                "你的账号已被封禁至 " + iso(expiresAt) + "。原因：" + reason
                        + "。如需申诉，可在登录页提交封禁复核申请。",
                "notify:ban:" + decisionId);
        logAction(actorId, "BAN_USER", "USER", targetUserId, decisionId, reason, null);
        buddy.backfillDaytimeInvites(now);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("decision_id", decisionId);
        out.put("user_id", targetUserId);
        out.put("expires_at", iso(expiresAt));
        out.put("execution", execution);
        return out;
    }

    @Transactional
    public Map<String, Object> unbanUser(long actorId, long targetUserId, String reason) {
        requireAdmin(actorId);
        var bans = jdbc.queryForList(
                "SELECT * FROM user_ban WHERE user_id=? AND lifted_at IS NULL ORDER BY banned_at DESC LIMIT 1",
                targetUserId);
        if (bans.isEmpty()) throw new IllegalStateException("该用户未被封禁");
        long banDecisionId = ((Number) bans.get(0).get("decision_id")).longValue();
        LocalDateTime now = LocalDateTime.now();
        long decisionId = insertDecision(actorId, banDecisionId, "UNBAN", targetUserId,
                null, null, null, reason, "解封", null, null, null, null);
        jdbc.update("UPDATE user_ban SET lifted_at=?, lifted_by=?, lift_decision_id=?, updated_at=? " +
                        "WHERE user_id=? AND lifted_at IS NULL",
                ts(now), actorId, decisionId, ts(now), targetUserId);
        notify(targetUserId, null, "你的账号封禁已解除。", "notify:unban:" + decisionId);
        logAction(actorId, "UNBAN_USER", "USER", targetUserId, decisionId, reason, null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("decision_id", decisionId);
        out.put("user_id", targetUserId);
        return out;
    }

    public List<Map<String, Object>> listBans(boolean expiredOnly) {
        LocalDateTime now = LocalDateTime.now();
        String sql = "SELECT b.user_id, b.decision_id, b.reason, b.banned_at, b.expires_at, " +
                "b.lifted_at, u.account, u.nickname FROM user_ban b " +
                "JOIN app_user u ON u.id=b.user_id";
        List<Object> args = new ArrayList<>();
        if (expiredOnly) {
            sql += " WHERE b.lifted_at IS NULL AND b.expires_at <= ?";
            args.add(ts(now));
        }
        sql += " ORDER BY CASE WHEN b.lifted_at IS NULL THEN 0 ELSE 1 END, b.user_id";
        var rows = jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("user_id", row.get("user_id"));
            m.put("account", row.get("account"));
            m.put("nickname", row.get("nickname"));
            m.put("decision_id", row.get("decision_id"));
            m.put("reason", row.get("reason"));
            m.put("banned_at", iso(row.get("banned_at")));
            m.put("expires_at", iso(row.get("expires_at")));
            LocalDateTime expiresAt = row.get("expires_at") == null
                    ? null : asLocalDateTime(row.get("expires_at"));
            m.put("expired", expiresAt != null && !expiresAt.isAfter(now));
            m.put("lifted_at", iso(row.get("lifted_at")));
            out.add(m);
        }
        return out;
    }

    public Map<String, Object> activeBan(long userId) {
        var rows = jdbc.queryForList(
                "SELECT decision_id, reason, banned_at, expires_at FROM user_ban " +
                        "WHERE user_id=? AND lifted_at IS NULL ORDER BY banned_at DESC LIMIT 1",
                userId);
        if (rows.isEmpty()) return null;
        var row = rows.get(0);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("decision_id", row.get("decision_id"));
        out.put("reason", row.get("reason"));
        out.put("banned_at", iso(row.get("banned_at")));
        out.put("expires_at", iso(row.get("expires_at")));
        return out;
    }

    // ---- 活动下架 ----

    public boolean isDelisted(long activityId) {
        return count("SELECT COUNT(*) FROM activity_delist WHERE activity_id=? AND delisted=1",
                activityId) > 0;
    }

    /**
     * 下架活动。注意：本方法刻意不加 @Transactional——buddy.cancelActivity 自带
     * REQUIRED 事务注解，若在其内部抛异常并穿出代理，当前事务会被标记 rollback-only，
     * 即使本方法 catch 也无法阻止整体回滚；而规格要求「取消失败不回滚下架本身」，
     * 因此下架写入逐条自动提交，取消动作失败只记 note / cancel_failed。
     */
    public Map<String, Object> delistActivity(long actorId, long activityId, String reason) {
        requireAdmin(actorId);
        requireText(reason, 500, "reason", "下架理由须为 1-500 字");
        var actRows = jdbc.queryForList(
                "SELECT status, organizer_id FROM activity WHERE id=?", activityId);
        if (actRows.isEmpty()) throw new IllegalStateException("活动不存在");
        if (isDelisted(activityId)) throw new IllegalStateException("活动已下架");
        String status = (String) actRows.get(0).get("status");
        long organizerId = ((Number) actRows.get(0).get("organizer_id")).longValue();
        long decisionId = insertDecision(actorId, null, "DELIST", null, activityId,
                null, null, reason, "下架", null, null, null, null);
        LocalDateTime now = LocalDateTime.now();
        if (count("SELECT COUNT(*) FROM activity_delist WHERE activity_id=?", activityId) > 0) {
            jdbc.update("UPDATE activity_delist SET delisted=1, decision_id=?, reason=?, " +
                            "updated_by=?, updated_at=? WHERE activity_id=?",
                    decisionId, reason, actorId, ts(now), activityId);
        } else {
            jdbc.update("INSERT INTO activity_delist(activity_id, delisted, decision_id, reason, " +
                            "updated_by, created_at, updated_at) VALUES (?,1,?,?,?,?,?)",
                    activityId, decisionId, reason, actorId, ts(now), ts(now));
        }
        boolean cancelFailed = false;
        String note = null;
        if (!"ENDED".equals(status) && !"CANCELLED".equals(status)) {
            try {
                buddy.cancelActivity(activityId, organizerId);
            } catch (Exception e) {
                cancelFailed = true;
                note = "活动取消失败：" + e.getMessage();
            }
        }
        String activityStatus = jdbc.queryForObject(
                "SELECT status FROM activity WHERE id=?", String.class, activityId);
        logAction(actorId, "DELIST_ACTIVITY", "ACTIVITY", activityId, decisionId, reason, note);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("decision_id", decisionId);
        out.put("activity_id", activityId);
        out.put("delisted", true);
        out.put("activity_status", activityStatus);
        if (cancelFailed) {
            out.put("cancel_failed", true);
            out.put("note", note);
        }
        return out;
    }

    @Transactional
    public Map<String, Object> relistActivity(long actorId, long activityId, String reason) {
        requireAdmin(actorId);
        if (!isDelisted(activityId)) throw new IllegalStateException("活动未下架");
        LocalDateTime now = LocalDateTime.now();
        long decisionId = insertDecision(actorId, null, "RELIST", null, activityId,
                null, null, reason, "恢复展示", null, null, null, null);
        jdbc.update("UPDATE activity_delist SET delisted=0, decision_id=?, reason=?, updated_by=?, " +
                        "updated_at=? WHERE activity_id=?",
                decisionId, reason, actorId, ts(now), activityId);
        logAction(actorId, "RELIST_ACTIVITY", "ACTIVITY", activityId, decisionId, reason, null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("decision_id", decisionId);
        out.put("activity_id", activityId);
        out.put("delisted", false);
        return out;
    }

    // ---- 举报 ----

    private Map<String, Object> complaintMap(Map<String, Object> row) {
        if (row == null) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", row.get("id"));
        m.put("applicant_id", row.get("applicant_id"));
        m.put("applicant_nickname", row.get("applicant_nickname"));
        m.put("activity_id", row.get("activity_id"));
        m.put("activity_title", row.get("activity_title"));
        m.put("subject_user_id", row.get("subject_user_id"));
        m.put("subject_nickname", row.get("subject_nickname"));
        m.put("category", row.get("category"));
        m.put("reason", row.get("reason"));
        m.put("handler_id", row.get("handler_id"));
        m.put("decision_id", row.get("decision_id"));
        m.put("state", row.get("state"));
        m.put("submitted_at", iso(row.get("submitted_at")));
        m.put("handled_at", iso(row.get("handled_at")));
        return m;
    }

    private Map<String, Object> complaintRow(long complaintId) {
        var rows = jdbc.queryForList(COMPLAINT_SELECT + " WHERE c.id=?", complaintId);
        return rows.isEmpty() ? null : complaintMap(rows.get(0));
    }

    @Transactional
    public Map<String, Object> fileComplaint(long applicantId, Long activityId,
                                             Long subjectUserId, String category, String reason) {
        if ((activityId == null) == (subjectUserId == null))
            throw new ValidationException("target", "请选择举报对象");
        if (category == null || !COMPLAINT_CATEGORIES.contains(category))
            throw new ValidationException("category", "举报类别不合法");
        requireText(reason, 2000, "reason", "举报理由须为 1-2000 字");
        if (activityId != null && count("SELECT COUNT(*) FROM activity WHERE id=?", activityId) == 0)
            throw new IllegalStateException("活动不存在");
        if (subjectUserId != null) {
            if (count("SELECT COUNT(*) FROM app_user WHERE id=?", subjectUserId) == 0)
                throw new IllegalStateException("用户不存在");
            if (subjectUserId.longValue() == applicantId)
                throw new IllegalStateException("不能举报自己");
        }
        long complaintId = insertComplaint(applicantId, activityId, subjectUserId,
                category, reason, LocalDateTime.now());
        logAction(applicantId, "COMPLAINT_FILE", "COMPLAINT", complaintId, null, reason, null);
        return complaintRow(complaintId);
    }

    public List<Map<String, Object>> listComplaints(Long applicantId, String state, int limit) {
        String sql = COMPLAINT_SELECT;
        List<Object> args = new ArrayList<>();
        List<String> where = new ArrayList<>();
        if (applicantId != null) {
            where.add("c.applicant_id=?");
            args.add(applicantId);
        }
        if (state != null && !state.isBlank()) {
            where.add("c.state=?");
            args.add(state);
        }
        if (!where.isEmpty()) sql += " WHERE " + String.join(" AND ", where);
        sql += " ORDER BY c.id DESC LIMIT ?";
        args.add(Math.max(1, limit));
        var rows = jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) out.add(complaintMap(row));
        return out;
    }

    public Map<String, Object> getComplaint(long complaintId) {
        return complaintRow(complaintId);
    }

    @Transactional
    public Map<String, Object> handleComplaint(long actorId, long complaintId,
                                               String outcome, String resultText) {
        requireAdmin(actorId);
        if (outcome == null || !COMPLAINT_OUTCOMES.contains(outcome))
            throw new ValidationException("outcome", "处理结果不合法");
        requireText(resultText, 1000, "result", "处理结论须为 1-1000 字");
        var rows = jdbc.queryForList("SELECT * FROM complaint WHERE id=?", complaintId);
        if (rows.isEmpty()) throw new IllegalStateException("举报不存在");
        var complaint = rows.get(0);
        if (!"PENDING".equals(complaint.get("state")))
            throw new IllegalStateException("该举报已处理");
        Long activityId = nullableLong(complaint.get("activity_id"));
        Long subjectUserId = nullableLong(complaint.get("subject_user_id"));
        LocalDateTime now = LocalDateTime.now();
        long decisionId = insertDecision(actorId, null, "COMPLAINT", subjectUserId, activityId,
                null, null, "举报处理", resultText, null, null, null, null);
        jdbc.update("UPDATE complaint SET handler_id=?, decision_id=?, state=?, handled_at=?, " +
                        "updated_at=? WHERE id=?",
                actorId, decisionId, outcome, ts(now), ts(now), complaintId);
        Map<String, Object> updated = complaintRow(complaintId);
        String target = activityId != null
                ? "活动「" + updated.get("activity_title") + "」"
                : "用户「" + updated.get("subject_nickname") + "」";
        notify(((Number) complaint.get("applicant_id")).longValue(), activityId,
                "你对" + target + "的举报已处理：" + resultText,
                "notify:complaint:" + complaintId + ":handled");
        logAction(actorId, "COMPLAINT_HANDLE", "COMPLAINT", complaintId, decisionId,
                resultText, null);
        return updated;
    }

    // ---- 申诉与复核 ----

    private Map<String, Object> decisionMap(Map<String, Object> row) {
        if (row == null) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", row.get("id"));
        m.put("actor_id", row.get("actor_id"));
        m.put("decision_type", row.get("decision_type"));
        m.put("subject_user_id", row.get("subject_user_id"));
        m.put("activity_id", row.get("activity_id"));
        m.put("attendance_revision_id", row.get("attendance_revision_id"));
        m.put("reason", row.get("reason"));
        m.put("result", row.get("result"));
        m.put("decided_at", iso(row.get("decided_at")));
        m.put("expires_at", iso(row.get("expires_at")));
        m.put("available_at", iso(row.get("available_at")));
        m.put("appeal_until", iso(row.get("appeal_until")));
        return m;
    }

    private Map<String, Object> decisionRow(long decisionId) {
        var rows = jdbc.queryForList(
                "SELECT * FROM governance_decision WHERE id=?", decisionId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    @Transactional
    public Map<String, Object> ensureAttendanceDecision(long attendanceId) {
        var attRows = jdbc.queryForList("SELECT * FROM attendance WHERE id=?", attendanceId);
        if (attRows.isEmpty()) throw new IllegalStateException("出勤记录不存在");
        var att = attRows.get(0);
        long version = ((Number) att.get("version")).longValue();
        var revRows = jdbc.queryForList(
                "SELECT * FROM attendance_revision WHERE attendance_id=? AND version=?",
                attendanceId, version);
        if (revRows.isEmpty()) throw new IllegalStateException("出勤修订记录不存在");
        var rev = revRows.get(0);
        long revisionId = ((Number) rev.get("id")).longValue();
        var existing = jdbc.queryForList(
                "SELECT * FROM governance_decision WHERE attendance_revision_id=? " +
                        "AND decision_type='ATTENDANCE' ORDER BY id LIMIT 1",
                revisionId);
        if (!existing.isEmpty()) return decisionMap(existing.get(0));
        Long actorId = nullableLong(rev.get("actor_id"));
        long subjectUserId = ((Number) att.get("user_id")).longValue();
        long activityId = ((Number) att.get("activity_id")).longValue();
        String reason = rev.get("reason") == null ? "" : (String) rev.get("reason");
        String result = rev.get("result") == null ? "" : (String) rev.get("result");
        LocalDateTime availableAt = rev.get("available_at") == null
                ? null : asLocalDateTime(rev.get("available_at"));
        LocalDateTime appealUntil = rev.get("appeal_until") == null
                ? null : asLocalDateTime(rev.get("appeal_until"));
        long decisionId = insertDecision(actorId, null, "ATTENDANCE", subjectUserId, activityId,
                null, revisionId, reason, result, null, availableAt, appealUntil, null);
        return decisionMap(jdbc.queryForMap(
                "SELECT * FROM governance_decision WHERE id=?", decisionId));
    }

    private Map<String, Object> duplicateAppeal(long appealId) {
        Map<String, Object> row = getAppeal(appealId);
        if (row == null) row = new LinkedHashMap<>();
        row.put("duplicate", true);
        return row;
    }

    private Long appealIdByDecision(long decisionId) {
        var rows = jdbc.queryForList(
                "SELECT id FROM appeal WHERE decision_id=? ORDER BY id LIMIT 1", decisionId);
        return rows.isEmpty() ? null : ((Number) rows.get(0).get("id")).longValue();
    }

    private Long appealIdByComplaint(long complaintId) {
        var rows = jdbc.queryForList(
                "SELECT id FROM appeal WHERE complaint_id=? ORDER BY id LIMIT 1", complaintId);
        return rows.isEmpty() ? null : ((Number) rows.get(0).get("id")).longValue();
    }

    @Transactional
    public Map<String, Object> fileAppeal(long applicantId, Long attendanceId,
                                          Long decisionId, Long complaintId, String reason) {
        requireText(reason, 2000, "reason", "申诉理由须为 1-2000 字");
        LocalDateTime now = LocalDateTime.now();
        if (attendanceId != null) {
            var attRows = jdbc.queryForList(
                    "SELECT * FROM attendance WHERE id=? FOR UPDATE", attendanceId);
            if (attRows.isEmpty()) throw new IllegalStateException("出勤记录不存在");
            var att = attRows.get(0);
            long ownerId = ((Number) att.get("user_id")).longValue();
            if (ownerId != applicantId)
                throw new IllegalStateException("只能申诉本人的出勤决定");
            if (att.get("finalized_at") == null)
                throw new IllegalStateException("出勤尚未定版，不能申诉");
            long version = ((Number) att.get("version")).longValue();
            var revRows = jdbc.queryForList(
                    "SELECT * FROM attendance_revision WHERE attendance_id=? AND version=?",
                    attendanceId, version);
            if (revRows.isEmpty())
                throw new IllegalStateException("出勤修订记录不存在");
            Object appealUntilRaw = revRows.get(0).get("appeal_until");
            if (appealUntilRaw == null
                    || now.isAfter(asLocalDateTime(appealUntilRaw)))
                throw new IllegalStateException("申诉期已届满");
            Map<String, Object> decision = ensureAttendanceDecision(attendanceId);
            long targetDecisionId = ((Number) decision.get("id")).longValue();
            Long existingId = appealIdByDecision(targetDecisionId);
            if (existingId != null) return duplicateAppeal(existingId);
            long appealId = insertAppeal(applicantId, targetDecisionId, null, reason, now);
            logAction(applicantId, "APPEAL_FILE", "APPEAL", appealId, targetDecisionId,
                    reason, null);
            return getAppeal(appealId);
        }
        if (complaintId != null) {
            var rows = jdbc.queryForList("SELECT * FROM complaint WHERE id=?", complaintId);
            if (rows.isEmpty()) throw new IllegalStateException("举报不存在");
            var complaint = rows.get(0);
            if (((Number) complaint.get("applicant_id")).longValue() != applicantId)
                throw new IllegalStateException("只能申诉本人的举报");
            Long linkedDecisionId = nullableLong(complaint.get("decision_id"));
            if (linkedDecisionId == null)
                throw new IllegalStateException("该举报尚未处理，不能申诉");
            if (decisionId == null || decisionId.longValue() != linkedDecisionId.longValue())
                throw new IllegalStateException("处理决定不匹配");
            Long existingId = appealIdByComplaint(complaintId);
            if (existingId == null) existingId = appealIdByDecision(linkedDecisionId);
            if (existingId != null) return duplicateAppeal(existingId);
            long appealId = insertAppeal(applicantId, linkedDecisionId, complaintId, reason, now);
            logAction(applicantId, "APPEAL_FILE", "APPEAL", appealId, linkedDecisionId,
                    reason, null);
            return getAppeal(appealId);
        }
        if (decisionId == null)
            throw new ValidationException("target", "请选择申诉对象");
        var rows = jdbc.queryForList(
                "SELECT * FROM governance_decision WHERE id=?", decisionId);
        if (rows.isEmpty()) throw new IllegalStateException("决定不存在");
        Long subjectUserId = nullableLong(rows.get(0).get("subject_user_id"));
        if (subjectUserId == null || subjectUserId.longValue() != applicantId)
            throw new IllegalStateException("只能申诉本人的决定");
        Long existingId = appealIdByDecision(decisionId);
        if (existingId != null) return duplicateAppeal(existingId);
        long appealId = insertAppeal(applicantId, decisionId, null, reason, now);
        logAction(applicantId, "APPEAL_FILE", "APPEAL", appealId, decisionId, reason, null);
        return getAppeal(appealId);
    }

    private Map<String, Object> appealMap(Map<String, Object> row) {
        if (row == null) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", row.get("id"));
        m.put("applicant_id", row.get("applicant_id"));
        m.put("applicant_nickname", row.get("applicant_nickname"));
        m.put("decision_id", row.get("decision_id"));
        m.put("decision_type", row.get("decision_type"));
        m.put("complaint_id", row.get("complaint_id"));
        m.put("reviewer_id", row.get("reviewer_id"));
        m.put("result_decision_id", row.get("result_decision_id"));
        m.put("reason", row.get("reason"));
        m.put("state", row.get("state"));
        m.put("submitted_at", iso(row.get("submitted_at")));
        m.put("reviewed_at", iso(row.get("reviewed_at")));
        m.put("attendance_id", row.get("attendance_id"));
        m.put("activity_id", row.get("activity_id"));
        m.put("subject_user_id", row.get("subject_user_id"));
        return m;
    }

    public List<Map<String, Object>> listAppeals(Long applicantId, String state, int limit) {
        String sql = APPEAL_SELECT;
        List<Object> args = new ArrayList<>();
        List<String> where = new ArrayList<>();
        if (applicantId != null) {
            where.add("ap.applicant_id=?");
            args.add(applicantId);
        }
        if (state != null && !state.isBlank()) {
            where.add("ap.state=?");
            args.add(state);
        }
        if (!where.isEmpty()) sql += " WHERE " + String.join(" AND ", where);
        sql += " ORDER BY ap.id DESC LIMIT ?";
        args.add(Math.max(1, limit));
        var rows = jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) out.add(appealMap(row));
        return out;
    }

    public Map<String, Object> getAppeal(long appealId) {
        var rows = jdbc.queryForList(APPEAL_SELECT + " WHERE ap.id=?", appealId);
        return rows.isEmpty() ? null : appealMap(rows.get(0));
    }

    @Transactional
    public Map<String, Object> reviewAppeal(long reviewerId, long appealId, String outcome,
                                            String newResult, String resultText) {
        requireAdmin(reviewerId);
        if (outcome == null || !REVIEW_APPEAL_OUTCOMES.contains(outcome))
            throw new ValidationException("outcome", "复核结果不合法");
        var appealRows = jdbc.queryForList("SELECT * FROM appeal WHERE id=?", appealId);
        if (appealRows.isEmpty()) throw new IllegalStateException("申诉不存在");
        var appeal = appealRows.get(0);
        if (!"PENDING".equals(appeal.get("state")))
            throw new IllegalStateException("该申诉已复核");
        long originalDecisionId = ((Number) appeal.get("decision_id")).longValue();
        var originalDecision = decisionRow(originalDecisionId);
        if (originalDecision == null) throw new IllegalStateException("原决定不存在");
        Long originalActorId = nullableLong(originalDecision.get("actor_id"));
        if (originalActorId != null && originalActorId.longValue() == reviewerId)
            throw new IllegalStateException("复核人须独立于原处理人");
        if (((Number) appeal.get("applicant_id")).longValue() == reviewerId)
            throw new IllegalStateException("复核人不能是申诉人");

        String decisionType = (String) originalDecision.get("decision_type");
        Long subjectUserId = nullableLong(originalDecision.get("subject_user_id"));
        Long activityId = nullableLong(originalDecision.get("activity_id"));
        Long participationId = nullableLong(originalDecision.get("participation_id"));
        String appealReason = (String) appeal.get("reason");
        String text = (resultText == null || resultText.isBlank()) ? null : resultText;
        LocalDateTime now = LocalDateTime.now();
        long resultDecisionId;
        String appealState;
        String notifyText;

        if ("UPHOLD".equals(outcome)) {
            resultDecisionId = insertDecision(reviewerId, originalDecisionId, "REVIEW",
                    subjectUserId, activityId, participationId,
                    nullableLong(originalDecision.get("attendance_revision_id")),
                    "申诉复核", text == null ? "维持原决定" : text,
                    null, null, null, null);
            appealState = "UPHELD";
            notifyText = "你的申诉已复核：维持原决定。";
        } else if ("ATTENDANCE".equals(decisionType)) {
            if (newResult == null || !ATTENDANCE_RESULTS.contains(newResult))
                throw new ValidationException("new_result", "更正结果不合法");
            Long revisionId = nullableLong(originalDecision.get("attendance_revision_id"));
            if (revisionId == null)
                throw new IllegalStateException("出勤修订记录不存在");
            var revRows = jdbc.queryForList(
                    "SELECT attendance_id FROM attendance_revision WHERE id=?", revisionId);
            if (revRows.isEmpty())
                throw new IllegalStateException("出勤修订记录不存在");
            long attendanceId = ((Number) revRows.get(0).get("attendance_id")).longValue();
            String correctReason = "申诉复核更正：" + (text == null ? appealReason : text);
            Map<String, Object> corrected = attendanceService.adminCorrect(
                    attendanceId, reviewerId, newResult, correctReason);
            Long newRevisionId = nullableLong(corrected.get("new_revision_id"));
            resultDecisionId = insertDecision(reviewerId, originalDecisionId, "REVIEW",
                    subjectUserId, activityId, participationId, newRevisionId,
                    "申诉复核", "更正为 " + newResult + (text == null ? "" : "：" + text),
                    null, null, null, null);
            appealState = "CORRECTED";
            notifyText = "你的申诉已复核：已更正为 " + newResult + "。";
        } else if ("COMPLAINT".equals(decisionType)) {
            resultDecisionId = insertDecision(reviewerId, originalDecisionId, "REVIEW",
                    subjectUserId, activityId, participationId, null,
                    "申诉复核", text == null ? "撤销原处理结论" : text,
                    null, null, null, null);
            Long complaintId = nullableLong(appeal.get("complaint_id"));
            Map<String, Object> complaint = null;
            if (complaintId != null) {
                var rows = jdbc.queryForList("SELECT * FROM complaint WHERE id=?", complaintId);
                if (!rows.isEmpty()) complaint = rows.get(0);
            }
            if (complaint == null) {
                var rows = jdbc.queryForList(
                        "SELECT * FROM complaint WHERE decision_id=? ORDER BY id DESC LIMIT 1",
                        originalDecisionId);
                if (!rows.isEmpty()) complaint = rows.get(0);
            }
            if (complaint == null) throw new IllegalStateException("原举报不存在");
            String newState = "RESOLVED".equals(complaint.get("state")) ? "DISMISSED" : "RESOLVED";
            jdbc.update("UPDATE complaint SET state=?, decision_id=?, updated_at=? WHERE id=?",
                    newState, resultDecisionId, ts(now), complaint.get("id"));
            appealState = "OVERTURNED";
            notifyText = "你的申诉已复核：已撤销原处理。";
        } else {
            throw new IllegalStateException("该类决定暂不支持更正，请维持或走对应业务通道");
        }

        jdbc.update("UPDATE appeal SET reviewer_id=?, result_decision_id=?, state=?, " +
                        "reviewed_at=?, updated_at=? WHERE id=?",
                reviewerId, resultDecisionId, appealState, ts(now), ts(now), appealId);
        notify(((Number) appeal.get("applicant_id")).longValue(), activityId,
                notifyText, "notify:appeal:" + appealId + ":reviewed");
        logAction(reviewerId, "APPEAL_REVIEW", "APPEAL", appealId, resultDecisionId,
                text, outcome);
        return getAppeal(appealId);
    }

    // ---- 找回 / 恢复 ----

    @Transactional
    public Map<String, Object> submitRecovery(String account, Integer requestType,
                                              String reason, String contact) {
        if (account == null || account.isBlank())
            throw new ValidationException("account", "请填写账号");
        if (requestType == null || (requestType != 1 && requestType != 2))
            throw new ValidationException("request_type", "申请类型不合法");
        requireText(reason, 2000, "reason", "申请理由须为 1-2000 字");
        if (contact != null && contact.codePointCount(0, contact.length()) > 100)
            throw new ValidationException("contact", "联系方式不能超过 100 字");
        var userRows = jdbc.queryForList(
                "SELECT id FROM app_user WHERE account=?", account);
        if (userRows.isEmpty()) throw new IllegalStateException("账号不存在");
        long applicantId = ((Number) userRows.get(0).get("id")).longValue();
        Long decisionId = null;
        if (requestType == 2) {
            var banRows = jdbc.queryForList(
                    "SELECT decision_id FROM user_ban WHERE user_id=? AND lifted_at IS NULL " +
                            "ORDER BY banned_at DESC LIMIT 1", applicantId);
            if (banRows.isEmpty())
                throw new IllegalStateException("该账号未被封禁，无需封禁复核");
            decisionId = ((Number) banRows.get(0).get("decision_id")).longValue();
            // 去重：已有待审找回申请或同一决定的待审申诉都返回原案（不重发查询凭据）。
            var existingReq = jdbc.queryForList(
                    "SELECT id, state FROM recovery_request WHERE applicant_id=? AND request_type=2 " +
                            "AND state='PENDING' ORDER BY id DESC LIMIT 1", applicantId);
            if (!existingReq.isEmpty()) {
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("id", existingReq.get(0).get("id"));
                out.put("duplicate", true);
                out.put("state", existingReq.get(0).get("state"));
                out.put("query_token", null);
                out.put("request_type", 2);
                return out;
            }
            var existingAppeal = jdbc.queryForList(
                    "SELECT id, state FROM appeal WHERE decision_id=? AND state='PENDING' " +
                            "ORDER BY id DESC LIMIT 1", decisionId);
            if (!existingAppeal.isEmpty()) {
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("id", existingAppeal.get(0).get("id"));
                out.put("duplicate", true);
                out.put("state", existingAppeal.get(0).get("state"));
                out.put("query_token", null);
                out.put("request_type", 2);
                out.put("case", "appeal");
                return out;
            }
        }
        String queryToken = newToken();
        String queryHash = sha256(queryToken);
        long requestId = insertRecoveryRequest(applicantId, requestType, decisionId, reason,
                contact, queryHash, LocalDateTime.now());
        logAction(applicantId, "RECOVERY_SUBMIT", "RECOVERY", requestId, decisionId, reason, null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", requestId);
        out.put("query_token", queryToken);
        out.put("request_type", requestType);
        out.put("state", "PENDING");
        return out;
    }

    public Map<String, Object> recoveryStatus(long requestId, String queryToken) {
        var rows = jdbc.queryForList(
                "SELECT * FROM recovery_request WHERE id=?", requestId);
        if (rows.isEmpty() || queryToken == null || queryToken.isBlank())
            throw new IllegalStateException("查询凭据不正确");
        var row = rows.get(0);
        String storedHash = (String) row.get("query_hash");
        boolean matches = storedHash != null && MessageDigest.isEqual(
                sha256(queryToken).getBytes(StandardCharsets.UTF_8),
                storedHash.getBytes(StandardCharsets.UTF_8));
        if (!matches) throw new IllegalStateException("查询凭据不正确");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("id"));
        out.put("request_type", row.get("request_type"));
        out.put("state", row.get("state"));
        out.put("applied_at", iso(row.get("applied_at")));
        out.put("reviewed_at", iso(row.get("reviewed_at")));
        out.put("recovered_at", iso(row.get("recovered_at")));
        out.put("has_reset_credential", row.get("reset_hash") != null);
        out.put("reset_expires_at", iso(row.get("reset_expires_at")));
        return out;
    }

    public List<Map<String, Object>> listRecovery(String state, int limit) {
        String sql = "SELECT r.*, u.account, u.nickname FROM recovery_request r " +
                "JOIN app_user u ON u.id=r.applicant_id";
        List<Object> args = new ArrayList<>();
        if (state != null && !state.isBlank()) {
            sql += " WHERE r.state=?";
            args.add(state);
        }
        sql += " ORDER BY r.id DESC LIMIT ?";
        args.add(Math.max(1, limit));
        var rows = jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", row.get("id"));
            m.put("applicant_id", row.get("applicant_id"));
            m.put("account", row.get("account"));
            m.put("nickname", row.get("nickname"));
            m.put("request_type", row.get("request_type"));
            m.put("decision_id", row.get("decision_id"));
            m.put("reviewer_id", row.get("reviewer_id"));
            m.put("state", row.get("state"));
            m.put("reason", row.get("reason"));
            m.put("contact", row.get("contact"));
            m.put("applied_at", iso(row.get("applied_at")));
            m.put("reviewed_at", iso(row.get("reviewed_at")));
            m.put("recovered_at", iso(row.get("recovered_at")));
            out.add(m);
        }
        return out;
    }

    @Transactional
    public Map<String, Object> reviewRecovery(long reviewerId, long requestId,
                                              String outcome, String note) {
        requireAdmin(reviewerId);
        if (outcome == null || !Set.of("APPROVE", "REJECT").contains(outcome))
            throw new ValidationException("outcome", "审核结果不合法");
        var rows = jdbc.queryForList(
                "SELECT * FROM recovery_request WHERE id=?", requestId);
        if (rows.isEmpty()) throw new IllegalStateException("申请不存在");
        var req = rows.get(0);
        if (!"PENDING".equals(req.get("state")))
            throw new IllegalStateException("该申请已审核");
        long applicantId = ((Number) req.get("applicant_id")).longValue();
        int requestType = ((Number) req.get("request_type")).intValue();
        Long originalDecisionId = nullableLong(req.get("decision_id"));
        LocalDateTime now = LocalDateTime.now();
        String noteText = (note == null || note.isBlank()) ? null : note;
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", requestId);

        if ("REJECT".equals(outcome)) {
            long decisionId = insertDecision(reviewerId, originalDecisionId, "RECOVERY",
                    applicantId, null, null, null, "账号恢复审核",
                    "驳回" + (noteText == null ? "" : noteText),
                    null, null, null, null);
            jdbc.update("UPDATE recovery_request SET state='REJECTED', reviewer_id=?, " +
                            "reviewed_at=?, result_decision_id=?, updated_at=? WHERE id=?",
                    reviewerId, ts(now), decisionId, ts(now), requestId);
            logAction(reviewerId, "RECOVERY_REVIEW", "RECOVERY", requestId, decisionId,
                    noteText, null);
            out.put("state", "REJECTED");
            return out;
        }

        if (requestType == 1) {
            String resetToken = newToken();
            long decisionId = insertDecision(reviewerId, originalDecisionId, "RECOVERY",
                    applicantId, null, null, null, "账号恢复审核", "批准，已签发重置凭据",
                    null, null, null, null);
            LocalDateTime resetExpiresAt = now.plusMinutes(resetMinutes);
            jdbc.update("UPDATE recovery_request SET state='APPROVED', reviewer_id=?, " +
                            "reviewed_at=?, result_decision_id=?, reset_hash=?, reset_expires_at=?, " +
                            "updated_at=? WHERE id=?",
                    reviewerId, ts(now), decisionId, sha256(resetToken), ts(resetExpiresAt),
                    ts(now), requestId);
            logAction(reviewerId, "RECOVERY_REVIEW", "RECOVERY", requestId, decisionId,
                    noteText, null);
            out.put("state", "APPROVED");
            out.put("reset_credential", resetToken);
            out.put("reset_expires_at", iso(resetExpiresAt));
            return out;
        }

        // type=2：封禁复核。复核人须独立于原封禁处理人。
        if (originalDecisionId == null)
            throw new IllegalStateException("原封禁决定不存在");
        var banDecision = decisionRow(originalDecisionId);
        if (banDecision == null) throw new IllegalStateException("原封禁决定不存在");
        Long originalActorId = nullableLong(banDecision.get("actor_id"));
        if (originalActorId != null && originalActorId.longValue() == reviewerId)
            throw new IllegalStateException("复核人须独立于原处理人");
        long decisionId = insertDecision(reviewerId, originalDecisionId, "REVIEW",
                applicantId, null, null, null, "封禁复核", "复核通过，解除封禁",
                null, null, null, null);
        jdbc.update("UPDATE user_ban SET lifted_at=?, lifted_by=?, lift_decision_id=?, updated_at=? " +
                        "WHERE user_id=? AND lifted_at IS NULL",
                ts(now), reviewerId, decisionId, ts(now), applicantId);
        jdbc.update("UPDATE recovery_request SET state='APPROVED', reviewer_id=?, reviewed_at=?, " +
                        "result_decision_id=?, updated_at=? WHERE id=?",
                reviewerId, ts(now), decisionId, ts(now), requestId);
        notify(applicantId, null, "你的封禁复核已通过，账号封禁已解除。",
                "notify:recovery:" + requestId + ":approved");
        logAction(reviewerId, "RECOVERY_REVIEW", "RECOVERY", requestId, decisionId,
                noteText, null);
        out.put("state", "APPROVED");
        return out;
    }

    @Transactional
    public Map<String, Object> resetPasswordWithCredential(String credential, String newPassword) {
        if (credential == null || credential.isBlank())
            throw new IllegalStateException("重置凭据无效或已使用");
        var rows = jdbc.queryForList(
                "SELECT r.*, u.account FROM recovery_request r JOIN app_user u ON u.id=r.applicant_id " +
                        "WHERE r.reset_hash=? AND r.state='APPROVED' AND r.request_type=1",
                sha256(credential));
        if (rows.isEmpty()) throw new IllegalStateException("重置凭据无效或已使用");
        var req = rows.get(0);
        LocalDateTime now = LocalDateTime.now();
        Object expiresRaw = req.get("reset_expires_at");
        if (expiresRaw == null || asLocalDateTime(expiresRaw).isBefore(now))
            throw new IllegalStateException("重置凭据已过期");
        String account = (String) req.get("account");
        boolean demoAccount = account != null
                && account.matches("^(demo(0[1-9]|1[0-9]|20)|organizer|temp0[1-3]|admin2?)$");
        if (newPassword == null || newPassword.isBlank())
            throw new IllegalStateException("新密码须为 8–64 位，且含字母与数字");
        if (!demoAccount && (newPassword.length() < 8 || newPassword.length() > 64
                || newPassword.chars().noneMatch(Character::isLetter)
                || newPassword.chars().noneMatch(Character::isDigit)))
            throw new IllegalStateException("新密码须为 8–64 位，且含字母与数字");
        long applicantId = ((Number) req.get("applicant_id")).longValue();
        long requestId = ((Number) req.get("id")).longValue();
        jdbc.update("UPDATE app_user SET password_hash=? WHERE id=?",
                AuthService.hash(newPassword), applicantId);
        jdbc.update("UPDATE recovery_request SET state='COMPLETED', recovered_at=?, reset_hash=NULL, " +
                        "updated_at=? WHERE id=?",
                ts(now), ts(now), requestId);
        auth.revokeSessionsForUser(applicantId);
        logAction(applicantId, "RECOVERY_RESET", "RECOVERY", requestId, null,
                "凭据重置密码", null);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        return out;
    }

    // ---- 信用审查消费 ----

    private Map<String, Object> creditReviewMap(Map<String, Object> row) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", row.get("id"));
        m.put("user_id", row.get("user_id"));
        m.put("nickname", row.get("nickname"));
        m.put("trigger_attendance_id", row.get("trigger_attendance_id"));
        m.put("absence_count", row.get("absence_count"));
        m.put("window_start", iso(row.get("window_start")));
        m.put("window_end", iso(row.get("window_end")));
        m.put("status", row.get("status"));
        m.put("created_at", iso(row.get("created_at")));
        return m;
    }

    public List<Map<String, Object>> listCreditReviews(String state, int limit) {
        String sql = "SELECT cr.*, u.nickname FROM credit_review cr " +
                "JOIN app_user u ON u.id=cr.user_id";
        List<Object> args = new ArrayList<>();
        if (state != null && !state.isBlank()) {
            sql += " WHERE cr.status=?";
            args.add(state);
        }
        sql += " ORDER BY cr.id DESC LIMIT ?";
        args.add(Math.max(1, limit));
        var rows = jdbc.queryForList(sql, args.toArray());
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) out.add(creditReviewMap(row));
        return out;
    }

    @Transactional
    public Map<String, Object> handleCreditReview(long actorId, long reviewId,
                                                  String outcome, String note) {
        requireAdmin(actorId);
        if (outcome == null || !Set.of("REVIEWED", "DISMISSED").contains(outcome))
            throw new ValidationException("outcome", "处理结果不合法");
        var rows = jdbc.queryForList("SELECT status FROM credit_review WHERE id=?", reviewId);
        if (rows.isEmpty()) throw new IllegalStateException("审查记录不存在");
        if (!"PENDING".equals(rows.get(0).get("status")))
            throw new IllegalStateException("该审查记录已处理");
        jdbc.update("UPDATE credit_review SET status=? WHERE id=?", outcome, reviewId);
        logAction(actorId, "CREDIT_REVIEW_HANDLE", "CREDIT_REVIEW", reviewId, null, note, null);
        var updated = jdbc.queryForList(
                "SELECT cr.*, u.nickname FROM credit_review cr JOIN app_user u ON u.id=cr.user_id " +
                        "WHERE cr.id=?", reviewId);
        return creditReviewMap(updated.get(0));
    }
}
