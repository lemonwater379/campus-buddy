-- R3 MySQL 8 existing-database migration: 54 explicit foreign keys from schema.sql.
-- Run mysql-foreign-key-preflight.sql first and require PASS with all orphan_count = 0.
-- Take a backup/snapshot before running this file. Keep writes and other DDL quiesced.
-- MySQL DDL is not transactional across statements: a failure can leave earlier FKs in place.
-- Run on the selected database via mysql CLI batch input without --force; stop on the first error.
-- For new databases use schema-mysql.sql instead. Do not run this file via Spring SQL init.

DELIMITER $$

DROP PROCEDURE IF EXISTS campus_buddy_r3_add_fk_20261120$$

CREATE PROCEDURE campus_buddy_r3_add_fk_20261120(
    IN p_child_table VARCHAR(64),
    IN p_child_column VARCHAR(64),
    IN p_parent_table VARCHAR(64),
    IN p_parent_column VARCHAR(64)
)
SQL SECURITY INVOKER
BEGIN
    DECLARE v_schema VARCHAR(64);
    DECLARE v_fk_name VARCHAR(64);
    DECLARE v_equivalent_count INT;
    DECLARE v_equivalent_named_count INT;
    DECLARE v_message VARCHAR(128);

    SET v_schema = DATABASE();
    SET v_fk_name = CONCAT('fk_', p_child_table, '_', p_child_column);

    IF @@SESSION.foreign_key_checks <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'R3 requires foreign_key_checks = 1';
    END IF;

    -- Include the parent schema and both rules; in InnoDB RESTRICT and NO ACTION are equivalent.
    -- Inspect all columns of each FK before matching to exclude composite FKs.
    SELECT COUNT(*),
           COUNT(CASE WHEN CAST(LOWER(f.CONSTRAINT_NAME) AS BINARY) = CAST(v_fk_name AS BINARY) THEN 1 END)
      INTO v_equivalent_count, v_equivalent_named_count
    FROM (
        SELECT rc.CONSTRAINT_NAME
        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS rc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu
          ON CAST(kcu.CONSTRAINT_SCHEMA AS BINARY) = CAST(rc.CONSTRAINT_SCHEMA AS BINARY)
         AND CAST(kcu.TABLE_SCHEMA AS BINARY) = CAST(rc.CONSTRAINT_SCHEMA AS BINARY)
         AND CAST(kcu.TABLE_NAME AS BINARY) = CAST(rc.TABLE_NAME AS BINARY)
         AND kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
         AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
        WHERE CAST(rc.CONSTRAINT_SCHEMA AS BINARY) = CAST(v_schema AS BINARY)
          AND CAST(rc.TABLE_NAME AS BINARY) = CAST(p_child_table AS BINARY)
          AND rc.MATCH_OPTION = 'NONE'
          AND rc.DELETE_RULE IN ('NO ACTION', 'RESTRICT')
          AND rc.UPDATE_RULE IN ('NO ACTION', 'RESTRICT')
        GROUP BY rc.CONSTRAINT_NAME
        HAVING COUNT(*) = 1 AND MAX(kcu.ORDINAL_POSITION) = 1
           AND CAST(LOWER(MAX(kcu.COLUMN_NAME)) AS BINARY) = CAST(p_child_column AS BINARY)
           AND CAST(MAX(kcu.REFERENCED_TABLE_SCHEMA) AS BINARY) = CAST(v_schema AS BINARY)
           AND CAST(MAX(kcu.REFERENCED_TABLE_NAME) AS BINARY) = CAST(p_parent_table AS BINARY)
           AND CAST(LOWER(MAX(kcu.REFERENCED_COLUMN_NAME)) AS BINARY) = CAST(p_parent_column AS BINARY)
    ) AS f;

    -- FK names are schema-wide. A conflict wins even if another FK matches the signature.
    IF v_equivalent_named_count = 0 AND EXISTS (
        SELECT 1 FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS rc
        WHERE CAST(rc.CONSTRAINT_SCHEMA AS BINARY) = CAST(v_schema AS BINARY)
          AND CAST(LOWER(rc.CONSTRAINT_NAME) AS BINARY) = CAST(v_fk_name AS BINARY)
    ) THEN
        SET v_message = CONCAT('R3 foreign key name has a different definition: ', v_fk_name);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_message;
    END IF;

    IF v_equivalent_count = 0 THEN
        -- With checks on, ALTER TABLE validates existing data; propagate all errors.
        SET @campus_buddy_r3_ddl = CONCAT(
            'ALTER TABLE `', REPLACE(v_schema, '`', '``'), '`.`', REPLACE(p_child_table, '`', '``'),
            '` ADD CONSTRAINT `', REPLACE(v_fk_name, '`', '``'), '` FOREIGN KEY (`',
            REPLACE(p_child_column, '`', '``'), '`) REFERENCES `', REPLACE(v_schema, '`', '``'),
            '`.`', REPLACE(p_parent_table, '`', '``'), '` (`', REPLACE(p_parent_column, '`', '``'), '`)'
        );
        PREPARE campus_buddy_r3_fk_ddl FROM @campus_buddy_r3_ddl;
        EXECUTE campus_buddy_r3_fk_ddl;
        DEALLOCATE PREPARE campus_buddy_r3_fk_ddl;
    END IF;
END$$

DELIMITER ;

-- Same (child table, child column) order as expected-foreign-keys.csv.
CALL campus_buddy_r3_add_fk_20261120('activity', 'organizer_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('activity_delist', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('activity_delist', 'decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('activity_delist', 'updated_by', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('administrator', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('appeal', 'applicant_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('appeal', 'complaint_id', 'complaint', 'id');
CALL campus_buddy_r3_add_fk_20261120('appeal', 'decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('appeal', 'result_decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('appeal', 'reviewer_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('attendance', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('attendance', 'participation_id', 'participation', 'id');
CALL campus_buddy_r3_add_fk_20261120('attendance', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('attendance_revision', 'attendance_id', 'attendance', 'id');
CALL campus_buddy_r3_add_fk_20261120('checkin', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('checkin', 'participation_id', 'participation', 'id');
CALL campus_buddy_r3_add_fk_20261120('checkin', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('complaint', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('complaint', 'applicant_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('complaint', 'decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('complaint', 'handler_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('complaint', 'subject_user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('credit_entry', 'attendance_id', 'attendance', 'id');
CALL campus_buddy_r3_add_fk_20261120('credit_entry', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('credit_recalc_history', 'source_revision_id', 'attendance_revision', 'id');
CALL campus_buddy_r3_add_fk_20261120('credit_recalc_history', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('credit_review', 'trigger_attendance_id', 'attendance', 'id');
CALL campus_buddy_r3_add_fk_20261120('credit_review', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('evaluation', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('evaluation', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('feedback', 'participation_id', 'participation', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_action', 'actor_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_action', 'decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_decision', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_decision', 'actor_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_decision', 'attendance_revision_id', 'attendance_revision', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_decision', 'participation_id', 'participation', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_decision', 'previous_decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('governance_decision', 'subject_user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('invitation', 'participation_id', 'participation', 'id');
CALL campus_buddy_r3_add_fk_20261120('notification', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('notification', 'invitation_id', 'invitation', 'id');
CALL campus_buddy_r3_add_fk_20261120('notification', 'sender_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('notification', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('participation', 'activity_id', 'activity', 'id');
CALL campus_buddy_r3_add_fk_20261120('participation', 'user_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('recovery_request', 'applicant_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('recovery_request', 'decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('recovery_request', 'result_decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('recovery_request', 'reviewer_id', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('user_ban', 'decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('user_ban', 'lift_decision_id', 'governance_decision', 'id');
CALL campus_buddy_r3_add_fk_20261120('user_ban', 'lifted_by', 'app_user', 'id');
CALL campus_buddy_r3_add_fk_20261120('user_ban', 'user_id', 'app_user', 'id');

DROP PROCEDURE campus_buddy_r3_add_fk_20261120;
