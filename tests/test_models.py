import pytest

from gps_toll.models import Route, TollPlaza, Vehicle, calculate_distance
from gps_toll.rates import VEHICLE_CLASSES
from gps_toll.simulation import load_default_plazas, load_default_route


@pytest.fixture(scope="module")
def route():
    return load_default_route()


def test_default_route_follows_the_real_road(route):
    # The road is about 362 km, much longer than the 227 km straight line between the cities.
    assert 355 < route.length_km < 370
    assert calculate_distance(route.start, route.end) == pytest.approx(227, abs=2)
    assert [p.name for p in route.places][0] == "Coimbatore"
    assert [p.name for p in route.places][-1] == "Bangalore"
    assert [p.km for p in route.places] == sorted(p.km for p in route.places)


@pytest.mark.parametrize("km", [0, 12.3, 100, 181.7, 300, 362])
def test_locate_is_inverse_of_point_at(route, km):
    km = min(km, route.length_km)
    assert route.locate(route.point_at(km)) == pytest.approx(km, abs=0.01)
    assert route.locate(route.point_at(km), near_km=km + 0.5, window_km=1) == pytest.approx(km, abs=0.01)


def test_point_at_clamps_to_route_ends(route):
    assert route.point_at(-5) == route.start
    assert route.point_at(route.length_km + 5) == pytest.approx(route.end)


def test_locate_snaps_off_road_position_to_nearest_point():
    road = Route.straight((11.0, 77.0), (11.0, 77.1))
    # 100 m north of the road, a third of the way along it.
    km = road.locate((11.0009, 77.0333))
    assert km == pytest.approx(road.length_km / 3, abs=0.05)


def test_place_lookup(route):
    assert route.place("salem").name == "Salem"
    with pytest.raises(KeyError):
        route.place("Chennai")


def test_route_needs_two_points():
    with pytest.raises(ValueError):
        Route([(11.0, 77.0)])


def test_toll_plaza_rates():
    plaza = TollPlaza("Test", (11.0, 77.0), tollable_km=50, fees={"car": 100})
    car, bus = VEHICLE_CLASSES["car"], VEHICLE_CLASSES["bus"]

    assert plaza.fee(car) == 100
    assert plaza.rate_per_km(car) == 2.0
    # No published bus fee: falls back to the representative per-km rate.
    assert plaza.fee(bus) == round(bus.rate_per_km * 50)


def test_toll_plaza_needs_positive_length():
    with pytest.raises(ValueError):
        TollPlaza("Bad", (11.0, 77.0), tollable_km=0)


def test_default_plazas_have_all_fees():
    plazas = load_default_plazas()
    assert len(plazas) == 8
    for plaza in plazas:
        assert set(plaza.fees) == set(VEHICLE_CLASSES)
        assert plaza.tollable_km > 0
        # Bigger vehicles never pay less than smaller ones.
        fees = [plaza.fees[key] for key in VEHICLE_CLASSES]
        assert fees == sorted(fees)


def test_vehicle_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        Vehicle(1, "TN 38 AA 0001", cruise_speed_kmh=0)
