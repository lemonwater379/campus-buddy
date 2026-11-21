-- R3 MySQL 8 read-only preflight and post-migration verification (mysql CLI).
-- Select the target database explicitly. Run in batch mode without --force.
-- 54 detail rows, then a SUMMARY row. A SQL error, missing summary, or STOP is a blocker.
-- Missing FKs are OK for preflight only; after migration require 54 actual FKs and no missing ones.
-- Relationship list and child nullability come from schema.sql (see expected-foreign-keys.csv).
WITH expected AS (
    SELECT 'activity' AS child_table, 'organizer_id' AS child_column,
           'app_user' AS parent_table, 'id' AS parent_column, 'NO' AS child_nullable,
           (SELECT COUNT(*) FROM `activity` AS c WHERE c.`organizer_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`organizer_id`)) AS orphan_count
    UNION ALL
    SELECT 'activity_delist', 'activity_id', 'activity', 'id', 'NO',
           (SELECT COUNT(*) FROM `activity_delist` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'activity_delist', 'decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `activity_delist` AS c WHERE c.`decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'activity_delist', 'updated_by', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `activity_delist` AS c WHERE c.`updated_by` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`updated_by`)) AS orphan_count
    UNION ALL
    SELECT 'administrator', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `administrator` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'appeal', 'applicant_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `appeal` AS c WHERE c.`applicant_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`applicant_id`)) AS orphan_count
    UNION ALL
    SELECT 'appeal', 'complaint_id', 'complaint', 'id', 'YES',
           (SELECT COUNT(*) FROM `appeal` AS c WHERE c.`complaint_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `complaint` AS p WHERE p.`id` = c.`complaint_id`)) AS orphan_count
    UNION ALL
    SELECT 'appeal', 'decision_id', 'governance_decision', 'id', 'NO',
           (SELECT COUNT(*) FROM `appeal` AS c WHERE c.`decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'appeal', 'result_decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `appeal` AS c WHERE c.`result_decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`result_decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'appeal', 'reviewer_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `appeal` AS c WHERE c.`reviewer_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`reviewer_id`)) AS orphan_count
    UNION ALL
    SELECT 'attendance', 'activity_id', 'activity', 'id', 'NO',
           (SELECT COUNT(*) FROM `attendance` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'attendance', 'participation_id', 'participation', 'id', 'NO',
           (SELECT COUNT(*) FROM `attendance` AS c WHERE c.`participation_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `participation` AS p WHERE p.`id` = c.`participation_id`)) AS orphan_count
    UNION ALL
    SELECT 'attendance', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `attendance` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'attendance_revision', 'attendance_id', 'attendance', 'id', 'NO',
           (SELECT COUNT(*) FROM `attendance_revision` AS c WHERE c.`attendance_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `attendance` AS p WHERE p.`id` = c.`attendance_id`)) AS orphan_count
    UNION ALL
    SELECT 'checkin', 'activity_id', 'activity', 'id', 'NO',
           (SELECT COUNT(*) FROM `checkin` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'checkin', 'participation_id', 'participation', 'id', 'NO',
           (SELECT COUNT(*) FROM `checkin` AS c WHERE c.`participation_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `participation` AS p WHERE p.`id` = c.`participation_id`)) AS orphan_count
    UNION ALL
    SELECT 'checkin', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `checkin` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'complaint', 'activity_id', 'activity', 'id', 'YES',
           (SELECT COUNT(*) FROM `complaint` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'complaint', 'applicant_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `complaint` AS c WHERE c.`applicant_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`applicant_id`)) AS orphan_count
    UNION ALL
    SELECT 'complaint', 'decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `complaint` AS c WHERE c.`decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'complaint', 'handler_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `complaint` AS c WHERE c.`handler_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`handler_id`)) AS orphan_count
    UNION ALL
    SELECT 'complaint', 'subject_user_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `complaint` AS c WHERE c.`subject_user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`subject_user_id`)) AS orphan_count
    UNION ALL
    SELECT 'credit_entry', 'attendance_id', 'attendance', 'id', 'NO',
           (SELECT COUNT(*) FROM `credit_entry` AS c WHERE c.`attendance_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `attendance` AS p WHERE p.`id` = c.`attendance_id`)) AS orphan_count
    UNION ALL
    SELECT 'credit_entry', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `credit_entry` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'credit_recalc_history', 'source_revision_id', 'attendance_revision', 'id', 'YES',
           (SELECT COUNT(*) FROM `credit_recalc_history` AS c WHERE c.`source_revision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `attendance_revision` AS p WHERE p.`id` = c.`source_revision_id`)) AS orphan_count
    UNION ALL
    SELECT 'credit_recalc_history', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `credit_recalc_history` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'credit_review', 'trigger_attendance_id', 'attendance', 'id', 'NO',
           (SELECT COUNT(*) FROM `credit_review` AS c WHERE c.`trigger_attendance_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `attendance` AS p WHERE p.`id` = c.`trigger_attendance_id`)) AS orphan_count
    UNION ALL
    SELECT 'credit_review', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `credit_review` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'evaluation', 'activity_id', 'activity', 'id', 'NO',
           (SELECT COUNT(*) FROM `evaluation` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'evaluation', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `evaluation` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'feedback', 'participation_id', 'participation', 'id', 'NO',
           (SELECT COUNT(*) FROM `feedback` AS c WHERE c.`participation_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `participation` AS p WHERE p.`id` = c.`participation_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_action', 'actor_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_action` AS c WHERE c.`actor_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`actor_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_action', 'decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_action` AS c WHERE c.`decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_decision', 'activity_id', 'activity', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_decision` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_decision', 'actor_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_decision` AS c WHERE c.`actor_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`actor_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_decision', 'attendance_revision_id', 'attendance_revision', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_decision` AS c WHERE c.`attendance_revision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `attendance_revision` AS p WHERE p.`id` = c.`attendance_revision_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_decision', 'participation_id', 'participation', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_decision` AS c WHERE c.`participation_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `participation` AS p WHERE p.`id` = c.`participation_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_decision', 'previous_decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_decision` AS c WHERE c.`previous_decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`previous_decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'governance_decision', 'subject_user_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `governance_decision` AS c WHERE c.`subject_user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`subject_user_id`)) AS orphan_count
    UNION ALL
    SELECT 'invitation', 'participation_id', 'participation', 'id', 'NO',
           (SELECT COUNT(*) FROM `invitation` AS c WHERE c.`participation_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `participation` AS p WHERE p.`id` = c.`participation_id`)) AS orphan_count
    UNION ALL
    SELECT 'notification', 'activity_id', 'activity', 'id', 'YES',
           (SELECT COUNT(*) FROM `notification` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'notification', 'invitation_id', 'invitation', 'id', 'YES',
           (SELECT COUNT(*) FROM `notification` AS c WHERE c.`invitation_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `invitation` AS p WHERE p.`id` = c.`invitation_id`)) AS orphan_count
    UNION ALL
    SELECT 'notification', 'sender_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `notification` AS c WHERE c.`sender_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`sender_id`)) AS orphan_count
    UNION ALL
    SELECT 'notification', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `notification` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'participation', 'activity_id', 'activity', 'id', 'NO',
           (SELECT COUNT(*) FROM `participation` AS c WHERE c.`activity_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `activity` AS p WHERE p.`id` = c.`activity_id`)) AS orphan_count
    UNION ALL
    SELECT 'participation', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `participation` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
    UNION ALL
    SELECT 'recovery_request', 'applicant_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `recovery_request` AS c WHERE c.`applicant_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`applicant_id`)) AS orphan_count
    UNION ALL
    SELECT 'recovery_request', 'decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `recovery_request` AS c WHERE c.`decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'recovery_request', 'result_decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `recovery_request` AS c WHERE c.`result_decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`result_decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'recovery_request', 'reviewer_id', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `recovery_request` AS c WHERE c.`reviewer_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`reviewer_id`)) AS orphan_count
    UNION ALL
    SELECT 'user_ban', 'decision_id', 'governance_decision', 'id', 'NO',
           (SELECT COUNT(*) FROM `user_ban` AS c WHERE c.`decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'user_ban', 'lift_decision_id', 'governance_decision', 'id', 'YES',
           (SELECT COUNT(*) FROM `user_ban` AS c WHERE c.`lift_decision_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `governance_decision` AS p WHERE p.`id` = c.`lift_decision_id`)) AS orphan_count
    UNION ALL
    SELECT 'user_ban', 'lifted_by', 'app_user', 'id', 'YES',
           (SELECT COUNT(*) FROM `user_ban` AS c WHERE c.`lifted_by` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`lifted_by`)) AS orphan_count
    UNION ALL
    SELECT 'user_ban', 'user_id', 'app_user', 'id', 'NO',
           (SELECT COUNT(*) FROM `user_ban` AS c WHERE c.`user_id` IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM `app_user` AS p WHERE p.`id` = c.`user_id`)) AS orphan_count
),
parent_keys AS (
    -- A prefix or the first column of a composite unique index is not a unique parent key.
    SELECT CAST(s.TABLE_NAME AS BINARY) AS table_name, LOWER(MAX(s.COLUMN_NAME)) AS column_name
    FROM INFORMATION_SCHEMA.STATISTICS AS s
    WHERE CAST(s.TABLE_SCHEMA AS BINARY) = CAST(DATABASE() AS BINARY)
      AND s.NON_UNIQUE = 0
    GROUP BY CAST(s.TABLE_NAME AS BINARY), s.INDEX_NAME
    HAVING COUNT(*) = 1 AND MAX(s.SEQ_IN_INDEX) = 1 AND MAX(s.SUB_PART) IS NULL
),
fk_catalog AS (
    -- Aggregate ALL constituent columns first, so no composite FK can match one of these FKs.
    SELECT CAST(rc.TABLE_NAME AS BINARY) AS child_table,
           LOWER(rc.CONSTRAINT_NAME) AS fk_name,
           rc.MATCH_OPTION, rc.DELETE_RULE, rc.UPDATE_RULE,
           COUNT(kcu.ORDINAL_POSITION) AS column_count,
           MAX(kcu.ORDINAL_POSITION) AS ordinal_position,
           LOWER(MAX(kcu.COLUMN_NAME)) AS child_column,
           CAST(MAX(kcu.REFERENCED_TABLE_SCHEMA) AS BINARY) AS parent_schema,
           CAST(MAX(kcu.REFERENCED_TABLE_NAME) AS BINARY) AS parent_table,
           LOWER(MAX(kcu.REFERENCED_COLUMN_NAME)) AS parent_column
    FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS rc
    LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu
      ON CAST(kcu.CONSTRAINT_SCHEMA AS BINARY) = CAST(rc.CONSTRAINT_SCHEMA AS BINARY)
     AND CAST(kcu.TABLE_SCHEMA AS BINARY) = CAST(rc.CONSTRAINT_SCHEMA AS BINARY)
     AND CAST(kcu.TABLE_NAME AS BINARY) = CAST(rc.TABLE_NAME AS BINARY)
     AND kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
     AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
    WHERE CAST(rc.CONSTRAINT_SCHEMA AS BINARY) = CAST(DATABASE() AS BINARY)
    GROUP BY CAST(rc.TABLE_NAME AS BINARY), rc.CONSTRAINT_NAME, rc.MATCH_OPTION, rc.DELETE_RULE, rc.UPDATE_RULE
),
fk_matches AS (
    SELECT e.child_table, e.child_column, COUNT(f.fk_name) AS equivalent_fk_count,
           COUNT(CASE WHEN CAST(f.fk_name AS BINARY) = CAST(CONCAT('fk_', e.child_table, '_', e.child_column) AS BINARY)
                      THEN 1 END) AS equivalent_named_count
    FROM expected AS e
    LEFT JOIN fk_catalog AS f
      ON f.child_table = CAST(e.child_table AS BINARY)
     AND CAST(f.child_column AS BINARY) = CAST(e.child_column AS BINARY)
     AND f.parent_schema = CAST(DATABASE() AS BINARY)
     AND f.parent_table = CAST(e.parent_table AS BINARY)
     AND CAST(f.parent_column AS BINARY) = CAST(e.parent_column AS BINARY)
     AND f.column_count = 1 AND f.ordinal_position = 1
     AND f.MATCH_OPTION = 'NONE'
     AND f.DELETE_RULE IN ('NO ACTION', 'RESTRICT')
     AND f.UPDATE_RULE IN ('NO ACTION', 'RESTRICT')
    GROUP BY e.child_table, e.child_column
),
per_fk AS (
    SELECT e.child_table, e.child_column, e.parent_table, e.parent_column, e.orphan_count,
           IF(ct.TABLE_TYPE = 'BASE TABLE' AND ct.ENGINE = 'InnoDB'
              AND pt.TABLE_TYPE = 'BASE TABLE' AND pt.ENGINE = 'InnoDB', 0, 1) AS engine_issue,
           IF(cc.DATA_TYPE = 'bigint' AND LOWER(cc.COLUMN_TYPE) NOT LIKE '%unsigned%'
              AND pc.DATA_TYPE = 'bigint' AND LOWER(pc.COLUMN_TYPE) NOT LIKE '%unsigned%', 0, 1) AS signed_bigint_issue,
           IF(CAST(cc.IS_NULLABLE AS BINARY) = CAST(e.child_nullable AS BINARY), 0, 1) AS child_nullability_issue,
           IF(EXISTS (
               SELECT 1 FROM parent_keys AS pk
               WHERE pk.table_name = CAST(e.parent_table AS BINARY)
                 AND CAST(pk.column_name AS BINARY) = CAST(e.parent_column AS BINARY)
           ), 0, 1) AS parent_key_issue,
           m.equivalent_fk_count,
           IF(m.equivalent_named_count = 0 AND EXISTS (
               SELECT 1 FROM fk_catalog AS n
               WHERE CAST(n.fk_name AS BINARY) = CAST(CONCAT('fk_', e.child_table, '_', e.child_column) AS BINARY)
           ), 1, 0) AS name_conflict
    FROM expected AS e
    JOIN fk_matches AS m ON m.child_table = e.child_table AND m.child_column = e.child_column
    LEFT JOIN INFORMATION_SCHEMA.TABLES AS ct
      ON CAST(ct.TABLE_SCHEMA AS BINARY) = CAST(DATABASE() AS BINARY)
     AND CAST(ct.TABLE_NAME AS BINARY) = CAST(e.child_table AS BINARY)
    LEFT JOIN INFORMATION_SCHEMA.TABLES AS pt
      ON CAST(pt.TABLE_SCHEMA AS BINARY) = CAST(DATABASE() AS BINARY)
     AND CAST(pt.TABLE_NAME AS BINARY) = CAST(e.parent_table AS BINARY)
    LEFT JOIN INFORMATION_SCHEMA.COLUMNS AS cc
      ON CAST(cc.TABLE_SCHEMA AS BINARY) = CAST(DATABASE() AS BINARY)
     AND CAST(cc.TABLE_NAME AS BINARY) = CAST(e.child_table AS BINARY)
     AND CAST(LOWER(cc.COLUMN_NAME) AS BINARY) = CAST(e.child_column AS BINARY)
    LEFT JOIN INFORMATION_SCHEMA.COLUMNS AS pc
      ON CAST(pc.TABLE_SCHEMA AS BINARY) = CAST(DATABASE() AS BINARY)
     AND CAST(pc.TABLE_NAME AS BINARY) = CAST(e.parent_table AS BINARY)
     AND CAST(LOWER(pc.COLUMN_NAME) AS BINARY) = CAST(e.parent_column AS BINARY)
),
summary AS (
    SELECT COUNT(*) AS checked_fk_count, SUM(orphan_count) AS orphan_count,
           SUM(engine_issue) AS engine_issue, SUM(signed_bigint_issue) AS signed_bigint_issue,
           SUM(child_nullability_issue) AS child_nullability_issue, SUM(parent_key_issue) AS parent_key_issue,
           SUM(equivalent_fk_count) AS equivalent_fk_count, SUM(name_conflict) AS name_conflict,
           SUM(equivalent_fk_count = 0) AS missing_fk_count,
           SUM(GREATEST(equivalent_fk_count - 1, 0)) AS duplicate_fk_count,
           (SELECT COUNT(*) FROM fk_catalog) AS actual_fk_count,
           IF(@@SESSION.foreign_key_checks = 1, 0, 1) AS fk_checks_off
    FROM per_fk
)
SELECT 'FK' AS row_kind, child_table, child_column, parent_table, parent_column, orphan_count,
       engine_issue, signed_bigint_issue, child_nullability_issue, parent_key_issue, equivalent_fk_count, name_conflict,
       NULL AS checked_fk_count, NULL AS missing_fk_count, NULL AS duplicate_fk_count,
       NULL AS actual_fk_count, NULL AS unexpected_fk_count, NULL AS fk_checks_off, NULL AS preflight_status
FROM per_fk
UNION ALL
SELECT 'SUMMARY', NULL, NULL, NULL, NULL, orphan_count,
       engine_issue, signed_bigint_issue, child_nullability_issue, parent_key_issue, equivalent_fk_count, name_conflict,
       checked_fk_count, missing_fk_count, duplicate_fk_count, actual_fk_count,
       actual_fk_count - equivalent_fk_count, fk_checks_off,
       CASE WHEN checked_fk_count = 54 AND orphan_count = 0 AND engine_issue = 0 AND signed_bigint_issue = 0
                  AND child_nullability_issue = 0 AND parent_key_issue = 0 AND name_conflict = 0
                  AND duplicate_fk_count = 0 AND actual_fk_count = equivalent_fk_count AND fk_checks_off = 0
            THEN 'PASS' ELSE 'STOP' END
FROM summary
ORDER BY row_kind, child_table, child_column;
