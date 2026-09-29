"""Comparison policy shared by alembic/env.py and the schema-drift check."""

# Type families that are the same thing to PostgreSQL callers here. Alembic would
# otherwise report VARCHAR vs TEXT, FLOAT vs NUMERIC or INTEGER vs BIGINT as changes.
_FAMILIES = (
    ("SMALLINT", "INTEGER", "BIGINT"),
    ("FLOAT", "REAL", "NUMERIC", "DOUBLE_PRECISION", "DOUBLE"),
    ("VARCHAR", "TEXT", "CHAR", "STRING", "AUTOSTRING"),
)


def _family(sqltype) -> str:
    name = type(sqltype).__name__.upper()
    for family in _FAMILIES:
        if name in family:
            return family[0]
    return name


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """False = "no change". None = let Alembic decide."""
    if _family(inspected_type) == _family(metadata_type):
        return False
    return None


def include_object(obj, name, type_, reflected, compare_to):
    """
    Keep autogenerate (and `alembic check`) additive and free of noise:
      - indexes are named and shaped by hand in the migrations and are a performance
        detail, not schema correctness — they are not compared;
      - anything the database has that the models don't know about (a table, column,
        constraint or foreign key added by a migration) is left alone, so a generated
        migration can never propose to DROP it.
    What is still reported is what would actually break: a model field, table,
    constraint or key that no migration creates, and real type/nullability changes.
    """
    if type_ == "index":
        return False
    return not (reflected and compare_to is None)
