package com.campusbuddy.controller;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * 框架级异常的统一返回体兜底（2026-11-18 批次1 F6 修复）。
 *
 * 为什么需要它：415（Content-Type 不支持）、405（方法不支持）、404（路径不存在）这类异常
 * 是 Spring MVC 在「进入控制器方法之前」抛出的（媒体类型匹配、请求映射、静态资源兜底），
 * 控制器内部的 @ExceptionHandler 覆盖不到这些场景；没有对应 handler 时会落到兜底
 * Exception handler，把本应是客户端错误的 415 变成 500，404 / 405 则返回 Spring 默认
 * 错误体而不是 {success,code,message,data,serverTime,traceId} 统一 envelope。
 * 这里用 @RestControllerAdvice 在框架层统一映射成与 ApiV1Controller 一致的 envelope。
 */
@RestControllerAdvice
public class GlobalErrorAdvice {

    private final ApiSupport support;

    public GlobalErrorAdvice(ApiSupport support) {
        this.support = support;
    }

    /** 请求 Content-Type 不被接口接受（如用 text/plain 发 JSON）→ 415。 */
    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<String> handleMediaTypeNotSupported(HttpMediaTypeNotSupportedException e) {
        return support.json(support.error("ERROR", "请求内容类型不支持", null),
                HttpStatus.UNSUPPORTED_MEDIA_TYPE);
    }

    /** 路径存在但 HTTP 方法不被支持（如 GET 打 POST 接口）→ 405。 */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<String> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        return support.json(support.error("ERROR", "请求方法不支持", null),
                HttpStatus.METHOD_NOT_ALLOWED);
    }

    /** 未知路径 → 404（Spring 6.1 起静态资源未命中抛 NoResourceFoundException）。 */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<String> handleNoResource(NoResourceFoundException e) {
        return support.json(support.error("ERROR", "接口不存在", null),
                HttpStatus.NOT_FOUND);
    }
}
