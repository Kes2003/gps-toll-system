import random

import pytest

from gps_toll.models import Place, Vehicle
from gps_toll.rates import VEHICLE_CLASSES
from gps_toll.simulation import (
    SimulationSettings,
    Trip,
    format_duration,
    load_default_route,
    load_default_zones,
    random_trips,
    run_simulation,
    simulate,
)

EXACT = SimulationSettings(gps_noise_m=0, speed_variation=0)


def test_full_trip_passes_every_toll_zone_in_order():
    (result,) = simulate(speed_kmh=80, settings=EXACT, rng=random.Random(1))
    zones = load_default_zones()

    assert [line.passage.zone for line in result.bill.lines] == list(zones)
    assert [plaza for _, plaza in result.plazas_passed] == [zone.plaza for zone in zones]
    for line in result.bill.lines:
        assert line.passage.entry.km == pytest.approx(line.passage.zone.start_km)
        assert line.passage.exit.km == pytest.approx(line.passage.zone.end_km)
        assert line.passage.entry.time_min < line.passage.exit.time_min


def test_trip_distance_and_time():
    route = load_default_route()
    (result,) = simulate(speed_kmh=80, settings=EXACT, rng=random.Random(1))

    trip_km = route.place("Bangalore").km - route.place("Coimbatore").km
    assert trip_km == pytest.approx(route.length_km, abs=0.01)
    assert result.distance_km == pytest.approx(trip_km, abs=0.001)
    assert result.duration_min == pytest.approx(trip_km / 80 * 60, rel=1e-6)
    assert result.track[-1].gps == pytest.approx(route.end, abs=1e-4)


def test_full_trip_toll_is_sum_of_zone_charges():
    zones = load_default_zones()
    car = VEHICLE_CLASSES["car"]
    (result,) = simulate(speed_kmh=80, settings=EXACT, rng=random.Random(1))

    expected = sum(zone.length_km * zone.plaza.rate_per_km(car) for zone in zones)
    expected -= 20 * zones[0].plaza.rate_per_km(car)  # the first 20 km are free
    assert result.bill.gnss_total == pytest.approx(expected)
    assert result.bill.fastag_total == sum(zone.plaza.fees["car"] for zone in zones)
    assert result.bill.gnss_total < result.bill.fastag_total


def test_gps_noise_barely_changes_the_toll():
    (exact,) = simulate(speed_kmh=80, settings=EXACT, rng=random.Random(1))
    for seed in range(3):
        (noisy,) = simulate(speed_kmh=80, settings=SimulationSettings(gps_noise_m=15), rng=random.Random(seed))
        assert len(noisy.bill.lines) == len(exact.bill.lines)
        assert noisy.bill.gnss_total == pytest.approx(exact.bill.gnss_total, abs=0.5)


def test_noisy_fixes_are_off_the_road_but_matched_back_onto_it():
    route = load_default_route()
    (result,) = simulate(speed_kmh=80, settings=SimulationSettings(gps_noise_m=10), rng=random.Random(2))

    offsets = [abs(route.locate(p.gps, near_km=p.km) - p.km) for p in result.track[1:200]]
    assert max(offsets) < 0.1
    assert any(p.gps != route.point_at(p.km) for p in result.track)
    assert [p.km for p in result.track] == sorted(p.km for p in result.track)


def test_speed_varies_around_cruising_speed():
    (result,) = simulate(speed_kmh=80, settings=SimulationSettings(speed_variation=0.1), rng=random.Random(3))
    speeds = [p.speed_kmh for p in result.track]

    assert min(speeds) < 75 and max(speeds) > 85
    assert all(0.3 * 80 <= s <= 1.3 * 80 for s in speeds)
    assert 70 < result.average_speed_kmh < 90


def test_partial_trip_pays_only_for_zones_it_uses():
    route = load_default_route()
    (result,) = simulate(origin="Salem", destination="Krishnagiri", speed_kmh=70, settings=EXACT, rng=random.Random(1))
    salem, krishnagiri = route.place("Salem").km, route.place("Krishnagiri").km

    assert result.distance_km == pytest.approx(krishnagiri - salem, abs=0.01)
    names = [line.passage.zone.plaza.name for line in result.bill.lines]
    assert names == ["Omalur (Kottagoundampatti)", "Thoppur (Palayam)", "Krishnagiri"]
    # Salem is inside the Omalur zone, so that passage starts at Salem, not the zone start.
    assert result.bill.lines[0].passage.entry.km == pytest.approx(salem, abs=0.01)
    assert result.bill.lines[-1].passage.exit.km == pytest.approx(krishnagiri, abs=0.01)
    # The Krishnagiri plaza is beyond Krishnagiri town, so FASTag charges only two plazas.
    assert [p.name for _, p in result.plazas_passed] == ["Omalur (Kottagoundampatti)", "Thoppur (Palayam)"]


def test_trip_must_go_towards_bangalore():
    route = load_default_route()
    with pytest.raises(ValueError):
        Trip(Vehicle(1, "TN 38 AA 0001"), route.place("Hosur"), route.place("Salem"))


def test_fleet_runs_concurrently():
    results = simulate(traffic=10, rng=random.Random(4))

    assert len(results) == 11
    assert len({r.vehicle.registration for r in results}) == 11
    departures = [r.track[0].time_min for r in results]
    assert departures[0] == 0
    assert any(d > 0 for d in departures[1:])
    for result in results:
        assert result.trip.origin.km < result.trip.destination.km
        assert result.distance_km == pytest.approx(result.trip.destination.km - result.trip.origin.km, abs=0.05)


def test_traffic_mix_and_national_permits():
    route = load_default_route()
    trips = random_trips(route, 300, random.Random(5))
    keys = [trip.vehicle.vehicle_class.key for trip in trips]

    assert set(keys) == set(VEHICLE_CLASSES)
    assert keys.count("car") > len(keys) / 3
    for trip in trips:
        assert trip.vehicle.national_permit == (trip.vehicle.vehicle_class.key in {"3axle", "mav", "oversized"})


def test_same_seed_gives_same_results():
    first = simulate(traffic=5, rng=random.Random(6))
    second = simulate(traffic=5, rng=random.Random(6))

    assert [r.bill.gnss_total for r in first] == [r.bill.gnss_total for r in second]
    assert [r.vehicle.registration for r in first] == [r.vehicle.registration for r in second]


def test_long_gps_interval_still_detects_every_zone():
    settings = SimulationSettings(gps_interval_s=60, gps_noise_m=0, speed_variation=0)
    (result,) = simulate(speed_kmh=120, settings=settings, rng=random.Random(1))

    assert len(result.bill.lines) == len(load_default_zones())


def test_run_simulation_with_custom_trip():
    route, zones = load_default_route(), load_default_zones()
    bus = Vehicle(7, "TN 30 BU 5555", VEHICLE_CLASSES["bus"], cruise_speed_kmh=60)
    trip = Trip(bus, route.place("Coimbatore"), Place("Salem", route.place("Salem").km), departure_min=30)

    (result,) = run_simulation(route, zones, [trip], EXACT, random.Random(1))

    assert result.track[0].time_min == 30
    assert "Bus / Truck" in result.summary()


def test_invalid_settings():
    with pytest.raises(ValueError):
        SimulationSettings(gps_interval_s=0)
    with pytest.raises(ValueError):
        SimulationSettings(gps_noise_m=-1)


@pytest.mark.parametrize("minutes, expected", [(0, "0 min"), (45.4, "45 min"), (60, "1 h 00 min"), (135, "2 h 15 min")])
def test_format_duration(minutes, expected):
    assert format_duration(minutes) == expected
