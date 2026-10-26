-- Empties the attendance, leave and import-audit data so the EXIM history can be loaded again from a
-- fresh export. Keeps tenants, legal entities, people, accounts, roles, policies, calendars and the
-- platform admins. Regularization requests are kept: the 2026-10-26 export has no
-- regularization file to rebuild them from. One transaction; run with: psql -v ON_ERROR_STOP=1 -f wipe_activity.sql
-- The cascade only reaches approval_delegations and leave_separation_settlements.
begin;
truncate punches, attendance_days,
  daily_report_rows, daily_report_snapshots, leave_applications, leave_approval_actions,
  leave_balance_transactions, leave_monthly_ledger, import_batches, entity_change_log,
  integration_requests, integration_rate_windows, auth_throttle, job_runs, approval_events,
  approval_instances cascade;
commit;
