# Copyright 2017-present, The Visdom Authors
"""Folding the instances' live counters into durable hourly rows.

What the instances report is cumulative and resets when one restarts, so the
arithmetic here is the whole point: a sample is worth only its difference from
the last one, and a total that went backwards means a restart rather than
negative usage.
"""
import datetime

from app import usage_rollup
from app.models import WorkspaceUsageHour


def setup_function():
    usage_rollup.reset_last_seen()


def _entry(writes=0, broadcasts=0, broadcast_bytes=0, stored=0):
    return {
        "writes": writes,
        "broadcasts": broadcasts,
        "broadcast_bytes": broadcast_bytes,
        "bytes": stored,
    }


def test_the_hour_bucket_is_the_top_of_the_hour():
    moment = datetime.datetime(2026, 5, 4, 13, 47, 31, 900, datetime.timezone.utc)
    assert usage_rollup.hour_start(moment) == datetime.datetime(
        2026, 5, 4, 13, 0, 0, 0, datetime.timezone.utc
    )


def test_a_counter_is_worth_only_what_is_new():
    assert usage_rollup.counter_delta(0, 10) == 10
    assert usage_rollup.counter_delta(10, 25) == 15
    assert usage_rollup.counter_delta(10, 10) == 0


def test_a_counter_that_went_backwards_means_a_restart():
    """Not negative usage: the instance came back and started from zero, so the
    new total is what it has counted since."""
    assert usage_rollup.counter_delta(500, 7) == 7
    assert usage_rollup.counter_delta(500, 0) == 0


def test_an_idle_deployment_records_nothing():
    last_seen = {}
    first = usage_rollup.deltas_from({"ws": _entry()}, last_seen)
    assert first == {}
    assert usage_rollup.deltas_from({"ws": _entry()}, last_seen) == {}


def test_only_the_difference_between_samples_is_recorded():
    last_seen = {}
    usage_rollup.deltas_from({"ws": _entry(writes=10)}, last_seen)
    second = usage_rollup.deltas_from({"ws": _entry(writes=30)}, last_seen)
    assert second["ws"]["writes"] == 20


def test_stored_bytes_is_a_level_not_a_total():
    """Summing a gauge across samples would invent storage nobody used."""
    last_seen = {}
    first = usage_rollup.deltas_from({"ws": _entry(stored=900)}, last_seen)
    second = usage_rollup.deltas_from({"ws": _entry(stored=900)}, last_seen)
    assert first["ws"]["peak_bytes"] == 900
    assert second["ws"]["peak_bytes"] == 900


def test_a_sample_becomes_a_row(client, make_user, make_workspace, db_session):
    workspace = make_workspace(make_user())
    snapshot = {workspace["id"]: _entry(writes=5, broadcasts=40, broadcast_bytes=2048)}

    assert usage_rollup.record(db_session, snapshot) == 1

    row = db_session.query(WorkspaceUsageHour).one()
    assert str(row.workspace_id) == workspace["id"]
    assert row.writes == 5
    assert row.broadcasts == 40
    assert row.broadcast_bytes == 2048


def test_two_samples_in_one_hour_land_on_one_row(
    client, make_user, make_workspace, db_session
):
    workspace = make_workspace(make_user())
    usage_rollup.record(db_session, {workspace["id"]: _entry(writes=5, stored=100)})
    usage_rollup.record(db_session, {workspace["id"]: _entry(writes=12, stored=80)})

    row = db_session.query(WorkspaceUsageHour).one()
    assert row.writes == 12
    assert row.peak_bytes == 100


def test_a_restart_mid_hour_does_not_lose_the_hour(
    client, make_user, make_workspace, db_session
):
    """The counters go back to zero; what was already banked stays banked."""
    workspace = make_workspace(make_user())
    usage_rollup.record(db_session, {workspace["id"]: _entry(writes=100)})
    usage_rollup.record(db_session, {workspace["id"]: _entry(writes=3)})

    row = db_session.query(WorkspaceUsageHour).one()
    assert row.writes == 103


def test_different_hours_are_different_rows(
    client, make_user, make_workspace, db_session
):
    workspace = make_workspace(make_user())
    one = datetime.datetime(2026, 5, 4, 10, 30, tzinfo=datetime.timezone.utc)
    two = datetime.datetime(2026, 5, 4, 11, 5, tzinfo=datetime.timezone.utc)

    usage_rollup.record(db_session, {workspace["id"]: _entry(writes=4)}, when=one)
    usage_rollup.record(db_session, {workspace["id"]: _entry(writes=9)}, when=two)

    rows = db_session.query(WorkspaceUsageHour).all()
    assert sorted(row.writes for row in rows) == [4, 5]


def test_a_workspace_the_database_does_not_know_is_skipped(db_session):
    """The instances report from the disk, which can outlive the row."""
    assert usage_rollup.record(db_session, {"not-a-uuid": _entry(writes=5)}) == 0
    assert db_session.query(WorkspaceUsageHour).count() == 0


def test_a_tick_that_reaches_nobody_records_nothing(db_session):
    def unreachable():
        raise OSError("no instance answered")

    assert usage_rollup.sample_once(db_session, unreachable) == 0


def test_a_tick_before_any_instance_answers_records_nothing(db_session):
    unanswered = {"answered": False, "workspaces": {}}
    assert usage_rollup.sample_once(db_session, lambda: unanswered) == 0
