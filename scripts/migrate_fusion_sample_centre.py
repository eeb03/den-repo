"""
Widen `fusion_samples` so a non-geographic sample can be persisted.

`database/models.py` now declares center_lat/center_lon nullable and adds
spatial_ref_kind / center_x / center_y. SQLAlchemy's `create_all` only
creates tables it does not find -- it never alters one that already exists
-- so a database created before this change keeps the old NOT NULL columns
and would still force placeholder coordinates onto any sample clustered in
a non-geographic frame.

SAFE BY DEFAULT: reports what it would do; `--apply` performs it.

    python -m scripts.migrate_fusion_sample_centre
    python -m scripts.migrate_fusion_sample_centre --apply

WIDENING ONLY. Dropping NOT NULL and adding nullable columns cannot
invalidate an existing row, so this is reversible in the sense that
matters: every row readable before is readable after. It does NOT delete,
rewrite, or reinterpret any stored value.

PostgreSQL applies in place. SQLite cannot drop a NOT NULL constraint
without rebuilding the table, so there the script reports what is needed and
does nothing destructive -- for a dev database the honest remedy is usually
to drop `fusion_samples` and let create_all rebuild it, since fusion samples
are derived data that /fusion/run regenerates.
"""
from __future__ import annotations

import argparse

from sqlalchemy import inspect, text

from database.session import engine
from utils.logger import get_logger

logger = get_logger(__name__)

TABLE = "fusion_samples"
NEW_COLUMNS = {
    "spatial_ref_kind": "VARCHAR",
    "center_x": "DOUBLE PRECISION",
    "center_y": "DOUBLE PRECISION",
    "n_reprojected": "INTEGER DEFAULT 0",
}
NULLABLE_COLUMNS = ("center_lat", "center_lon")


def inspect_table() -> dict:
    """What the live table looks like right now."""
    inspector = inspect(engine)
    if TABLE not in inspector.get_table_names():
        return {"exists": False}
    columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
    return {
        "exists": True,
        "dialect": engine.dialect.name,
        "columns": sorted(columns),
        "missing_columns": [c for c in NEW_COLUMNS if c not in columns],
        "still_not_null": [c for c in NULLABLE_COLUMNS
                           if c in columns and not columns[c]["nullable"]],
    }


def plan(state: dict) -> list[str]:
    """The SQL that would bring the table up to date, in order."""
    if not state.get("exists"):
        return []
    statements = []
    for column in state["missing_columns"]:
        type_ = NEW_COLUMNS[column]
        if state["dialect"] == "sqlite" and type_ == "DOUBLE PRECISION":
            type_ = "REAL"
        statements.append(f"ALTER TABLE {TABLE} ADD COLUMN {column} {type_}")
    for column in state["still_not_null"]:
        # SQLite cannot express this; reported separately rather than emitted.
        if state["dialect"] != "sqlite":
            statements.append(f"ALTER TABLE {TABLE} ALTER COLUMN {column} DROP NOT NULL")
    return statements


def migrate(apply: bool = False) -> dict:
    state = inspect_table()
    if not state.get("exists"):
        return {**state, "statements": [], "applied": False,
                "note": f"{TABLE} does not exist yet; create_all will build it correctly."}

    statements = plan(state)
    blocked = (state["dialect"] == "sqlite" and state["still_not_null"])
    result = {**state, "statements": statements, "applied": False, "blocked_by_sqlite": bool(blocked)}

    if apply and statements:
        with engine.begin() as connection:
            for sql in statements:
                logger.info(f"migrate_fusion_sample_centre: {sql}")
                connection.execute(text(sql))
        result["applied"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="execute the statements (default: report only)")
    args = parser.parse_args()

    result = migrate(apply=args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN (pass --apply to execute)"
    print(f"\nfusion_samples centre migration -- {mode}")
    if not result.get("exists"):
        print(f"  {result['note']}")
        return 0

    print(f"  dialect: {result['dialect']}")
    print(f"  missing columns: {result['missing_columns'] or 'none'}")
    print(f"  still NOT NULL:  {result['still_not_null'] or 'none'}")
    if not result["statements"]:
        print("\n  nothing to do -- the table is already up to date.")
    for sql in result["statements"]:
        print(f"    {'executed' if result['applied'] else 'would run'}: {sql}")

    if result["blocked_by_sqlite"]:
        print(
            f"\n  NOTE: SQLite cannot drop a NOT NULL constraint in place, so "
            f"{result['still_not_null']} remain constrained. Non-geographic fusion "
            f"samples still cannot be persisted on this database.\n"
            f"  Remedy: DROP TABLE {TABLE} and let create_all rebuild it. Fusion "
            f"samples are derived data -- /fusion/run regenerates them from records."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
