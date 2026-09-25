"""SimPy simulation of vehicles driving the Coimbatore -> Bangalore highway.

Each vehicle is a SimPy process. Every few seconds of simulated time it moves on
at its current speed (which drifts around its cruising speed), takes a noisy GPS
fix, and map-matches that fix back onto the road. The matched positions drive the
toll zone entry/exit registration in ``gps_toll.tolling``.
"""

from __future__ import annotations

import functools
import logging
import math
import random
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, List, Optional, Sequence, Tuple

import simpy

from gps_toll.models import Coordinate, Place, Route, TollPlaza, Vehicle, load_toll_plazas
from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VEHICLE_CLASSES, VehicleClass
from gps_toll.tolling import (
    GNSS_FREE_KM_PER_DAY,
    TollBill,
    TollEvent,
    TollZone,
    ZonePassage,
    build_toll_zones,
    calculate_bill,
    zone_at,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
ROUTE_FILE = DATA_DIR / "route.json"
TOLL_PLAZAS_FILE = DATA_DIR / "toll_plazas.json"

DEFAULT_ORIGIN = "Coimbatore"
DEFAULT_DESTINATION = "Bangalore"

# Share of each vehicle class in random traffic, and their cruising speed ranges (km/h).
TRAFFIC_MIX = {"car": 0.55, "lcv": 0.12, "bus": 0.08, "3axle": 0.07, "mav": 0.13, "oversized": 0.05}
SPEED_RANGES = {
    "car": (60, 100),
    "lcv": (50, 85),
    "bus": (50, 80),
    "3axle": (40, 65),
    "mav": (40, 60),
    "oversized": (35, 55),
}
# Heavy goods vehicles run on National Permits, so they get no free GNSS distance.
NATIONAL_PERMIT_CLASSES = {"3axle", "mav", "oversized"}
REGISTRATION_PREFIXES = ["TN 37", "TN 38", "TN 33", "TN 30", "TN 29", "TN 24", "KA 01", "KA 05", "KA 51", "KL 07"]

# How quickly a vehicle's speed drifts back to its cruising speed.
SPEED_REVERSION_MIN = 5.0
METRES_PER_DEGREE_LAT = 111_320.0


@dataclass(frozen=True)
class SimulationSettings:
    gps_interval_s: float = 10.0
    gps_noise_m: float = 5.0
    # Standard deviation of speed, as a fraction of the cruising speed.
    speed_variation: float = 0.1
    rate_override: Optional[float] = None
    free_km_per_day: float = GNSS_FREE_KM_PER_DAY

    def __post_init__(self) -> None:
        if self.gps_interval_s <= 0:
            raise ValueError("gps_interval_s must be positive")
        if self.gps_noise_m < 0 or self.speed_variation < 0:
            raise ValueError("gps_noise_m and speed_variation must not be negative")
        if self.rate_override is not None and self.rate_override < 0:
            raise ValueError("rate_override must not be negative")


@dataclass(frozen=True)
class Trip:
    vehicle: Vehicle
    origin: Place
    destination: Place
    departure_min: float = 0.0

    def __post_init__(self) -> None:
        if self.destination.km <= self.origin.km:
            raise ValueError(
                f"{self.destination.name} is not after {self.origin.name} on the route "
                "(vehicles drive from Coimbatore towards Bangalore)"
            )


@dataclass(frozen=True)
class TrackPoint:
    time_min: float
    gps: Coordinate  # noisy GPS fix
    km: float  # map-matched distance along the route
    speed_kmh: float


@dataclass
class TripResult:
    trip: Trip
    track: List[TrackPoint] = field(default_factory=list)
    passages: List[ZonePassage] = field(default_factory=list)
    plazas_passed: List[Tuple[float, TollPlaza]] = field(default_factory=list)
    bill: TollBill = field(default_factory=lambda: TollBill((), ()))

    @property
    def vehicle(self) -> Vehicle:
        return self.trip.vehicle

    @property
    def distance_km(self) -> float:
        return self.track[-1].km - self.track[0].km if self.track else 0.0

    @property
    def duration_min(self) -> float:
        return self.track[-1].time_min - self.track[0].time_min if self.track else 0.0

    @property
    def average_speed_kmh(self) -> float:
        return self.distance_km / (self.duration_min / 60) if self.duration_min else 0.0

    @property
    def toll_amount(self) -> float:
        return self.bill.gnss_total

    def summary(self) -> str:
        vehicle, trip = self.vehicle, self.trip
        permit = "National Permit" if vehicle.national_permit else "no National Permit"
        lines = [
            f"Vehicle: {vehicle.registration}, {vehicle.vehicle_class.name}, {permit}",
            f"Trip: {trip.origin.name} -> {trip.destination.name}, {self.distance_km:.1f} km in "
            f"{format_duration(self.duration_min)} (average {self.average_speed_kmh:.1f} km/h)",
        ]
        if self.bill.lines:
            lines.append("Toll zones (entry km - exit km, distance x rate):")
            for line in self.bill.lines:
                p = line.passage
                free = f", {line.free_km:.1f} km free" if line.free_km else ""
                lines.append(
                    f"  {p.zone.plaza.name:28s} {p.entry.km:6.1f} - {p.exit.km:6.1f} km  "
                    f"{p.distance_km:5.1f} km x {line.rate_per_km:.2f} = {line.amount:7.2f} INR{free}"
                )
        else:
            lines.append("No toll zones on this trip")
        lines.append(
            f"Distance in toll zones: {self.bill.tolled_km:.1f} km ({self.bill.free_km:.1f} km free)"
        )
        lines.append(f"GNSS toll (distance based): {self.bill.gnss_total:.2f} INR")
        lines.append(
            f"FASTag toll ({len(self.bill.fastag_fees)} plazas, full fee): {self.bill.fastag_total:.2f} INR"
            f"  -> saving {self.bill.saving:.2f} INR"
        )
        return "\n".join(lines)


def format_duration(minutes: float) -> str:
    hours, mins = divmod(round(minutes), 60)
    return f"{hours} h {mins:02d} min" if hours else f"{mins} min"


class _VehicleRun:
    """Drives one vehicle along the route and registers its toll zone entries and exits."""

    def __init__(
        self,
        env: simpy.Environment,
        trip: Trip,
        route: Route,
        zones: Sequence[TollZone],
        settings: SimulationSettings,
        rng: random.Random,
        result: TripResult,
    ) -> None:
        self.env, self.trip, self.route, self.zones = env, trip, route, zones
        self.settings, self.rng, self.result = settings, rng, result
        self.true_km = trip.origin.km
        self.matched_km: Optional[float] = None
        self.speed = trip.vehicle.cruise_speed_kmh
        self.current: Optional[Tuple[TollZone, TollEvent]] = None

    def gps_fix(self) -> Coordinate:
        lat, lon = self.route.point_at(self.true_km)
        noise = self.settings.gps_noise_m
        if noise == 0:
            return (lat, lon)
        north, east = self.rng.gauss(0, noise), self.rng.gauss(0, noise)
        return (
            lat + north / METRES_PER_DEGREE_LAT,
            lon + east / (METRES_PER_DEGREE_LAT * math.cos(math.radians(lat))),
        )

    def next_speed(self, dt_min: float) -> float:
        """Ornstein-Uhlenbeck drift around the cruising speed."""
        cruise = self.trip.vehicle.cruise_speed_kmh
        sigma = self.settings.speed_variation * cruise
        theta = 1 / SPEED_REVERSION_MIN
        speed = self.speed + theta * (cruise - self.speed) * dt_min
        speed += sigma * math.sqrt(2 * theta * dt_min) * self.rng.gauss(0, 1)
        return min(max(speed, 0.3 * cruise, 5.0), 1.3 * cruise)

    def record_fix(self) -> None:
        fix = self.gps_fix()
        previous_km = self.matched_km
        if previous_km is None:
            km = self.route.locate(fix, near_km=self.true_km, window_km=1.0)
        else:
            window = 1.0 + 2 * self.speed * self.settings.gps_interval_s / 3600
            # Vehicles only drive forwards, so noise can't move the matched position back.
            km = max(previous_km, self.route.locate(fix, near_km=previous_km, window_km=window))
        self.matched_km = km
        self.result.track.append(TrackPoint(self.env.now, fix, km, self.speed))
        self.update_toll_zones(previous_km, km, fix)

    def update_toll_zones(self, previous_km: Optional[float], km: float, fix: Coordinate) -> None:
        now = self.env.now
        if previous_km is not None:
            for zone in self.zones:
                if previous_km < zone.plaza_km <= km:
                    self.result.plazas_passed.append((now, zone.plaza))
                    logger.debug("%s passed %s plaza", self.trip.vehicle.registration, zone.plaza.name)

        if self.current is not None:
            zone, entry = self.current
            if km < zone.end_km:
                return
            self.close_zone(TollEvent(now, fix, zone.end_km))

        zone = zone_at(self.zones, km)
        if zone is not None:
            # If the last fix was before the zone, the vehicle crossed into it at its start.
            entered_from_outside = previous_km is not None and previous_km < zone.start_km
            entry_km = zone.start_km if entered_from_outside else km
            self.current = (zone, TollEvent(now, fix, entry_km))
            logger.info(
                "%s entered %s toll zone at km %.1f", self.trip.vehicle.registration, zone.plaza.name, entry_km
            )

    def close_zone(self, exit_event: TollEvent) -> None:
        zone, entry = self.current
        self.result.passages.append(ZonePassage(zone, entry, exit_event))
        logger.info(
            "%s left %s toll zone at km %.1f", self.trip.vehicle.registration, zone.plaza.name, exit_event.km
        )
        self.current = None

    def drive(self) -> Generator[simpy.Event, None, None]:
        yield self.env.timeout(self.trip.departure_min)
        logger.info(
            "%s (%s) leaves %s for %s",
            self.trip.vehicle.registration,
            self.trip.vehicle.vehicle_class.name,
            self.trip.origin.name,
            self.trip.destination.name,
        )
        self.record_fix()

        interval_min = self.settings.gps_interval_s / 60
        destination_km = self.trip.destination.km
        while self.true_km < destination_km:
            self.speed = self.next_speed(interval_min)
            step_km = self.speed * interval_min / 60
            remaining_km = destination_km - self.true_km
            if remaining_km <= step_km:
                yield self.env.timeout(remaining_km / self.speed * 60)
                self.true_km = destination_km
            else:
                yield self.env.timeout(interval_min)
                self.true_km += step_km
            self.record_fix()

        if self.current is not None:
            zone, _ = self.current
            last = self.result.track[-1]
            self.close_zone(TollEvent(self.env.now, last.gps, min(last.km, zone.end_km)))
        logger.info("%s reached %s", self.trip.vehicle.registration, self.trip.destination.name)


def run_simulation(
    route: Route,
    zones: Sequence[TollZone],
    trips: Sequence[Trip],
    settings: SimulationSettings = SimulationSettings(),
    rng: Optional[random.Random] = None,
) -> List[TripResult]:
    """Drive every trip at once in one SimPy environment and bill each vehicle."""
    rng = rng or random.Random()
    env = simpy.Environment()
    results = []
    for trip in trips:
        result = TripResult(trip)
        results.append(result)
        env.process(_VehicleRun(env, trip, route, zones, settings, rng, result).drive())
    env.run()

    for result in results:
        result.bill = calculate_bill(
            result.passages,
            [plaza for _, plaza in result.plazas_passed],
            result.vehicle,
            settings.rate_override,
            settings.free_km_per_day,
        )
    return results


@functools.lru_cache(maxsize=None)
def load_default_route() -> Route:
    return Route.from_json(ROUTE_FILE)


@functools.lru_cache(maxsize=None)
def load_default_plazas() -> Tuple[TollPlaza, ...]:
    return tuple(load_toll_plazas(TOLL_PLAZAS_FILE))


@functools.lru_cache(maxsize=None)
def load_default_zones() -> Tuple[TollZone, ...]:
    return tuple(build_toll_zones(load_default_route(), load_default_plazas()))


def random_registration(rng: random.Random) -> str:
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(2))
    return f"{rng.choice(REGISTRATION_PREFIXES)} {letters} {rng.randint(1000, 9999)}"


def make_vehicle(
    vehicle_id: int,
    vehicle_class: VehicleClass,
    rng: random.Random,
    speed_kmh: Optional[float] = None,
    national_permit: Optional[bool] = None,
) -> Vehicle:
    if speed_kmh is None:
        speed_kmh = rng.uniform(*SPEED_RANGES.get(vehicle_class.key, (50, 80)))
    if national_permit is None:
        national_permit = vehicle_class.key in NATIONAL_PERMIT_CLASSES
    return Vehicle(vehicle_id, random_registration(rng), vehicle_class, speed_kmh, national_permit)


def random_trips(route: Route, count: int, rng: random.Random, first_id: int = 1, max_departure_min: float = 120) -> List[Trip]:
    """Random traffic: vehicle classes in the usual mix, joining and leaving at random towns."""
    classes = [VEHICLE_CLASSES[key] for key in TRAFFIC_MIX]
    weights = list(TRAFFIC_MIX.values())
    trips = []
    for vehicle_id in range(first_id, first_id + count):
        vehicle = make_vehicle(vehicle_id, rng.choices(classes, weights)[0], rng)
        origin, destination = sorted(rng.sample(range(len(route.places)), 2))
        trips.append(Trip(vehicle, route.places[origin], route.places[destination], rng.uniform(0, max_departure_min)))
    return trips


def simulate(
    vehicle_class: VehicleClass = DEFAULT_VEHICLE_CLASS,
    speed_kmh: Optional[float] = None,
    origin: str = DEFAULT_ORIGIN,
    destination: str = DEFAULT_DESTINATION,
    national_permit: Optional[bool] = None,
    traffic: int = 0,
    settings: SimulationSettings = SimulationSettings(),
    rng: Optional[random.Random] = None,
    route: Optional[Route] = None,
    zones: Optional[Sequence[TollZone]] = None,
) -> List[TripResult]:
    """Simulate your vehicle plus ``traffic`` random vehicles. Your vehicle's result comes first."""
    rng = rng or random.Random()
    route = route or load_default_route()
    zones = load_default_zones() if zones is None else zones
    vehicle = make_vehicle(1, vehicle_class, rng, speed_kmh, national_permit)
    trips = [Trip(vehicle, route.place(origin), route.place(destination))]
    trips += random_trips(route, traffic, rng, first_id=2)
    return run_simulation(route, zones, trips, settings, rng)
