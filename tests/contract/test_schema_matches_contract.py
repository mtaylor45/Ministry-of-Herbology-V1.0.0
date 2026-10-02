"""The migrations are the database contract.

they catch the mistakes that actually happen — an entity from the plan quietly
dropped, a care value with no citation path, an enum that drifted from the
OpenAPI document.
"""

import re

ENTITIES = [
    "member",
    "site",
    "map_layer",
    "location",
    "source",
    "species",
    "care_value",
    "specimen",
    "photo",
    "log_entry",
    "sensor_source",
    "reading",
    "weather_obs",
    "weather_forecast",
    "weather_alert",
    "water_balance",
    "care_rule",
    "task",
    "task_event",
    "frost_alert",
    "calendar_feed",
    "plate",
    "field_note",
    "integration",
    "job_run",
]

HYPERTABLES = ["reading", "weather_obs", "weather_forecast"]


def _schema(repo_root) -> str:
    return "\n".join(
        p.read_text()
        for p in sorted((repo_root / "contracts" / "schema").glob("*.sql"))
    )


def test_every_planned_entity_has_a_table(repo_root):
    sql = _schema(repo_root)
    missing = [e for e in ENTITIES if f"CREATE TABLE {e} (" not in sql]
    assert not missing, f"entities in the plan with no table: {missing}"


def test_time_series_tables_are_hypertables(repo_root):
    sql = _schema(repo_root)
    for table in HYPERTABLES:
        assert f"create_hypertable('{table}'" in sql, f"{table} is not a hypertable"


def test_uncited_care_values_must_be_unknown_confidence(repo_root):
    """no invented plant facts, enforced in the database."""
    sql = _schema(repo_root)
    assert "care_value_uncited_is_unknown" in sql


def test_tasks_carry_both_a_themed_and_a_plain_title(repo_root):
    """every themed string is paired with a plain one."""
    sql = _schema(repo_root)
    task_block = sql.split("CREATE TABLE task (")[1].split(");")[0]
    assert re.search(
        r"^\s*title\s+text NOT NULL", task_block, re.MULTILINE
    ), "task.title must be required"
    assert re.search(
        r"^\s*plain_title\s+text NOT NULL", task_block, re.MULTILINE
    ), "task.plain_title must be required — a themed title may never ship alone"


def test_tasks_have_a_stable_unique_ics_uid(repo_root):
    """Reschedules must update a calendar event in place, not duplicate it."""
    sql = _schema(repo_root)
    assert "ics_uid" in sql
    assert "CREATE UNIQUE INDEX task_ics_uid_key" in sql


def test_task_status_enum_matches_the_openapi_document(repo_root, spec):
    sql = _schema(repo_root)
    check = re.search(
        r"status\s+text NOT NULL DEFAULT 'due'\s*\n\s*CHECK \(status IN \(([^)]*)\)",
        sql,
    )
    assert check, "could not find the task status CHECK constraint"
    in_sql = {v.strip().strip("'") for v in check.group(1).split(",")}
    in_spec = set(spec["components"]["schemas"]["TaskStatus"]["enum"])
    assert in_sql == in_spec, f"task status drifted: SQL {in_sql} vs spec {in_spec}"


def test_migrations_are_numbered_and_forward_only(repo_root):
    files = sorted((repo_root / "contracts" / "schema").glob("*.sql"))
    assert files, "no migrations"
    for index, path in enumerate(files, start=1):
        assert re.match(
            rf"^{index:03d}_[a-z0-9_]+\.sql$", path.name
        ), f"{path.name} breaks the NNN_slug.sql numbering"
