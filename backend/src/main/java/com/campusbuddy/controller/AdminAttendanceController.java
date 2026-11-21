package com.campusbuddy.controller;

import com.campusbuddy.service.AttendanceService;
import com.campusbuddy.service.AuthService;
import com.campusbuddy.service.ConflictException;
import com.campusbuddy.service.ForbiddenException;
import com.campusbuddy.service.GovernanceService;
import com.campusbuddy.service.IdempotencyService;
import com.campusbuddy.service.RateLimitException;
import com.campusbuddy.service.ValidationException;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import java.util.*;
import java.util.function.Supplier;

/**
 * 文档功能补齐 DG-ADM-01（SDD §6.9）：管理员查看活动出勤名单与代核组织者本人出勤。
 */
@RestController
@RequestMapping("/api/v1")
public class AdminAttendanceController {
    private final IdempotencyService idem;
    private final ApiSupport support;
    private final AuthService auth;
    private final GovernanceService governance;
    private final AttendanceService attendance;

    public AdminAttendanceController(IdempotencyService idem, ApiSupport support,
                                     AuthService auth, GovernanceService governance,
                                     AttendanceService attendance) {
        this.idem = idem;
        this.support = support;
        this.auth = auth;
        this.governance = governance;
        this.attendance = attendance;
    }

    /** 与 ApiV1Controller.requireAdmin 同口径：未登录 / 停用同样按 403 处理。 */
    private long requireAdmin(String h) {
        Long id = auth.userId(h);
        if (id == null) throw new ForbiddenException("未登录");
        var user = auth.me(id);
        if (!"ACTIVE".equals(user.get("status"))) throw new ForbiddenException("账号已停用");
        governance.requireAdmin(id);
        return id;
    }

    // ---- 与 ApiV1Controller 同口径的最小适配 ----

    /**
     * 写接口幂等包装：带 {@code Idempotency-Key} 时，由 {@code IdempotencyService.execute()}
     * 按 (用户, 接口模板, 键) 先占位再执行；无键或空白键直接执行 handler。
     * 同键同请求摘要回放首次响应（状态码相同、body 逐字一致，含业务错误响应）；
     * 同键异摘要返回 409 {@code IDEMPOTENCY_CONFLICT}；
     * 同键同摘要遇到执行中占位且等待后仍未完成时，返回 409 {@code IDEMPOTENCY_IN_PROGRESS}。
     * handler 抛出的业务异常（限下方捕获集）先转成 envelope，再作为 {@code Outcome} 存储。
     */
    private ResponseEntity<String> idempotent(HttpServletRequest req, long userId, String endpointKey,
                                              String bodyJson,
                                              Supplier<ResponseEntity<String>> handler) {
        String key = req.getHeader("Idempotency-Key");
        if (key == null || key.isBlank()) return handler.get();
        String hash = ApiSupport.sha256(req.getMethod() + " " + req.getRequestURI() + "\n" + bodyJson);
        IdempotencyService.Result result = idem.execute(userId, endpointKey, key, hash, () -> {
            ResponseEntity<String> resp;
            try {
                resp = handler.get();
            } catch (ConflictException | IllegalStateException | EmptyResultDataAccessException
                     | RateLimitException e) {
                resp = errorResponse(e);
            }
            return new IdempotencyService.Outcome(resp.getStatusCode().value(),
                    resp.getBody() == null ? "" : resp.getBody());
        });
        return switch (result.kind()) {
            case EXECUTED, REPLAY, CONFLICT, IN_PROGRESS ->
                    support.raw(result.responseBody(), result.httpStatus());
        };
    }

    /**
     * 出勤行的 ID 键（沿用 GOVERNANCE_ID_KEYS 的做法）：id / participation_id /
     * activity_id / user_id 也在 ApiSupport.ID_KEYS 内；decided_by 是真实用户 ID
     * 但两处既有键表都没有，这里一并显式字符串化。null 原样保留，version 不是 ID。
     */
    private static final String[] ATTENDANCE_ID_KEYS = {
            "id", "participation_id", "activity_id", "user_id", "decided_by"
    };

    /** 复制一行并把指定键上的 Number 值转成字符串（不改动服务层返回的原 Map）。 */
    private static Map<String, Object> strIds(Map<String, Object> row, String... keys) {
        if (row == null) return null;
        Map<String, Object> out = new LinkedHashMap<>(row);
        for (String key : keys) {
            Object v = out.get(key);
            if (v instanceof Number n) out.put(key, n.toString());
        }
        return out;
    }

    /** 出勤列表逐行字符串化 ID 键。 */
    private static List<Map<String, Object>> strIds(List<Map<String, Object>> rows) {
        if (rows == null) return List.of();
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) out.add(strIds(row, ATTENDANCE_ID_KEYS));
        return out;
    }

    /** 出勤列表统一分页：先逐行字符串化 ID，再按 page/pageSize 切片。 */
    private static Map<String, Object> pageAttendance(List<Map<String, Object>> rows,
                                                      Integer page, Integer pageSize) {
        int[] pp = ApiSupport.pagination(page, pageSize);
        return ApiSupport.page(strIds(rows), pp[0], pp[1]);
    }

    private static String str(Map<String, Object> body, String key) {
        if (body == null) return null;
        Object v = body.get(key);
        return v instanceof String s ? s : null;
    }

    // ---- 错误映射（新控制器不共享 ApiV1Controller 的局部 @ExceptionHandler，按同口径复制） ----

    @ExceptionHandler({ConflictException.class, ValidationException.class,
            EmptyResultDataAccessException.class, ForbiddenException.class,
            IllegalStateException.class, RateLimitException.class})
    public ResponseEntity<String> handleBusiness(Exception e) {
        return errorResponse(e);
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<String> handleUnreadable(HttpMessageNotReadableException e) {
        return support.json(support.error("ERROR", "请求体格式不正确", null), HttpStatus.BAD_REQUEST);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<String> handleBadParam(MethodArgumentTypeMismatchException e) {
        return support.json(support.error("ERROR", "参数格式不正确", null), HttpStatus.BAD_REQUEST);
    }

    /** 业务异常 → envelope；判定顺序与 ApiV1Controller.errorResponse 一致。 */
    private ResponseEntity<String> errorResponse(Throwable e) {
        if (e instanceof RateLimitException) {
            return support.json(support.error("TOO_MANY_ATTEMPTS", e.getMessage(), null),
                    HttpStatus.TOO_MANY_REQUESTS);
        }
        if (e instanceof ConflictException ce) {
            return support.json(support.error("CONFLICT", ce.getMessage(), ce.data()), HttpStatus.CONFLICT);
        }
        if (e instanceof ValidationException ve) {
            return support.json(support.error("VALIDATION", ve.getMessage(),
                    Map.of("fieldErrors", ve.fieldErrors())), HttpStatus.BAD_REQUEST);
        }
        if (e instanceof EmptyResultDataAccessException) {
            return support.json(support.error("ERROR", "记录不存在", null), HttpStatus.BAD_REQUEST);
        }
        if (e instanceof ForbiddenException) {
            return support.json(support.error("FORBIDDEN", e.getMessage(), null), HttpStatus.FORBIDDEN);
        }
        if (e instanceof IllegalStateException) {
            return support.json(support.error("ERROR", e.getMessage(), null), HttpStatus.BAD_REQUEST);
        }
        return support.json(support.error("ERROR", "服务器内部错误", null),
                HttpStatus.INTERNAL_SERVER_ERROR);
    }

    // ---- DG-ADM-01：管理员出勤名单 / 代核组织者本人 ----

    @GetMapping("/admin/activities/{id}/attendance")
    public ResponseEntity<String> listAttendanceForAdmin(@PathVariable long id,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageAttendance(
                attendance.listAttendanceForAdmin(id), page, pageSize)), HttpStatus.OK);
    }

    @PostMapping("/admin/activities/{id}/attendance/organizer")
    public ResponseEntity<String> verifyOrganizerAttendance(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me,
                "POST /api/v1/admin/activities/{id}/attendance/organizer", bodyJson, () ->
                        support.json(support.ok(strIds(governance.correctOrganizerAttendance(
                                me, id, str(body, "result"), str(body, "evidence")),
                                ATTENDANCE_ID_KEYS)), HttpStatus.OK));
    }
}
