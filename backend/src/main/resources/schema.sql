-- 校园活动组队与候补平台 · PostgreSQL 建表脚本（SRS 第 4 章）
-- 注意：PostgreSQL 中 USER 是保留字，故 SRS 的 user 表在此命名为 app_user，
-- 其余表名、字段、唯一约束、状态枚举与 SRS 一一对应。
-- 核心规则：有效占用 = 正式人数 + 未过期待确认邀请数，必须 <= capacity；
-- 同一活动同一用户只有一条当前参与记录；邀请终态只能转换一次。
CREATE TABLE IF NOT EXISTS app_user (
    id            BIGSERIAL PRIMARY KEY,
    account       VARCHAR(32) NOT NULL UNIQUE CHECK (char_length(account) BETWEEN 4 AND 32),
    password_hash VARCHAR(255) NOT NULL,
    nickname      VARCHAR(30) NOT NULL CHECK (char_length(nickname) BETWEEN 1 AND 30),
    contact       VARCHAR(100) NOT NULL DEFAULT '',
    role          VARCHAR(10) NOT NULL DEFAULT 'USER' CHECK (role IN ('USER', 'ADMIN')),
    status        VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activity (
    id           BIGSERIAL PRIMARY KEY,
    organizer_id BIGINT NOT NULL REFERENCES app_user(id),
    title        VARCHAR(50) NOT NULL CHECK (char_length(title) BETWEEN 1 AND 50),
    category     VARCHAR(10) NOT NULL CHECK (category IN ('羽毛球', '桌游', '学习组', '其他')),
    description  TEXT NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
    conditions   VARCHAR(500) NOT NULL DEFAULT '' CHECK (char_length(conditions) <= 500),
    location     VARCHAR(100) NOT NULL CHECK (char_length(location) BETWEEN 1 AND 100),
    capacity     INT NOT NULL CHECK (capacity BETWEEN 1 AND 100),
    deadline     TIMESTAMP NOT NULL,
    start_time   TIMESTAMP NOT NULL,
    end_time     TIMESTAMP NOT NULL,
    status       VARCHAR(10) NOT NULL DEFAULT 'OPEN'
                 CHECK (status IN ('OPEN', 'READY', 'RUNNING', 'ENDED', 'CANCELLED')),
    -- 2026-11-17：活动封面图（站内相对路径 /img/cover-N.webp 或 /uploads/<uuid>.<ext>；
    -- NULL = 前端按活动 id 轮换默认封面）。
    cover_url    VARCHAR(255),
    created_at   TIMESTAMP NOT NULL DEFAULT now(),
    updated_at   TIMESTAMP NOT NULL DEFAULT now(),
    CHECK (deadline <= start_time AND start_time < end_time)
);

CREATE TABLE IF NOT EXISTS participation (
    id          BIGSERIAL PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activity(id),
    user_id     BIGINT NOT NULL REFERENCES app_user(id),
    status      VARCHAR(10) NOT NULL CHECK (status IN
                    ('FORMAL', 'WAITING', 'INVITED', 'WITHDRAWN', 'EXPIRED', 'CANCELLED')),
    queued_at   TIMESTAMP,
    joined_at   TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (activity_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_part_activity_status
    ON participation(activity_id, status, queued_at, id);

CREATE TABLE IF NOT EXISTS invitation (
    id               BIGSERIAL PRIMARY KEY,
    participation_id BIGINT NOT NULL REFERENCES participation(id),
    status           VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN
                         ('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED', 'INVALID')),
    issued_at        TIMESTAMP NOT NULL,
    expires_at       TIMESTAMP NOT NULL,
    responded_at     TIMESTAMP,
    event_key        VARCHAR(100) NOT NULL UNIQUE,
    CHECK (issued_at < expires_at)
);
CREATE INDEX IF NOT EXISTS idx_inv_status_expires ON invitation(status, expires_at);

CREATE TABLE IF NOT EXISTS notification (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES app_user(id),
    activity_id   BIGINT REFERENCES activity(id),
    invitation_id BIGINT REFERENCES invitation(id),
    type          VARCHAR(10) NOT NULL CHECK (type IN ('报名', '候补', '邀请', '变更', '退出', '取消', '留言')),
    content       TEXT NOT NULL CHECK (char_length(content) <= 1000),
    event_key     VARCHAR(100) NOT NULL,
    sender_id     BIGINT REFERENCES app_user(id),
    read_at       TIMESTAMP,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    -- 阶段一 B-CEM-07（2026-11-15）：通知发件箱。新库默认 PUBLISHED 保证种子/历史语义；
    -- 业务代码写入时显式给 PENDING，由发布任务按 publish_at 翻为 PUBLISHED。
    status        VARCHAR(16) NOT NULL DEFAULT 'PUBLISHED',
    publish_at    TIMESTAMP,
    UNIQUE (user_id, event_key)
);
CREATE INDEX IF NOT EXISTS idx_notif_user_created ON notification(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id               BIGSERIAL PRIMARY KEY,
    participation_id BIGINT NOT NULL UNIQUE REFERENCES participation(id),
    score            INT NOT NULL CHECK (score BETWEEN 1 AND 5),
    content          VARCHAR(500) NOT NULL DEFAULT '' CHECK (char_length(content) <= 500),
    created_at       TIMESTAMP NOT NULL DEFAULT now()
);

-- 阶段一 A2（2026-11-15）：写接口幂等回执。按 (用户, 接口, 幂等键) 唯一，
-- 同一请求摘要回放首次响应；摘要不同由接口层报 409。
CREATE TABLE IF NOT EXISTS command_receipts (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    endpoint      VARCHAR(220) NOT NULL,
    idem_key      VARCHAR(128) NOT NULL,
    request_hash  VARCHAR(64) NOT NULL,
    response_body TEXT NOT NULL,
    http_status   INT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (user_id, endpoint, idem_key)
);

-- 阶段一 A1（2026-11-15）：参与状态变迁流水（报名/退出/放弃/邀请/取消/改期/移出），
-- 只增不改，供历史展示与后续治理/信用引用。
CREATE TABLE IF NOT EXISTS participation_events (
    id               BIGSERIAL PRIMARY KEY,
    participation_id BIGINT NOT NULL,
    activity_id      BIGINT NOT NULL,
    user_id          BIGINT NOT NULL,
    event_type       VARCHAR(32) NOT NULL,
    from_status      VARCHAR(16),
    to_status        VARCHAR(16),
    detail           VARCHAR(500),
    created_at       TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_part_event_pid ON participation_events(participation_id);
CREATE INDEX IF NOT EXISTS idx_part_event_aid ON participation_events(activity_id);

-- 阶段二 CEM-08（2026-11-15）：签到事实。一人一活动一条，签到是证据不是结论。
CREATE TABLE IF NOT EXISTS checkin (
    id               BIGSERIAL PRIMARY KEY,
    activity_id      BIGINT NOT NULL REFERENCES activity(id),
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    participation_id BIGINT NOT NULL REFERENCES participation(id),
    checkin_at       TIMESTAMP NOT NULL,
    UNIQUE (activity_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_checkin_activity ON checkin(activity_id);

-- 阶段二 CEM-08：签到错码限流计数（连续错误与锁定截止）。
CREATE TABLE IF NOT EXISTS checkin_attempt (
    id           BIGSERIAL PRIMARY KEY,
    activity_id  BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    fail_count   INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMP,
    last_fail_at TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (activity_id, user_id)
);

-- 阶段二 CEM-08：出勤记录（活动开始时正式资格快照）。result 是核对结论，
-- finalized_at 非空表示核对期届满已定版封存（阶段四复核前不可再改）。
CREATE TABLE IF NOT EXISTS attendance (
    id               BIGSERIAL PRIMARY KEY,
    participation_id BIGINT NOT NULL UNIQUE REFERENCES participation(id),
    activity_id      BIGINT NOT NULL REFERENCES activity(id),
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    result           VARCHAR(24) NOT NULL DEFAULT 'UNVERIFIED'
                     CHECK (result IN ('PRESENT','ABSENT_VERIFIED','EXEMPT','UNVERIFIED')),
    version          BIGINT NOT NULL DEFAULT 1,
    decided_by       BIGINT,
    finalized_at     TIMESTAMP,
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (activity_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_attendance_activity ON attendance(activity_id);

-- 阶段二 CEM-08：出勤事实版本（只追加不覆盖）。actor_id 为空=系统形成；
-- available_at / appeal_until 供阶段三信用结算与阶段四申诉引用。
CREATE TABLE IF NOT EXISTS attendance_revision (
    id            BIGSERIAL PRIMARY KEY,
    attendance_id BIGINT NOT NULL REFERENCES attendance(id),
    version       BIGINT NOT NULL,
    actor_id      BIGINT,
    result        VARCHAR(24) NOT NULL,
    reason        TEXT,
    available_at  TIMESTAMP,
    appeal_until  TIMESTAMP,
    created_at    TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (attendance_id, version)
);

-- 阶段二 CEM-08：活动评价（独立表；现有 feedback 表与 notification 留言互不相干，不动）。
CREATE TABLE IF NOT EXISTS evaluation (
    id               BIGSERIAL PRIMARY KEY,
    activity_id      BIGINT NOT NULL REFERENCES activity(id),
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    participation_id BIGINT,
    rating           INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content          VARCHAR(500) NOT NULL DEFAULT '' CHECK (char_length(content) <= 500),
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (activity_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_activity ON evaluation(activity_id);

-- 阶段三 CEM-10（2026-11-15）：信用流水。当前分是按事实时间序列（活动结束时间、
-- 活动 id、参与 id）从 100 起逐笔钳制 0–100 重放的投影，不落用户表；
-- 每份出勤事实版本至多结算一次；事实更正后由重算更新同一行并另留审计批次。
CREATE TABLE IF NOT EXISTS credit_entry (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES app_user(id),
    attendance_id    BIGINT NOT NULL REFERENCES attendance(id),
    fact_version     BIGINT NOT NULL,
    fact_result      VARCHAR(24) NOT NULL,
    activity_id      BIGINT NOT NULL,
    participation_id BIGINT NOT NULL,
    fact_end_time    TIMESTAMP NOT NULL,
    delta            INT NOT NULL,
    score_before     INT NOT NULL CHECK (score_before BETWEEN 0 AND 100),
    score_after      INT NOT NULL CHECK (score_after BETWEEN 0 AND 100),
    settled_at       TIMESTAMP NOT NULL DEFAULT now(),
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (attendance_id, fact_version)
);
CREATE INDEX IF NOT EXISTS idx_credit_entry_user ON credit_entry(user_id, fact_end_time, activity_id, participation_id);
CREATE INDEX IF NOT EXISTS idx_credit_entry_attendance ON credit_entry(attendance_id);

-- 阶段三 CEM-10：信用重算审计批次（只记前后快照，不维护第二套当前分）。
CREATE TABLE IF NOT EXISTS credit_recalc_history (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES app_user(id),
    source_revision_id BIGINT REFERENCES attendance_revision(id),
    before_snapshot    TEXT NOT NULL,
    after_snapshot     TEXT NOT NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_credit_recalc_user ON credit_recalc_history(user_id, created_at);

-- 阶段三 CEM-10：近 30 日累计 3 次核实缺席的管理员审查记录（阶段四工作台消费）。
-- 本阶段只落表：尚无管理员通知通道，不向普通用户发通知，避免误导。
CREATE TABLE IF NOT EXISTS credit_review (
    id                    BIGSERIAL PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES app_user(id),
    trigger_attendance_id BIGINT NOT NULL REFERENCES attendance(id),
    absence_count         INT NOT NULL,
    window_start          TIMESTAMP NOT NULL,
    window_end            TIMESTAMP NOT NULL,
    status                VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','REVIEWED','DISMISSED')),
    created_at            TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (user_id, trigger_attendance_id)
);
CREATE INDEX IF NOT EXISTS idx_credit_review_user ON credit_review(user_id, status);

-- 阶段四 CEM-09（2026-11-15）：平台治理。管理员身份与授权、不可变决定历史
-- （governance_decision）、当前封禁态（user_ban）、活动下架标记（activity_delist）、
-- 举报 / 申诉 / 找回恢复案件，以及治理操作审计。
CREATE TABLE IF NOT EXISTS administrator (
    user_id            BIGINT PRIMARY KEY REFERENCES app_user(id),
    enabled            INT NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    authorized_at      TIMESTAMP NOT NULL DEFAULT now(),
    authorization_note VARCHAR(500) NOT NULL DEFAULT '',
    created_at         TIMESTAMP NOT NULL DEFAULT now(),
    updated_at         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance_decision (
    id                     BIGSERIAL PRIMARY KEY,
    actor_id               BIGINT REFERENCES app_user(id),
    previous_decision_id   BIGINT REFERENCES governance_decision(id),
    decision_type          VARCHAR(24) NOT NULL CHECK (decision_type IN
                               ('BAN','UNBAN','DELIST','RELIST','COMPLAINT','ATTENDANCE','REVIEW','RECOVERY')),
    subject_user_id        BIGINT REFERENCES app_user(id),
    activity_id            BIGINT REFERENCES activity(id),
    participation_id       BIGINT REFERENCES participation(id),
    attendance_revision_id BIGINT REFERENCES attendance_revision(id),
    reason                 VARCHAR(500) NOT NULL DEFAULT '',
    result                 VARCHAR(1000) NOT NULL DEFAULT '',
    decided_at             TIMESTAMP NOT NULL DEFAULT now(),
    expires_at             TIMESTAMP,
    available_at           TIMESTAMP,
    appeal_until           TIMESTAMP,
    execution_state        TEXT,
    created_at             TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gov_decision_subject
    ON governance_decision(subject_user_id, decision_type, decided_at);
CREATE INDEX IF NOT EXISTS idx_gov_decision_activity ON governance_decision(activity_id);
CREATE INDEX IF NOT EXISTS idx_gov_decision_revision ON governance_decision(attendance_revision_id);

CREATE TABLE IF NOT EXISTS user_ban (
    user_id          BIGINT PRIMARY KEY REFERENCES app_user(id),
    decision_id      BIGINT NOT NULL REFERENCES governance_decision(id),
    reason           VARCHAR(500) NOT NULL DEFAULT '',
    banned_at        TIMESTAMP NOT NULL DEFAULT now(),
    expires_at       TIMESTAMP NOT NULL,
    lifted_at        TIMESTAMP,
    lifted_by        BIGINT REFERENCES app_user(id),
    lift_decision_id BIGINT REFERENCES governance_decision(id),
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activity_delist (
    activity_id BIGINT PRIMARY KEY REFERENCES activity(id),
    delisted    INT NOT NULL DEFAULT 0 CHECK (delisted IN (0, 1)),
    decision_id BIGINT REFERENCES governance_decision(id),
    reason      VARCHAR(500) NOT NULL DEFAULT '',
    updated_by  BIGINT REFERENCES app_user(id),
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS complaint (
    id              BIGSERIAL PRIMARY KEY,
    applicant_id    BIGINT NOT NULL REFERENCES app_user(id),
    activity_id     BIGINT REFERENCES activity(id),
    subject_user_id BIGINT REFERENCES app_user(id),
    category        VARCHAR(24) NOT NULL DEFAULT '其他',
    reason          VARCHAR(2000) NOT NULL,
    handler_id      BIGINT REFERENCES app_user(id),
    decision_id     BIGINT REFERENCES governance_decision(id),
    state           VARCHAR(24) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','RESOLVED','DISMISSED')),
    submitted_at    TIMESTAMP NOT NULL DEFAULT now(),
    handled_at      TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_complaint_state ON complaint(state, submitted_at);
CREATE INDEX IF NOT EXISTS idx_complaint_applicant ON complaint(applicant_id);

CREATE TABLE IF NOT EXISTS appeal (
    id                 BIGSERIAL PRIMARY KEY,
    applicant_id       BIGINT NOT NULL REFERENCES app_user(id),
    decision_id        BIGINT NOT NULL REFERENCES governance_decision(id),
    complaint_id       BIGINT REFERENCES complaint(id),
    reviewer_id        BIGINT REFERENCES app_user(id),
    result_decision_id BIGINT REFERENCES governance_decision(id),
    reason             VARCHAR(2000) NOT NULL,
    state              VARCHAR(24) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','UPHELD','OVERTURNED','CORRECTED')),
    submitted_at       TIMESTAMP NOT NULL DEFAULT now(),
    reviewed_at        TIMESTAMP,
    created_at         TIMESTAMP NOT NULL DEFAULT now(),
    updated_at         TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (decision_id),
    UNIQUE (complaint_id)
);
CREATE INDEX IF NOT EXISTS idx_appeal_state ON appeal(state, submitted_at);
CREATE INDEX IF NOT EXISTS idx_appeal_applicant ON appeal(applicant_id);

CREATE TABLE IF NOT EXISTS recovery_request (
    id                 BIGSERIAL PRIMARY KEY,
    applicant_id       BIGINT NOT NULL REFERENCES app_user(id),
    request_type       INT NOT NULL CHECK (request_type IN (1, 2)),
    decision_id        BIGINT REFERENCES governance_decision(id),
    reviewer_id        BIGINT REFERENCES app_user(id),
    result_decision_id BIGINT REFERENCES governance_decision(id),
    reason             VARCHAR(2000) NOT NULL,
    contact            VARCHAR(100) NOT NULL DEFAULT '',
    state              VARCHAR(24) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','APPROVED','REJECTED','COMPLETED')),
    query_hash         VARCHAR(64) NOT NULL,
    reset_hash         VARCHAR(64),
    reset_expires_at   TIMESTAMP,
    applied_at         TIMESTAMP NOT NULL DEFAULT now(),
    reviewed_at        TIMESTAMP,
    recovered_at       TIMESTAMP,
    created_at         TIMESTAMP NOT NULL DEFAULT now(),
    updated_at         TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_recovery_applicant ON recovery_request(applicant_id, state);
CREATE INDEX IF NOT EXISTS idx_recovery_state ON recovery_request(state, applied_at);

CREATE TABLE IF NOT EXISTS governance_action (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    BIGINT REFERENCES app_user(id),
    action      VARCHAR(32) NOT NULL,
    target_type VARCHAR(24) NOT NULL,
    target_id   BIGINT,
    decision_id BIGINT REFERENCES governance_decision(id),
    reason      VARCHAR(500) NOT NULL DEFAULT '',
    detail      TEXT,
    request_id  VARCHAR(64),
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_governance_action_time ON governance_action(created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_governance_action_target ON governance_action(target_type, target_id);
