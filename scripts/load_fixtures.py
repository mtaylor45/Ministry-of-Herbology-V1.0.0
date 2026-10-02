#!/usr/bin/env python3
"""Load the fixture data into the dev database.

idempotent: run it as often as you like. It refuses to run against anything
that does not look like a development database, because it truncates.

    python scripts/load_fixtures.py
    python scripts/load_fixtures.py --database-url postgresql://...

On a deployed stack the database has no published port and sits on an
internal network, so nothing on the host can connect to it. ``--sql`` prints
the same load as one SQL transaction instead, for ``psql`` inside the database
container — the way ``scripts/migrate.sh`` reaches it, never handling the
password (docs/deploy/README.md §10)::

    python3 scripts/load_fixtures.py --sql \
      | docker exec -i $(docker ps -qf name=moh_db) psql -v ON_ERROR_STOP=1 -U herbology -d herbology

``--sql`` needs nothing beyond the standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"

#: Truncated in this order, so foreign keys never block the reload.
WIPE_ORDER = [
    "task_event",
    "task",
    "frost_alert",
    "care_rule",
    "water_balance",
    "log_entry",
    "photo",
    "field_note",
    "plate",
    "specimen",
    "care_value",
    "species",
    "source",
    "reading",
    "sensor_source",
    "weather_forecast",
    "weather_obs",
    "weather_alert",
    "location",
    "map_layer",
    "site",
    "calendar_feed",
    "member",
]

DEV_MARKERS = ("localhost", "127.0.0.1", "@db:", "herbology-dev")


def load(relative: str):
    with (FIXTURES / relative).open() as fh:
        return json.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "MOH_DATABASE_URL",
            "postgresql://herbology:herbology@localhost:5432/herbology",
        ),
    )
    parser.add_argument(
        "--force", action="store_true", help="Skip the dev-database check"
    )
    parser.add_argument(
        "--sql",
        action="store_true",
        help="Print the load as one SQL transaction instead of connecting",
    )
    args = parser.parse_args()

    if args.sql:
        sys.stdout.write("BEGIN;\n")
        for statement, params in statements():
            sys.stdout.write(render(statement, params) + ";\n")
        sys.stdout.write("COMMIT;\n")
        return 0

    url = args.database_url.replace("postgresql+asyncpg://", "postgresql://")
    if not args.force and not any(marker in url for marker in DEV_MARKERS):
        print(
            f"{url!r} does not look like a development database. Refusing to truncate."
        )
        print("Pass --force if you are certain.")
        return 1

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed. Run: pip install 'psycopg[binary]'")
        return 1

    with psycopg.connect(url, autocommit=False) as conn, conn.cursor() as cur:
        loaded = list(statements())
        for statement, params in loaded:
            cur.execute(statement, params)
        conn.commit()

    print(f"Loaded the fixture household: {len(loaded)} statements.")
    return 0


def sql(statement: str, params=None):
    return statement, params


def statements():
    """The whole load, as (statement, parameters) pairs, in order."""
    site = load("site.json")
    locations = load("locations/locations.json")
    sources = load("species/sources.json")
    species = load("species/species.json")
    specimens = load("specimens/specimens.json")

    yield sql(f"TRUNCATE {', '.join(WIPE_ORDER)} CASCADE")

    yield sql(
        "INSERT INTO site (id, name, latitude, longitude, elevation_m, timezone, nws_zone)"
        " VALUES (%(id)s, %(name)s, %(latitude)s, %(longitude)s, %(elevation_m)s,"
        " %(timezone)s, %(nws_zone)s)",
        site,
    )

    for row in locations:
        yield sql(
            "INSERT INTO location (id, site_id, parent_id, name, kind, is_outdoor,"
            " is_covered, sun_exposure) VALUES (%(id)s, %(site_id)s, %(parent_id)s,"
            " %(name)s, %(kind)s, %(is_outdoor)s, %(is_covered)s, %(sun_exposure)s)",
            row,
        )

    for row in sources:
        yield sql(
            "INSERT INTO source (id, kind, title, url, license, retrieved_at)"
            " VALUES (%(id)s, %(kind)s, %(title)s, %(url)s, %(license)s, %(retrieved_at)s)",
            row,
        )

    columns = [
        "id",
        "accepted_name",
        "family",
        "genus",
        "common_names",
        "native_range",
        "summary",
        "light_label",
        "water_k_c",
        "water_interval_days",
        "soil_ph_min",
        "soil_ph_max",
        "soil_type",
        "fertilizer_note",
        "humidity_min_pct",
        "min_temp_c",
        "max_temp_c",
        "usda_zone_min",
        "usda_zone_max",
        "dormancy_months",
        "toxic_to_pets",
        "toxic_to_children",
        "toxicity_note",
        "enrichment_state",
    ]
    for row in species:
        yield sql(
            f"INSERT INTO species ({', '.join(columns)}) VALUES"
            f" ({', '.join(f'%({c})s' for c in columns)})",
            {c: row.get(c) for c in columns},
        )
        for index, value in enumerate(row["care_values"]):
            yield sql(
                "INSERT INTO care_value (id, species_id, field, value, unit, source_id,"
                " confidence) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    f"018900ff-0000-7000-8000-{abs(hash((row['id'], index))) % 10**12:012d}",
                    row["id"],
                    value["field"],
                    json.dumps(value["value"]),
                    value.get("unit"),
                    value.get("source_id"),
                    value["confidence"],
                ),
            )

    specimen_columns = [
        "id",
        "species_id",
        "nickname",
        "cultivar",
        "is_group",
        "count",
        "location_id",
        "is_outdoor",
        "in_container",
        "container_litres",
        "acquired_on",
        "provenance",
        "status",
    ]
    for row in specimens:
        yield sql(
            f"INSERT INTO specimen ({', '.join(specimen_columns)}) VALUES"
            f" ({', '.join(f'%({c})s' for c in specimen_columns)})",
            {c: row.get(c) for c in specimen_columns},
        )


def literal(value) -> str:
    """One parameter as an SQL literal, for ``--sql``.

    Fixture data only: strings, numbers, booleans, null, and lists of those,
    which become array literals the target column's type coerces.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        items = ",".join(
            (
                "NULL"
                if v is None
                else '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
            )
            for v in value
        )
        return literal("{" + items + "}")
    return "'" + str(value).replace("'", "''") + "'"


def render(statement: str, params) -> str:
    if params is None:
        return statement
    if isinstance(params, dict):
        return re.sub(r"%\((\w+)\)s", lambda m: literal(params[m.group(1)]), statement)
    values = iter(params)
    return re.sub(r"%s", lambda _: literal(next(values)), statement)


if __name__ == "__main__":
    sys.exit(main())
