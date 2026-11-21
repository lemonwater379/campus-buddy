package com.campusbuddy.controller;

import com.campusbuddy.service.AuthService;
import com.campusbuddy.service.ConflictException;
import com.campusbuddy.service.EvidenceService;
import com.campusbuddy.service.ForbiddenException;
import com.campusbuddy.service.RateLimitException;
import com.campusbuddy.service.ValidationException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * DG-BE-07（SDD §6.12）：证据文件上传与下载。
 * <p>
 * POST /api/v1/evidence 只上传并返回文件编号（暂存，尚不可下载）；案件提交时由服务层
 * 绑定归属。GET /api/v1/evidence/{id} 每次读取都重新校验所属案件权限（暂存一律 403；
 * 已绑定仅申请人本人或启用管理员），以二进制流下发——证据目录不做任何静态映射。
 * 本控制器不共享 ApiV1Controller 的局部 @ExceptionHandler，错误映射按
 * AdminAttendanceController 的同口径在本类内复制。
 */
@RestController
@RequestMapping("/api/v1")
public class EvidenceController {
    private final ApiSupport support;
    private final AuthService auth;
    private final EvidenceService evidence;

    public EvidenceController(ApiSupport support, AuthService auth, EvidenceService evidence) {
        this.support = support;
        this.auth = auth;
        this.evidence = evidence;
    }

    /** 登录 + ACTIVE 校验（照 ApiV1Controller.uploadImage 口径）：未登录 / 已停用返回 null。 */
    private Long authenticate(String h) {
        Long me = auth.userId(h);
        if (me == null) return null;
        if (!"ACTIVE".equals(auth.me(me).get("status"))) return null;
        return me;
    }

    private ResponseEntity<String> unauthorized(String h) {
        Long me = auth.userId(h);
        String message = me == null ? "未登录" : "账号已停用";
        return support.json(support.error("UNAUTHORIZED", message, null),
                HttpStatus.UNAUTHORIZED);
    }

    @PostMapping("/evidence")
    public ResponseEntity<?> upload(
            @RequestParam(value = "file", required = false) MultipartFile file,
            @RequestHeader(value = "Authorization", required = false) String h) {
        Long me = authenticate(h);
        if (me == null) return unauthorized(h);
        if (file == null || file.isEmpty())
            throw new ValidationException("file", "请选择要上传的文件");
        byte[] bytes;
        try {
            bytes = file.getBytes();
        } catch (IOException e) {
            throw new IllegalStateException("文件读取失败，请重试", e);
        }
        Map<String, Object> data = evidence.store(me, file.getOriginalFilename(),
                file.getContentType(), bytes);
        return support.json(support.ok(data), HttpStatus.OK);
    }

    @GetMapping("/evidence/{id}")
    public ResponseEntity<?> download(@PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String h) {
        Long me = authenticate(h);
        if (me == null) return unauthorized(h);
        EvidenceService.EvidenceFile file = evidence.loadForDownload(id, me);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(file.mimeType()))
                .header(HttpHeaders.CONTENT_DISPOSITION, contentDisposition(file.originalName()))
                .contentLength(file.bytes().length)
                .body(file.bytes());
    }

    /** Content-Disposition：ASCII 兜底名（非 ASCII/引号/反斜杠替换为 _）+ UTF-8 编码名。 */
    private static String contentDisposition(String originalName) {
        String name = originalName == null || originalName.isBlank() ? "evidence" : originalName;
        StringBuilder ascii = new StringBuilder();
        for (char c : name.toCharArray()) {
            ascii.append(c >= 0x20 && c <= 0x7E && c != '"' && c != '\\' ? c : '_');
        }
        String encoded = URLEncoder.encode(name, StandardCharsets.UTF_8).replace("+", "%20");
        return "attachment; filename=\"" + ascii + "\"; filename*=UTF-8''" + encoded;
    }

    // ---- 错误映射（与 ApiV1Controller / AdminAttendanceController 同口径） ----

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

    /** multipart 超限在进入控制器前被拦截，单独给明确文案（上限口径与证据 5MB 一致）。 */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<String> handleMaxUpload(MaxUploadSizeExceededException e) {
        String message = "文件不能超过 5MB";
        return support.json(support.error("VALIDATION", message,
                Map.of("fieldErrors", Map.of("file", message))), HttpStatus.BAD_REQUEST);
    }

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
}
