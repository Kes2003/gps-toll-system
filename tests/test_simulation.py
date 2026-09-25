import random

import pytest

from gps_toll.billing import issue_receipt
from gps_toll.models import Car, Highway, TollPoint, calculate_distance
from gps_toll.simulation import (
    BANGALORE,
    COIMBATORE,
    default_highway,
    default_toll_points,
    format_duration,
    run_simulation,
    simulate_default_trip,
)


@pytest.fixture
def highway():
    return default_highway()


def test_interpolate_endpoints_and_clamping(highway):
    assert highway.interpolate(0) == COIMBATORE
    assert highway.interpolate(1) == pytest.approx(BANGALORE)
    assert highway.interpolate(-0.5) == COIMBATORE
    assert highway.interpolate(1.5) == pytest.approx(BANGALORE)


def test_car_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        Car(1, 0)


@pytest.mark.parametrize("speed", [50, 75.5, 100, 300])
def test_all_toll_points_detected_in_order(highway, speed):
    result = run_simulation(Car(1, speed), highway, default_toll_points(highway))

    assert [c.toll_point.name for c in result.crossings] == ["Toll Point 1", "Toll Point 2", "Toll Point 3"]
    for crossing in result.crossings:
        assert calculate_distance(crossing.position, crossing.toll_point.location) <= crossing.toll_point.radius_km


def test_trip_reaches_destination_in_expected_time(highway):
    result = run_simulation(Car(1, 80), highway, default_toll_points(highway))

    assert result.track[-1].position == pytest.approx(highway.end)
    assert result.distance_km == pytest.approx(highway.length_km)
    assert result.duration_min == pytest.approx(highway.length_km / 80 * 60)


def test_toll_charged_between_first_and_last_toll_point(highway):
    rate = 2.0
    result = run_simulation(Car(1, 80), highway, default_toll_points(highway), toll_rate_per_km=rate)

    assert result.entry.toll_point.name == "Toll Point 1"
    assert result.exit.toll_point.name == "Toll Point 3"
    # Toll points sit at 30% and 70% of the highway; each fix is within one zone radius of its toll point.
    assert result.tolled_distance_km == pytest.approx(0.4 * highway.length_km, abs=2.0)
    assert result.toll_amount == pytest.approx(result.tolled_distance_km * rate)


def test_no_toll_without_two_toll_points(highway):
    single = [TollPoint("Only", highway.interpolate(0.5))]

    for toll_points in ([], single):
        result = run_simulation(Car(1, 80), highway, toll_points)
        assert result.exit is None
        assert result.tolled_distance_km == 0
        assert result.toll_amount == 0


def test_negative_rate_rejected(highway):
    with pytest.raises(ValueError):
        run_simulation(Car(1, 80), highway, [], toll_rate_per_km=-1)


def test_toll_zone_not_counted_twice():
    # A short road that starts and ends inside the same large toll zone.
    road = Highway((11.0, 77.0), (11.01, 77.0))
    zone = TollPoint("Big", road.interpolate(0.5), radius_km=5)

    result = run_simulation(Car(1, 60), road, [zone])

    assert len(result.crossings) == 1


def test_random_speed_is_repeatable_with_seed():
    first = simulate_default_trip(rng=random.Random(7))
    second = simulate_default_trip(rng=random.Random(7))

    assert 50 <= first.car.speed_kmh <= 100
    assert first.car.speed_kmh == second.car.speed_kmh
    assert first.toll_amount == second.toll_amount


def test_receipt_matches_trip():
    result = simulate_default_trip(speed_kmh=60)
    receipt = issue_receipt(result, random.Random(1))

    assert receipt.amount_inr == round(result.toll_amount, 2)
    assert 1_000_000_000 <= receipt.transaction_id <= 9_999_999_999
    assert f"Amount Paid: {result.toll_amount:.2f} INR" in receipt.as_text()


@pytest.mark.parametrize("minutes, expected", [(0, "0 min"), (45.4, "45 min"), (60, "1 h 00 min"), (135, "2 h 15 min")])
def test_format_duration(minutes, expected):
    assert format_duration(minutes) == expected
