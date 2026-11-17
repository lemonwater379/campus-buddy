package com.campusbuddy.controller;

import com.campusbuddy.service.AttendanceService;
import com.campusbuddy.service.AuthService;
import com.campusbuddy.service.BuddyService;
import com.campusbuddy.service.ConflictException;
import com.campusbuddy.service.CreditService;
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
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import java.sql.PreparedStatement;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.*;
import java.util.function.Supplier;

/**
 * /api/v1 统一接口层（阶段一，2026-11-15）。
 * 所有响应都经 ApiSupport 包成 {success,code,message,data,serverTime,traceId}，
 * ID 一律字符串化；列表按 {items,page,pageSize,total} 分页；
 * 写接口支持 Idempotency-Key 回执。业务规则与文案沿用旧 ApiController。
 */
@RestController
@RequestMapping("/api/v1")
public class ApiV1Controller {
    private final JdbcTemplate jdbc;
    private final AuthService auth;
    private final BuddyService buddy;
    private final IdempotencyService idem;
    private final ApiSupport support;
    /** 阶段二 CEM-08：签到 / 出勤 / 评价。 */
    private final AttendanceService attendance;
    /** 阶段三 CEM-10：信用查询。 */
    private final CreditService credit;
    /** 阶段四 CEM-09：平台治理（管理员 / 封禁 / 下架 / 举报 / 申诉 / 找回）。 */
    private final GovernanceService governance;
    /** 仅用于 /demo/reset 的自增序列重置分支（与 BuddyService 同一做法）。 */
    private final boolean mysql;

    public ApiV1Controller(JdbcTemplate jdbc, AuthService auth, BuddyService buddy,
                           IdempotencyService idem, ApiSupport support,
                           AttendanceService attendance, CreditService credit,
                           GovernanceService governance) {
        this.jdbc = jdbc;
        this.auth = auth;
        this.buddy = buddy;
        this.idem = idem;
        this.support = support;
        this.attendance = attendance;
        this.credit = credit;
        this.governance = governance;
        this.mysql = detectMysql(jdbc);
    }

    private static boolean detectMysql(JdbcTemplate jdbc) {
        try (var con = jdbc.getDataSource().getConnection()) {
            return con.getMetaData().getDatabaseProductName().toLowerCase().contains("mysql");
        } catch (Exception e) {
            throw new IllegalStateException("无法识别数据库产品", e);
        }
    }

    private Long require(String authHeader) {
        Long id = auth.userId(authHeader);
        if (id == null) throw new IllegalStateException("未登录");
        // 停用账号的旧 token 不能再操作：登录时拦停用只是第一道关，
        // token 发出后被停用的账号必须在每次鉴权时再查一次状态。
        var user = auth.me(id);
        if (!"ACTIVE".equals(user.get("status"))) throw new IllegalStateException("账号已停用");
        return id;
    }

    /**
     * 阶段四 CEM-09：管理员鉴权。未登录 / 停用同样按 403 处理（治理端点不向普通用户
     * 暴露业务细节）；非管理员由 GovernanceService.requireAdmin 抛 ForbiddenException。
     */
    private long requireAdmin(String h) {
        Long id = auth.userId(h);
        if (id == null) throw new ForbiddenException("未登录");
        var user = auth.me(id);
        if (!"ACTIVE".equals(user.get("status"))) throw new ForbiddenException("账号已停用");
        governance.requireAdmin(id);
        return id;
    }

    // ---- 统一错误映射 ----

    @ExceptionHandler(ConflictException.class)
    public ResponseEntity<String> handleConflict(ConflictException e) {
        return errorResponse(e);
    }

    @ExceptionHandler(ValidationException.class)
    public ResponseEntity<String> handleValidation(ValidationException e) {
        return errorResponse(e);
    }

    @ExceptionHandler(EmptyResultDataAccessException.class)
    public ResponseEntity<String> handleNotFound(EmptyResultDataAccessException e) {
        return errorResponse(e);
    }

    @ExceptionHandler(ForbiddenException.class)
    public ResponseEntity<String> handleForbidden(ForbiddenException e) {
        return errorResponse(e);
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<String> handleBusiness(IllegalStateException e) {
        return errorResponse(e);
    }

    @ExceptionHandler(RateLimitException.class)
    public ResponseEntity<String> handleRateLimit(RateLimitException e) {
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

    @ExceptionHandler(Exception.class)
    public ResponseEntity<String> handleOther(Exception e) {
        return errorResponse(e);
    }

    /** 业务异常 → envelope。ValidationException 必须先于其父类 IllegalStateException 判断。 */
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
            // 查不到记录（不存在的活动 / 参与记录 / 邀请）是客户端错误，不应返回 500。
            return support.json(support.error("ERROR", "记录不存在", null), HttpStatus.BAD_REQUEST);
        }
        if (e instanceof ForbiddenException) {
            // 阶段四 CEM-09：无权限 / 未登录 / 账号停用 → 403。
            return support.json(support.error("FORBIDDEN", e.getMessage(), null), HttpStatus.FORBIDDEN);
        }
        if (e instanceof IllegalStateException) {
            return support.json(support.error("ERROR", e.getMessage(), null), HttpStatus.BAD_REQUEST);
        }
        return support.json(support.error("ERROR", "服务器内部错误", null),
                HttpStatus.INTERNAL_SERVER_ERROR);
    }

    // ---- 幂等包装 ----

    /**
     * 写接口统一入口：带 Idempotency-Key 时按 (用户, 接口模板, 键) 去重。
     * 同键同请求摘要回放首次响应（状态码 + body）；同键异摘要返回 409 IDEMPOTENCY_CONFLICT。
     * handler 内部抛出的业务异常先转成 envelope 再存储，保证重试拿到同一错误。
     */
    private ResponseEntity<String> idempotent(HttpServletRequest req, long userId, String endpointKey,
                                              String bodyJson,
                                              Supplier<ResponseEntity<String>> handler) {
        String key = req.getHeader("Idempotency-Key");
        if (key == null || key.isBlank()) return handler.get();
        String hash = ApiSupport.sha256(req.getMethod() + " " + req.getRequestURI() + "\n" + bodyJson);
        Map<String, Object> found = idem.find(userId, endpointKey, key);
        if (found != null) {
            if (hash.equals(found.get("request_hash"))) {
                int status = ((Number) found.get("http_status")).intValue();
                return support.raw(String.valueOf(found.get("response_body")), status);
            }
            return support.json(support.error("IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同请求", null),
                    HttpStatus.CONFLICT);
        }
        ResponseEntity<String> resp;
        try {
            resp = handler.get();
        } catch (ConflictException | IllegalStateException | EmptyResultDataAccessException
                 | RateLimitException e) {
            resp = errorResponse(e);
        }
        idem.save(userId, endpointKey, key, hash,
                resp.getBody() == null ? "" : resp.getBody(), resp.getStatusCode().value());
        return resp;
    }

    private static boolean flag(Map<String, Object> body, String key) {
        if (body == null) return false;
        Object v = body.get(key);
        if (v instanceof Boolean b) return b;
        return v != null && "true".equalsIgnoreCase(v.toString());
    }

    // ---- 阶段四 CEM-09：治理返回体的 ID 字符串化 / body 取值小工具 ----

    /**
     * 治理新表的键不在 ApiSupport.ID_KEYS 内（id / activity_id / user_id 等已由其处理），
     * 服务层返回 Number，控制器在装 envelope 前统一转成字符串。
     */
    private static final String[] GOVERNANCE_ID_KEYS = {
            "decision_id", "complaint_id", "appeal_id", "attendance_id",
            "reviewer_id", "handler_id", "applicant_id", "subject_user_id",
            "result_decision_id", "previous_decision_id", "attendance_revision_id",
            "trigger_attendance_id", "lift_decision_id",
            // 审计行（governance_action）里的操作者 / 对象 ID，同样遵守“ID 一律字符串”契约。
            "actor_id", "target_id"
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

    /** 列表逐行处理治理相关 ID 键。 */
    private static List<Map<String, Object>> strIds(List<Map<String, Object>> rows) {
        if (rows == null) return List.of();
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) out.add(strIds(row, GOVERNANCE_ID_KEYS));
        return out;
    }

    /** 治理列表统一分页：先逐行字符串化新键，再按 page/pageSize 切片。 */
    private static Map<String, Object> pageGovernance(List<Map<String, Object>> rows,
                                                      Integer page, Integer pageSize) {
        int[] pp = ApiSupport.pagination(page, pageSize);
        return ApiSupport.page(strIds(rows), pp[0], pp[1]);
    }

    private static String str(Map<String, Object> body, String key) {
        if (body == null) return null;
        Object v = body.get(key);
        return v instanceof String s ? s : null;
    }

    private static Long longOf(Object v) {
        if (v instanceof Number n) return n.longValue();
        if (v instanceof String s && !s.isBlank()) {
            try { return Long.parseLong(s.trim()); } catch (NumberFormatException ignored) { }
        }
        return null;
    }

    private static Long num(Map<String, Object> body, String key) {
        return body == null ? null : longOf(body.get(key));
    }

    private static Integer intVal(Map<String, Object> body, String key) {
        Long v = num(body, key);
        return v == null ? null : v.intValue();
    }

    /** 必填的数值型 body 字段（缺失时报 400 而不是 NPE 500）。 */
    private static long requiredLong(Map<String, Object> body, String key) {
        Long v = num(body, key);
        if (v == null) throw new ValidationException(key, "缺少 " + key);
        return v;
    }

    // ---- 健康 ----

    @GetMapping("/health")
    public ResponseEntity<String> health() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("server_time", LocalDateTime.now().toString());
        data.put("invite_ttl_seconds", buddy.inviteTtlSeconds());
        data.put("users", jdbc.queryForObject("SELECT COUNT(*) FROM app_user", Integer.class));
        data.put("activities", jdbc.queryForObject("SELECT COUNT(*) FROM activity", Integer.class));
        return support.json(support.ok(data), HttpStatus.OK);
    }

    // ---- 账号 ----

    @PostMapping("/login")
    public ResponseEntity<String> login(@RequestBody Map<String, String> body) {
        String token = auth.login(body.get("account"), body.get("password"));
        if (token == null) throw new IllegalStateException("账号或密码错误");
        Long id = auth.userId("Bearer " + token);
        // 阶段四 CEM-09：登录响应附带治理状态（管理员标记 / 是否处于封禁）。
        Map<String, Object> user = new LinkedHashMap<>(auth.me(id));
        user.put("is_admin", governance.isAdmin(id));
        user.put("banned", governance.activeBan(id) != null);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("token", token);
        data.put("user", user);
        return support.json(support.ok(data), HttpStatus.OK);
    }

    @PostMapping("/register")
    public ResponseEntity<String> register(@RequestBody Map<String, String> body) {
        String account = body.get("account"), password = body.get("password");
        if (account == null || account.length() < 4 || account.length() > 32)
            throw new IllegalStateException("账号需为 4-32 字符");
        if (password == null || password.length() < 6)
            throw new IllegalStateException("密码至少 6 位");
        // 旧代码不校验昵称长度，超长时数据库 CHECK 报错被 catch 全吞，
        // 统一误报为“账号已存在”。先校验，再按异常原因区分报错。
        String nickname = body.get("nickname");
        if (nickname == null || nickname.isBlank()) nickname = account;
        if (nickname.codePointCount(0, nickname.length()) < 1 || nickname.codePointCount(0, nickname.length()) > 30)
            throw new IllegalStateException("昵称需为 1-30 字");
        try {
            jdbc.update("INSERT INTO app_user(account, password_hash, nickname) VALUES (?,?,?)",
                    account, AuthService.hash(password), nickname);
        } catch (Exception e) {
            // 只有唯一约束冲突才是“账号已存在”，其他数据库错误不再冒充它。
            Throwable t = e;
            while (t != null) {
                String m = t.getMessage();
                // PostgreSQL 唯一冲突文案是 "duplicate key"，MySQL 是 "Duplicate entry ..."，
                // 统一按小写匹配，两库重复注册都报“账号已存在”。
                if (m != null) {
                    String lower = m.toLowerCase();
                    if (lower.contains("duplicate key") || lower.contains("duplicate entry"))
                        throw new IllegalStateException("账号已存在");
                }
                t = t.getCause();
            }
            throw new IllegalStateException("注册失败，请重试");
        }
        return support.json(support.ok(Map.of()), HttpStatus.OK);
    }

    @GetMapping("/me")
    public ResponseEntity<String> me(@RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        // 阶段四 CEM-09：与 /login 口径一致，附带 is_admin / banned；不放封禁详情。
        Map<String, Object> user = new LinkedHashMap<>(auth.me(me));
        user.put("is_admin", governance.isAdmin(me));
        user.put("banned", governance.activeBan(me) != null);
        return support.json(support.ok(Map.of("user", user)), HttpStatus.OK);
    }

    // 任务 10（2026-11-09）：改密码。登录态，传原密码 + 新密码；校验原密码、
    // 新密码符合 SDD 规则（8–64 位、含字母与数字）后更新散列并撤销全部旧会话
    // token（含当前 token，改完须重新登录）。注册接口不动。
    @PostMapping("/me/password")
    public ResponseEntity<String> changePassword(@RequestBody Map<String, String> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/me/password", support.toJson(body), () -> {
            auth.changePassword(me, body.get("old_password"), body.get("new_password"));
            return support.json(support.ok(Map.of()), HttpStatus.OK);
        });
    }

    // 阶段一 A5：资料修改（当前仅昵称）。字段错误返回 VALIDATION + fieldErrors.nickname。
    @PatchMapping("/me/profile")
    public ResponseEntity<String> updateProfile(@RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        String nickname = body != null && body.get("nickname") instanceof String
                ? (String) body.get("nickname") : null;
        return idempotent(req, me, "PATCH /api/v1/me/profile",
                support.toJson(body == null ? Map.of() : body), () ->
                        support.json(support.ok(Map.of("user", auth.updateNickname(me, nickname))), HttpStatus.OK));
    }

    // 阶段三 CEM-10：本人信用查询（当前分 + 流水分页，仅本人可见）。
    @GetMapping("/me/credit")
    public ResponseEntity<String> myCredit(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        var rows = credit.listEntries(me);
        int[] pp = ApiSupport.pagination(page, pageSize);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("score", credit.currentScore(me));
        data.put("entries", ApiSupport.page(rows, pp[0], pp[1]));
        return support.json(support.ok(data), HttpStatus.OK);
    }

    // ---- 活动大厅 ----

    @GetMapping("/activities")
    public ResponseEntity<String> activities(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        Long me = auth.userId(h);
        // 停用账号只读大厅时也不再带上本人状态，避免旧 token 在只读路径上仍被当作有效身份。
        if (me != null) {
            try {
                if (!"ACTIVE".equals(auth.me(me).get("status"))) me = null;
            } catch (Exception e) { me = null; }
        }
        // 任务 9（2026-11-10）：大厅默认不列已取消活动；/my 与 /my/organized 不动。
        String sql = "SELECT a.*, u.nickname AS organizer_name, " +
                "(SELECT COUNT(*) FROM participation p WHERE p.activity_id=a.id AND p.status='FORMAL') AS formal_count, " +
                "(SELECT COUNT(*) FROM participation p WHERE p.activity_id=a.id AND p.status='WAITING') AS waiting_count, " +
                "(SELECT COUNT(*) FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                " WHERE p.activity_id=a.id AND i.status='PENDING' AND i.expires_at > now()) AS reserved_count " +
                "FROM activity a JOIN app_user u ON u.id=a.organizer_id WHERE 1=1 AND a.status <> 'CANCELLED' " +
                // 阶段四 CEM-09：治理下架的活动不在大厅展示（/my 与 /my/organized 仍可见）。
                "AND NOT EXISTS (SELECT 1 FROM activity_delist d WHERE d.activity_id=a.id AND d.delisted=1) ";
        List<Object> args = new ArrayList<>();
        if (q != null && !q.isBlank()) { sql += "AND a.title LIKE ? "; args.add("%" + q.trim() + "%"); }
        if (category != null && !category.isBlank() && !"全部".equals(category)) {
            sql += "AND a.category = ? "; args.add(category);
        }
        sql += "ORDER BY a.start_time, a.id";
        var rows = jdbc.queryForList(sql, args.toArray());
        if (me != null) {
            for (var row : rows) {
                var mine = jdbc.queryForList(
                        "SELECT status FROM participation WHERE activity_id=? AND user_id=?",
                        row.get("id"), me);
                row.put("my_status", mine.isEmpty() ? null : mine.get(0).get("status"));
            }
        }
        int[] pp = ApiSupport.pagination(page, pageSize);
        return support.json(support.ok(ApiSupport.page(rows, pp[0], pp[1])), HttpStatus.OK);
    }

    @GetMapping("/activities/{id}")
    public ResponseEntity<String> activityDetail(@PathVariable long id,
            @RequestParam(required = false) Integer rosterPage,
            @RequestParam(required = false) Integer rosterPageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        Long me = auth.userId(h);
        Map<String, Object> out = buddy.activityDetail(id, me);
        // 阶段四 CEM-09：下架活动仅组织者与管理员可见；其余人按不存在处理。
        boolean delisted = governance.isDelisted(id);
        out.put("delisted", delisted);
        if (delisted) {
            Long organizerId = longOf(out.get("organizer_id"));
            boolean isOrganizer = me != null && organizerId != null && me.longValue() == organizerId;
            if (me == null || (!isOrganizer && !governance.isAdmin(me)))
                throw new IllegalStateException("活动已下架");
        }
        // 组织者名单单独分页（rosterPage/rosterPageSize，默认 1/20），其余字段不变。
        Object roster = out.get("roster");
        if (roster instanceof List<?> list) {
            int[] pp = ApiSupport.pagination(rosterPage, rosterPageSize);
            out.put("roster", ApiSupport.page(list, pp[0], pp[1]));
        }
        // 阶段二 CEM-08：评价汇总所有人可见；本人签到 / 出勤 / 评价仅登录时返回。
        out.put("evaluation_summary", attendance.evaluationSummary(id));
        if (me != null) {
            out.put("my_checkin", attendance.myCheckin(id, me));
            out.put("my_attendance", attendance.myAttendance(id, me));
            out.put("my_evaluation", attendance.myEvaluation(id, me));
        }
        return support.json(support.ok(out), HttpStatus.OK);
    }

    // ---- 阶段二 CEM-08：签到 / 出勤 / 评价 ----

    @GetMapping("/activities/{id}/checkin-code")
    public ResponseEntity<String> checkinCode(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        return support.json(support.ok(attendance.checkinCode(id, me)), HttpStatus.OK);
    }

    @PostMapping("/activities/{id}/checkins")
    public ResponseEntity<String> checkin(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/activities/{id}/checkins", bodyJson, () -> {
            String code = null;
            if (body != null) {
                Object raw = body.get("code");
                if (raw instanceof String s) code = s;
                else if (raw instanceof Number n) code = String.valueOf(n);
            }
            return support.json(support.ok(attendance.checkin(id, me, code)), HttpStatus.OK);
        });
    }

    @GetMapping("/activities/{id}/attendance")
    public ResponseEntity<String> listAttendance(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        return support.json(support.ok(attendance.listAttendance(id, me)), HttpStatus.OK);
    }

    @PutMapping("/activities/{id}/attendance/{userId}")
    public ResponseEntity<String> verifyAttendance(@PathVariable long id, @PathVariable long userId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        String result = body != null && body.get("result") instanceof String rs ? rs : null;
        String evidence = body != null && body.get("evidence") instanceof String ev ? ev : null;
        Long versionValue = null;
        if (body != null && body.get("version") instanceof Number n) versionValue = n.longValue();
        // lambda 捕获要求 effectively final，先固定下来。
        final Long version = versionValue;
        return idempotent(req, me, "PUT /api/v1/activities/{id}/attendance/{userId}",
                support.toJson(body == null ? Map.of() : body), () -> support.json(
                        support.ok(attendance.verify(id, me, userId, result, evidence, version)),
                        HttpStatus.OK));
    }

    @PostMapping("/activities/{id}/evaluations")
    public ResponseEntity<String> createEvaluation(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        Integer ratingValue = null;
        if (body != null) {
            Object raw = body.get("rating");
            if (raw instanceof Number n) ratingValue = n.intValue();
            else if (raw instanceof String s) {
                try { ratingValue = Integer.parseInt(s.trim()); } catch (NumberFormatException ignored) { }
            }
        }
        String content = body != null && body.get("content") instanceof String cs ? cs : null;
        // lambda 捕获要求 effectively final，先固定下来。
        final Integer rating = ratingValue;
        return idempotent(req, me, "POST /api/v1/activities/{id}/evaluations",
                support.toJson(body == null ? Map.of() : body),
                () -> support.json(support.ok(attendance.upsertEvaluation(id, me, rating, content)),
                        HttpStatus.OK));
    }

    @GetMapping("/activities/{id}/evaluations")
    public ResponseEntity<String> evaluations(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        return support.json(support.ok(attendance.listEvaluations(id, me)), HttpStatus.OK);
    }

    @PostMapping("/activities")
    public ResponseEntity<String> create(@RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/activities", support.toJson(body), () -> {
            // 旧代码对空标题、缺地点、非法类别、缺容量一律不校验，
            // 走到数据库约束或空指针时直接返回 500；且用 SELECT MAX(id) 取新活动 id，
            // 并发创建时多个请求会拿到同一个（别人的）id。全部在此处校验 + 用
            // 可移植的 RETURN_GENERATED_KEYS 取新活动 id（PostgreSQL 与 MySQL 驱动都支持）。
            // 阶段一：字段明确的校验错误汇总进 fieldErrors，统一 VALIDATION + 400。
            Map<String, String> errors = new LinkedHashMap<>();
            String title = body.get("title") instanceof String ? (String) body.get("title") : null;
            if (title == null || title.isBlank() || title.codePointCount(0, title.length()) > 50)
                errors.put("title", "标题需为 1-50 字");
            String location = body.get("location") instanceof String ? (String) body.get("location") : null;
            if (location == null || location.isBlank() || location.codePointCount(0, location.length()) > 100)
                errors.put("location", "地点需为 1-100 字");
            Integer capacity = null;
            Object capRaw = body.get("capacity");
            if (capRaw instanceof Number) capacity = ((Number) capRaw).intValue();
            else if (capRaw instanceof String) {
                try { capacity = Integer.parseInt(((String) capRaw).trim()); } catch (NumberFormatException ignored) { }
            }
            if (capacity == null || capacity < 1 || capacity > 100)
                errors.put("capacity", "人数上限需为 1-100");
            String category = body.get("category") instanceof String ? (String) body.get("category") : "其他";
            if (!Set.of("羽毛球", "桌游", "学习组", "其他").contains(category))
                errors.put("category", "类别不合法");
            String description = body.get("description") instanceof String ? (String) body.get("description") : "";
            String conditions = body.get("conditions") instanceof String ? (String) body.get("conditions") : "";
            if (description.codePointCount(0, description.length()) > 2000)
                errors.put("description", "介绍不能超过 2000 字");
            if (conditions.codePointCount(0, conditions.length()) > 500)
                errors.put("conditions", "参与条件不能超过 500 字");
            LocalDateTime deadline = null, start = null, end = null;
            try {
                // 前端 datetime-local 发来东八区墙钟，库里直接存东八区墙钟，
                // 不做任何时区转换（2026-11-06 时区统一改造，旧 shanghaiToUtcWall 已删除）。
                deadline = LocalDateTime.parse((String) body.get("deadline"));
            } catch (Exception e) { errors.put("deadline", "时间格式不正确"); }
            try { start = LocalDateTime.parse((String) body.get("start_time")); }
            catch (Exception e) { errors.put("start_time", "时间格式不正确"); }
            try { end = LocalDateTime.parse((String) body.get("end_time")); }
            catch (Exception e) { errors.put("end_time", "时间格式不正确"); }
            if (deadline != null && start != null && end != null
                    && !(LocalDateTime.now().isBefore(deadline) && !deadline.isAfter(start) && start.isBefore(end)))
                errors.put("start_time", "时间需满足：现在 < 报名截止 ≤ 开始 < 结束");
            if (!errors.isEmpty())
                throw new ValidationException(errors, errors.values().iterator().next());
            // lambda 内只能捕获 final / effectively-final 变量，先复制一份。
            // 取新活动 id 必须用列名数组 new String[]{"id"} 而不是 Statement.RETURN_GENERATED_KEYS：
            // PostgreSQL 驱动后者会把整行都当作生成键返回，getKey() 会因多键报错。
            final int capFinal = capacity;
            final LocalDateTime deadlineFinal = deadline, startFinal = start, endFinal = end;
            KeyHolder keyHolder = new GeneratedKeyHolder();
            jdbc.update(con -> {
                PreparedStatement ps = con.prepareStatement(
                        "INSERT INTO activity(organizer_id, title, category, description, conditions, location, capacity, deadline, start_time, end_time) " +
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        new String[]{"id"});
                ps.setLong(1, me);
                ps.setString(2, title);
                ps.setString(3, category);
                ps.setString(4, description);
                ps.setString(5, conditions);
                ps.setString(6, location);
                ps.setInt(7, capFinal);
                ps.setTimestamp(8, Timestamp.valueOf(deadlineFinal));
                ps.setTimestamp(9, Timestamp.valueOf(startFinal));
                ps.setTimestamp(10, Timestamp.valueOf(endFinal));
                return ps;
            }, keyHolder);
            Long id = keyHolder.getKey().longValue();
            return support.json(support.ok(Map.of("id", id)), HttpStatus.OK);
        });
    }

    @PostMapping("/activities/{id}/cancel")
    public ResponseEntity<String> cancel(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        // 任务 1（2026-11-09）：取消逻辑与取消通知都在 BuddyService.cancelActivity
        // 内完成（SDD §6.8：取消通知所有受影响成员）；二次取消幂等，不重发通知。
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/activities/{id}/cancel", "{}",
                () -> support.json(support.ok(buddy.cancelActivity(id, me)), HttpStatus.OK));
    }

    // 任务 2（2026-11-09）：组织者报名截止前改活动时间（开始 / 结束 / 截止三项）。
    // 只改时间，不扩容量与活动信息；R5 校验（截止前、时间顺序、待确认邀请保护）
    // 与变更通知都在 BuddyService.reschedule 内。前端入口由苏晴在详情页组织者视角加。
    @PostMapping("/activities/{id}/reschedule")
    public ResponseEntity<String> reschedule(@PathVariable long id,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/activities/{id}/reschedule", support.toJson(body), () -> {
            LocalDateTime deadline, start, end;
            try {
                deadline = LocalDateTime.parse((String) body.get("deadline"));
                start = LocalDateTime.parse((String) body.get("start_time"));
                end = LocalDateTime.parse((String) body.get("end_time"));
            } catch (Exception e) {
                throw new IllegalStateException("时间格式不正确");
            }
            return support.json(support.ok(buddy.reschedule(id, me, deadline, start, end)), HttpStatus.OK);
        });
    }

    // 任务 9（2026-11-09）：站内留言——详情页「给组织者留言」，登录用户报名前后均可。
    @PostMapping("/activities/{id}/messages")
    public ResponseEntity<String> postMessage(@PathVariable long id,
            @RequestBody Map<String, String> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/activities/{id}/messages", support.toJson(body),
                () -> support.json(support.ok(buddy.postMessage(id, me, body.get("content"))), HttpStatus.OK));
    }

    // 任务 17（2026-11-10）：留言查询接口——组织者看全部留言，本人只看自己发过的
    // （各附组织者回复）；他人留言不可见。详情页「我发过的留言」区用此接口。
    @GetMapping("/activities/{id}/messages")
    public ResponseEntity<String> messages(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        var act = jdbc.queryForMap("SELECT organizer_id FROM activity WHERE id=?", id);
        var list = Objects.equals(((Number) act.get("organizer_id")).longValue(), me)
                ? buddy.listMessages(id)
                : buddy.listMyMessages(id, me);
        return support.json(support.ok(list), HttpStatus.OK);
    }

    // 任务 9：组织者在名单视图回一条（每条留言只能回一条，回复走站内通知给留言人）。
    @PostMapping("/activities/{id}/messages/{mid}/reply")
    public ResponseEntity<String> replyMessage(@PathVariable long id, @PathVariable long mid,
            @RequestBody Map<String, String> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/activities/{id}/messages/{mid}/reply", support.toJson(body),
                () -> support.json(support.ok(buddy.replyMessage(id, me, mid, body.get("content"))), HttpStatus.OK));
    }

    // 阶段一 B-CEM-03：组织者有据移出成员。
    @PostMapping("/activities/{id}/members/{userId}/remove")
    public ResponseEntity<String> removeMember(@PathVariable long id, @PathVariable long userId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        String reason = body != null && body.get("reason") instanceof String
                ? (String) body.get("reason") : null;
        return idempotent(req, me, "POST /api/v1/activities/{id}/members/{userId}/remove",
                support.toJson(body == null ? Map.of() : body), () -> support.json(
                        support.ok(buddy.removeMember(id, me, userId, reason)), HttpStatus.OK));
    }

    // ---- 报名 / 退出 / 放弃候补 / 递补 ----

    @PostMapping("/activities/{id}/signup")
    public ResponseEntity<String> signup(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        boolean confirm = flag(body, "confirmConflict");
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/activities/{id}/signup", bodyJson, () -> {
            // 阶段四 CEM-09：下架活动不可报名（大厅已隐藏，直连详情页也拦住）。
            if (governance.isDelisted(id)) throw new IllegalStateException("活动已下架，无法报名");
            return support.json(support.ok(buddy.signup(id, me, confirm)), HttpStatus.OK);
        });
    }

    @PostMapping("/participations/{id}/withdraw")
    public ResponseEntity<String> withdraw(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/participations/{id}/withdraw", "{}",
                () -> support.json(support.ok(buddy.withdraw(id, me)), HttpStatus.OK));
    }

    // 阶段一 A7：放弃候补（与正式退出分开）。
    @PostMapping("/participations/{id}/abandon")
    public ResponseEntity<String> abandon(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/participations/{id}/abandon", "{}",
                () -> support.json(support.ok(buddy.abandon(id, me)), HttpStatus.OK));
    }

    // 阶段一 A1：参与事件流，本人或活动组织者可见。
    @GetMapping("/participations/{id}/events")
    public ResponseEntity<String> events(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        return support.json(support.ok(buddy.listEvents(id, me)), HttpStatus.OK);
    }

    @PostMapping("/invitations/{id}/accept")
    public ResponseEntity<String> accept(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        boolean confirm = flag(body, "confirmConflict");
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/invitations/{id}/accept", bodyJson,
                () -> support.json(support.ok(buddy.respondInvitation(id, me, true, confirm)), HttpStatus.OK));
    }

    @PostMapping("/invitations/{id}/reject")
    public ResponseEntity<String> reject(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/invitations/{id}/reject", "{}",
                () -> support.json(support.ok(buddy.respondInvitation(id, me, false, false)), HttpStatus.OK));
    }

    // ---- 我的活动 / 通知 ----

    @GetMapping("/my")
    public ResponseEntity<String> my(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        var rows = jdbc.queryForList(
                "SELECT p.*, a.title, a.location, a.capacity, a.start_time, a.deadline, " +
                // 阶段四 CEM-09：下架活动仍在“我的活动”中展示，附带标记供前端提示。
                "(SELECT COALESCE(d.delisted,0) FROM activity_delist d WHERE d.activity_id=a.id) AS delisted, " +
                "(SELECT i.id FROM invitation i WHERE i.participation_id=p.id AND i.status='PENDING' ORDER BY i.id DESC LIMIT 1) AS invitation_id, " +
                "(SELECT i.expires_at FROM invitation i WHERE i.participation_id=p.id AND i.status='PENDING' ORDER BY i.id DESC LIMIT 1) AS invitation_expires_at " +
                "FROM participation p JOIN activity a ON a.id=p.activity_id WHERE p.user_id=? " +
                "ORDER BY p.updated_at DESC, p.id DESC", me);
        int[] pp = ApiSupport.pagination(page, pageSize);
        return support.json(support.ok(ApiSupport.page(rows, pp[0], pp[1])), HttpStatus.OK);
    }

    // 任务 2：我组织的活动（带正式/候补/预留人数）。新接口，不改 /api/my 的返回形状
    // （测试与前端都按列表使用它），苏晴在前端另调此接口渲染「我组织的」一栏。
    @GetMapping("/my/organized")
    public ResponseEntity<String> myOrganized(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        var rows = jdbc.queryForList(
                "SELECT a.*, " +
                // 阶段四 CEM-09：同 /my，下架活动保留展示并附带标记。
                "(SELECT COALESCE(d.delisted,0) FROM activity_delist d WHERE d.activity_id=a.id) AS delisted, " +
                "(SELECT COUNT(*) FROM participation p WHERE p.activity_id=a.id AND p.status='FORMAL') AS formal_count, " +
                "(SELECT COUNT(*) FROM participation p WHERE p.activity_id=a.id AND p.status='WAITING') AS waiting_count, " +
                "(SELECT COUNT(*) FROM invitation i JOIN participation p ON p.id=i.participation_id " +
                " WHERE p.activity_id=a.id AND i.status='PENDING' AND i.expires_at > now()) AS reserved_count " +
                "FROM activity a WHERE a.organizer_id=? ORDER BY a.start_time, a.id", me);
        int[] pp = ApiSupport.pagination(page, pageSize);
        return support.json(support.ok(ApiSupport.page(rows, pp[0], pp[1])), HttpStatus.OK);
    }

    @GetMapping("/notifications")
    public ResponseEntity<String> notifications(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        // 任务 4 配合（2026-11-10）：邀请通知附加 expires_at（LEFT JOIN invitation），
        // 前端倒计时优先用该字段，解析通知文案为兜底；非邀请类通知该字段为 null。
        // 阶段一：只返回已发布通知（outbox），data 额外保留 unread 字段。
        var all = buddy.listNotifications(me);
        int[] pp = ApiSupport.pagination(page, pageSize);
        Map<String, Object> data = ApiSupport.page(all, pp[0], pp[1]);
        data.put("unread", buddy.unreadCount(me));
        return support.json(support.ok(data), HttpStatus.OK);
    }

    @PostMapping("/notifications/{id}/read")
    public ResponseEntity<String> readNotification(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/notifications/{id}/read", "{}",
                () -> support.json(support.ok(buddy.readNotification(me, id)), HttpStatus.OK));
    }

    @PostMapping("/notifications/read-all")
    public ResponseEntity<String> readAll(@RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        return idempotent(req, me, "POST /api/v1/notifications/read-all", "{}", () -> {
            jdbc.update("UPDATE notification SET read_at=? " +
                            "WHERE user_id=? AND read_at IS NULL AND status='PUBLISHED'",
                    Timestamp.valueOf(LocalDateTime.now()), me);
            return support.json(support.ok(Map.of()), HttpStatus.OK);
        });
    }

    // ---- 阶段四 CEM-09：用户侧治理（举报 / 申诉 / 账号找回） ----

    @PostMapping("/complaints")
    public ResponseEntity<String> fileComplaint(@RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/complaints", bodyJson, () ->
                support.json(support.ok(strIds(governance.fileComplaint(me,
                        num(body, "activity_id"), num(body, "subject_user_id"),
                        str(body, "category"), str(body, "reason")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/complaints/mine")
    public ResponseEntity<String> myComplaints(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        return support.json(support.ok(pageGovernance(
                governance.listComplaints(me, null, 500), page, pageSize)), HttpStatus.OK);
    }

    @GetMapping("/complaints/{id}")
    public ResponseEntity<String> complaintDetail(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        Map<String, Object> row = governance.getComplaint(id);
        if (row == null) throw new IllegalStateException("记录不存在");
        Long applicantId = longOf(row.get("applicant_id"));
        // 仅举报人本人或管理员可见；他人一律按不存在处理，不泄露记录存在性。
        if (applicantId == null || (applicantId != me && !governance.isAdmin(me)))
            throw new IllegalStateException("记录不存在");
        return support.json(support.ok(strIds(row, GOVERNANCE_ID_KEYS)), HttpStatus.OK);
    }

    @PostMapping("/appeals")
    public ResponseEntity<String> fileAppeal(@RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = require(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/appeals", bodyJson, () ->
                support.json(support.ok(strIds(governance.fileAppeal(me,
                        num(body, "attendance_id"), num(body, "decision_id"),
                        num(body, "complaint_id"), str(body, "reason")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/appeals/mine")
    public ResponseEntity<String> myAppeals(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        return support.json(support.ok(pageGovernance(
                governance.listAppeals(me, null, 500), page, pageSize)), HttpStatus.OK);
    }

    @GetMapping("/appeals/{id}")
    public ResponseEntity<String> appealDetail(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = require(h);
        Map<String, Object> row = governance.getAppeal(id);
        if (row == null) throw new IllegalStateException("记录不存在");
        Long applicantId = longOf(row.get("applicant_id"));
        if (applicantId == null || (applicantId != me && !governance.isAdmin(me)))
            throw new IllegalStateException("记录不存在");
        return support.json(support.ok(strIds(row, GOVERNANCE_ID_KEYS)), HttpStatus.OK);
    }

    // 账号找回 / 封禁复核：未登录也可提交与查询。幂等分组 userId 传 0（带键时以 0 分组）。
    @PostMapping("/recovery")
    public ResponseEntity<String> submitRecovery(@RequestBody(required = false) Map<String, Object> body,
            HttpServletRequest req) {
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, 0L, "POST /api/v1/recovery", bodyJson, () ->
                support.json(support.ok(strIds(governance.submitRecovery(
                        str(body, "account"), intVal(body, "request_type"),
                        str(body, "reason"), str(body, "contact")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/recovery/{id}")
    public ResponseEntity<String> recoveryStatus(@PathVariable long id,
            @RequestParam(value = "query_token", required = false) String queryToken) {
        return support.json(support.ok(strIds(
                governance.recoveryStatus(id, queryToken), GOVERNANCE_ID_KEYS)), HttpStatus.OK);
    }

    @PostMapping("/recovery/reset")
    public ResponseEntity<String> recoveryReset(@RequestBody(required = false) Map<String, Object> body,
            HttpServletRequest req) {
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, 0L, "POST /api/v1/recovery/reset", bodyJson, () ->
                support.json(support.ok(governance.resetPasswordWithCredential(
                        str(body, "credential"), str(body, "new_password"))), HttpStatus.OK));
    }

    // ---- 阶段四 CEM-09：管理员治理工作台（全部 requireAdmin） ----

    @GetMapping("/admin/overview")
    public ResponseEntity<String> adminOverview(
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(governance.overview()), HttpStatus.OK);
    }

    @GetMapping("/admin/admins")
    public ResponseEntity<String> adminAdmins(
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(strIds(governance.listAdmins())), HttpStatus.OK);
    }

    @PostMapping("/admin/admins")
    public ResponseEntity<String> appointAdmin(@RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/admins", bodyJson, () ->
                support.json(support.ok(strIds(governance.appointAdmin(me,
                        requiredLong(body, "user_id"), str(body, "note")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @PostMapping("/admin/admins/{userId}/revoke")
    public ResponseEntity<String> revokeAdmin(@PathVariable long userId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/admins/{userId}/revoke", bodyJson, () ->
                support.json(support.ok(strIds(governance.revokeAdmin(me, userId,
                        str(body, "reason")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/users")
    public ResponseEntity<String> adminUsers(@RequestParam(required = false) String q,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listUsers(q, 500), page, pageSize)), HttpStatus.OK);
    }

    @GetMapping("/admin/users/{id}/ban-impact")
    public ResponseEntity<String> banImpact(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        long me = requireAdmin(h);
        return support.json(support.ok(strIds(
                governance.banImpact(me, id), GOVERNANCE_ID_KEYS)), HttpStatus.OK);
    }

    @PostMapping("/admin/users/{id}/ban")
    public ResponseEntity<String> banUser(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/users/{id}/ban", bodyJson, () ->
                support.json(support.ok(strIds(governance.banUser(me, id,
                        intVal(body, "days"), str(body, "reason"),
                        str(body, "future_formal"), str(body, "organized")),
                        GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @PostMapping("/admin/users/{id}/unban")
    public ResponseEntity<String> unbanUser(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/users/{id}/unban", bodyJson, () ->
                support.json(support.ok(strIds(governance.unbanUser(me, id,
                        str(body, "reason")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/bans")
    public ResponseEntity<String> adminBans(
            @RequestParam(value = "expired_only", required = false) Boolean expiredOnly,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listBans(Boolean.TRUE.equals(expiredOnly)), page, pageSize)), HttpStatus.OK);
    }

    @GetMapping("/admin/activities")
    public ResponseEntity<String> adminActivities(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listActivitiesAdmin(), page, pageSize)), HttpStatus.OK);
    }

    @PostMapping("/admin/activities/{id}/delist")
    public ResponseEntity<String> delistActivity(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/activities/{id}/delist", bodyJson, () ->
                support.json(support.ok(strIds(governance.delistActivity(me, id,
                        str(body, "reason")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @PostMapping("/admin/activities/{id}/relist")
    public ResponseEntity<String> relistActivity(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/activities/{id}/relist", bodyJson, () ->
                support.json(support.ok(strIds(governance.relistActivity(me, id,
                        str(body, "reason")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/complaints")
    public ResponseEntity<String> adminComplaints(
            @RequestParam(required = false) String state,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listComplaints(null, state, 500), page, pageSize)), HttpStatus.OK);
    }

    @PostMapping("/admin/complaints/{id}/handle")
    public ResponseEntity<String> handleComplaint(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/complaints/{id}/handle", bodyJson, () ->
                support.json(support.ok(strIds(governance.handleComplaint(me, id,
                        str(body, "outcome"), str(body, "result")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/appeals")
    public ResponseEntity<String> adminAppeals(
            @RequestParam(required = false) String state,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listAppeals(null, state, 500), page, pageSize)), HttpStatus.OK);
    }

    @PostMapping("/admin/appeals/{id}/review")
    public ResponseEntity<String> reviewAppeal(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/appeals/{id}/review", bodyJson, () ->
                support.json(support.ok(strIds(governance.reviewAppeal(me, id,
                        str(body, "outcome"), str(body, "new_result"), str(body, "result")),
                        GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/recovery")
    public ResponseEntity<String> adminRecovery(
            @RequestParam(required = false) String state,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listRecovery(state, 500), page, pageSize)), HttpStatus.OK);
    }

    @PostMapping("/admin/recovery/{id}/review")
    public ResponseEntity<String> reviewRecovery(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/recovery/{id}/review", bodyJson, () ->
                support.json(support.ok(strIds(governance.reviewRecovery(me, id,
                        str(body, "outcome"), str(body, "note")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/credit-reviews")
    public ResponseEntity<String> adminCreditReviews(
            @RequestParam(required = false) String state,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listCreditReviews(state, 500), page, pageSize)), HttpStatus.OK);
    }

    @PostMapping("/admin/credit-reviews/{id}/handle")
    public ResponseEntity<String> handleCreditReview(@PathVariable long id,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String h,
            HttpServletRequest req) {
        long me = requireAdmin(h);
        String bodyJson = support.toJson(body == null ? Map.of() : body);
        return idempotent(req, me, "POST /api/v1/admin/credit-reviews/{id}/handle", bodyJson, () ->
                support.json(support.ok(strIds(governance.handleCreditReview(me, id,
                        str(body, "outcome"), str(body, "note")), GOVERNANCE_ID_KEYS)), HttpStatus.OK));
    }

    @GetMapping("/admin/actions")
    public ResponseEntity<String> adminActions(@RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize,
            @RequestHeader(value = "Authorization", required = false) String h) {
        requireAdmin(h);
        return support.json(support.ok(pageGovernance(
                governance.listActions(500), page, pageSize)), HttpStatus.OK);
    }

    // ---- 演示重置（仅演示用）：清空业务数据并恢复种子 ----
    // 修复前：无需任何登录即可调用，且不清空内存会话。序列重启后新注册用户
    // 会复用旧用户的 id，旧 token 不经任何校验就能冒用新用户（已复现）。
    // 修复后：必须登录才能重置；种子写入成功后清空全部会话；删除 + 种子在同一事务内。
    @Transactional
    @PostMapping("/demo/reset")
    public ResponseEntity<String> reset(@RequestHeader(value = "Authorization", required = false) String h) {
        require(h);
        // 阶段四 CEM-09 治理新表：按 FK 依赖从子到父清空（须先于 attendance_revision /
        // activity / app_user 清空）。
        jdbc.update("DELETE FROM governance_action");
        jdbc.update("DELETE FROM appeal");
        jdbc.update("DELETE FROM complaint");
        jdbc.update("DELETE FROM recovery_request");
        jdbc.update("DELETE FROM user_ban");
        jdbc.update("DELETE FROM activity_delist");
        jdbc.update("DELETE FROM governance_decision");
        jdbc.update("DELETE FROM administrator");
        // 阶段一新表也一并清空，否则序列重置后旧事件/回执会挂到新数据上。
        // 阶段三 CEM-10 新表：引用 attendance / attendance_revision，先于其清空。
        jdbc.update("DELETE FROM credit_recalc_history");
        jdbc.update("DELETE FROM credit_review");
        jdbc.update("DELETE FROM credit_entry");
        // 阶段二 CEM-08 新表：按外键依赖从子到父清空。
        jdbc.update("DELETE FROM evaluation");
        jdbc.update("DELETE FROM attendance_revision");
        jdbc.update("DELETE FROM attendance");
        jdbc.update("DELETE FROM checkin");
        jdbc.update("DELETE FROM checkin_attempt");
        jdbc.update("DELETE FROM participation_events");
        jdbc.update("DELETE FROM command_receipts");
        jdbc.update("DELETE FROM feedback");
        jdbc.update("DELETE FROM notification");
        jdbc.update("DELETE FROM invitation");
        jdbc.update("DELETE FROM participation");
        jdbc.update("DELETE FROM activity");
        jdbc.update("DELETE FROM app_user");
        // 重置自增序列，避免演示时编号无限增长
        // MySQL 没有 SEQUENCE：表已清空，AUTO_INCREMENT = 1 即从 1 开始；
        // PostgreSQL 保持原 ALTER SEQUENCE。
        if (mysql) {
            jdbc.execute("ALTER TABLE app_user AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE activity AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE participation AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE invitation AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE notification AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE participation_events AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE command_receipts AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE evaluation AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE attendance_revision AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE attendance AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE checkin AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE checkin_attempt AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE credit_entry AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE credit_recalc_history AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE credit_review AUTO_INCREMENT = 1");
            // 阶段四 CEM-09：仅 5 张治理表有自增主键（user_ban / activity_delist /
            // administrator 的主键是外键列，无自增，不重置）。
            jdbc.execute("ALTER TABLE governance_action AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE appeal AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE complaint AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE recovery_request AUTO_INCREMENT = 1");
            jdbc.execute("ALTER TABLE governance_decision AUTO_INCREMENT = 1");
        } else {
            jdbc.execute("ALTER SEQUENCE app_user_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE activity_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE participation_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE invitation_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE notification_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE participation_events_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE command_receipts_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE evaluation_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE attendance_revision_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE attendance_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE checkin_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE checkin_attempt_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE credit_entry_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE credit_recalc_history_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE credit_review_id_seq RESTART WITH 1");
            // 阶段四 CEM-09：5 张有 BIGSERIAL 主键的治理表。
            jdbc.execute("ALTER SEQUENCE governance_action_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE appeal_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE complaint_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE recovery_request_id_seq RESTART WITH 1");
            jdbc.execute("ALTER SEQUENCE governance_decision_id_seq RESTART WITH 1");
        }
        // 种子逻辑与 SeedRunner 相同，这里直接复用其 run()（空库时写入）
        new com.campusbuddy.service.SeedRunner(jdbc).run();
        auth.clearSessions();
        return support.json(support.ok(Map.of()), HttpStatus.OK);
    }
}
