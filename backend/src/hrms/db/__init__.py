"""
Database conventions, the rules that check them, and the helpers migrations use to follow them.

- conventions.py: the registry. Which columns hold which allowed values, and every deliberate
  exception to a rule, each with its reason.
- schema_rules.py: reads the live catalog and lists every violation
  (tests/test_schema_conventions.py runs it in CI; `python -m hrms.db.schema_rules` prints it).
- migration_kit.py: SQL builders for migrations, so the conventional way is the easy way.

docs/database-conventions.md explains the rules for people.
"""
