package com.campusbuddy.service;

/**
 * 带稳定错误码的业务异常：HTTP 400，code 由调用方给出（如 ACTIVITY_CANCELLED），
 * 供前端按 code 分支，不必再正则匹配 message。
 * 继承 IllegalStateException 以兼容既有“业务错误一律 400”的处理口径。
 */
public class CodedException extends IllegalStateException {
    private final String code;

    public CodedException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() { return code; }
}
