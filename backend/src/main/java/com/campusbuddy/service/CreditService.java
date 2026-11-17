package com.campusbuddy.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.*;

/**
 * 阶段三 CEM-10（2026-11-15）：信用结算、事实更正重算与缺席审查扫描。
 *
 * 口径（见 phase3/specs/spec-backend.md）：
 * - 信用初始 100、范围 0–100；到场 +2、核实缺席 −10、豁免 / 未核实 0。
 * - 当前分是可重建投影，不落用户表：按事实时间序列（活动结束时间、活动 id、
 *   参与 id）升序从 100 起逐笔钳制重放。
 * - 事实顺序固定为活动 end_time → activity_id → participation_id；结算与重算共用
 *   同一事实视图，保证两处重放结果一致。
 * - 每份出勤事实版本至多结算一次（UNIQUE(attendance_id, fact_version)）；事实更正
 *   后由重算更新同一行，credit_recalc_history 只记前后快照，不维护第二套当前分。
 * - 双库：构造时检测数据库产品名并缓存，冲突忽略按 MySQL / PostgreSQL 两种方言
 *   分别写入（与 AttendanceService 同做法）。
 */
@Service
public class CreditService {
    /** 信用初始分与取值范围（SDD CEM-10）。 */
    private static final int INITIAL = 100;
    /** 近 30 日累计 3 次核实缺席触发管理员审查。 */
    private static final int REVIEW_DAYS = 30;
    private static final int REVIEW_THRESHOLD = 3;

    /** 结算与重算共用的事实视图：已结算流水 + 出勤行当前事实。 */
    private static final String FACT_SQL =
            "SELECT e.id AS entry_id, e.attendance_id, e.fact_version, e.fact_result, e.delta, " +
            "e.score_before, e.score_after, e.fact_end_time, a.result AS cur_result, " +
            "a.version AS cur_version, a.activity_id, a.participation_id " +
            "FROM credit_entry e JOIN attendance a ON a.id = e.attendance_id " +
            "WHERE e.user_id = ?";

    /** 事实序列顺序：活动结束时间 → 活动 id → 参与 id。 */
    private static final Comparator<Fact> FACT_ORDER = Comparator
            .<Fact, LocalDateTime>comparing(Fact::factEndTime)
            .thenComparingLong(Fact::activityId)
            .thenComparingLong(Fact::participationId);

    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final long appealMinutes;
    /** 逐项独立事务：结算 / 重算各自包裹，单条失败不影响其余条目。 */
    private final TransactionTemplate tx;
    /** 双库分支：与 AttendanceService.detectMysql 同口径，启动时判定一次并缓存。 */
    private final boolean mysql;

    public CreditService(JdbcTemplate jdbc, PlatformTransactionManager tm, ObjectMapper mapper,
                         @Value("${app.credit.appeal-minutes}") long appealMinutes) {
        this.jdbc = jdbc;
        this.mapper = mapper;
        this.appealMinutes = appealMinutes;
        this.tx = new TransactionTemplate(tm);
        this.mysql = detectMysql(jdbc);
    }

    /** 与 AttendanceService.detectMysql 同实现（规格要求照抄该私有静态方法）。 */
    private static boolean detectMysql(JdbcTemplate jdbc) {
        try (var con = jdbc.getDataSource().getConnection()) {
            return con.getMetaData().getDatabaseProductName().toLowerCase().contains("mysql");
        } catch (Exception e) {
            throw new IllegalStateException("无法识别数据库产品", e);
        }
    }

    /** 东八区墙钟 → JDBC Timestamp，不做时区换算（与 AttendanceService.ts 同口径）。 */
    private static Timestamp ts(LocalDateTime t) { return Timestamp.valueOf(t); }

    /** 与 AttendanceService.asLocalDateTime 同实现：MySQL 驱动返回 LocalDateTime、
     *  PostgreSQL 驱动返回 Timestamp，统一归一化，只做类型转换。 */
    private static LocalDateTime asLocalDateTime(Object v) {
        if (v instanceof LocalDateTime ldt) return ldt;
        if (v instanceof Timestamp t) return t.toLocalDateTime();
        if (v instanceof java.util.Date d) return new Timestamp(d.getTime()).toLocalDateTime();
        throw new IllegalStateException("无法识别的时间类型: " + v);
    }

    /** 时间字段统一输出 ISO 字符串（与 AttendanceService.iso 同口径）。 */
    private static String iso(Object v) { return v == null ? null : asLocalDateTime(v).toString(); }

    /** 出勤结论 → 信用增量：到场 +2、核实缺席 −10、豁免 / 未核实 0。 */
    static int deltaFor(String result) {
        if ("PRESENT".equals(result)) return 2;
        if ("ABSENT_VERIFIED".equals(result)) return -10;
        return 0;
    }

    /** 逐步钳制在 0–100。 */
    private static int clamp(int score) { return Math.min(100, Math.max(0, score)); }

    /** 结算与重算共用的事实视图行（排序后的内存视图）。 */
    private record Fact(Long entryId, long attendanceId, long factVersion, long curVersion,
                        String curResult, Integer delta, Integer scoreBefore, Integer scoreAfter,
                        LocalDateTime factEndTime, long activityId, long participationId) { }

    /** 取某用户全部已结算流水的事实视图。 */
    private List<Fact> factsOf(long userId) {
        var rows = jdbc.queryForList(FACT_SQL, userId);
        List<Fact> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            out.add(new Fact(
                    ((Number) row.get("entry_id")).longValue(),
                    ((Number) row.get("attendance_id")).longValue(),
                    ((Number) row.get("fact_version")).longValue(),
                    ((Number) row.get("cur_version")).longValue(),
                    (String) row.get("cur_result"),
                    row.get("delta") == null ? null : ((Number) row.get("delta")).intValue(),
                    row.get("score_before") == null ? null : ((Number) row.get("score_before")).intValue(),
                    row.get("score_after") == null ? null : ((Number) row.get("score_after")).intValue(),
                    asLocalDateTime(row.get("fact_end_time")),
                    ((Number) row.get("activity_id")).longValue(),
                    ((Number) row.get("participation_id")).longValue()));
        }
        return out;
    }

    /** ObjectMapper 序列化快照；失败即业务不可继续。 */
    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("信用快照序列化失败", e);
        }
    }

    /**
     * 结算单条出勤：资格为已定版、定版时间 + 申诉期已届满、该出勤尚无流水、
     * 且无未决争议。整条链路在事务内完成：锁用户行 → 锁出勤行 → 重核资格 →
     * 取用户全部已结算流水合并本条候选 → 从 100 重放 → 落账 / 修复链条。
     *
     * @return 是否在本轮完成结算（不满足资格返回 false，异常由调用方兜住）
     */
    public boolean settleOne(long attendanceId, LocalDateTime now) {
        return Boolean.TRUE.equals(tx.execute(status -> settleOneInTx(attendanceId, now)));
    }

    private boolean settleOneInTx(long attendanceId, LocalDateTime now) {
        // 1. 先查 attendance 取 user_id（不存在返回 false）。
        var who = jdbc.queryForList("SELECT user_id FROM attendance WHERE id=?", attendanceId);
        if (who.isEmpty()) return false;
        long userId = ((Number) who.get(0).get("user_id")).longValue();
        // 2. 锁用户行（用户级串行，避免与重算互相穿插），再锁出勤行并重读。
        jdbc.queryForList("SELECT id FROM app_user WHERE id=? FOR UPDATE", userId);
        var attRows = jdbc.queryForList("SELECT * FROM attendance WHERE id=? FOR UPDATE", attendanceId);
        if (attRows.isEmpty()) return false;
        Map<String, Object> att = attRows.get(0);
        // 3. 资格重核（锁内重核，避免截止时刻申诉与结算互相遗漏）。
        Object finalizedRaw = att.get("finalized_at");
        if (finalizedRaw == null) return false;
        if (asLocalDateTime(finalizedRaw).plusMinutes(appealMinutes).isAfter(now)) return false;
        Integer settled = jdbc.queryForObject(
                "SELECT COUNT(*) FROM credit_entry WHERE attendance_id=?", Integer.class, attendanceId);
        if (settled != null && settled > 0) return false;
        if (hasUnresolvedDispute(att)) return false;
        // 4. 取该用户全部已结算流水 + 本条候选，按事实序列合并排序后从 100 重放。
        long activityId = ((Number) att.get("activity_id")).longValue();
        long participationId = ((Number) att.get("participation_id")).longValue();
        String curResult = (String) att.get("result");
        long curVersion = ((Number) att.get("version")).longValue();
        var actRows = jdbc.queryForList("SELECT end_time FROM activity WHERE id=?", activityId);
        LocalDateTime endTime = asLocalDateTime(actRows.get(0).get("end_time"));
        List<Fact> facts = factsOf(userId);
        facts.add(new Fact(null, attendanceId, curVersion, curVersion, curResult, null, null, null,
                endTime, activityId, participationId));
        facts.sort(FACT_ORDER);
        int score = INITIAL;
        for (Fact f : facts) {
            int d = deltaFor(f.curResult());
            int before = score;
            score = clamp(score + d);
            if (f.entryId() == null) {
                // 5a. 候选条落账：UNIQUE(attendance_id, fact_version) 保证每份事实只结算一次。
                jdbc.update("INSERT INTO credit_entry(user_id, attendance_id, fact_version, fact_result, " +
                                "activity_id, participation_id, fact_end_time, delta, score_before, " +
                                "score_after, settled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        userId, attendanceId, f.factVersion(), f.curResult(), f.activityId(),
                        f.participationId(), ts(f.factEndTime()), d, before, score, ts(now));
            } else if (f.scoreBefore() == null || f.scoreBefore().intValue() != before
                    || f.scoreAfter() == null || f.scoreAfter().intValue() != score) {
                // 5b. 已有条只修复链条两列，不动 delta / fact_version（事实更正走 recalcUser）。
                jdbc.update("UPDATE credit_entry SET score_before=?, score_after=?, updated_at=? WHERE id=?",
                        before, score, ts(now), f.entryId());
            }
        }
        return true;
    }

    /**
     * 事实更正后按时间序列重放该用户全部流水：被更正事实的 delta 随当前结论变化，
     * 其余条 delta 不变、仅 before / after 可能平移；有变化时逐条更新并写入一条
     * 前后快照审计。
     *
     * @param sourceRevisionId 触发本次重算的修订行（可为空：修订行缺失时不阻断重算）
     * @return 是否有流水发生变化（无事可做返回 false）
     */
    public boolean recalcUser(long userId, Long sourceRevisionId) {
        return Boolean.TRUE.equals(tx.execute(status -> recalcUserInTx(userId, sourceRevisionId)));
    }

    private boolean recalcUserInTx(long userId, Long sourceRevisionId) {
        // 1. 锁用户行，与结算 / 其他重算串行。
        jdbc.queryForList("SELECT id FROM app_user WHERE id=? FOR UPDATE", userId);
        // 2. 取全部已结算流水，按事实序列重放（delta 一律按当前结论）。
        List<Fact> facts = factsOf(userId);
        facts.sort(FACT_ORDER);
        if (facts.isEmpty()) return false;
        int storedFinal = facts.get(facts.size() - 1).scoreAfter() == null
                ? INITIAL : facts.get(facts.size() - 1).scoreAfter();
        int score = INITIAL;
        List<Integer> changedIndexes = new ArrayList<>();
        List<int[]> replayed = new ArrayList<>(facts.size()); // {before, after, delta}
        for (int i = 0; i < facts.size(); i++) {
            Fact f = facts.get(i);
            int d = deltaFor(f.curResult());
            int before = score;
            score = clamp(score + d);
            replayed.add(new int[]{before, score, d});
            // 3. 任一字段与重放结果不一致即视为变化。
            if (f.factVersion() != f.curVersion()
                    || f.delta() == null || f.delta().intValue() != d
                    || f.scoreBefore() == null || f.scoreBefore().intValue() != before
                    || f.scoreAfter() == null || f.scoreAfter().intValue() != score) {
                changedIndexes.add(i);
            }
        }
        if (changedIndexes.isEmpty()) return false;
        // 4. before 快照（存量）→ 逐条更新 → after 快照（新值）。
        Map<String, Object> beforeSnapshot = new LinkedHashMap<>();
        beforeSnapshot.put("score", storedFinal);
        List<Map<String, Object>> beforeEntries = new ArrayList<>(changedIndexes.size());
        for (int idx : changedIndexes) {
            Fact f = facts.get(idx);
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("entry_id", f.entryId());
            e.put("attendance_id", f.attendanceId());
            e.put("fact_version", f.factVersion());
            e.put("delta", f.delta());
            e.put("score_before", f.scoreBefore());
            e.put("score_after", f.scoreAfter());
            beforeEntries.add(e);
        }
        beforeSnapshot.put("entries", beforeEntries);

        LocalDateTime now = LocalDateTime.now();
        List<Map<String, Object>> afterEntries = new ArrayList<>(changedIndexes.size());
        for (int idx : changedIndexes) {
            Fact f = facts.get(idx);
            int[] r = replayed.get(idx);
            jdbc.update("UPDATE credit_entry SET fact_version=?, fact_result=?, delta=?, score_before=?, " +
                            "score_after=?, updated_at=? WHERE id=?",
                    f.curVersion(), f.curResult(), r[2], r[0], r[1], ts(now), f.entryId());
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("entry_id", f.entryId());
            e.put("attendance_id", f.attendanceId());
            e.put("fact_version", f.curVersion());
            e.put("delta", r[2]);
            e.put("score_before", r[0]);
            e.put("score_after", r[1]);
            afterEntries.add(e);
        }
        Map<String, Object> afterSnapshot = new LinkedHashMap<>();
        afterSnapshot.put("score", score);
        afterSnapshot.put("entries", afterEntries);
        // 5. 只记前后快照，不维护第二套当前分。
        jdbc.update("INSERT INTO credit_recalc_history(user_id, source_revision_id, before_snapshot, " +
                        "after_snapshot) VALUES (?,?,?,?)",
                userId, sourceRevisionId, json(beforeSnapshot), json(afterSnapshot));
        return true;
    }

    /**
     * SweepService 每轮调用：结算 → 事实更正重算 → 缺席审查扫描。
     * 不加 @Transactional，逐项独立事务，单条失败留给下一轮重试。
     */
    public void settleSweep(LocalDateTime now) {
        // 1. 结算：定版时间 + 申诉期已届满的全体出勤。
        var settleIds = jdbc.queryForList(
                "SELECT id FROM attendance WHERE finalized_at IS NOT NULL AND finalized_at <= ? " +
                        "ORDER BY finalized_at, id",
                Long.class, ts(now.minusMinutes(appealMinutes)));
        for (Long id : settleIds) {
            try { settleOne(id, now); } catch (Exception e) { /* 下轮重试 */ }
        }
        // 2. 重算扫描：流水事实版本落后于出勤当前版本的条目，按用户分组。
        var stale = jdbc.queryForList(
                "SELECT e.user_id, e.attendance_id FROM credit_entry e " +
                        "JOIN attendance a ON a.id=e.attendance_id " +
                        "WHERE a.version <> e.fact_version ORDER BY e.user_id, e.attendance_id");
        Map<Long, Long> firstAttendance = new LinkedHashMap<>();
        for (var row : stale) {
            long uid = ((Number) row.get("user_id")).longValue();
            long aid = ((Number) row.get("attendance_id")).longValue();
            firstAttendance.putIfAbsent(uid, aid);
        }
        for (var entry : firstAttendance.entrySet()) {
            try {
                long userId = entry.getKey();
                long attendanceId = entry.getValue();
                // 每人取首条出勤的当前版本修订行作 sourceRevisionId。
                var rev = jdbc.queryForList(
                        "SELECT id FROM attendance_revision WHERE attendance_id=? " +
                                "AND version=(SELECT version FROM attendance WHERE id=?)",
                        Long.class, attendanceId, attendanceId);
                Long revId = rev.isEmpty() ? null : rev.get(0);
                recalcUser(userId, revId);
            } catch (Exception e) { /* 下轮重试 */ }
        }
        // 3. 审查扫描：近 30 日核实缺席按用户分组，≥3 条落一条待审查记录。
        var absRows = jdbc.queryForList(
                "SELECT att.user_id, att.id AS attendance_id, act.end_time AS end_time, " +
                        "att.activity_id, att.participation_id " +
                        "FROM attendance att JOIN activity act ON act.id=att.activity_id " +
                        "WHERE att.result='ABSENT_VERIFIED' AND att.finalized_at IS NOT NULL " +
                        "AND act.end_time >= ? " +
                        "ORDER BY att.user_id, act.end_time, att.activity_id, att.participation_id",
                ts(now.minusDays(REVIEW_DAYS)));
        // 按 (user_id, end_time, activity_id, participation_id) 排序后 Java 分组。
        Map<Long, List<Map<String, Object>>> groups = new LinkedHashMap<>();
        for (var row : absRows) {
            long uid = ((Number) row.get("user_id")).longValue();
            groups.computeIfAbsent(uid, k -> new ArrayList<>()).add(row);
        }
        for (var entry : groups.entrySet()) {
            List<Map<String, Object>> group = entry.getValue();
            if (group.size() < REVIEW_THRESHOLD) continue;
            long userId = entry.getKey();
            var trigger = group.get(group.size() - 1);
            long triggerId = ((Number) trigger.get("attendance_id")).longValue();
            LocalDateTime windowEnd = asLocalDateTime(trigger.get("end_time"));
            LocalDateTime windowStart = windowEnd.minusDays(REVIEW_DAYS);
            try {
                String sql = mysql
                        ? "INSERT IGNORE INTO credit_review(user_id, trigger_attendance_id, absence_count, " +
                                "window_start, window_end, status) VALUES (?,?,?,?,?, 'PENDING')"
                        : "INSERT INTO credit_review(user_id, trigger_attendance_id, absence_count, " +
                                "window_start, window_end, status) VALUES (?,?,?,?,?, 'PENDING') " +
                                "ON CONFLICT (user_id, trigger_attendance_id) DO NOTHING";
                jdbc.update(sql, userId, triggerId, group.size(), ts(windowStart), ts(windowEnd));
            } catch (Exception e) { /* 下轮重试 */ }
        }
    }

    /**
     * 是否存在未决争议：该出勤当前处理决定（governance_decision.attendance_revision_id）
     * 存在 PENDING 申诉时，保持待结算（SDD §6.11）。
     *
     * <p>阶段四 CEM-09（2026-11-15）已接入真实查询：按出勤 id 经
     * attendance_revision → governance_decision → appeal 反查未结申诉。
     * 结算在出勤行锁内重核本条件，避免截止时刻申诉与结算互相遗漏（SDD §6.11 末段）。
     */
    private boolean hasUnresolvedDispute(Map<String, Object> att) {
        long attendanceId = ((Number) att.get("id")).longValue();
        Integer n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM appeal a " +
                        "JOIN governance_decision d ON d.id = a.decision_id " +
                        "JOIN attendance_revision r ON r.id = d.attendance_revision_id " +
                        "WHERE r.attendance_id = ? AND a.state = 'PENDING'",
                Integer.class, attendanceId);
        return n != null && n > 0;
    }

    /** 当前信用分：序列序最后一条的 score_after；无流水为初始 100。 */
    public int currentScore(long userId) {
        var rows = jdbc.queryForList(
                "SELECT score_after FROM credit_entry WHERE user_id=? " +
                        "ORDER BY fact_end_time DESC, activity_id DESC, participation_id DESC LIMIT 1",
                userId);
        if (rows.isEmpty()) return INITIAL;
        return ((Number) rows.get(0).get("score_after")).intValue();
    }

    /** 本人信用流水（序列序倒序）；activity_title 供前端直接展示。 */
    public List<Map<String, Object>> listEntries(long userId) {
        var rows = jdbc.queryForList(
                "SELECT e.*, act.title AS activity_title FROM credit_entry e " +
                        "JOIN activity act ON act.id = e.activity_id WHERE e.user_id = ? " +
                        "ORDER BY e.fact_end_time DESC, e.activity_id DESC, e.participation_id DESC",
                userId);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (var row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", row.get("id"));
            m.put("attendance_id", row.get("attendance_id"));
            m.put("activity_id", row.get("activity_id"));
            m.put("activity_title", row.get("activity_title"));
            m.put("participation_id", row.get("participation_id"));
            m.put("fact_version", row.get("fact_version"));
            m.put("fact_result", row.get("fact_result"));
            m.put("delta", row.get("delta"));
            m.put("score_before", row.get("score_before"));
            m.put("score_after", row.get("score_after"));
            m.put("settled_at", iso(row.get("settled_at")));
            out.add(m);
        }
        return out;
    }
}
