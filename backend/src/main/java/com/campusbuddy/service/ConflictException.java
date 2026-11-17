package com.campusbuddy.service;

/**
 * 业务冲突（如报名时间与已有活动重叠）。与普通 IllegalStateException 的区别：
 * 返回 HTTP 409 + code=CONFLICT，并把携带的数据放进统一返回体的 data。
 */
public class ConflictException extends RuntimeException {
    private final Object data;

    public ConflictException(String message, Object data) {
        super(message);
        this.data = data;
    }

    public Object data() { return data; }
}
