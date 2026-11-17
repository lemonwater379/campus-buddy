package com.campusbuddy.service;

import java.util.Map;

/**
 * 字段级校验错误：HTTP 400 + code=VALIDATION，data.fieldErrors 按字段给出提示。
 * 继承 IllegalStateException 以兼容既有“业务错误一律 400”的处理口径。
 */
public class ValidationException extends IllegalStateException {
    private final Map<String, String> fieldErrors;

    public ValidationException(Map<String, String> fieldErrors, String message) {
        super(message);
        this.fieldErrors = fieldErrors;
    }

    public ValidationException(String field, String message) {
        this(Map.of(field, message), message);
    }

    public Map<String, String> fieldErrors() { return fieldErrors; }
}
