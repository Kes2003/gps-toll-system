"""SimPy simulation of a car driving along a highway through GPS toll zones.

The car's GPS position is sampled as it drives. The first toll zone it enters is
registered as the entry point and the last one as the exit point; the toll is
the distance driven between them multiplied by the per-km rate.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Generator, List, Optional, Sequence

import simpy

from gps_toll.models import Car, Coordinate, Highway, TollCrossing, TollPoint

logger = logging.getLogger(__name__)

COIMBATORE: Coordinate = (11.0168, 76.9558)
BANGALORE: Coordinate = (12.9716, 77.5946)

# Toll points at 30%, 50% and 70% of the way along the highway.
DEFAULT_TOLL_FRACTIONS = (0.3, 0.5, 0.7)
DEFAULT_TOLL_RADIUS_KM = 1.0
DEFAULT_TOLL_RATE_PER_KM = 0.25  # INR
MIN_SPEED_KMH = 50.0
MAX_SPEED_KMH = 100.0

# Upper bound on the time between two GPS fixes, in simulated minutes.
MAX_TIME_STEP_MIN = 1.0


@dataclass(frozen=True)
class TrackPoint:
    """A single GPS fix: when it was taken, where, and the distance driven so far."""

    time_min: float
    position: Coordinate
    odometer_km: float


@dataclass
class TripResult:
    car: Car
    highway: Highway
    toll_points: List[TollPoint]
    toll_rate_per_km: float
    track: List[TrackPoint] = field(default_factory=list)
    crossings: List[TollCrossing] = field(default_factory=list)

    @property
    def distance_km(self) -> float:
        return self.track[-1].odometer_km if self.track else 0.0

    @property
    def duration_min(self) -> float:
        return self.track[-1].time_min if self.track else 0.0

    @property
    def entry(self) -> Optional[TollCrossing]:
        return self.crossings[0] if self.crossings else None

    @property
    def exit(self) -> Optional[TollCrossing]:
        # A trip needs two different toll crossings to have a chargeable segment.
        return self.crossings[-1] if len(self.crossings) >= 2 else None

    @property
    def tolled_distance_km(self) -> float:
        if self.entry is None or self.exit is None:
            return 0.0
        return self.exit.odometer_km - self.entry.odometer_km

    @property
    def toll_amount(self) -> float:
        return self.tolled_distance_km * self.toll_rate_per_km

    def summary(self) -> str:
        lines = [
            f"Route: {self.highway.start_name} -> {self.highway.end_name} ({self.distance_km:.2f} km)",
            f"Speed: {self.car.speed_kmh:.2f} km/h, travel time: {format_duration(self.duration_min)}",
        ]
        for crossing in self.crossings:
            lines.append(
                f"  Passed {crossing.toll_point.name} at {crossing.odometer_km:.2f} km "
                f"(t = {format_duration(crossing.time_min)})"
            )
        if self.entry and self.exit:
            lines.append(f"Toll entry: {self.entry.toll_point.name}, exit: {self.exit.toll_point.name}")
        else:
            lines.append("No chargeable toll segment (fewer than two toll zones passed)")
        lines.append(
            f"Distance charged: {self.tolled_distance_km:.2f} km @ {self.toll_rate_per_km:.2f} INR/km"
        )
        lines.append(f"Total toll amount: {self.toll_amount:.2f} INR")
        return "\n".join(lines)


def format_duration(minutes: float) -> str:
    hours, mins = divmod(round(minutes), 60)
    return f"{hours} h {mins:02d} min" if hours else f"{mins} min"


def car_process(
    env: simpy.Environment,
    car: Car,
    highway: Highway,
    toll_points: Sequence[TollPoint],
    track: List[TrackPoint],
    crossings: List[TollCrossing],
) -> Generator[simpy.Event, None, None]:
    """Drive ``car`` from the start of ``highway`` to its end, recording GPS fixes and toll crossings."""
    total_km = highway.length_km

    # Keep the distance between GPS fixes no larger than the smallest toll zone
    # radius so a car can never skip over a zone between two fixes.
    step_km = car.speed_kmh * MAX_TIME_STEP_MIN / 60
    if toll_points:
        step_km = min(step_km, min(toll.radius_km for toll in toll_points))

    odometer = 0.0
    inside: set = set()

    def record_fix(position: Coordinate) -> None:
        track.append(TrackPoint(env.now, position, odometer))
        logger.debug("Car %s at %s (%.2f km)", car.car_id, position, odometer)
        for toll in toll_points:
            if not toll.contains(position):
                inside.discard(toll.name)
            elif toll.name not in inside:
                inside.add(toll.name)
                crossings.append(TollCrossing(toll, env.now, position, odometer))
                logger.info("Car %s entered %s at %.2f km", car.car_id, toll.name, odometer)

    logger.info("Car %s starts at %s with speed %.2f km/h", car.car_id, highway.start_name, car.speed_kmh)
    record_fix(highway.start)

    for step in range(1, math.ceil(total_km / step_km) + 1):
        next_odometer = min(step * step_km, total_km)
        yield env.timeout((next_odometer - odometer) / car.speed_kmh * 60)
        odometer = next_odometer
        record_fix(highway.interpolate(odometer / total_km))

    logger.info("Car %s reached %s", car.car_id, highway.end_name)


def run_simulation(
    car: Car,
    highway: Highway,
    toll_points: Sequence[TollPoint],
    toll_rate_per_km: float = DEFAULT_TOLL_RATE_PER_KM,
) -> TripResult:
    if toll_rate_per_km < 0:
        raise ValueError(f"toll_rate_per_km must not be negative, got {toll_rate_per_km}")

    result = TripResult(car, highway, list(toll_points), toll_rate_per_km)
    env = simpy.Environment()
    env.process(car_process(env, car, highway, result.toll_points, result.track, result.crossings))
    env.run()
    return result


def default_highway() -> Highway:
    return Highway(COIMBATORE, BANGALORE, "Coimbatore", "Bangalore")


def default_toll_points(highway: Highway, radius_km: float = DEFAULT_TOLL_RADIUS_KM) -> List[TollPoint]:
    return [
        TollPoint(f"Toll Point {i}", highway.interpolate(fraction), radius_km)
        for i, fraction in enumerate(DEFAULT_TOLL_FRACTIONS, start=1)
    ]


def simulate_default_trip(
    speed_kmh: Optional[float] = None,
    toll_rate_per_km: float = DEFAULT_TOLL_RATE_PER_KM,
    rng: Optional[random.Random] = None,
) -> TripResult:
    """Simulate one car on the Coimbatore -> Bangalore highway. A random speed is used if none is given."""
    if speed_kmh is None:
        speed_kmh = (rng or random).uniform(MIN_SPEED_KMH, MAX_SPEED_KMH)
    highway = default_highway()
    return run_simulation(Car(1, speed_kmh), highway, default_toll_points(highway), toll_rate_per_km)
