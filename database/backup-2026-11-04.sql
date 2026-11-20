-- 东八区口径，2026-11-06 迁移；2026-11-19 种子：4 个活动整体 +24h（截止 11-14 18:09–21:09、开始 11-15 18:09–21:09，错开），标题去星期词（羽毛球双打/桌游之夜/学习组/羽毛球友谊赛）；任务 11 种子介绍/条件/地点写具体（江安校区、水平费用进条件）；通知 type CHECK 已放开 '取消'/'留言' + sender_id 列；任务 1 sweep 已补 READY→OPEN 回流
--
-- PostgreSQL database dump
--

-- Dumped from database version 16.2 (Ubuntu 16.2-1ubuntu4)
-- Dumped by pg_dump version 16.2 (Ubuntu 16.2-1ubuntu4)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: activity; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.activity (
    id bigint NOT NULL,
    organizer_id bigint NOT NULL,
    title character varying(50) NOT NULL,
    category character varying(10) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    conditions character varying(500) DEFAULT ''::character varying NOT NULL,
    location character varying(100) NOT NULL,
    capacity integer NOT NULL,
    deadline timestamp without time zone NOT NULL,
    start_time timestamp without time zone NOT NULL,
    end_time timestamp without time zone NOT NULL,
    status character varying(10) DEFAULT 'OPEN'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    cover_url character varying(255),
    CONSTRAINT activity_capacity_check CHECK (((capacity >= 1) AND (capacity <= 100))),
    CONSTRAINT activity_category_check CHECK (((category)::text = ANY (ARRAY[('羽毛球'::character varying)::text, ('桌游'::character varying)::text, ('学习组'::character varying)::text, ('其他'::character varying)::text]))),
    CONSTRAINT activity_check CHECK (((deadline <= start_time) AND (start_time < end_time))),
    CONSTRAINT activity_conditions_check CHECK ((char_length((conditions)::text) <= 500)),
    CONSTRAINT activity_description_check CHECK ((char_length(description) <= 2000)),
    CONSTRAINT activity_location_check CHECK (((char_length((location)::text) >= 1) AND (char_length((location)::text) <= 100))),
    CONSTRAINT activity_status_check CHECK (((status)::text = ANY (ARRAY[('OPEN'::character varying)::text, ('READY'::character varying)::text, ('RUNNING'::character varying)::text, ('ENDED'::character varying)::text, ('CANCELLED'::character varying)::text]))),
    CONSTRAINT activity_title_check CHECK (((char_length((title)::text) >= 1) AND (char_length((title)::text) <= 50)))
);


ALTER TABLE public.activity OWNER TO postgres;

--
-- Name: activity_delist; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.activity_delist (
    activity_id bigint NOT NULL,
    delisted integer DEFAULT 0 NOT NULL,
    decision_id bigint,
    reason character varying(500) DEFAULT ''::character varying NOT NULL,
    updated_by bigint,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT activity_delist_delisted_check CHECK ((delisted = ANY (ARRAY[0, 1])))
);


ALTER TABLE public.activity_delist OWNER TO postgres;

--
-- Name: activity_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.activity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.activity_id_seq OWNER TO postgres;

--
-- Name: activity_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.activity_id_seq OWNED BY public.activity.id;


--
-- Name: administrator; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.administrator (
    user_id bigint NOT NULL,
    enabled integer DEFAULT 1 NOT NULL,
    authorized_at timestamp without time zone DEFAULT now() NOT NULL,
    authorization_note character varying(500) DEFAULT ''::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT administrator_enabled_check CHECK ((enabled = ANY (ARRAY[0, 1])))
);


ALTER TABLE public.administrator OWNER TO postgres;

--
-- Name: app_user; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.app_user (
    id bigint NOT NULL,
    account character varying(32) NOT NULL,
    password_hash character varying(255) NOT NULL,
    nickname character varying(30) NOT NULL,
    contact character varying(100) DEFAULT ''::character varying NOT NULL,
    role character varying(10) DEFAULT 'USER'::character varying NOT NULL,
    status character varying(10) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT app_user_account_check CHECK (((char_length((account)::text) >= 4) AND (char_length((account)::text) <= 32))),
    CONSTRAINT app_user_nickname_check CHECK (((char_length((nickname)::text) >= 1) AND (char_length((nickname)::text) <= 30))),
    CONSTRAINT app_user_role_check CHECK (((role)::text = ANY (ARRAY[('USER'::character varying)::text, ('ADMIN'::character varying)::text]))),
    CONSTRAINT app_user_status_check CHECK (((status)::text = ANY (ARRAY[('ACTIVE'::character varying)::text, ('DISABLED'::character varying)::text])))
);


ALTER TABLE public.app_user OWNER TO postgres;

--
-- Name: app_user_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.app_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.app_user_id_seq OWNER TO postgres;

--
-- Name: app_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.app_user_id_seq OWNED BY public.app_user.id;


--
-- Name: appeal; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.appeal (
    id bigint NOT NULL,
    applicant_id bigint NOT NULL,
    decision_id bigint NOT NULL,
    complaint_id bigint,
    reviewer_id bigint,
    result_decision_id bigint,
    reason character varying(2000) NOT NULL,
    state character varying(24) DEFAULT 'PENDING'::character varying NOT NULL,
    submitted_at timestamp without time zone DEFAULT now() NOT NULL,
    reviewed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT appeal_state_check CHECK (((state)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('UPHELD'::character varying)::text, ('OVERTURNED'::character varying)::text, ('CORRECTED'::character varying)::text])))
);


ALTER TABLE public.appeal OWNER TO postgres;

--
-- Name: appeal_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.appeal_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.appeal_id_seq OWNER TO postgres;

--
-- Name: appeal_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.appeal_id_seq OWNED BY public.appeal.id;


--
-- Name: attendance; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.attendance (
    id bigint NOT NULL,
    participation_id bigint NOT NULL,
    activity_id bigint NOT NULL,
    user_id bigint NOT NULL,
    result character varying(24) DEFAULT 'UNVERIFIED'::character varying NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    decided_by bigint,
    finalized_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT attendance_result_check CHECK (((result)::text = ANY (ARRAY[('PRESENT'::character varying)::text, ('ABSENT_VERIFIED'::character varying)::text, ('EXEMPT'::character varying)::text, ('UNVERIFIED'::character varying)::text])))
);


ALTER TABLE public.attendance OWNER TO postgres;

--
-- Name: attendance_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.attendance_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.attendance_id_seq OWNER TO postgres;

--
-- Name: attendance_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.attendance_id_seq OWNED BY public.attendance.id;


--
-- Name: attendance_revision; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.attendance_revision (
    id bigint NOT NULL,
    attendance_id bigint NOT NULL,
    version bigint NOT NULL,
    actor_id bigint,
    result character varying(24) NOT NULL,
    reason text,
    available_at timestamp without time zone,
    appeal_until timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.attendance_revision OWNER TO postgres;

--
-- Name: attendance_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.attendance_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.attendance_revision_id_seq OWNER TO postgres;

--
-- Name: attendance_revision_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.attendance_revision_id_seq OWNED BY public.attendance_revision.id;


--
-- Name: checkin; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.checkin (
    id bigint NOT NULL,
    activity_id bigint NOT NULL,
    user_id bigint NOT NULL,
    participation_id bigint NOT NULL,
    checkin_at timestamp without time zone NOT NULL
);


ALTER TABLE public.checkin OWNER TO postgres;

--
-- Name: checkin_attempt; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.checkin_attempt (
    id bigint NOT NULL,
    activity_id bigint NOT NULL,
    user_id bigint NOT NULL,
    fail_count integer DEFAULT 0 NOT NULL,
    locked_until timestamp without time zone,
    last_fail_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.checkin_attempt OWNER TO postgres;

--
-- Name: checkin_attempt_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.checkin_attempt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.checkin_attempt_id_seq OWNER TO postgres;

--
-- Name: checkin_attempt_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.checkin_attempt_id_seq OWNED BY public.checkin_attempt.id;


--
-- Name: checkin_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.checkin_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.checkin_id_seq OWNER TO postgres;

--
-- Name: checkin_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.checkin_id_seq OWNED BY public.checkin.id;


--
-- Name: command_receipts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.command_receipts (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    endpoint character varying(220) NOT NULL,
    idem_key character varying(128) NOT NULL,
    request_hash character varying(64) NOT NULL,
    response_body text NOT NULL,
    http_status integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.command_receipts OWNER TO postgres;

--
-- Name: command_receipts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.command_receipts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.command_receipts_id_seq OWNER TO postgres;

--
-- Name: command_receipts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.command_receipts_id_seq OWNED BY public.command_receipts.id;


--
-- Name: complaint; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.complaint (
    id bigint NOT NULL,
    applicant_id bigint NOT NULL,
    activity_id bigint,
    subject_user_id bigint,
    category character varying(24) DEFAULT '其他'::character varying NOT NULL,
    reason character varying(2000) NOT NULL,
    handler_id bigint,
    decision_id bigint,
    state character varying(24) DEFAULT 'PENDING'::character varying NOT NULL,
    submitted_at timestamp without time zone DEFAULT now() NOT NULL,
    handled_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT complaint_state_check CHECK (((state)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('RESOLVED'::character varying)::text, ('DISMISSED'::character varying)::text])))
);


ALTER TABLE public.complaint OWNER TO postgres;

--
-- Name: complaint_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.complaint_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.complaint_id_seq OWNER TO postgres;

--
-- Name: complaint_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.complaint_id_seq OWNED BY public.complaint.id;


--
-- Name: credit_entry; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.credit_entry (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    attendance_id bigint NOT NULL,
    fact_version bigint NOT NULL,
    fact_result character varying(24) NOT NULL,
    activity_id bigint NOT NULL,
    participation_id bigint NOT NULL,
    fact_end_time timestamp without time zone NOT NULL,
    delta integer NOT NULL,
    score_before integer NOT NULL,
    score_after integer NOT NULL,
    settled_at timestamp without time zone DEFAULT now() NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT credit_entry_score_after_check CHECK (((score_after >= 0) AND (score_after <= 100))),
    CONSTRAINT credit_entry_score_before_check CHECK (((score_before >= 0) AND (score_before <= 100)))
);


ALTER TABLE public.credit_entry OWNER TO postgres;

--
-- Name: credit_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.credit_entry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.credit_entry_id_seq OWNER TO postgres;

--
-- Name: credit_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.credit_entry_id_seq OWNED BY public.credit_entry.id;


--
-- Name: credit_recalc_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.credit_recalc_history (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    source_revision_id bigint,
    before_snapshot text NOT NULL,
    after_snapshot text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.credit_recalc_history OWNER TO postgres;

--
-- Name: credit_recalc_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.credit_recalc_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.credit_recalc_history_id_seq OWNER TO postgres;

--
-- Name: credit_recalc_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.credit_recalc_history_id_seq OWNED BY public.credit_recalc_history.id;


--
-- Name: credit_review; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.credit_review (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    trigger_attendance_id bigint NOT NULL,
    absence_count integer NOT NULL,
    window_start timestamp without time zone NOT NULL,
    window_end timestamp without time zone NOT NULL,
    status character varying(16) DEFAULT 'PENDING'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT credit_review_status_check CHECK (((status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('REVIEWED'::character varying)::text, ('DISMISSED'::character varying)::text])))
);


ALTER TABLE public.credit_review OWNER TO postgres;

--
-- Name: credit_review_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.credit_review_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.credit_review_id_seq OWNER TO postgres;

--
-- Name: credit_review_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.credit_review_id_seq OWNED BY public.credit_review.id;


--
-- Name: evaluation; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.evaluation (
    id bigint NOT NULL,
    activity_id bigint NOT NULL,
    user_id bigint NOT NULL,
    participation_id bigint,
    rating integer NOT NULL,
    content character varying(500) DEFAULT ''::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT evaluation_content_check CHECK ((char_length((content)::text) <= 500)),
    CONSTRAINT evaluation_rating_check CHECK (((rating >= 1) AND (rating <= 5)))
);


ALTER TABLE public.evaluation OWNER TO postgres;

--
-- Name: evaluation_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.evaluation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.evaluation_id_seq OWNER TO postgres;

--
-- Name: evaluation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.evaluation_id_seq OWNED BY public.evaluation.id;


--
-- Name: feedback; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.feedback (
    id bigint NOT NULL,
    participation_id bigint NOT NULL,
    score integer NOT NULL,
    content character varying(500) DEFAULT ''::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT feedback_content_check CHECK ((char_length((content)::text) <= 500)),
    CONSTRAINT feedback_score_check CHECK (((score >= 1) AND (score <= 5)))
);


ALTER TABLE public.feedback OWNER TO postgres;

--
-- Name: feedback_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feedback_id_seq OWNER TO postgres;

--
-- Name: feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.feedback_id_seq OWNED BY public.feedback.id;


--
-- Name: governance_action; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.governance_action (
    id bigint NOT NULL,
    actor_id bigint,
    action character varying(32) NOT NULL,
    target_type character varying(24) NOT NULL,
    target_id bigint,
    decision_id bigint,
    reason character varying(500) DEFAULT ''::character varying NOT NULL,
    detail text,
    request_id character varying(64),
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.governance_action OWNER TO postgres;

--
-- Name: governance_action_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.governance_action_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.governance_action_id_seq OWNER TO postgres;

--
-- Name: governance_action_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.governance_action_id_seq OWNED BY public.governance_action.id;


--
-- Name: governance_decision; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.governance_decision (
    id bigint NOT NULL,
    actor_id bigint,
    previous_decision_id bigint,
    decision_type character varying(24) NOT NULL,
    subject_user_id bigint,
    activity_id bigint,
    participation_id bigint,
    attendance_revision_id bigint,
    reason character varying(500) DEFAULT ''::character varying NOT NULL,
    result character varying(1000) DEFAULT ''::character varying NOT NULL,
    decided_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone,
    available_at timestamp without time zone,
    appeal_until timestamp without time zone,
    execution_state text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT governance_decision_decision_type_check CHECK (((decision_type)::text = ANY (ARRAY[('BAN'::character varying)::text, ('UNBAN'::character varying)::text, ('DELIST'::character varying)::text, ('RELIST'::character varying)::text, ('COMPLAINT'::character varying)::text, ('ATTENDANCE'::character varying)::text, ('REVIEW'::character varying)::text, ('RECOVERY'::character varying)::text])))
);


ALTER TABLE public.governance_decision OWNER TO postgres;

--
-- Name: governance_decision_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.governance_decision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.governance_decision_id_seq OWNER TO postgres;

--
-- Name: governance_decision_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.governance_decision_id_seq OWNED BY public.governance_decision.id;


--
-- Name: invitation; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.invitation (
    id bigint NOT NULL,
    participation_id bigint NOT NULL,
    status character varying(10) DEFAULT 'PENDING'::character varying NOT NULL,
    issued_at timestamp without time zone NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    responded_at timestamp without time zone,
    event_key character varying(100) NOT NULL,
    CONSTRAINT invitation_check CHECK ((issued_at < expires_at)),
    CONSTRAINT invitation_status_check CHECK (((status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('ACCEPTED'::character varying)::text, ('REJECTED'::character varying)::text, ('EXPIRED'::character varying)::text, ('INVALID'::character varying)::text])))
);


ALTER TABLE public.invitation OWNER TO postgres;

--
-- Name: invitation_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.invitation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.invitation_id_seq OWNER TO postgres;

--
-- Name: invitation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.invitation_id_seq OWNED BY public.invitation.id;


--
-- Name: notification; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notification (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    activity_id bigint,
    invitation_id bigint,
    type character varying(10) NOT NULL,
    content text NOT NULL,
    event_key character varying(100) NOT NULL,
    read_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    sender_id bigint,
    status character varying(16) DEFAULT 'PUBLISHED'::character varying NOT NULL,
    publish_at timestamp without time zone,
    CONSTRAINT notification_content_check CHECK ((char_length(content) <= 1000)),
    CONSTRAINT notification_type_check CHECK (((type)::text = ANY (ARRAY[('报名'::character varying)::text, ('候补'::character varying)::text, ('邀请'::character varying)::text, ('变更'::character varying)::text, ('退出'::character varying)::text, ('取消'::character varying)::text, ('留言'::character varying)::text])))
);


ALTER TABLE public.notification OWNER TO postgres;

--
-- Name: notification_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.notification_id_seq OWNER TO postgres;

--
-- Name: notification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.notification_id_seq OWNED BY public.notification.id;


--
-- Name: participation; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.participation (
    id bigint NOT NULL,
    activity_id bigint NOT NULL,
    user_id bigint NOT NULL,
    status character varying(10) NOT NULL,
    queued_at timestamp without time zone,
    joined_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT participation_status_check CHECK (((status)::text = ANY (ARRAY[('FORMAL'::character varying)::text, ('WAITING'::character varying)::text, ('INVITED'::character varying)::text, ('WITHDRAWN'::character varying)::text, ('EXPIRED'::character varying)::text, ('CANCELLED'::character varying)::text])))
);


ALTER TABLE public.participation OWNER TO postgres;

--
-- Name: participation_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.participation_events (
    id bigint NOT NULL,
    participation_id bigint NOT NULL,
    activity_id bigint NOT NULL,
    user_id bigint NOT NULL,
    event_type character varying(32) NOT NULL,
    from_status character varying(16),
    to_status character varying(16),
    detail character varying(500),
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.participation_events OWNER TO postgres;

--
-- Name: participation_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.participation_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.participation_events_id_seq OWNER TO postgres;

--
-- Name: participation_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.participation_events_id_seq OWNED BY public.participation_events.id;


--
-- Name: participation_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.participation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.participation_id_seq OWNER TO postgres;

--
-- Name: participation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.participation_id_seq OWNED BY public.participation.id;


--
-- Name: recovery_request; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.recovery_request (
    id bigint NOT NULL,
    applicant_id bigint NOT NULL,
    request_type integer NOT NULL,
    decision_id bigint,
    reviewer_id bigint,
    result_decision_id bigint,
    reason character varying(2000) NOT NULL,
    contact character varying(100) DEFAULT ''::character varying NOT NULL,
    state character varying(24) DEFAULT 'PENDING'::character varying NOT NULL,
    query_hash character varying(64) NOT NULL,
    reset_hash character varying(64),
    reset_expires_at timestamp without time zone,
    applied_at timestamp without time zone DEFAULT now() NOT NULL,
    reviewed_at timestamp without time zone,
    recovered_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT recovery_request_request_type_check CHECK ((request_type = ANY (ARRAY[1, 2]))),
    CONSTRAINT recovery_request_state_check CHECK (((state)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('APPROVED'::character varying)::text, ('REJECTED'::character varying)::text, ('COMPLETED'::character varying)::text])))
);


ALTER TABLE public.recovery_request OWNER TO postgres;

--
-- Name: recovery_request_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.recovery_request_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.recovery_request_id_seq OWNER TO postgres;

--
-- Name: recovery_request_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.recovery_request_id_seq OWNED BY public.recovery_request.id;


--
-- Name: user_ban; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_ban (
    user_id bigint NOT NULL,
    decision_id bigint NOT NULL,
    reason character varying(500) DEFAULT ''::character varying NOT NULL,
    banned_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    lifted_at timestamp without time zone,
    lifted_by bigint,
    lift_decision_id bigint,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_ban OWNER TO postgres;

--
-- Name: activity id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity ALTER COLUMN id SET DEFAULT nextval('public.activity_id_seq'::regclass);


--
-- Name: app_user id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_user ALTER COLUMN id SET DEFAULT nextval('public.app_user_id_seq'::regclass);


--
-- Name: appeal id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal ALTER COLUMN id SET DEFAULT nextval('public.appeal_id_seq'::regclass);


--
-- Name: attendance id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance ALTER COLUMN id SET DEFAULT nextval('public.attendance_id_seq'::regclass);


--
-- Name: attendance_revision id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance_revision ALTER COLUMN id SET DEFAULT nextval('public.attendance_revision_id_seq'::regclass);


--
-- Name: checkin id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin ALTER COLUMN id SET DEFAULT nextval('public.checkin_id_seq'::regclass);


--
-- Name: checkin_attempt id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin_attempt ALTER COLUMN id SET DEFAULT nextval('public.checkin_attempt_id_seq'::regclass);


--
-- Name: command_receipts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.command_receipts ALTER COLUMN id SET DEFAULT nextval('public.command_receipts_id_seq'::regclass);


--
-- Name: complaint id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint ALTER COLUMN id SET DEFAULT nextval('public.complaint_id_seq'::regclass);


--
-- Name: credit_entry id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_entry ALTER COLUMN id SET DEFAULT nextval('public.credit_entry_id_seq'::regclass);


--
-- Name: credit_recalc_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_recalc_history ALTER COLUMN id SET DEFAULT nextval('public.credit_recalc_history_id_seq'::regclass);


--
-- Name: credit_review id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_review ALTER COLUMN id SET DEFAULT nextval('public.credit_review_id_seq'::regclass);


--
-- Name: evaluation id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation ALTER COLUMN id SET DEFAULT nextval('public.evaluation_id_seq'::regclass);


--
-- Name: feedback id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feedback ALTER COLUMN id SET DEFAULT nextval('public.feedback_id_seq'::regclass);


--
-- Name: governance_action id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_action ALTER COLUMN id SET DEFAULT nextval('public.governance_action_id_seq'::regclass);


--
-- Name: governance_decision id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision ALTER COLUMN id SET DEFAULT nextval('public.governance_decision_id_seq'::regclass);


--
-- Name: invitation id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invitation ALTER COLUMN id SET DEFAULT nextval('public.invitation_id_seq'::regclass);


--
-- Name: notification id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification ALTER COLUMN id SET DEFAULT nextval('public.notification_id_seq'::regclass);


--
-- Name: participation id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation ALTER COLUMN id SET DEFAULT nextval('public.participation_id_seq'::regclass);


--
-- Name: participation_events id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation_events ALTER COLUMN id SET DEFAULT nextval('public.participation_events_id_seq'::regclass);


--
-- Name: recovery_request id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recovery_request ALTER COLUMN id SET DEFAULT nextval('public.recovery_request_id_seq'::regclass);


--
-- Data for Name: activity; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.activity (id, organizer_id, title, category, description, conditions, location, capacity, deadline, start_time, end_time, status, created_at, updated_at, cover_url) FROM stdin;
1	1	羽毛球双打	羽毛球	羽毛球双打，新手友好，欢迎一个人来；现场分组轮换，保证每人都能打上。	水平不限，免费参加；自带球拍，没有球拍可提前说一声	江安校区体育馆三楼	4	2026-11-23 18:09:12.336937	2026-11-24 18:09:12.336937	2026-11-24 20:09:12.336937	OPEN	2026-11-05 01:09:12.337632	2026-11-12 09:04:53.483721	\N
3	1	学习组	学习组	一起自习，互相监督、互不打扰；中途可以组队讨论题目，新手友好，欢迎一个人来。	水平不限，免费参加；自带学习资料，学习时保持安静	江安校区图书馆三楼	10	2026-11-23 20:09:12.336937	2026-11-24 20:09:12.336937	2026-11-24 22:09:12.336937	OPEN	2026-11-05 01:09:12.339985	2026-11-12 09:04:53.483721	\N
4	1	羽毛球友谊赛	羽毛球	羽毛球友谊赛，以球会友、切磋为主；新手友好，欢迎一个人来，现场分组保证每人都有上场机会。	水平不限，免费参加；自带球拍和水	江安校区体育馆三楼	6	2026-11-23 21:09:12.336937	2026-11-24 21:09:12.336937	2026-11-24 23:09:12.336937	OPEN	2026-11-08 09:32:47.802226	2026-11-12 09:04:53.483721	\N
2	1	桌游之夜	桌游	本周玩卡坦岛。轻松桌游夜，有主持人带玩，新手友好，欢迎一个人来；狼人杀、卡坦岛、剧本杀轮着玩。	水平不限，免费参加；自带想玩的桌游也可以	江安校区活动中心201	4	2026-11-23 19:09:12.336937	2026-11-24 19:09:12.336937	2026-11-24 21:09:12.336937	OPEN	2026-11-05 01:09:12.339019	2026-11-12 09:04:53.483721	\N
\.


--
-- Data for Name: activity_delist; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.activity_delist (activity_id, delisted, decision_id, reason, updated_by, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: administrator; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.administrator (user_id, enabled, authorized_at, authorization_note, created_at, updated_at) FROM stdin;
22	1	2026-11-16 09:02:39.111289	种子管理员（本地演示，部署须改密）	2026-11-16 09:02:39.111842	2026-11-16 09:02:39.111842
23	1	2026-11-16 09:02:40.214127	种子管理员（本地演示，部署须改密）	2026-11-16 09:02:40.214765	2026-11-16 09:02:40.214765
\.


--
-- Data for Name: app_user; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.app_user (id, account, password_hash, nickname, contact, role, status, created_at) FROM stdin;
22	admin	b796b7f3197210b442006d4cf1be4ee6:c8849113293e54623b06fd61e91a7ad6108a72309662a8421ccf93ef7e2e4383	管理员		USER	ACTIVE	2026-11-16 09:02:39.10104
23	admin2	155c8e3393f2bb605e86c6dba30b5019:d510f44f83a201f698c0d457b031993451c518567fd23c0dbdb04dae25fe4818	管理员二		USER	ACTIVE	2026-11-16 09:02:40.211916
2	demo01	f43e91ba75bb731e25324bcacab5ebe7:4425ff66800445ef1bd0b770652a2b5b12d070b34888ce4e20cce82b4f8fe116	同学1		USER	ACTIVE	2026-11-05 01:09:12.327632
3	demo02	a100eff64c111df0a3dc537de28e87f3:b2269dc0e5d1edc272eddc1aae84e3491ba375b7c21ce6d93d45988462a33e8a	同学2		USER	ACTIVE	2026-11-05 01:09:12.328293
4	demo03	bdbe07bfae03a8d0f4dd783df7636f83:0bc944dc7b63b972e1fef037e06c05329fc714f5938c16b639c43784cc4ca1ff	同学3		USER	ACTIVE	2026-11-05 01:09:12.328739
5	demo04	76fd4adb62ab0ddf888d9d359fb3f920:9bd1a528c26560c0baa457743232c5374edffd874ed2f7a7c86a4edad7bc37c2	同学4		USER	ACTIVE	2026-11-05 01:09:12.329671
6	demo05	6e2c391579579b2af70f60ab6a737a07:e2fd2daa989523d32c3793bdd712b839077a759050d305160993399df3967951	同学5		USER	ACTIVE	2026-11-05 01:09:12.330362
7	demo06	55d7db2526d717642e815f4c298176cb:d2b754504eba8951ecc8a5cea3ed9e5ac31b065a1f581e9a61aef6b13965b5bf	同学6		USER	ACTIVE	2026-11-05 01:09:12.330802
8	demo07	8b19b7b4756ff55fd6ac2142dc187b23:053cae8606c041a599b029d009d10062f25cf09aec6cbaf23cde1e6311b7d219	同学7		USER	ACTIVE	2026-11-05 01:09:12.331101
9	demo08	e72976e59a770199c5244021b249eb7d:253dbf17086d233b4439801a80a58a494a202c18e577b75ea1a094a158ff43e9	同学8		USER	ACTIVE	2026-11-05 01:09:12.331483
10	demo09	6b6ee393d48e2d7bfab707bdb3c69e27:b7fa09319409d834befe5af06178207766cfec01c492de2ab34c96589160f981	同学9		USER	ACTIVE	2026-11-05 01:09:12.332001
11	demo10	54ea2adc71007b843243af14951a69c3:26e4dbd4d797bde33e98cca49864329acd84a1cb47146b2b3d4e2c235b510b46	同学10		USER	ACTIVE	2026-11-05 01:09:12.332413
12	demo11	74db0e4c3bd3a1cf1fd873403f4d6879:1d3d1f1aa456e7beeaf526034b0832bf9aabec21ccc6e76df0ddb87978906982	同学11		USER	ACTIVE	2026-11-05 01:09:12.332954
13	demo12	8d886bcfddd8cd9f48ad3340ad29b608:3013c12dcab0f33d741b47e138257e3757ea30848640fe7b20ee8280129555a9	同学12		USER	ACTIVE	2026-11-05 01:09:12.333534
14	demo13	5bd7209d36f21a8c6e08aa78ae52c3ca:665be08ad0aafa6a3d23d86dc4f854358bfa50b8d68ad981fc6566612e1c5e13	同学13		USER	ACTIVE	2026-11-05 01:09:12.333854
15	demo14	86f0788f923a0654e88239302a9b681b:40daec7940ee468a83420693fc6fc1ba3b9ab052d3a9e54247fc8678b3156b39	同学14		USER	ACTIVE	2026-11-05 01:09:12.334135
16	demo15	5646166cde59efb519af86c5389cf206:35490854d58e84ba76e3886db1c3e09843c7a6111b91fcccbca3ba961f594de0	同学15		USER	ACTIVE	2026-11-05 01:09:12.334438
17	demo16	d7979a1264bfb19fb68209f6dda6c5dc:c76fd8a570a457fa5caa4612dea337e3997a4e3e6f60caab10de800ab7cf8850	同学16		USER	ACTIVE	2026-11-05 01:09:12.334826
18	demo17	971316620e431dbe0612b0c555a6a7b1:175cbbca2a778d7190b4b42d2fb31bec19c2758e21e020f26c474cd2f16cfacd	同学17		USER	ACTIVE	2026-11-05 01:09:12.335233
19	demo18	3d947cf06a29d810e7750b71a17ebba7:f5f1880b375f479949e833d565c38441f80003c24fd1b010afec7477a3c60738	同学18		USER	ACTIVE	2026-11-05 01:09:12.335624
20	demo19	c5c612ec6a1d1981ac425dee8d8e0451:21af53ec68b823da88445305971da0cc2d96b7e45afddc1a3854490701b07812	同学19		USER	ACTIVE	2026-11-05 01:09:12.335907
21	demo20	550760ed63c868e73b59d1dfb2bd20e3:717febae3cc987d3236ac9ecf3e46951e6787d05bd2ba5fa795de61dae9e7a6d	同学20		USER	ACTIVE	2026-11-05 01:09:12.336177
1	organizer	64b49ba6586576e2dcf7171fd1c2ec40:40211c707fc682c258644ae65ec9a8fcfcfaed4b83f05d046bdadcc0bc225a70	组织者小陈		USER	ACTIVE	2026-11-05 01:09:12.325273
\.


--
-- Data for Name: appeal; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.appeal (id, applicant_id, decision_id, complaint_id, reviewer_id, result_decision_id, reason, state, submitted_at, reviewed_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: attendance; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.attendance (id, participation_id, activity_id, user_id, result, version, decided_by, finalized_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: attendance_revision; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.attendance_revision (id, attendance_id, version, actor_id, result, reason, available_at, appeal_until, created_at) FROM stdin;
\.


--
-- Data for Name: checkin; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.checkin (id, activity_id, user_id, participation_id, checkin_at) FROM stdin;
\.


--
-- Data for Name: checkin_attempt; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.checkin_attempt (id, activity_id, user_id, fail_count, locked_until, last_fail_at, updated_at) FROM stdin;
\.


--
-- Data for Name: command_receipts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.command_receipts (id, user_id, endpoint, idem_key, request_hash, response_body, http_status, created_at) FROM stdin;
\.


--
-- Data for Name: complaint; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.complaint (id, applicant_id, activity_id, subject_user_id, category, reason, handler_id, decision_id, state, submitted_at, handled_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: credit_entry; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.credit_entry (id, user_id, attendance_id, fact_version, fact_result, activity_id, participation_id, fact_end_time, delta, score_before, score_after, settled_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: credit_recalc_history; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.credit_recalc_history (id, user_id, source_revision_id, before_snapshot, after_snapshot, created_at) FROM stdin;
\.


--
-- Data for Name: credit_review; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.credit_review (id, user_id, trigger_attendance_id, absence_count, window_start, window_end, status, created_at) FROM stdin;
\.


--
-- Data for Name: evaluation; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.evaluation (id, activity_id, user_id, participation_id, rating, content, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: feedback; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.feedback (id, participation_id, score, content, created_at) FROM stdin;
\.


--
-- Data for Name: governance_action; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.governance_action (id, actor_id, action, target_type, target_id, decision_id, reason, detail, request_id, created_at) FROM stdin;
\.


--
-- Data for Name: governance_decision; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.governance_decision (id, actor_id, previous_decision_id, decision_type, subject_user_id, activity_id, participation_id, attendance_revision_id, reason, result, decided_at, expires_at, available_at, appeal_until, execution_state, created_at) FROM stdin;
\.


--
-- Data for Name: invitation; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.invitation (id, participation_id, status, issued_at, expires_at, responded_at, event_key) FROM stdin;
\.


--
-- Data for Name: notification; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notification (id, user_id, activity_id, invitation_id, type, content, event_key, read_at, created_at, sender_id, status, publish_at) FROM stdin;
\.


--
-- Data for Name: participation; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.participation (id, activity_id, user_id, status, queued_at, joined_at, updated_at) FROM stdin;
1	1	2	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
2	1	3	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
3	1	4	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
4	2	2	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
5	2	3	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
6	2	4	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
7	2	5	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
8	2	6	WAITING	2026-11-05 01:14:12.336937	\N	2026-11-05 01:09:12.336937
9	2	7	WAITING	2026-11-05 01:15:12.336937	\N	2026-11-05 01:09:12.336937
11	3	3	FORMAL	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
10	3	2	WITHDRAWN	\N	2026-11-05 01:09:12.336937	2026-11-05 01:09:12.336937
\.


--
-- Data for Name: participation_events; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.participation_events (id, participation_id, activity_id, user_id, event_type, from_status, to_status, detail, created_at) FROM stdin;
\.


--
-- Data for Name: recovery_request; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.recovery_request (id, applicant_id, request_type, decision_id, reviewer_id, result_decision_id, reason, contact, state, query_hash, reset_hash, reset_expires_at, applied_at, reviewed_at, recovered_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: user_ban; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.user_ban (user_id, decision_id, reason, banned_at, expires_at, lifted_at, lifted_by, lift_decision_id, created_at, updated_at) FROM stdin;
\.


--
-- Name: activity_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.activity_id_seq', 4, true);


--
-- Name: app_user_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.app_user_id_seq', 23, true);


--
-- Name: appeal_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.appeal_id_seq', 1, false);


--
-- Name: attendance_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.attendance_id_seq', 1, false);


--
-- Name: attendance_revision_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.attendance_revision_id_seq', 1, false);


--
-- Name: checkin_attempt_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.checkin_attempt_id_seq', 1, false);


--
-- Name: checkin_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.checkin_id_seq', 1, false);


--
-- Name: command_receipts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.command_receipts_id_seq', 1, false);


--
-- Name: complaint_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.complaint_id_seq', 1, false);


--
-- Name: credit_entry_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.credit_entry_id_seq', 1, false);


--
-- Name: credit_recalc_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.credit_recalc_history_id_seq', 1, false);


--
-- Name: credit_review_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.credit_review_id_seq', 1, false);


--
-- Name: evaluation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.evaluation_id_seq', 1, false);


--
-- Name: feedback_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.feedback_id_seq', 1, false);


--
-- Name: governance_action_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.governance_action_id_seq', 1, false);


--
-- Name: governance_decision_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.governance_decision_id_seq', 1, false);


--
-- Name: invitation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.invitation_id_seq', 1, false);


--
-- Name: notification_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.notification_id_seq', 1, false);


--
-- Name: participation_events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.participation_events_id_seq', 1, false);


--
-- Name: participation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.participation_id_seq', 11, true);


--
-- Name: recovery_request_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.recovery_request_id_seq', 1, false);


--
-- Name: activity_delist activity_delist_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_delist
    ADD CONSTRAINT activity_delist_pkey PRIMARY KEY (activity_id);


--
-- Name: activity activity_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity
    ADD CONSTRAINT activity_pkey PRIMARY KEY (id);


--
-- Name: administrator administrator_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.administrator
    ADD CONSTRAINT administrator_pkey PRIMARY KEY (user_id);


--
-- Name: app_user app_user_account_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_account_key UNIQUE (account);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);


--
-- Name: appeal appeal_complaint_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_complaint_id_key UNIQUE (complaint_id);


--
-- Name: appeal appeal_decision_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_decision_id_key UNIQUE (decision_id);


--
-- Name: appeal appeal_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_pkey PRIMARY KEY (id);


--
-- Name: attendance attendance_activity_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_activity_id_user_id_key UNIQUE (activity_id, user_id);


--
-- Name: attendance attendance_participation_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_participation_id_key UNIQUE (participation_id);


--
-- Name: attendance attendance_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_pkey PRIMARY KEY (id);


--
-- Name: attendance_revision attendance_revision_attendance_id_version_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance_revision
    ADD CONSTRAINT attendance_revision_attendance_id_version_key UNIQUE (attendance_id, version);


--
-- Name: attendance_revision attendance_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance_revision
    ADD CONSTRAINT attendance_revision_pkey PRIMARY KEY (id);


--
-- Name: checkin checkin_activity_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin
    ADD CONSTRAINT checkin_activity_id_user_id_key UNIQUE (activity_id, user_id);


--
-- Name: checkin_attempt checkin_attempt_activity_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin_attempt
    ADD CONSTRAINT checkin_attempt_activity_id_user_id_key UNIQUE (activity_id, user_id);


--
-- Name: checkin_attempt checkin_attempt_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin_attempt
    ADD CONSTRAINT checkin_attempt_pkey PRIMARY KEY (id);


--
-- Name: checkin checkin_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin
    ADD CONSTRAINT checkin_pkey PRIMARY KEY (id);


--
-- Name: command_receipts command_receipts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.command_receipts
    ADD CONSTRAINT command_receipts_pkey PRIMARY KEY (id);


--
-- Name: command_receipts command_receipts_user_id_endpoint_idem_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.command_receipts
    ADD CONSTRAINT command_receipts_user_id_endpoint_idem_key_key UNIQUE (user_id, endpoint, idem_key);


--
-- Name: complaint complaint_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint
    ADD CONSTRAINT complaint_pkey PRIMARY KEY (id);


--
-- Name: credit_entry credit_entry_attendance_id_fact_version_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_entry
    ADD CONSTRAINT credit_entry_attendance_id_fact_version_key UNIQUE (attendance_id, fact_version);


--
-- Name: credit_entry credit_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_entry
    ADD CONSTRAINT credit_entry_pkey PRIMARY KEY (id);


--
-- Name: credit_recalc_history credit_recalc_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_recalc_history
    ADD CONSTRAINT credit_recalc_history_pkey PRIMARY KEY (id);


--
-- Name: credit_review credit_review_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_review
    ADD CONSTRAINT credit_review_pkey PRIMARY KEY (id);


--
-- Name: credit_review credit_review_user_id_trigger_attendance_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_review
    ADD CONSTRAINT credit_review_user_id_trigger_attendance_id_key UNIQUE (user_id, trigger_attendance_id);


--
-- Name: evaluation evaluation_activity_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation
    ADD CONSTRAINT evaluation_activity_id_user_id_key UNIQUE (activity_id, user_id);


--
-- Name: evaluation evaluation_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation
    ADD CONSTRAINT evaluation_pkey PRIMARY KEY (id);


--
-- Name: feedback feedback_participation_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_participation_id_key UNIQUE (participation_id);


--
-- Name: feedback feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_pkey PRIMARY KEY (id);


--
-- Name: governance_action governance_action_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_action
    ADD CONSTRAINT governance_action_pkey PRIMARY KEY (id);


--
-- Name: governance_decision governance_decision_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_pkey PRIMARY KEY (id);


--
-- Name: invitation invitation_event_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invitation
    ADD CONSTRAINT invitation_event_key_key UNIQUE (event_key);


--
-- Name: invitation invitation_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invitation
    ADD CONSTRAINT invitation_pkey PRIMARY KEY (id);


--
-- Name: notification notification_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (id);


--
-- Name: notification notification_user_id_event_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_user_id_event_key_key UNIQUE (user_id, event_key);


--
-- Name: participation participation_activity_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation
    ADD CONSTRAINT participation_activity_id_user_id_key UNIQUE (activity_id, user_id);


--
-- Name: participation_events participation_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation_events
    ADD CONSTRAINT participation_events_pkey PRIMARY KEY (id);


--
-- Name: participation participation_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation
    ADD CONSTRAINT participation_pkey PRIMARY KEY (id);


--
-- Name: recovery_request recovery_request_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recovery_request
    ADD CONSTRAINT recovery_request_pkey PRIMARY KEY (id);


--
-- Name: user_ban user_ban_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_ban
    ADD CONSTRAINT user_ban_pkey PRIMARY KEY (user_id);


--
-- Name: idx_appeal_applicant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_appeal_applicant ON public.appeal USING btree (applicant_id);


--
-- Name: idx_appeal_state; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_appeal_state ON public.appeal USING btree (state, submitted_at);


--
-- Name: idx_attendance_activity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_attendance_activity ON public.attendance USING btree (activity_id);


--
-- Name: idx_checkin_activity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_checkin_activity ON public.checkin USING btree (activity_id);


--
-- Name: idx_complaint_applicant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_complaint_applicant ON public.complaint USING btree (applicant_id);


--
-- Name: idx_complaint_state; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_complaint_state ON public.complaint USING btree (state, submitted_at);


--
-- Name: idx_credit_entry_attendance; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_credit_entry_attendance ON public.credit_entry USING btree (attendance_id);


--
-- Name: idx_credit_entry_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_credit_entry_user ON public.credit_entry USING btree (user_id, fact_end_time, activity_id, participation_id);


--
-- Name: idx_credit_recalc_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_credit_recalc_user ON public.credit_recalc_history USING btree (user_id, created_at);


--
-- Name: idx_credit_review_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_credit_review_user ON public.credit_review USING btree (user_id, status);


--
-- Name: idx_evaluation_activity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_evaluation_activity ON public.evaluation USING btree (activity_id);


--
-- Name: idx_gov_decision_activity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_gov_decision_activity ON public.governance_decision USING btree (activity_id);


--
-- Name: idx_gov_decision_revision; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_gov_decision_revision ON public.governance_decision USING btree (attendance_revision_id);


--
-- Name: idx_gov_decision_subject; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_gov_decision_subject ON public.governance_decision USING btree (subject_user_id, decision_type, decided_at);


--
-- Name: idx_governance_action_target; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_governance_action_target ON public.governance_action USING btree (target_type, target_id);


--
-- Name: idx_governance_action_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_governance_action_time ON public.governance_action USING btree (created_at DESC, id DESC);


--
-- Name: idx_inv_status_expires; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_inv_status_expires ON public.invitation USING btree (status, expires_at);


--
-- Name: idx_notif_user_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notif_user_created ON public.notification USING btree (user_id, created_at DESC);


--
-- Name: idx_part_activity_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_part_activity_status ON public.participation USING btree (activity_id, status, queued_at, id);


--
-- Name: idx_part_event_aid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_part_event_aid ON public.participation_events USING btree (activity_id);


--
-- Name: idx_part_event_pid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_part_event_pid ON public.participation_events USING btree (participation_id);


--
-- Name: idx_recovery_applicant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_recovery_applicant ON public.recovery_request USING btree (applicant_id, state);


--
-- Name: idx_recovery_state; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_recovery_state ON public.recovery_request USING btree (state, applied_at);


--
-- Name: activity_delist activity_delist_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_delist
    ADD CONSTRAINT activity_delist_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: activity_delist activity_delist_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_delist
    ADD CONSTRAINT activity_delist_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.governance_decision(id);


--
-- Name: activity_delist activity_delist_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_delist
    ADD CONSTRAINT activity_delist_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.app_user(id);


--
-- Name: activity activity_organizer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity
    ADD CONSTRAINT activity_organizer_id_fkey FOREIGN KEY (organizer_id) REFERENCES public.app_user(id);


--
-- Name: administrator administrator_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.administrator
    ADD CONSTRAINT administrator_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: appeal appeal_applicant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_applicant_id_fkey FOREIGN KEY (applicant_id) REFERENCES public.app_user(id);


--
-- Name: appeal appeal_complaint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_complaint_id_fkey FOREIGN KEY (complaint_id) REFERENCES public.complaint(id);


--
-- Name: appeal appeal_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.governance_decision(id);


--
-- Name: appeal appeal_result_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_result_decision_id_fkey FOREIGN KEY (result_decision_id) REFERENCES public.governance_decision(id);


--
-- Name: appeal appeal_reviewer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.appeal
    ADD CONSTRAINT appeal_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.app_user(id);


--
-- Name: attendance attendance_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: attendance attendance_participation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_participation_id_fkey FOREIGN KEY (participation_id) REFERENCES public.participation(id);


--
-- Name: attendance_revision attendance_revision_attendance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance_revision
    ADD CONSTRAINT attendance_revision_attendance_id_fkey FOREIGN KEY (attendance_id) REFERENCES public.attendance(id);


--
-- Name: attendance attendance_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attendance
    ADD CONSTRAINT attendance_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: checkin checkin_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin
    ADD CONSTRAINT checkin_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: checkin checkin_participation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin
    ADD CONSTRAINT checkin_participation_id_fkey FOREIGN KEY (participation_id) REFERENCES public.participation(id);


--
-- Name: checkin checkin_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkin
    ADD CONSTRAINT checkin_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: complaint complaint_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint
    ADD CONSTRAINT complaint_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: complaint complaint_applicant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint
    ADD CONSTRAINT complaint_applicant_id_fkey FOREIGN KEY (applicant_id) REFERENCES public.app_user(id);


--
-- Name: complaint complaint_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint
    ADD CONSTRAINT complaint_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.governance_decision(id);


--
-- Name: complaint complaint_handler_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint
    ADD CONSTRAINT complaint_handler_id_fkey FOREIGN KEY (handler_id) REFERENCES public.app_user(id);


--
-- Name: complaint complaint_subject_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.complaint
    ADD CONSTRAINT complaint_subject_user_id_fkey FOREIGN KEY (subject_user_id) REFERENCES public.app_user(id);


--
-- Name: credit_entry credit_entry_attendance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_entry
    ADD CONSTRAINT credit_entry_attendance_id_fkey FOREIGN KEY (attendance_id) REFERENCES public.attendance(id);


--
-- Name: credit_entry credit_entry_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_entry
    ADD CONSTRAINT credit_entry_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: credit_recalc_history credit_recalc_history_source_revision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_recalc_history
    ADD CONSTRAINT credit_recalc_history_source_revision_id_fkey FOREIGN KEY (source_revision_id) REFERENCES public.attendance_revision(id);


--
-- Name: credit_recalc_history credit_recalc_history_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_recalc_history
    ADD CONSTRAINT credit_recalc_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: credit_review credit_review_trigger_attendance_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_review
    ADD CONSTRAINT credit_review_trigger_attendance_id_fkey FOREIGN KEY (trigger_attendance_id) REFERENCES public.attendance(id);


--
-- Name: credit_review credit_review_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credit_review
    ADD CONSTRAINT credit_review_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: evaluation evaluation_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation
    ADD CONSTRAINT evaluation_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: evaluation evaluation_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation
    ADD CONSTRAINT evaluation_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: feedback feedback_participation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.feedback
    ADD CONSTRAINT feedback_participation_id_fkey FOREIGN KEY (participation_id) REFERENCES public.participation(id);


--
-- Name: governance_action governance_action_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_action
    ADD CONSTRAINT governance_action_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.app_user(id);


--
-- Name: governance_action governance_action_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_action
    ADD CONSTRAINT governance_action_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.governance_decision(id);


--
-- Name: governance_decision governance_decision_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: governance_decision governance_decision_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.app_user(id);


--
-- Name: governance_decision governance_decision_attendance_revision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_attendance_revision_id_fkey FOREIGN KEY (attendance_revision_id) REFERENCES public.attendance_revision(id);


--
-- Name: governance_decision governance_decision_participation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_participation_id_fkey FOREIGN KEY (participation_id) REFERENCES public.participation(id);


--
-- Name: governance_decision governance_decision_previous_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_previous_decision_id_fkey FOREIGN KEY (previous_decision_id) REFERENCES public.governance_decision(id);


--
-- Name: governance_decision governance_decision_subject_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.governance_decision
    ADD CONSTRAINT governance_decision_subject_user_id_fkey FOREIGN KEY (subject_user_id) REFERENCES public.app_user(id);


--
-- Name: invitation invitation_participation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.invitation
    ADD CONSTRAINT invitation_participation_id_fkey FOREIGN KEY (participation_id) REFERENCES public.participation(id);


--
-- Name: notification notification_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: notification notification_invitation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_invitation_id_fkey FOREIGN KEY (invitation_id) REFERENCES public.invitation(id);


--
-- Name: notification notification_sender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_sender_id_fkey FOREIGN KEY (sender_id) REFERENCES public.app_user(id);


--
-- Name: notification notification_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: participation participation_activity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation
    ADD CONSTRAINT participation_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activity(id);


--
-- Name: participation participation_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.participation
    ADD CONSTRAINT participation_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- Name: recovery_request recovery_request_applicant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recovery_request
    ADD CONSTRAINT recovery_request_applicant_id_fkey FOREIGN KEY (applicant_id) REFERENCES public.app_user(id);


--
-- Name: recovery_request recovery_request_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recovery_request
    ADD CONSTRAINT recovery_request_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.governance_decision(id);


--
-- Name: recovery_request recovery_request_result_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recovery_request
    ADD CONSTRAINT recovery_request_result_decision_id_fkey FOREIGN KEY (result_decision_id) REFERENCES public.governance_decision(id);


--
-- Name: recovery_request recovery_request_reviewer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.recovery_request
    ADD CONSTRAINT recovery_request_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.app_user(id);


--
-- Name: user_ban user_ban_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_ban
    ADD CONSTRAINT user_ban_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.governance_decision(id);


--
-- Name: user_ban user_ban_lift_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_ban
    ADD CONSTRAINT user_ban_lift_decision_id_fkey FOREIGN KEY (lift_decision_id) REFERENCES public.governance_decision(id);


--
-- Name: user_ban user_ban_lifted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_ban
    ADD CONSTRAINT user_ban_lifted_by_fkey FOREIGN KEY (lifted_by) REFERENCES public.app_user(id);


--
-- Name: user_ban user_ban_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_ban
    ADD CONSTRAINT user_ban_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id);


--
-- PostgreSQL database dump complete
--

