"""Run the GPS toll simulation.

    python main.py                     # Tkinter GUI
    python main.py --cli               # print results in the terminal and save the map
    python main.py --cli --traffic 20  # your vehicle plus 20 other vehicles
    python main.py --history           # show saved trips
"""

from __future__ import annotations

import argparse
import logging
import random
from typing import List, Optional

from gps_toll.billing import issue_receipt
from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VEHICLE_CLASSES
from gps_toll.simulation import (
    DEFAULT_DESTINATION,
    DEFAULT_ORIGIN,
    SimulationSettings,
    format_duration,
    load_default_route,
    load_default_zones,
    simulate,
)
from gps_toll.storage import DEFAULT_DB_FILE, TripStore
from gps_toll.visualization import DEFAULT_MAP_FILE, save_figures, save_route_map


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    places = [p.name for p in load_default_route().places]
    defaults = SimulationSettings()
    parser = argparse.ArgumentParser(
        description="GPS toll-based system simulation on the Coimbatore -> Bangalore highway (NH544 / NH44)."
    )
    parser.add_argument("--cli", action="store_true", help="run without the GUI and print the results")
    parser.add_argument("--history", nargs="?", type=int, const=20, metavar="N",
                        help="print the last N saved trips (default 20) and exit")

    vehicle = parser.add_argument_group("your vehicle")
    vehicle.add_argument("--vehicle", choices=VEHICLE_CLASSES, default=DEFAULT_VEHICLE_CLASS.key,
                         help=f"vehicle class (default: {DEFAULT_VEHICLE_CLASS.key})")
    vehicle.add_argument("--speed", type=float, help="cruising speed in km/h (default: random for the class)")
    vehicle.add_argument("--from", dest="origin", choices=places, default=DEFAULT_ORIGIN, metavar="PLACE",
                         help=f"where the trip starts: {', '.join(places)} (default: {DEFAULT_ORIGIN})")
    vehicle.add_argument("--to", dest="destination", choices=places, default=DEFAULT_DESTINATION, metavar="PLACE",
                         help=f"where the trip ends (default: {DEFAULT_DESTINATION})")
    vehicle.add_argument("--national-permit", action=argparse.BooleanOptionalAction, default=None,
                         help="whether the vehicle has a National Permit (no free GNSS distance); "
                              "default: yes for 3-axle and larger goods vehicles")

    sim = parser.add_argument_group("simulation")
    sim.add_argument("--traffic", type=int, default=0, metavar="N", help="number of other random vehicles (default: 0)")
    sim.add_argument("--gps-noise", type=float, default=defaults.gps_noise_m, metavar="METRES",
                     help=f"GPS error standard deviation (default: {defaults.gps_noise_m:g})")
    sim.add_argument("--gps-interval", type=float, default=defaults.gps_interval_s, metavar="SECONDS",
                     help=f"time between GPS fixes (default: {defaults.gps_interval_s:g})")
    sim.add_argument("--speed-variation", type=float, default=defaults.speed_variation, metavar="FRACTION",
                     help=f"how much speed varies around the cruising speed (default: {defaults.speed_variation:g})")
    sim.add_argument("--rate", type=float, help="charge every toll zone at this rate in INR per km instead")
    sim.add_argument("--seed", type=int, help="random seed, for repeatable runs")

    output = parser.add_argument_group("output")
    output.add_argument("--db", default=DEFAULT_DB_FILE, help=f"trip history database (default: {DEFAULT_DB_FILE})")
    output.add_argument("--no-db", action="store_true", help="don't save trips")
    output.add_argument("--map-file", default=DEFAULT_MAP_FILE, help=f"where to save the map (default: {DEFAULT_MAP_FILE})")
    output.add_argument("--plots-dir", help="also save the charts as PNG files in this folder (CLI mode only)")
    output.add_argument("-v", "--verbose", action="store_true", help="log every toll zone entry and exit")

    args = parser.parse_args(argv)
    if args.speed is not None and args.speed <= 0:
        parser.error("--speed must be positive")
    if args.rate is not None and args.rate < 0:
        parser.error("--rate must not be negative")
    if args.traffic < 0:
        parser.error("--traffic must not be negative")
    if args.gps_noise < 0 or args.gps_interval <= 0 or args.speed_variation < 0:
        parser.error("--gps-noise and --speed-variation must not be negative, --gps-interval must be positive")
    route = load_default_route()
    if route.place(args.destination).km <= route.place(args.origin).km:
        parser.error(f"--to {args.destination} must come after --from {args.origin} on the way to Bangalore")
    return args


def settings_from_args(args: argparse.Namespace) -> SimulationSettings:
    return SimulationSettings(
        gps_interval_s=args.gps_interval,
        gps_noise_m=args.gps_noise,
        speed_variation=args.speed_variation,
        rate_override=args.rate,
    )


def run_cli(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    route, zones = load_default_route(), load_default_zones()
    results = simulate(
        vehicle_class=VEHICLE_CLASSES[args.vehicle],
        speed_kmh=args.speed,
        origin=args.origin,
        destination=args.destination,
        national_permit=args.national_permit,
        traffic=args.traffic,
        settings=settings_from_args(args),
        rng=rng,
    )
    receipts = [issue_receipt(result, rng) for result in results]

    print("\nSimulation results")
    print(results[0].summary())
    print("\nPayment receipt")
    print(receipts[0].as_text())

    if len(results) > 1:
        print(f"\nAll vehicles ({len(results)})")
        print(f"{'Vehicle':14s} {'Type':30s} {'Route':28s} {'km':>6s} {'GNSS':>9s} {'FASTag':>9s}")
        for result in results:
            trip = f"{result.trip.origin.name} -> {result.trip.destination.name}"
            print(
                f"{result.vehicle.registration:14s} {result.vehicle.vehicle_class.name:30s} {trip:28s} "
                f"{result.distance_km:6.1f} {result.bill.gnss_total:9.2f} {result.bill.fastag_total:9.2f}"
            )
        print(
            f"{'Total':73s} {sum(r.distance_km for r in results):7.1f} "
            f"{sum(r.bill.gnss_total for r in results):9.2f} {sum(r.bill.fastag_total for r in results):9.2f}"
        )

    if not args.no_db:
        with TripStore(args.db) as store:
            for result, receipt in zip(results, receipts):
                store.save(result, receipt)
        print(f"\nSaved {len(results)} trip(s) to {args.db}")

    map_path = save_route_map(route, zones, results, args.map_file)
    print(f"Map saved to {map_path}")
    if args.plots_dir:
        for path in save_figures(route, zones, results, args.plots_dir):
            print(f"Chart saved to {path}")


def print_history(db_file: str, limit: int) -> None:
    with TripStore(db_file) as store:
        trips = store.recent_trips(limit)
        totals = store.totals()
    if not trips:
        print(f"No trips saved in {db_file} yet.")
        return
    print(f"{'#':>4s}  {'Recorded':19s}  {'Vehicle':14s} {'Type':9s} {'Route':28s} {'km':>6s} {'Time':>11s} "
          f"{'GNSS':>9s} {'FASTag':>9s}")
    for trip in trips:
        route = f"{trip.origin} -> {trip.destination}"
        print(
            f"{trip.id:4d}  {trip.recorded_at.replace('T', ' '):19s}  {trip.registration:14s} {trip.vehicle_class:9s} "
            f"{route:28s} {trip.distance_km:6.1f} {format_duration(trip.duration_min):>11s} "
            f"{trip.gnss_toll:9.2f} {trip.fastag_toll:9.2f}"
        )
    print(
        f"\n{totals.trips} trips in total, {totals.distance_km:,.1f} km, GNSS tolls {totals.gnss_toll:,.2f} INR "
        f"(FASTag would be {totals.fastag_toll:,.2f} INR)"
    )


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")

    if args.history is not None:
        print_history(args.db, args.history)
    elif args.cli:
        run_cli(args)
    else:
        # Imported here so --cli works on machines without Tk installed.
        from gps_toll.gui import run_app

        run_app(
            speed_kmh=args.speed,
            vehicle_class=VEHICLE_CLASSES[args.vehicle],
            settings=settings_from_args(args),
            map_file=args.map_file,
            db_file=None if args.no_db else args.db,
            origin=args.origin,
            destination=args.destination,
            traffic=args.traffic,
            national_permit=args.national_permit,
            rng=random.Random(args.seed),
        )


if __name__ == "__main__":
    main()
