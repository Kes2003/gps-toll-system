import random

import pytest

from gps_toll.billing import issue_receipt
from gps_toll.simulation import simulate
from gps_toll.storage import TripStore


@pytest.fixture
def results():
    return simulate(traffic=3, rng=random.Random(8))


def test_trips_and_charges_are_saved(tmp_path, results):
    rng = random.Random(1)
    with TripStore(tmp_path / "trips.db") as store:
        ids = [store.save(result, issue_receipt(result, rng)) for result in results]
        trips = store.recent_trips()

        assert [t.id for t in trips] == sorted(ids, reverse=True)
        mine = next(t for t in trips if t.id == ids[0])
        assert mine.registration == results[0].vehicle.registration
        assert mine.vehicle_class == results[0].vehicle.vehicle_class.key
        assert mine.gnss_toll == pytest.approx(results[0].bill.gnss_total, abs=0.005)
        assert mine.fastag_toll == results[0].bill.fastag_total

        charges = store.charges(ids[0])
        assert [c.toll_plaza for c in charges] == [l.passage.zone.plaza.name for l in results[0].bill.lines]
        assert sum(c.amount for c in charges) == pytest.approx(results[0].bill.gnss_total, abs=0.05)


def test_history_survives_reopening(tmp_path, results):
    path = tmp_path / "trips.db"
    with TripStore(path) as store:
        store.save(results[0], issue_receipt(results[0]))
    with TripStore(path) as store:
        store.save(results[1], issue_receipt(results[1]))
        totals = store.totals()

    assert totals.trips == 2
    assert totals.distance_km == pytest.approx(results[0].distance_km + results[1].distance_km)


def test_empty_history(tmp_path):
    with TripStore(tmp_path / "empty.db") as store:
        assert store.recent_trips() == []
        assert store.totals().trips == 0
