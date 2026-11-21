package com.campusbuddy.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/** 定时任务：活动生命周期 + 候补超时扫描。重复执行幂等，重启后补扫。 */
@Service
public class SweepService {
    private static final Logger log = LoggerFactory.getLogger(SweepService.class);
    private final JdbcTemplate jdbc;
    private final BuddyService buddy;
    /** 阶段二 CEM-08：出勤快照补建与核对期届满定版。 */
    private final AttendanceService attendance;
    /** 阶段三 CEM-10：信用结算、事实更正重算与缺席审查扫描。 */
    private final CreditService credit;

    public SweepService(JdbcTemplate jdbc, BuddyService buddy, AttendanceService attendance,
                        CreditService credit) {
        this.jdbc = jdbc;
        this.buddy = buddy;
        this.attendance = attendance;
        this.credit = credit;
    }

    @Scheduled(fixedDelayString = "${app.sweep-seconds:10}000")
    public void sweep() {
        LocalDateTime now = LocalDateTime.now();
        // 任务 1（2026-11-08 P0）：READY→OPEN 回流。截止未到且未开始的活动回到报名期。
        // 根因：sweep 只有 OPEN→READY 的单向流转；种子时间平移 / 恢复后截止回到未来，
        // 状态却留在 READY，报名（要求 OPEN）与递补（promote 第一行要求 OPEN）双死。
        // 回流与 OPEN→READY 互斥（截止 </> now），先执行回流再执行正向流转，不会互相打架；
        // READY 且已开始的仍由下面的 RUNNING 流转接走，截止已过的仍留在 READY。
        jdbc.update("UPDATE activity SET status='OPEN', updated_at=? WHERE status='READY' AND deadline > ? AND start_time > ?",
                java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now));
        // 活动生命周期（不碰已取消）
        jdbc.update("UPDATE activity SET status='ENDED', updated_at=? WHERE status IN ('OPEN','READY','RUNNING') AND end_time <= ?",
                java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now));
        jdbc.update("UPDATE activity SET status='RUNNING', updated_at=? WHERE status IN ('OPEN','READY') AND start_time <= ? AND end_time > ?",
                java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now));
        jdbc.update("UPDATE activity SET status='READY', updated_at=? WHERE status='OPEN' AND deadline <= ? AND start_time > ?",
                java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now), java.sql.Timestamp.valueOf(now));
        // 超时邀请：逐条在事务内抢占处理，失败可重试
        List<Long> expired = jdbc.queryForList(
                "SELECT id FROM invitation WHERE status='PENDING' AND expires_at <= ? ORDER BY expires_at, id",
                Long.class, java.sql.Timestamp.valueOf(now));
        int expiredCount = 0;
        int skippedCount = 0;
        int expireFailed = 0;
        for (Long id : expired) {
            try {
                if (buddy.expireOne(id)) {
                    expiredCount++;
                } else {
                    skippedCount++;
                }
            } catch (Exception e) {
                expireFailed++;
                log.warn("sweep invite expire failed, invitationId={}, exception={}",
                        id, e.getClass().getSimpleName());
            }
        }
        log.info("sweep invite expire: attempted={}, expired={}, skipped={}, failed={}",
                expired.size(), expiredCount, skippedCount, expireFailed);
        // 任务 9（C 路 C1 / 序号 40+41）：报名截止收尾。生命周期推进后，对已截止且仍是
        // OPEN/READY/RUNNING、并仍有 WAITING/INVITED 参与的活动逐条收尾（WAITING → EXPIRED；
        // INVITED 的 PENDING 邀请 → INVALID、参与 → EXPIRED），不发新邀请、不改活动状态。
        // 放在超时邀请逐条过期之后，保证「已到期邀请先 EXPIRED、其余再 INVALID」的次序。
        // 每条活动独立事务（closeOutActivity 带 @Transactional），单条失败只计数不阻断本轮。
        // G06（2026-11-21）：RUNNING 也纳入收尾候选，避免截止后活动被推进到 RUNNING 时队列无人清理。
        List<Long> closeoutDue = jdbc.queryForList(
                "SELECT a.id FROM activity a " +
                        "WHERE a.deadline <= ? AND a.status IN ('OPEN','READY','RUNNING') " +
                        "AND EXISTS (SELECT 1 FROM participation p " +
                        "WHERE p.activity_id = a.id AND p.status IN ('WAITING','INVITED')) " +
                        "ORDER BY a.deadline, a.id LIMIT 200",
                Long.class, java.sql.Timestamp.valueOf(now));
        int waitingClosed = 0;
        int invitedClosed = 0;
        int closeoutFailed = 0;
        for (Long activityId : closeoutDue) {
            try {
                Map<String, Object> result = buddy.closeOutActivity(activityId, now);
                if (result != null) {
                    waitingClosed += intValue(result.get("waitingClosed"));
                    invitedClosed += intValue(result.get("invitedClosed"));
                }
            } catch (Exception e) {
                closeoutFailed++;
                log.warn("sweep closeout failed, activityId={}", activityId, e);
            }
        }
        log.info("sweep closeout: activities={}, waitingClosed={}, invitedClosed={}, failed={}",
                closeoutDue.size(), waitingClosed, invitedClosed, closeoutFailed);
        // 任务 8：白天补发夜间暂缓的递补邀请（夜间空缺等白天补发给候补第 1 名）。
        // backfillDaytimeInvites 内部先判白天，夜间直接返回。
        try {
            buddy.backfillDaytimeInvites(now);
        } catch (Exception e) {
            log.warn("sweep backfillDaytimeInvites failed, exception={}, message={}",
                    e.getClass().getSimpleName(), safeFailureSummary(e));
        }
        // 阶段二 CEM-08：出勤快照补建与核对期届满定版。失败下轮重试。
        try {
            attendance.sweepAttendance(now);
        } catch (Exception e) {
            log.warn("sweep sweepAttendance failed, exception={}, message={}",
                    e.getClass().getSimpleName(), safeFailureSummary(e));
        }
        // 阶段三 CEM-10：信用结算、事实更正重算与缺席审查扫描。失败下轮重试。
        try {
            credit.settleSweep(now);
        } catch (Exception e) {
            log.warn("sweep settleSweep failed, exception={}, message={}",
                    e.getClass().getSimpleName(), safeFailureSummary(e));
        }
    }

    /** 原始异常消息可能含 SQL、绑定值或用户信息；仅按类型返回固定文案。 */
    private static String safeFailureSummary(Exception e) {
        if (e instanceof DataAccessException) {
            return "data access failed";
        }
        if (e instanceof IllegalArgumentException) {
            return "invalid argument";
        }
        if (e instanceof IllegalStateException) {
            return "invalid state";
        }
        return "details withheld";
    }

    /** closeOutActivity 返回计数可能是 Integer/Long，统一按 Number 读取，缺失按 0。 */
    private static int intValue(Object value) {
        return value instanceof Number ? ((Number) value).intValue() : 0;
    }

    /** 阶段一 B-CEM-07：通知发件箱发布任务。业务写入 PENDING，这里在 publish_at
     *  到期后翻为 PUBLISHED；高频短间隔执行，让通知列表 ≤1 秒内可见。失败下轮重试。 */
    @Scheduled(fixedDelay = 500)
    public void publishOutbox() {
        LocalDateTime now = LocalDateTime.now();
        Timestamp cutoff = Timestamp.valueOf(now);
        Long duePendingCount = null;
        try {
            duePendingCount = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM notification WHERE status='PENDING' AND publish_at <= ?",
                    Long.class, cutoff);
        } catch (Exception ignored) {
            // COUNT 仅用于失败诊断；取不到时仍照常发布。
        }
        try {
            jdbc.update("UPDATE notification SET status='PUBLISHED' " +
                            "WHERE status='PENDING' AND publish_at <= ?",
                    cutoff);
        } catch (Exception e) {
            log.warn("publishOutbox failed, failedBatches=1, duePendingCount={}, oldestPendingAgeMinutes={}",
                    duePendingCount == null ? "unknown" : duePendingCount.toString(),
                    oldestPendingAgeMinutes(now));
        }
    }

    private String oldestPendingAgeMinutes(LocalDateTime now) {
        try {
            Timestamp oldest = jdbc.queryForObject(
                    "SELECT MIN(created_at) FROM notification WHERE status='PENDING'", Timestamp.class);
            if (oldest == null) {
                return "none";
            }
            return Long.toString(Math.max(0L, Duration.between(oldest.toLocalDateTime(), now).toMinutes()));
        } catch (Exception ignored) {
            return "unknown";
        }
    }
}
