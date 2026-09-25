import pytest

from gps_toll.models import Route, TollPlaza, Vehicle, calculate_distance
from gps_toll.rates import VEHICLE_CLASSES
from gps_toll.simulation import load_default_plazas, load_default_route, load_default_zones
from gps_toll.tolling import TollEvent, TollZone, ZonePassage, build_toll_zones, calculate_bill, zone_at

CAR = VEHICLE_CLASSES["car"]


def test_default_zones_are_ordered_and_do_not_overlap():
    route, zones = load_default_route(), load_default_zones()

    assert len(zones) == 8
    for zone in zones:
        assert 0 <= zone.start_km <= zone.plaza_km <= zone.end_km <= route.length_km
        assert zone.length_km <= zone.plaza.tollable_km + 1e-9
    for left, right in zip(zones, zones[1:]):
        assert left.end_km <= right.start_km


def test_zone_centred_on_plaza_when_there_is_room():
    road = Route.straight((11.0, 77.0), (11.0, 78.0))
    plaza = TollPlaza("Middle", road.point_at(50), tollable_km=20)

    (zone,) = build_toll_zones(road, [plaza])

    assert zone.start_km == pytest.approx(40, abs=0.01)
    assert zone.end_km == pytest.approx(60, abs=0.01)


def test_overlapping_zones_split_at_midpoint():
    road = Route.straight((11.0, 77.0), (11.0, 78.0))
    first = TollPlaza("A", road.point_at(40), tollable_km=40)  # 20 - 60
    second = TollPlaza("B", road.point_at(70), tollable_km=40)  # 50 - 90

    a, b = build_toll_zones(road, [second, first])

    assert (a.plaza.name, b.plaza.name) == ("A", "B")
    assert a.end_km == pytest.approx(55, abs=0.01)
    assert b.start_km == pytest.approx(55, abs=0.01)


def test_zone_at():
    zones = load_default_zones()
    assert zone_at(zones, zones[2].start_km + 1) is zones[2]
    assert zone_at(zones, 0.5) is None


def _passage(zone: TollZone, entry_km: float, exit_km: float) -> ZonePassage:
    return ZonePassage(zone, TollEvent(0, (0, 0), entry_km), TollEvent(1, (0, 0), exit_km))


def test_bill_applies_20_free_km_then_plaza_rates():
    zones = load_default_zones()
    passages = [_passage(zones[0], zones[0].start_km, zones[0].end_km), _passage(zones[1], zones[1].start_km, zones[1].end_km)]
    car = Vehicle(1, "TN 38 AA 0001", CAR)

    bill = calculate_bill(passages, [zones[0].plaza, zones[1].plaza], car)

    first, second = bill.lines
    assert first.free_km == 20
    assert first.amount == pytest.approx((zones[0].length_km - 20) * zones[0].plaza.rate_per_km(CAR))
    assert second.free_km == 0
    assert second.amount == pytest.approx(zones[1].length_km * zones[1].plaza.rate_per_km(CAR))
    assert bill.fastag_total == zones[0].plaza.fees["car"] + zones[1].plaza.fees["car"]
    assert bill.saving == pytest.approx(bill.fastag_total - bill.gnss_total)


def test_free_distance_spans_zones():
    zones = load_default_zones()
    passages = [_passage(zones[0], zones[0].end_km - 5, zones[0].end_km), _passage(zones[1], zones[1].start_km, zones[1].end_km)]

    bill = calculate_bill(passages, [], Vehicle(1, "TN 38 AA 0001", CAR))

    assert [line.free_km for line in bill.lines] == pytest.approx([5, 15])
    assert bill.lines[0].amount == 0


def test_national_permit_vehicles_get_no_free_distance():
    zones = load_default_zones()
    passages = [_passage(zones[0], zones[0].start_km, zones[0].end_km)]
    truck = Vehicle(1, "TN 38 AA 0001", VEHICLE_CLASSES["mav"], national_permit=True)

    bill = calculate_bill(passages, [], truck)

    assert bill.free_km == 0
    assert bill.gnss_total == pytest.approx(zones[0].length_km * zones[0].plaza.rate_per_km(truck.vehicle_class))


def test_rate_override():
    zones = load_default_zones()
    passages = [_passage(zones[0], zones[0].start_km, zones[0].start_km + 30)]

    bill = calculate_bill(passages, [], Vehicle(1, "TN 38 AA 0001", CAR), rate_override=2.0, free_km_per_day=0)

    assert bill.gnss_total == pytest.approx(60)
    with pytest.raises(ValueError):
        calculate_bill(passages, [], Vehicle(1, "TN 38 AA 0001", CAR), rate_override=-1)


def test_plazas_file_matches_route():
    route = load_default_route()
    for plaza in load_default_plazas():
        # Every plaza sits on the road (within 100 m).
        km = route.locate(plaza.location)
        assert calculate_distance(route.point_at(km), plaza.location) < 0.1
