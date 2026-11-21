package com.campusbuddy.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 启动期数据库结构自检（fail-fast）。
 * <p>
 * 背景：2026-11-18 Azure 事故——旧库缺 notification.status / notification.publish_at 两列，
 * 旧版应用带病启动、健康检查照常 ok，报名/通知接口全部 500。本检查把该失败前移到启动期：
 * 26 张业务表必须存在，4 个迁移补列必须已按定义落地，任一不符即中止启动。
 * <p>
 * 补列来源（按当前方言选用 pg / mysql 文件）：
 * <ul>
 *   <li>notification.status、notification.publish_at：
 *       design-review-20261115/phase1/migrations/001-outbox-pg.sql / 001-outbox-mysql.sql</li>
 *   <li>notification.sender_id：
 *       daily-simulation/runs/2026-11-09/migrations/001-notification-types-1109-pg.sql / -mysql.sql</li>
 *   <li>activity.cover_url：
 *       ui-workflow/runs/2026-11-17-register/migrations/001-cover-pg.sql / 001-cover-mysql.sql</li>
 * </ul>
 * 逃生开关：app.schema-check.enabled=false（环境变量 SCHEMA_CHECK_ENABLED），仅供临时排障。
 * <p>
 * {@code @Order(1)} 保证先于无 @Order 的 SeedRunner（CommandLineRunner）执行：
 * 结构不全时不再让种子数据写入雪上加霜。
 */
@Component
@Order(1)
public class SchemaReadinessChecker implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(SchemaReadinessChecker.class);

    /**
     * 26 张业务表，全部由启动建表脚本 schema.sql / schema-mysql.sql 创建。
     * auth_session 由 AuthService 运行时懒初始化管理，不纳入 REQUIRED_TABLES。
     */
    private static final List<String> REQUIRED_TABLES = List.of(
            "app_user", "activity", "participation", "invitation", "notification", "feedback",
            "command_receipts", "participation_events", "checkin", "checkin_attempt", "attendance",
            "attendance_revision", "evaluation", "credit_entry", "credit_recalc_history",
            "credit_review", "administrator", "governance_decision", "user_ban", "activity_delist",
            "complaint", "appeal", "recovery_request", "evidence_file",
            "governance_action", "activity_change_log");

    private static final String OUTBOX_MIGRATION =
            "design-review-20261115/phase1/migrations/001-outbox-%s.sql";
    private static final String NOTIFICATION_TYPES_MIGRATION =
            "daily-simulation/runs/2026-11-09/migrations/001-notification-types-1109-%s.sql";
    private static final String COVER_MIGRATION =
            "ui-workflow/runs/2026-11-17-register/migrations/001-cover-%s.sql";

    private final JdbcTemplate jdbc;
    private final boolean enabled;

    public SchemaReadinessChecker(JdbcTemplate jdbc,
                                  @Value("${app.schema-check.enabled:true}") boolean enabled) {
        this.jdbc = jdbc;
        this.enabled = enabled;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (!enabled) {
            log.warn("结构自检已跳过（app.schema-check.enabled=false）");
            return;
        }
        String productName = jdbc.execute((ConnectionCallback<String>) con ->
                con.getMetaData().getDatabaseProductName());
        Dialect dialect = Dialect.of(productName);
        String schema = currentSchema(dialect);

        // 一次性收集全部缺失/不符项，避免修一项、重启、再暴露下一项。
        List<String> problems = new ArrayList<>();
        checkTables(dialect, schema, problems);
        checkColumns(dialect, schema, problems);
        if (!problems.isEmpty()) {
            problems.forEach(log::error);
            throw new IllegalStateException("数据库结构自检失败：共 " + problems.size()
                    + " 项缺失或不符 —— " + String.join("；", problems));
        }
        log.info("结构自检通过（26 表 + 4 个迁移补列）");
    }

    /** 当前 schema：PostgreSQL 取 current_schema()，MySQL 取 DATABASE()。 */
    private String currentSchema(Dialect dialect) {
        String schema = dialect == Dialect.POSTGRES
                ? jdbc.queryForObject("SELECT current_schema()", String.class)
                : jdbc.queryForObject("SELECT DATABASE()", String.class);
        if (schema == null || schema.isBlank()) {
            throw new IllegalStateException("无法确定当前数据库 schema（" + dialect.productName + "）");
        }
        return schema;
    }

    private void checkTables(Dialect dialect, String schema, List<String> problems) {
        for (String table : REQUIRED_TABLES) {
            Integer count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM information_schema.tables " +
                            "WHERE table_schema = ? AND table_name = ?",
                    Integer.class, schema, table);
            if (count == null || count == 0) {
                problems.add("缺失表 " + table
                        + "（应由启动建表脚本 " + dialect.schemaScript + " 创建）");
            }
        }
    }

    private void checkColumns(Dialect dialect, String schema, List<String> problems) {
        String outbox = migration(OUTBOX_MIGRATION, dialect);
        String notificationTypes = migration(NOTIFICATION_TYPES_MIGRATION, dialect);
        String cover = migration(COVER_MIGRATION, dialect);

        Map<String, Object> status = column(schema, "notification", "status");
        if (status == null) {
            problems.add("缺少列 notification.status（应由 " + outbox + " 提供）");
        } else {
            String nullable = value(status, "is_nullable");
            if (!"NO".equals(nullable)) {
                problems.add("notification.status 须为 NOT NULL（is_nullable=NO），当前 is_nullable="
                        + display(nullable) + "（来源：" + outbox + "）");
            }
            String defaultValue = value(status, "column_default");
            if (defaultValue == null || !defaultValue.contains("PUBLISHED")) {
                problems.add("notification.status 默认值须包含 PUBLISHED，当前 column_default="
                        + display(defaultValue) + "（来源：" + outbox + "）");
            }
        }

        Map<String, Object> publishAt = column(schema, "notification", "publish_at");
        if (publishAt == null) {
            problems.add("缺少列 notification.publish_at（应由 " + outbox + " 提供）");
        } else {
            String dataType = value(publishAt, "data_type");
            if (!dialect.publishAtType.equals(dataType)) {
                problems.add("notification.publish_at 类型须为 " + dialect.publishAtType
                        + "，当前 data_type=" + display(dataType) + "（来源：" + outbox + "）");
            }
        }

        checkNullable(schema, "notification", "sender_id", "YES", notificationTypes, problems);
        checkNullable(schema, "activity", "cover_url", "YES", cover, problems);
    }

    /** 校验某列存在且 is_nullable 为期望值（YES/NO）；不存在时一并记为缺失项。 */
    private void checkNullable(String schema, String table, String columnName, String expected,
                               String source, List<String> problems) {
        Map<String, Object> row = column(schema, table, columnName);
        if (row == null) {
            problems.add("缺少列 " + table + "." + columnName + "（应由 " + source + " 提供）");
            return;
        }
        String nullable = value(row, "is_nullable");
        if (!expected.equals(nullable)) {
            problems.add(table + "." + columnName + " 的 is_nullable 须为 " + expected
                    + "，当前为 " + display(nullable) + "（来源：" + source + "）");
        }
    }

    private Map<String, Object> column(String schema, String table, String columnName) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns " +
                        "WHERE table_schema = ? AND table_name = ? AND column_name = ?",
                schema, table, columnName);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private static String migration(String template, Dialect dialect) {
        return String.format(Locale.ROOT, template, dialect.fileSuffix);
    }

    /** 结果集列名大小写按驱动可能不同，统一忽略大小写取值。 */
    private static String value(Map<String, Object> row, String key) {
        for (Map.Entry<String, Object> entry : row.entrySet()) {
            if (key.equalsIgnoreCase(entry.getKey())) {
                return entry.getValue() == null ? null : entry.getValue().toString();
            }
        }
        return null;
    }

    private static String display(String value) {
        return value == null ? "null" : value;
    }

    private enum Dialect {
        POSTGRES("PostgreSQL", "pg", "timestamp without time zone",
                "backend/src/main/resources/schema.sql"),
        MYSQL("MySQL", "mysql", "timestamp",
                "backend/src/main/resources/schema-mysql.sql");

        private final String productName;
        private final String fileSuffix;
        private final String publishAtType;
        private final String schemaScript;

        Dialect(String productName, String fileSuffix, String publishAtType, String schemaScript) {
            this.productName = productName;
            this.fileSuffix = fileSuffix;
            this.publishAtType = publishAtType;
            this.schemaScript = schemaScript;
        }

        static Dialect of(String productName) {
            if (productName != null && productName.contains(POSTGRES.productName)) {
                return POSTGRES;
            }
            if (productName != null && productName.contains(MYSQL.productName)) {
                return MYSQL;
            }
            throw new IllegalStateException("数据库结构自检不支持当前数据库：" + productName
                    + "（仅支持 PostgreSQL / MySQL；可用 app.schema-check.enabled=false 跳过）");
        }
    }
}
