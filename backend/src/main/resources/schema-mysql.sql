-- 校园活动组队与候补平台 · MySQL 8 建表脚本（与 schema.sql 同规则）
-- 与 PostgreSQL 版一一对应：8 张表（含阶段一 command_receipts / participation_events）、
-- 容量/唯一/邀请/候补硬规则、中文分类 CHECK 含“其他”。
-- MySQL 8 方言要点：
--   * BIGINT AUTO_INCREMENT 代替 BIGSERIAL；DATETIME DEFAULT NOW() 代替 TIMESTAMP DEFAULT now()
--   * MySQL 不支持 CREATE INDEX IF NOT EXISTS，且 Spring 的 sql init 每次启动都会跑脚本，
--     索引必须定义在 CREATE TABLE 内部，表用 CREATE TABLE IF NOT EXISTS，
--     这样重复执行不报错；UNIQUE 约束同样放表内。
--   * CHECK 约束保留（MySQL 8.0.16+ 支持）；char_length() MySQL 同名可用。
--   * 显式 ENGINE=InnoDB（外键生效）与 utf8mb4（中文分类/昵称不乱码）。
--   * MySQL 8 忽略列级 REFERENCES；实际外键由表级 CONSTRAINT ... FOREIGN KEY 建立。
--     IF NOT EXISTS 不给旧表补约束；已有库需另跑 20261120-002 MySQL 迁移。
CREATE TABLE IF NOT EXISTS app_user (
    id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account       VARCHAR(32) NOT NULL UNIQUE CHECK (char_length(account) BETWEEN 4 AND 32),
    password_hash VARCHAR(255) NOT NULL,
    nickname      VARCHAR(30) NOT NULL CHECK (char_length(nickname) BETWEEN 1 AND 30),
    contact       VARCHAR(100) NOT NULL DEFAULT '',
    role          VARCHAR(10) NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
    status        VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at    DATETIME NOT NULL DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS activity (
    id           BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    organizer_id BIGINT NOT NULL REFERENCES app_user(id),
    title        VARCHAR(50) NOT NULL CHECK (char_length(title) BETWEEN 1 AND 50),
    category     VARCHAR(10) NOT NULL CHECK (category IN ('羽毛球', '桌游', '学习组', '其他')),
    description  TEXT NOT NULL CHECK (char_length(description) <= 2000),
    conditions   VARCHAR(500) NOT NULL DEFAULT '' CHECK (char_length(conditions) <= 500),
    location     VARCHAR(100) NOT NULL CHECK (char_length(location) BETWEEN 1 AND 100),
    capacity     INT NOT NULL CHECK (capacity BETWEEN 1 AND 100),
    deadline     DATETIME NOT NULL,
    start_time   DATETIME NOT NULL,
    end_time     DATETIME NOT NULL,
    status       VARCHAR(10) NOT NULL DEFAULT 'OPEN'
                 CHECK (status IN ('OPEN', 'READY', 'RUNNING', 'ENDED', 'CANCELLED')),
    -- 2026-11-17：活动封面图（站内相对路径 /img/cover-N.webp 或 /uploads/<uuid>.<ext>；
    -- NULL = 前端按活动 id 轮换默认封面）。
    cover_url    VARCHAR(255) NULL,
    created_at   DATETIME NOT NULL DEFAULT NOW(),
    updated_at   DATETIME NOT NULL DEFAULT NOW(),
    CHECK (deadline <= start_time AND start_time < end_time),
    CONSTRAINT fk_activity_organizer_id FOREIGN KEY (organizer_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS participation (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activity(id),
    user_id     BIGINT NOT NULL REFERENCES app_user(id),
    status      VARCHAR(10) NOT NULL CHECK (status IN
                    ('FORMAL', 'WAITING', 'INVITED', 'WITHDRAWN', 'EXPIRED', 'CANCELLED')),
    queued_at   DATETIME,
    joined_at   DATETIME,
    updated_at  DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (activity_id, user_id),
    INDEX idx_part_activity_status (activity_id, status, queued_at, id),
    CONSTRAINT fk_participation_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_participation_user_id FOREIGN KEY (user_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS invitation (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    participation_id BIGINT NOT NULL REFERENCES participation(id),
    status           VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN
                         ('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED', 'INVALID')),
    issued_at        DATETIME NOT NULL,
    expires_at       DATETIME NOT NULL,
    responded_at     DATETIME,
    event_key        VARCHAR(100) NOT NULL UNIQUE,
    CHECK (issued_at < expires_at),
    INDEX idx_inv_status_expires (status, expires_at),
    CONSTRAINT fk_invitation_participation_id FOREIGN KEY (participation_id) REFERENCES participation(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notification (
    id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES app_user(id),
    activity_id   BIGINT REFERENCES activity(id),
    invitation_id BIGINT REFERENCES invitation(id),
    type          VARCHAR(10) NOT NULL CHECK (type IN ('报名', '候补', '邀请', '变更', '退出', '取消', '留言')),
    content       TEXT NOT NULL CHECK (char_length(content) <= 1000),
    event_key     VARCHAR(100) NOT NULL,
    sender_id     BIGINT NULL REFERENCES app_user(id),
    read_at       DATETIME,
    created_at    DATETIME NOT NULL DEFAULT NOW(),
    -- 阶段一 B-CEM-07（2026-11-15）：通知发件箱。新库默认 PUBLISHED 保证种子/历史语义；
    -- 业务代码写入时显式给 PENDING，由发布任务按 publish_at 翻为 PUBLISHED。
    status        VARCHAR(16) NOT NULL DEFAULT 'PUBLISHED',
    -- 与 001-outbox-mysql.sql 及活库对齐：publish_at 须为 TIMESTAMP（DATETIME 与迁移/活库不一致，2026-11-20 R5 修正）。
    publish_at    TIMESTAMP NULL,
    UNIQUE (user_id, event_key),
    INDEX idx_notif_user_created (user_id, created_at DESC),
    CONSTRAINT fk_notification_user_id FOREIGN KEY (user_id) REFERENCES app_user(id),
    CONSTRAINT fk_notification_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_notification_invitation_id FOREIGN KEY (invitation_id) REFERENCES invitation(id),
    CONSTRAINT fk_notification_sender_id FOREIGN KEY (sender_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feedback (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    participation_id BIGINT NOT NULL UNIQUE REFERENCES participation(id),
    score            INT NOT NULL CHECK (score BETWEEN 1 AND 5),
    content          VARCHAR(500) NOT NULL DEFAULT '' CHECK (char_length(content) <= 500),
    created_at       DATETIME NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_feedback_participation_id FOREIGN KEY (participation_id) REFERENCES participation(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段一 A2（2026-11-15）：写接口幂等回执。按 (用户, 接口, 幂等键) 唯一，
-- 同一请求摘要回放首次响应；摘要不同由接口层报 409。
CREATE TABLE IF NOT EXISTS command_receipts (
    id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    endpoint      VARCHAR(220) NOT NULL,
    idem_key      VARCHAR(128) NOT NULL,
    request_hash  VARCHAR(64) NOT NULL,
    response_body TEXT NOT NULL,
    http_status   INT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, endpoint, idem_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段一 A1（2026-11-15）：参与状态变迁流水（报名/退出/放弃/邀请/取消/改期/移出），
-- 只增不改，供历史展示与后续治理/信用引用。
CREATE TABLE IF NOT EXISTS participation_events (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    participation_id BIGINT NOT NULL,
    activity_id      BIGINT NOT NULL,
    user_id          BIGINT NOT NULL,
    event_type       VARCHAR(32) NOT NULL,
    from_status      VARCHAR(16) NULL,
    to_status        VARCHAR(16) NULL,
    detail           VARCHAR(500) NULL,
    created_at       DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_part_event_pid (participation_id),
    INDEX idx_part_event_aid (activity_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段二 CEM-08（2026-11-15）：签到事实。一人一活动一条，签到是证据不是结论。
CREATE TABLE IF NOT EXISTS checkin (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    activity_id      BIGINT NOT NULL REFERENCES activity(id),
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    participation_id BIGINT NOT NULL REFERENCES participation(id),
    checkin_at       DATETIME NOT NULL,
    UNIQUE (activity_id, user_id),
    INDEX idx_checkin_activity (activity_id),
    CONSTRAINT fk_checkin_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_checkin_user_id FOREIGN KEY (user_id) REFERENCES app_user(id),
    CONSTRAINT fk_checkin_participation_id FOREIGN KEY (participation_id) REFERENCES participation(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段二 CEM-08：签到错码限流计数（连续错误与锁定截止）。
CREATE TABLE IF NOT EXISTS checkin_attempt (
    id           BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    activity_id  BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    fail_count   INT NOT NULL DEFAULT 0,
    locked_until DATETIME NULL,
    last_fail_at DATETIME NULL,
    updated_at   DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (activity_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段二 CEM-08：出勤记录（活动开始时正式资格快照）。result 是核对结论，
-- finalized_at 非空表示核对期届满已定版封存（阶段四复核前不可再改）。
CREATE TABLE IF NOT EXISTS attendance (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    participation_id BIGINT NOT NULL UNIQUE REFERENCES participation(id),
    activity_id      BIGINT NOT NULL REFERENCES activity(id),
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    result           VARCHAR(24) NOT NULL DEFAULT 'UNVERIFIED'
                     CHECK (result IN ('PRESENT','ABSENT_VERIFIED','EXEMPT','UNVERIFIED')),
    version          BIGINT NOT NULL DEFAULT 1,
    decided_by       BIGINT NULL,
    finalized_at     DATETIME NULL,
    created_at       DATETIME NOT NULL DEFAULT NOW(),
    updated_at       DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (activity_id, user_id),
    INDEX idx_attendance_activity (activity_id),
    CONSTRAINT fk_attendance_participation_id FOREIGN KEY (participation_id) REFERENCES participation(id),
    CONSTRAINT fk_attendance_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_attendance_user_id FOREIGN KEY (user_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段二 CEM-08：出勤事实版本（只追加不覆盖）。actor_id 为空=系统形成；
-- available_at / appeal_until 供阶段三信用结算与阶段四申诉引用。
CREATE TABLE IF NOT EXISTS attendance_revision (
    id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    attendance_id BIGINT NOT NULL REFERENCES attendance(id),
    version       BIGINT NOT NULL,
    actor_id      BIGINT NULL,
    result        VARCHAR(24) NOT NULL,
    reason        TEXT NULL,
    available_at  DATETIME NULL,
    appeal_until  DATETIME NULL,
    created_at    DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (attendance_id, version),
    CONSTRAINT fk_attendance_revision_attendance_id FOREIGN KEY (attendance_id) REFERENCES attendance(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段二 CEM-08：活动评价（独立表；现有 feedback 表与 notification 留言互不相干，不动）。
CREATE TABLE IF NOT EXISTS evaluation (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    activity_id      BIGINT NOT NULL REFERENCES activity(id),
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    participation_id BIGINT NULL,
    rating           INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content          VARCHAR(500) NOT NULL DEFAULT '' CHECK (char_length(content) <= 500),
    created_at       DATETIME NOT NULL DEFAULT NOW(),
    updated_at       DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (activity_id, user_id),
    INDEX idx_evaluation_activity (activity_id),
    CONSTRAINT fk_evaluation_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_evaluation_user_id FOREIGN KEY (user_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段三 CEM-10（2026-11-15）：信用流水。当前分是按事实时间序列（活动结束时间、
-- 活动 id、参与 id）从 100 起逐笔钳制 0–100 重放的投影，不落用户表；
-- 每份出勤事实版本至多结算一次；事实更正后由重算更新同一行并另留审计批次。
CREATE TABLE IF NOT EXISTS credit_entry (
    id               BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    attendance_id    BIGINT NOT NULL REFERENCES attendance(id),
    fact_version     BIGINT NOT NULL,
    fact_result      VARCHAR(24) NOT NULL,
    activity_id      BIGINT NOT NULL,
    participation_id BIGINT NOT NULL,
    fact_end_time    DATETIME NOT NULL,
    delta            INT NOT NULL,
    score_before     INT NOT NULL CHECK (score_before BETWEEN 0 AND 100),
    score_after      INT NOT NULL CHECK (score_after BETWEEN 0 AND 100),
    settled_at       DATETIME NOT NULL DEFAULT NOW(),
    created_at       DATETIME NOT NULL DEFAULT NOW(),
    updated_at       DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (attendance_id, fact_version),
    INDEX idx_credit_entry_user (user_id, fact_end_time, activity_id, participation_id),
    INDEX idx_credit_entry_attendance (attendance_id),
    CONSTRAINT fk_credit_entry_user_id FOREIGN KEY (user_id) REFERENCES app_user(id),
    CONSTRAINT fk_credit_entry_attendance_id FOREIGN KEY (attendance_id) REFERENCES attendance(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段三 CEM-10：信用重算审计批次（只记前后快照，不维护第二套当前分）。
CREATE TABLE IF NOT EXISTS credit_recalc_history (
    id                 BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES app_user(id),
    source_revision_id BIGINT NULL REFERENCES attendance_revision(id),
    before_snapshot    TEXT NOT NULL,
    after_snapshot     TEXT NOT NULL,
    created_at         DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_credit_recalc_user (user_id, created_at),
    CONSTRAINT fk_credit_recalc_history_user_id FOREIGN KEY (user_id) REFERENCES app_user(id),
    CONSTRAINT fk_credit_recalc_history_source_revision_id FOREIGN KEY (source_revision_id) REFERENCES attendance_revision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段三 CEM-10：近 30 日累计 3 次核实缺席的管理员审查记录（阶段四工作台消费）。
-- 本阶段只落表：尚无管理员通知通道，不向普通用户发通知，避免误导。
CREATE TABLE IF NOT EXISTS credit_review (
    id                    BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES app_user(id),
    trigger_attendance_id BIGINT NOT NULL REFERENCES attendance(id),
    absence_count         INT NOT NULL,
    window_start          DATETIME NOT NULL,
    window_end            DATETIME NOT NULL,
    status                VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','REVIEWED','DISMISSED')),
    created_at            DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, trigger_attendance_id),
    INDEX idx_credit_review_user (user_id, status),
    CONSTRAINT fk_credit_review_user_id FOREIGN KEY (user_id) REFERENCES app_user(id),
    CONSTRAINT fk_credit_review_trigger_attendance_id FOREIGN KEY (trigger_attendance_id) REFERENCES attendance(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 阶段四 CEM-09（2026-11-15）：平台治理。管理员身份与授权、不可变决定历史
-- （governance_decision）、当前封禁态（user_ban）、活动下架标记（activity_delist）、
-- 举报 / 申诉 / 找回恢复案件，以及治理操作审计。
CREATE TABLE IF NOT EXISTS administrator (
    user_id            BIGINT NOT NULL PRIMARY KEY REFERENCES app_user(id),
    enabled            INT NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    authorized_at      DATETIME NOT NULL DEFAULT NOW(),
    authorization_note VARCHAR(500) NOT NULL DEFAULT '',
    created_at         DATETIME NOT NULL DEFAULT NOW(),
    updated_at         DATETIME NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_administrator_user_id FOREIGN KEY (user_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS governance_decision (
    id                     BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    actor_id               BIGINT NULL REFERENCES app_user(id),
    previous_decision_id   BIGINT NULL REFERENCES governance_decision(id),
    decision_type          VARCHAR(24) NOT NULL CHECK (decision_type IN
                               ('BAN','UNBAN','DELIST','RELIST','COMPLAINT','ATTENDANCE','REVIEW','RECOVERY','REMOVAL')),
    subject_user_id        BIGINT NULL REFERENCES app_user(id),
    activity_id            BIGINT NULL REFERENCES activity(id),
    participation_id       BIGINT NULL REFERENCES participation(id),
    attendance_revision_id BIGINT NULL REFERENCES attendance_revision(id),
    reason                 VARCHAR(500) NOT NULL DEFAULT '',
    result                 VARCHAR(1000) NOT NULL DEFAULT '',
    decided_at             DATETIME NOT NULL DEFAULT NOW(),
    expires_at             DATETIME NULL,
    available_at           DATETIME NULL,
    appeal_until           DATETIME NULL,
    execution_state        TEXT NULL,
    created_at             DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_gov_decision_subject (subject_user_id, decision_type, decided_at),
    INDEX idx_gov_decision_activity (activity_id),
    INDEX idx_gov_decision_revision (attendance_revision_id),
    CONSTRAINT fk_governance_decision_actor_id FOREIGN KEY (actor_id) REFERENCES app_user(id),
    CONSTRAINT fk_governance_decision_previous_decision_id FOREIGN KEY (previous_decision_id) REFERENCES governance_decision(id),
    CONSTRAINT fk_governance_decision_subject_user_id FOREIGN KEY (subject_user_id) REFERENCES app_user(id),
    CONSTRAINT fk_governance_decision_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_governance_decision_participation_id FOREIGN KEY (participation_id) REFERENCES participation(id),
    CONSTRAINT fk_governance_decision_attendance_revision_id FOREIGN KEY (attendance_revision_id) REFERENCES attendance_revision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_ban (
    user_id          BIGINT NOT NULL PRIMARY KEY REFERENCES app_user(id),
    decision_id      BIGINT NOT NULL REFERENCES governance_decision(id),
    reason           VARCHAR(500) NOT NULL DEFAULT '',
    banned_at        DATETIME NOT NULL DEFAULT NOW(),
    expires_at       DATETIME NOT NULL,
    lifted_at        DATETIME NULL,
    lifted_by        BIGINT NULL REFERENCES app_user(id),
    lift_decision_id BIGINT NULL REFERENCES governance_decision(id),
    created_at       DATETIME NOT NULL DEFAULT NOW(),
    updated_at       DATETIME NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_user_ban_user_id FOREIGN KEY (user_id) REFERENCES app_user(id),
    CONSTRAINT fk_user_ban_decision_id FOREIGN KEY (decision_id) REFERENCES governance_decision(id),
    CONSTRAINT fk_user_ban_lifted_by FOREIGN KEY (lifted_by) REFERENCES app_user(id),
    CONSTRAINT fk_user_ban_lift_decision_id FOREIGN KEY (lift_decision_id) REFERENCES governance_decision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS activity_delist (
    activity_id BIGINT NOT NULL PRIMARY KEY REFERENCES activity(id),
    delisted    INT NOT NULL DEFAULT 0 CHECK (delisted IN (0, 1)),
    decision_id BIGINT NULL REFERENCES governance_decision(id),
    reason      VARCHAR(500) NOT NULL DEFAULT '',
    updated_by  BIGINT NULL REFERENCES app_user(id),
    created_at  DATETIME NOT NULL DEFAULT NOW(),
    updated_at  DATETIME NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_activity_delist_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_activity_delist_decision_id FOREIGN KEY (decision_id) REFERENCES governance_decision(id),
    CONSTRAINT fk_activity_delist_updated_by FOREIGN KEY (updated_by) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS complaint (
    id              BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    applicant_id    BIGINT NOT NULL REFERENCES app_user(id),
    activity_id     BIGINT NULL REFERENCES activity(id),
    subject_user_id BIGINT NULL REFERENCES app_user(id),
    category        VARCHAR(24) NOT NULL DEFAULT '其他',
    reason          VARCHAR(2000) NOT NULL,
    handler_id      BIGINT NULL REFERENCES app_user(id),
    decision_id     BIGINT NULL REFERENCES governance_decision(id),
    state           VARCHAR(24) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','RESOLVED','DISMISSED')),
    submitted_at    DATETIME NOT NULL DEFAULT NOW(),
    handled_at      DATETIME NULL,
    created_at      DATETIME NOT NULL DEFAULT NOW(),
    updated_at      DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_complaint_state (state, submitted_at),
    INDEX idx_complaint_applicant (applicant_id),
    CONSTRAINT fk_complaint_applicant_id FOREIGN KEY (applicant_id) REFERENCES app_user(id),
    CONSTRAINT fk_complaint_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_complaint_subject_user_id FOREIGN KEY (subject_user_id) REFERENCES app_user(id),
    CONSTRAINT fk_complaint_handler_id FOREIGN KEY (handler_id) REFERENCES app_user(id),
    CONSTRAINT fk_complaint_decision_id FOREIGN KEY (decision_id) REFERENCES governance_decision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS appeal (
    id                 BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    applicant_id       BIGINT NOT NULL REFERENCES app_user(id),
    decision_id        BIGINT NOT NULL REFERENCES governance_decision(id),
    complaint_id       BIGINT NULL REFERENCES complaint(id),
    reviewer_id        BIGINT NULL REFERENCES app_user(id),
    result_decision_id BIGINT NULL REFERENCES governance_decision(id),
    reason             VARCHAR(2000) NOT NULL,
    state              VARCHAR(24) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','UPHELD','OVERTURNED','CORRECTED')),
    submitted_at       DATETIME NOT NULL DEFAULT NOW(),
    reviewed_at        DATETIME NULL,
    created_at         DATETIME NOT NULL DEFAULT NOW(),
    updated_at         DATETIME NOT NULL DEFAULT NOW(),
    -- S2（2026-11-21）：MySQL 无部分唯一索引，用生成列实现「仅 PENDING 唯一」（存量库迁移见 merge/work/server-ddl-s2-mysql.sql）。
    pending_decision_id  BIGINT GENERATED ALWAYS AS (CASE WHEN state = 'PENDING' THEN decision_id ELSE NULL END) STORED,
    pending_complaint_id BIGINT GENERATED ALWAYS AS (CASE WHEN state = 'PENDING' THEN complaint_id ELSE NULL END) STORED,
    UNIQUE (pending_decision_id),
    UNIQUE (pending_complaint_id),
    INDEX idx_appeal_state (state, submitted_at),
    INDEX idx_appeal_applicant (applicant_id),
    CONSTRAINT fk_appeal_applicant_id FOREIGN KEY (applicant_id) REFERENCES app_user(id),
    CONSTRAINT fk_appeal_decision_id FOREIGN KEY (decision_id) REFERENCES governance_decision(id),
    CONSTRAINT fk_appeal_complaint_id FOREIGN KEY (complaint_id) REFERENCES complaint(id),
    CONSTRAINT fk_appeal_reviewer_id FOREIGN KEY (reviewer_id) REFERENCES app_user(id),
    CONSTRAINT fk_appeal_result_decision_id FOREIGN KEY (result_decision_id) REFERENCES governance_decision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recovery_request (
    id                 BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    applicant_id       BIGINT NOT NULL REFERENCES app_user(id),
    request_type       INT NOT NULL CHECK (request_type IN (1, 2)),
    decision_id        BIGINT NULL REFERENCES governance_decision(id),
    reviewer_id        BIGINT NULL REFERENCES app_user(id),
    result_decision_id BIGINT NULL REFERENCES governance_decision(id),
    reason             VARCHAR(2000) NOT NULL,
    contact            VARCHAR(100) NOT NULL DEFAULT '',
    state              VARCHAR(24) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','APPROVED','REJECTED','COMPLETED')),
    query_hash         VARCHAR(64) NOT NULL,
    reset_hash         VARCHAR(64) NULL,
    reset_expires_at   DATETIME NULL,
    applied_at         DATETIME NOT NULL DEFAULT NOW(),
    reviewed_at        DATETIME NULL,
    recovered_at       DATETIME NULL,
    created_at         DATETIME NOT NULL DEFAULT NOW(),
    updated_at         DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_recovery_applicant (applicant_id, state),
    INDEX idx_recovery_state (state, applied_at),
    CONSTRAINT fk_recovery_request_applicant_id FOREIGN KEY (applicant_id) REFERENCES app_user(id),
    CONSTRAINT fk_recovery_request_decision_id FOREIGN KEY (decision_id) REFERENCES governance_decision(id),
    CONSTRAINT fk_recovery_request_reviewer_id FOREIGN KEY (reviewer_id) REFERENCES app_user(id),
    CONSTRAINT fk_recovery_request_result_decision_id FOREIGN KEY (result_decision_id) REFERENCES governance_decision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- DG-BE-07（SDD §7）：暂存证据的 complaint_id、appeal_id、recovery_request_id 均为 NULL，暂存期间不可下载。
CREATE TABLE IF NOT EXISTS evidence_file (
    id                  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    owner_id            BIGINT NOT NULL REFERENCES app_user(id),
    complaint_id        BIGINT NULL REFERENCES complaint(id),
    appeal_id           BIGINT NULL REFERENCES appeal(id),
    recovery_request_id BIGINT NULL REFERENCES recovery_request(id),
    storage_key         VARCHAR(255) NOT NULL,
    original_name       VARCHAR(255) NOT NULL,
    mime_type           VARCHAR(64) NOT NULL,
    size_bytes          BIGINT NOT NULL,
    sha256              BINARY(32) NOT NULL,
    created_at          DATETIME NOT NULL DEFAULT NOW(),
    UNIQUE (storage_key),
    INDEX idx_evidence_file_complaint_id (complaint_id),
    INDEX idx_evidence_file_appeal_id (appeal_id),
    INDEX idx_evidence_file_recovery_request_id (recovery_request_id),
    CONSTRAINT fk_evidence_file_owner_id FOREIGN KEY (owner_id) REFERENCES app_user(id),
    CONSTRAINT fk_evidence_file_complaint_id FOREIGN KEY (complaint_id) REFERENCES complaint(id),
    CONSTRAINT fk_evidence_file_appeal_id FOREIGN KEY (appeal_id) REFERENCES appeal(id),
    CONSTRAINT fk_evidence_file_recovery_request_id FOREIGN KEY (recovery_request_id) REFERENCES recovery_request(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS governance_action (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    actor_id    BIGINT NULL REFERENCES app_user(id),
    action      VARCHAR(32) NOT NULL,
    target_type VARCHAR(24) NOT NULL,
    target_id   BIGINT NULL,
    decision_id BIGINT NULL REFERENCES governance_decision(id),
    reason      VARCHAR(500) NOT NULL DEFAULT '',
    detail      TEXT NULL,
    request_id  VARCHAR(64) NULL,
    created_at  DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_governance_action_time (created_at, id),
    INDEX idx_governance_action_target (target_type, target_id),
    CONSTRAINT fk_governance_action_actor_id FOREIGN KEY (actor_id) REFERENCES app_user(id),
    CONSTRAINT fk_governance_action_decision_id FOREIGN KEY (decision_id) REFERENCES governance_decision(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- DG-BE-06（2026-11-20）：活动字段级变更日志（一行一字段；field 为空表示整活动级事件如 CREATE/CANCEL 的状态行由 field=status 记）。
CREATE TABLE IF NOT EXISTS activity_change_log (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activity(id),
    actor_id    BIGINT NULL REFERENCES app_user(id),
    change_type VARCHAR(24) NOT NULL,
    field       VARCHAR(32) NULL,
    old_value   TEXT NULL,
    new_value   TEXT NULL,
    reason      VARCHAR(500) NULL,
    created_at  DATETIME NOT NULL DEFAULT NOW(),
    INDEX idx_activity_change_log_activity (activity_id, id),
    CONSTRAINT fk_activity_change_log_activity_id FOREIGN KEY (activity_id) REFERENCES activity(id),
    CONSTRAINT fk_activity_change_log_actor_id FOREIGN KEY (actor_id) REFERENCES app_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- DG-BE-02 结构清单补齐（2026-11-20）：会话表此前仅由 AuthService 运行时懒建，此处补声明式 DDL；
-- 运行时懒初始化口径不变，本表不纳入 SchemaReadinessChecker 的 REQUIRED_TABLES。
CREATE TABLE IF NOT EXISTS auth_session (
    token_hash     VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id        BIGINT NOT NULL,
    created_at     BIGINT NOT NULL,
    last_access_at BIGINT NOT NULL,
    INDEX idx_auth_session_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
