package com.campusbuddy.service;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 写接口幂等回执（command_receipts）：按 (user_id, endpoint, idem_key) 唯一。
 * 同一键同一请求摘要直接回放首次响应；摘要不同由 controller 返回 409。
 */
@Service
public class IdempotencyService {
    private final JdbcTemplate jdbc;

    public IdempotencyService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    /** 返回已存回执 {request_hash, response_body, http_status}，没有则 null。 */
    public Map<String, Object> find(long userId, String endpoint, String key) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT request_hash, response_body, http_status FROM command_receipts " +
                        "WHERE user_id=? AND endpoint=? AND idem_key=?",
                userId, endpoint, key);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 保存回执。并发下唯一键冲突说明已有先存者，按“以先存者为准”静默忽略。 */
    public void save(long userId, String endpoint, String key,
                     String requestHash, String responseBody, int httpStatus) {
        try {
            jdbc.update("INSERT INTO command_receipts(user_id, endpoint, idem_key, request_hash, " +
                            "response_body, http_status, created_at) VALUES (?,?,?,?,?,?,?)",
                    userId, endpoint, key, requestHash, responseBody, httpStatus,
                    Timestamp.valueOf(LocalDateTime.now()));
        } catch (DataIntegrityViolationException ignored) {
            // 唯一键冲突：并发重试，先存者为准。
        }
    }
}
