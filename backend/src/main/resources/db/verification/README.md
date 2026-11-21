# MySQL 8 foreign keys (R3)

- **New MySQL database:** Use Spring SQL init with `classpath:schema-mysql.sql`. Its table-level constraints are only applied when a table is created; `CREATE TABLE IF NOT EXISTS` does not upgrade existing tables. PostgreSQL continues to use `schema.sql` unchanged.
- **Existing MySQL database:** Apply `../migrations/20261120-002-mysql-explicit-foreign-keys.sql` manually with the `mysql` CLI, not Spring. The migration reuses the guarded-procedure pattern from `001-outbox-mysql.sql` and checks definitions, not just names. `expected-foreign-keys.csv` is the 54-relationship contract from PostgreSQL; InnoDB `NO ACTION` and `RESTRICT` are equivalent for these checks.

## Operator steps

Use an approved maintenance window: keep writes and other DDL quiesced from preflight through verification. Select the intended database explicitly and use an account that can inspect the entire schema and, for migration, manage the helper procedure and add foreign keys. Use fresh CLI sessions in batch mode without `--force`, with `foreign_key_checks = 1`.

1. Run `mysql-foreign-key-preflight.sql` against the existing database (for example, `mysql --batch --skip-force --database=YOUR_DB < mysql-foreign-key-preflight.sql` from this directory, using the approved connection options). Require 54 `FK` rows with every `orphan_count = 0` and a `SUMMARY` row with `preflight_status = PASS`. A SQL error or missing summary is a stop. Missing FKs are allowed at this stage; incompatible metadata, conflicting names, duplicate or unexpected FKs, and orphans are not. Investigate failures separately; these scripts do not repair data.
2. Take a restorable backup/snapshot before running migration DDL. MySQL does not roll back DDL across statements; table locks or rebuilds and automatic supporting indexes are possible.
3. Run the migration against the same database via `mysql` batch input (without `--force`). Stop on any error: earlier constraints may already be in place. Inspect the failure, rerun preflight, and resolve it before retrying.
4. Rerun preflight to verify **exactly 54 semantic FKs**: require `PASS`, `actual_fk_count = equivalent_fk_count = 54` in `SUMMARY`, and `equivalent_fk_count = 1` for every `FK` row. Missing, duplicate and unexpected counts must all be zero.
5. Rerun the migration and repeat step 4. The second run must succeed, leave the FK inventory unchanged, and skip every equivalent FK, even if its name differs.
6. Run application checks for startup, activities, participation, notifications, and governance. On a disposable copy, explicitly check demo reset with linked `governance_decision` rows: InnoDB checks the self-reference immediately and can reject a bulk delete that encounters a parent before its child.

This task performed static validation only; no database was connected to and the migration was not executed.
