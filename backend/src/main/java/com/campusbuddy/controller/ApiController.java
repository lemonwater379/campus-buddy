package com.campusbuddy.controller;

import com.campusbuddy.service.BuddyService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 旧接口层：阶段一（2026-11-15）起只保留 GET /api/health 兼容健康检查，
 * 其余端点全部迁到 /api/v1（见 ApiV1Controller）。返回格式保持旧的 {ok:true,...}。
 */
@RestController
@RequestMapping("/api")
public class ApiController {
    private final JdbcTemplate jdbc;
    private final BuddyService buddy;

    public ApiController(JdbcTemplate jdbc, BuddyService buddy) {
        this.jdbc = jdbc;
        this.buddy = buddy;
    }

    // ---- 健康 ----
    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("ok", true, "server_time", LocalDateTime.now().toString(),
                "invite_ttl_seconds", buddy.inviteTtlSeconds(),
                "users", jdbc.queryForObject("SELECT COUNT(*) FROM app_user", Integer.class),
                "activities", jdbc.queryForObject("SELECT COUNT(*) FROM activity", Integer.class));
    }
}
