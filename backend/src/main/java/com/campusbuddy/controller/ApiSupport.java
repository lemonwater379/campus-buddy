package com.campusbuddy.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.*;

/**
 * /api/v1 公共支撑：统一返回体、ID 字符串化、分页解析与切片、SHA-256。
 * 统一返回体固定为 {"success","code","message","data","serverTime","traceId"}，
 * 所有 data 在包装前都会过一遍 deepStringifyIds：前端契约要求 ID 一律为字符串。
 */
@Component
public class ApiSupport {
    /** JSON 中需要字符串化的键（只处理 Number 值，null / 已是字符串的原样保留）。 */
    private static final Set<String> ID_KEYS = Set.of(
            "id", "activity_id", "organizer_id", "user_id",
            "participation_id", "invitation_id", "sender_id");

    /** 返回 JSON 字符串时显式带 UTF-8：StringHttpMessageConverter 在响应头无 charset 时
     *  可能按 ISO-8859-1 写，中文业务文案会乱码。 */
    private static final MediaType JSON_UTF8 =
            new MediaType(MediaType.APPLICATION_JSON, StandardCharsets.UTF_8);

    private final ObjectMapper mapper;

    public ApiSupport(ObjectMapper mapper) { this.mapper = mapper; }

    /** 构造统一返回体。成功：code=OK / message=ok；错误码与文案由调用方给出。 */
    public Map<String, Object> envelope(boolean success, String code, String message, Object data) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("success", success);
        out.put("code", code);
        out.put("message", message);
        out.put("data", deepStringifyIds(data));
        out.put("serverTime", LocalDateTime.now().toString());
        out.put("traceId", UUID.randomUUID().toString());
        return out;
    }

    public Map<String, Object> ok(Object data) {
        return envelope(true, "OK", "ok", data);
    }

    public Map<String, Object> error(String code, String message, Object data) {
        return envelope(false, code, message, data);
    }

    /** 序列化为 JSON 字符串响应。 */
    public ResponseEntity<String> json(Object body, HttpStatus status) {
        try {
            return ResponseEntity.status(status).contentType(JSON_UTF8)
                    .body(mapper.writeValueAsString(body));
        } catch (Exception e) {
            throw new IllegalStateException("响应序列化失败", e);
        }
    }

    /** 原样返回已存的 JSON 字符串（幂等回执重放），避免二次序列化。 */
    public ResponseEntity<String> raw(String body, int status) {
        return ResponseEntity.status(status).contentType(JSON_UTF8).body(body);
    }

    /** 请求体转 JSON 字符串（幂等摘要用）。 */
    public String toJson(Object body) {
        try {
            return mapper.writeValueAsString(body);
        } catch (Exception e) {
            throw new IllegalStateException("请求序列化失败", e);
        }
    }

    /** 递归 Map/List，把 ID 键上的 Number 值转成字符串；保持原顺序。 */
    public static Object deepStringifyIds(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<Object, Object> out = new LinkedHashMap<>();
            for (Map.Entry<?, ?> e : map.entrySet()) {
                Object k = e.getKey();
                Object v = e.getValue();
                if (k instanceof String key && ID_KEYS.contains(key) && v instanceof Number n) {
                    out.put(k, n.toString());
                } else {
                    out.put(k, deepStringifyIds(v));
                }
            }
            return out;
        }
        if (value instanceof List<?> list) {
            List<Object> out = new ArrayList<>(list.size());
            for (Object item : list) out.add(deepStringifyIds(item));
            return out;
        }
        return value;
    }

    /** 分页参数：page 默认 1，pageSize 默认 20 并钳制在 1..100。 */
    public static int[] pagination(Integer page, Integer pageSize) {
        int p = (page == null || page < 1) ? 1 : page;
        int ps = (pageSize == null) ? 20 : pageSize;
        if (ps < 1) ps = 1;
        if (ps > 100) ps = 100;
        return new int[]{p, ps};
    }

    /** 全量列表在 controller 切片（数据量小，避免 service 改签名）。
     *  page 越界时返回空 items，但 total 仍是全量条数。 */
    public static Map<String, Object> page(List<?> items, int page, int pageSize) {
        int total = items == null ? 0 : items.size();
        long startL = (long) (page - 1) * pageSize;
        int start = (int) Math.min(startL, total);
        int end = Math.min(start + pageSize, total);
        List<?> pageItems;
        if (total == 0 || start >= total) pageItems = List.of();
        else pageItems = new ArrayList<>(items.subList(start, end));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", pageItems);
        out.put("page", page);
        out.put("pageSize", pageSize);
        out.put("total", total);
        return out;
    }

    /** SHA-256 十六进制小写（幂等请求摘要）。 */
    public static String sha256(String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(text.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }
}
