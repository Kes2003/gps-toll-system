import pytest

from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VEHICLE_CLASSES


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
