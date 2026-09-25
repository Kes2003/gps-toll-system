import pytest

from gps_toll.models import Car
from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VEHICLE_CLASSES
from gps_toll.simulation import default_highway, default_toll_points, run_simulation, simulate_default_trip


def test_default_vehicle_is_car_at_1_50_per_km():
    assert DEFAULT_VEHICLE_CLASS is VEHICLE_CLASSES["car"]
    assert DEFAULT_VEHICLE_CLASS.rate_per_km == 1.50


@pytest.mark.parametrize("vehicle_class", VEHICLE_CLASSES.values(), ids=VEHICLE_CLASSES.keys())
def test_rates_follow_nh_fee_rules_base_rates(vehicle_class):
    # Every class is revised from its 2007-08 base rate by the same factor as a car.
    car = VEHICLE_CLASSES["car"]
    factor = car.rate_per_km / car.base_rate_2007_per_km
    assert vehicle_class.rate_per_km == pytest.approx(vehicle_class.base_rate_2007_per_km * factor, abs=0.01)


def test_rates_increase_with_vehicle_size():
    rates = [vc.rate_per_km for vc in VEHICLE_CLASSES.values()]
    assert rates == sorted(rates)


@pytest.mark.parametrize("key", VEHICLE_CLASSES)
def test_trip_charged_at_vehicle_class_rate(key):
    vehicle_class = VEHICLE_CLASSES[key]
    result = simulate_default_trip(speed_kmh=80, vehicle_class=vehicle_class)

    assert result.toll_rate_per_km == vehicle_class.rate_per_km
    assert result.toll_amount == pytest.approx(result.tolled_distance_km * vehicle_class.rate_per_km)


def test_explicit_rate_overrides_vehicle_class():
    highway = default_highway()
    result = run_simulation(Car(1, 80, VEHICLE_CLASSES["bus"]), highway, default_toll_points(highway), 3.0)

    assert result.toll_rate_per_km == 3.0
