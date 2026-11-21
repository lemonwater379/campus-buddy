package com.campusbuddy.service;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * 写接口幂等回执（command_receipts）：按 (user_id, endpoint, idem_key) 唯一。
 * 同一键同一请求摘要直接回放首次响应；摘要不同由 controller 返回 409。
 *
 * <p>四态用现有列哨兵表达（表无状态列，response_body / http_status 均 NOT NULL）：
 * <ul>
 *   <li>占位（执行中）：http_status=0、response_body='' 的行，只有 execute() 内部可见；
 *       find() 带 http_status&lt;&gt;0 条件，占位行永不作为可重放回执露出。</li>
 *   <li>已完成：业务正常返回 Outcome（任何状态码，含 400）后回填真实 http_status / response_body（created_at 不变）。</li>
 *   <li>失败释放：仅业务抛异常（或返回 null Outcome）时 DELETE 占位行，不留回执，同键重试可重新执行。</li>
 *   <li>并发等待：同键同摘要占位未决时轮询等待；超时以 IN_PROGRESS 结果确定性返回。</li>
 * </ul>
 */
@Service
public class IdempotencyService {
    /** http_status 哨兵：0 = 占位（执行中）；真实 HTTP 状态码永不为 0。 */
    static final int STATUS_PLACEHOLDER = 0;
    /** 占位轮询间隔（毫秒）。 */
    private static final long POLL_INTERVAL_MS = 50L;
    /** 单轮占位轮询上限（毫秒，约 2 秒）。 */
    private static final long POLL_TIMEOUT_MS = 2_000L;
    /** 抢占占位的整体上限（含首次 INSERT）。 */
    private static final int MAX_ACQUIRE_ATTEMPTS = 3;
    /** 占位存活超过该秒数视为陈旧，可条件删除后抢占。 */
    private static final long STALE_PLACEHOLDER_SECONDS = 60L;
    /** 单行语句死锁重试上限（重试次数，不含首次执行）。 */
    private static final int MAX_DEADLOCK_RETRIES = 3;
    /** 死锁重试基础间隔（毫秒），按重试次序递增 25 / 50 / 75。 */
    private static final long DEADLOCK_BACKOFF_BASE_MS = 25L;

    /** CONFLICT 的固定响应体（与既有 controller 的 IDEMPOTENCY_CONFLICT 口径一致）。 */
    public static final String CONFLICT_BODY =
            "{\"success\":false,\"code\":\"IDEMPOTENCY_CONFLICT\","
                    + "\"message\":\"同一幂等键对应了不同请求\",\"data\":null}";
    /** IN_PROGRESS 的固定响应体（确定性：不带时间戳 / 随机 traceId）。 */
    public static final String IN_PROGRESS_BODY =
            "{\"success\":false,\"code\":\"IDEMPOTENCY_IN_PROGRESS\","
                    + "\"message\":\"相同幂等键的请求正在处理中\",\"data\":null}";

    private final JdbcTemplate jdbc;

    public IdempotencyService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    /** execute() 的四种结局。 */
    public enum Kind { EXECUTED, REPLAY, CONFLICT, IN_PROGRESS }

    /** 业务动作的一次执行结果（状态码 + 响应体，响应体 null 规范为空串）。 */
    public record Outcome(int httpStatus, String responseBody) {
        public Outcome { responseBody = responseBody == null ? "" : responseBody; }
    }

    /** execute() 的编排结果：结局 + 应回给调用方的状态码与响应体。 */
    public record Result(Kind kind, int httpStatus, String responseBody) {
        public Result { responseBody = responseBody == null ? "" : responseBody; }

        public static Result executed(Outcome outcome) {
            return new Result(Kind.EXECUTED, outcome.httpStatus(), outcome.responseBody());
        }

        public static Result replay(int httpStatus, String responseBody) {
            return new Result(Kind.REPLAY, httpStatus, responseBody);
        }

        public static Result conflict() { return new Result(Kind.CONFLICT, 409, CONFLICT_BODY); }

        public static Result inProgress() { return new Result(Kind.IN_PROGRESS, 409, IN_PROGRESS_BODY); }
    }

    /** 返回已存回执 {request_hash, response_body, http_status}，没有则 null。占位行（http_status=0）永不露出。 */
    public Map<String, Object> find(long userId, String endpoint, String key) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT request_hash, response_body, http_status FROM command_receipts " +
                        "WHERE user_id=? AND endpoint=? AND idem_key=? AND http_status<>0",
                userId, endpoint, key);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 保存回执。并发下唯一键冲突说明已有先存者，按“以先存者为准”静默忽略。 */
    public void save(long userId, String endpoint, String key,
                     String requestHash, String responseBody, int httpStatus) {
        try {
            withDeadlockRetry(() -> jdbc.update(
                    "INSERT INTO command_receipts(user_id, endpoint, idem_key, request_hash, " +
                            "response_body, http_status, created_at) VALUES (?,?,?,?,?,?,?)",
                    userId, endpoint, key, requestHash, responseBody, httpStatus,
                    Timestamp.valueOf(LocalDateTime.now())));
        } catch (DataIntegrityViolationException ignored) {
            // 唯一键冲突：并发重试，先存者为准。
        }
    }

    /**
     * 占位编排：先 INSERT 占位行抢执行权，抢到者执行业务动作；
     * 正常返回非 null Outcome（任何状态码）一律回填为正式回执（EXECUTED）；
     * 仅在业务抛异常或返回 null Outcome 时删除占位释放，不留回执
     * （业务异常原样抛出，返回 null 则抛 IllegalStateException）；
     * 撞唯一键者按现有行裁决：异摘要 CONFLICT、同摘要已完成 REPLAY、同摘要占位轮询等待
     * （对方完成则重放、释放则重新抢占，整体抢占上限 3 次，单轮轮询约 2 秒超时返回 IN_PROGRESS）。
     */
    public Result execute(long userId, String endpoint, String key, String requestHash,
                          Supplier<Outcome> action) {
        for (int attempt = 1; ; attempt++) {
            try {
                insertPlaceholder(userId, endpoint, key, requestHash);
            } catch (DataIntegrityViolationException uniqueConflict) {
                Result settled = awaitExisting(userId, endpoint, key, requestHash);
                if (settled != null) return settled;
                // 现有行已被释放（或陈旧占位已清）：重新抢占，整体上限 MAX_ACQUIRE_ATTEMPTS 次。
                if (attempt >= MAX_ACQUIRE_ATTEMPTS) return Result.inProgress();
                continue;
            }
            return runOwned(userId, endpoint, key, action);
        }
    }

    /**
     * 已抢到占位者：业务动作只执行一次，绝不重试。
     * 正常返回非 null Outcome 时一律回填；抛异常或返回 null Outcome 时释放占位。
     */
    private Result runOwned(long userId, String endpoint, String key, Supplier<Outcome> action) {
        Outcome outcome;
        try {
            outcome = action.get();
        } catch (RuntimeException | Error e) {
            try {
                deletePlaceholder(userId, endpoint, key);
            } catch (RuntimeException releaseFailure) {
                e.addSuppressed(releaseFailure);
            }
            throw e;
        }
        if (outcome == null) {
            deletePlaceholder(userId, endpoint, key);
            throw new IllegalStateException("幂等业务动作返回了 null Outcome");
        }
        backfillReceipt(userId, endpoint, key, outcome);
        return Result.executed(outcome);
    }

    /**
     * 撞唯一键后的裁决：返回 null 表示现有行已消失 / 陈旧占位已清，调用方应重新抢占；
     * 否则返回 REPLAY / CONFLICT / IN_PROGRESS 之一。异摘要（含占位行）直接 CONFLICT，不等待。
     */
    private Result awaitExisting(long userId, String endpoint, String key, String requestHash) {
        long deadlineNanos = System.nanoTime() + POLL_TIMEOUT_MS * 1_000_000L;
        while (true) {
            Map<String, Object> row = findRaw(userId, endpoint, key);
            if (row == null) return null; // 对方已释放 → 重新抢占
            if (!requestHash.equals(row.get("request_hash"))) return Result.conflict();
            int status = ((Number) row.get("http_status")).intValue();
            if (status != STATUS_PLACEHOLDER) {
                return Result.replay(status, String.valueOf(row.get("response_body")));
            }
            // 同摘要占位未决：陈旧占位（>60s）条件删除后重新抢占
            LocalDateTime createdAt = toLocalDateTime(row.get("created_at"));
            if (createdAt != null
                    && createdAt.isBefore(LocalDateTime.now().minusSeconds(STALE_PLACEHOLDER_SECONDS))) {
                deleteStalePlaceholder(userId, endpoint, key, createdAt);
                return null;
            }
            if (System.nanoTime() >= deadlineNanos) return Result.inProgress();
            if (!sleepQuietly(POLL_INTERVAL_MS)) return Result.inProgress(); // 被中断：确定性返回
        }
    }

    /** 内部读行（含占位行与 created_at），不走 find() 的 http_status 过滤。 */
    private Map<String, Object> findRaw(long userId, String endpoint, String key) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT request_hash, response_body, http_status, created_at FROM command_receipts " +
                        "WHERE user_id=? AND endpoint=? AND idem_key=?",
                userId, endpoint, key);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 插入占位行：http_status=0、response_body=''。唯一键冲突原样抛出（绝不重试），由 execute() 裁决。 */
    private void insertPlaceholder(long userId, String endpoint, String key, String requestHash) {
        withDeadlockRetry(() -> jdbc.update(
                "INSERT INTO command_receipts(user_id, endpoint, idem_key, request_hash, " +
                        "response_body, http_status, created_at) VALUES (?,?,?,?,'',0,?)",
                userId, endpoint, key, requestHash, Timestamp.valueOf(LocalDateTime.now())));
    }

    /** 回填占位行为正式回执（created_at 不变，仅回填 body / status）。 */
    private void backfillReceipt(long userId, String endpoint, String key, Outcome outcome) {
        withDeadlockRetry(() -> jdbc.update(
                "UPDATE command_receipts SET response_body=?, http_status=? " +
                        "WHERE user_id=? AND endpoint=? AND idem_key=? AND http_status=0",
                outcome.responseBody(), outcome.httpStatus(), userId, endpoint, key));
    }

    /** 释放占位行（仅删 http_status=0 的行，不误删已完成回执）。 */
    private void deletePlaceholder(long userId, String endpoint, String key) {
        withDeadlockRetry(() -> jdbc.update(
                "DELETE FROM command_receipts " +
                        "WHERE user_id=? AND endpoint=? AND idem_key=? AND http_status=0",
                userId, endpoint, key));
    }

    /** 条件删除陈旧占位：带读到的 created_at 做乐观条件，避免误删他人刚抢到的新占位。 */
    private void deleteStalePlaceholder(long userId, String endpoint, String key, LocalDateTime createdAt) {
        withDeadlockRetry(() -> jdbc.update(
                "DELETE FROM command_receipts " +
                        "WHERE user_id=? AND endpoint=? AND idem_key=? AND http_status=0 AND created_at=?",
                userId, endpoint, key, Timestamp.valueOf(createdAt)));
    }

    /**
     * B2-5 最小实现：回执表单行语句的死锁重试。
     * CannotAcquireLockException 与 DeadlockLoserDataAccessException 在 Spring 6.1 中同为
     * PessimisticLockingFailureException 的子类（javap 实测，兄弟类），故按共同父类捕获，
     * 最多重试 3 次、间隔 25 / 50 / 75ms 递增；唯一键冲突（DataIntegrityViolationException）
     * 不在此捕获范围，绝不重试；业务 action 不经此助手，绝不重试。
     */
    private int withDeadlockRetry(Supplier<Integer> statement) {
        PessimisticLockingFailureException last = null;
        for (int retry = 0; retry <= MAX_DEADLOCK_RETRIES; retry++) {
            try {
                return statement.get();
            } catch (PessimisticLockingFailureException e) {
                last = e;
                if (retry == MAX_DEADLOCK_RETRIES) break;
                if (!sleepQuietly(DEADLOCK_BACKOFF_BASE_MS * (retry + 1))) break;
            }
        }
        throw last;
    }

    /** created_at 的 JDBC 返回类型随驱动而异（Timestamp / LocalDateTime / OffsetDateTime），统一转换；未知类型返回 null（不做陈旧判定）。 */
    private static LocalDateTime toLocalDateTime(Object value) {
        if (value == null) return null;
        if (value instanceof LocalDateTime ldt) return ldt;
        if (value instanceof Timestamp ts) return ts.toLocalDateTime();
        if (value instanceof OffsetDateTime odt) return odt.toLocalDateTime();
        if (value instanceof java.util.Date date) {
            return LocalDateTime.ofInstant(date.toInstant(), ZoneId.systemDefault());
        }
        return null;
    }

    /** 睡眠；被中断时恢复中断标志并返回 false，由调用方走确定性出口。 */
    private static boolean sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }
}
