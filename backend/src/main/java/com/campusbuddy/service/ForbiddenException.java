package com.campusbuddy.service;

/**
 * 权限不足：控制器统一映射为 HTTP 403 + code=FORBIDDEN。
 * 与普通业务错误（IllegalStateException → 400）区分，未登录 / 非管理员都走这里。
 */
public class ForbiddenException extends RuntimeException {
    public ForbiddenException(String message) {
        super(message);
    }
}
