package com.campusbuddy.service;

/** 限流（如签到错码锁定）：HTTP 429 + code=TOO_MANY_ATTEMPTS（SDD §11 错误码表）。
 *  不继承 IllegalStateException，避免被当普通业务错误映射为 400。 */
public class RateLimitException extends RuntimeException {
    public RateLimitException(String message) { super(message); }
}
