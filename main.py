"""Run the GPS toll simulation.

    python main.py            # Tkinter GUI
    python main.py --cli      # print results in the terminal and save the map
"""

from __future__ import annotations

import argparse
import logging
import random
from typing import List, Optional

from gps_toll.billing import issue_receipt
from gps_toll.simulation import DEFAULT_TOLL_RATE_PER_KM, simulate_default_trip
from gps_toll.visualization import DEFAULT_MAP_FILE, create_path_figure, save_route_map


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPS toll-based system simulation (Coimbatore -> Bangalore).")
    parser.add_argument("--cli", action="store_true", help="run without the GUI and print the results")
    parser.add_argument("--speed", type=float, help="car speed in km/h (default: random between 50 and 100)")
    parser.add_argument(
        "--rate", type=float, default=DEFAULT_TOLL_RATE_PER_KM,
        help=f"toll rate in INR per km (default: {DEFAULT_TOLL_RATE_PER_KM})",
    )
    parser.add_argument("--seed", type=int, help="random seed, for repeatable runs")
    parser.add_argument("--map-file", default=DEFAULT_MAP_FILE, help=f"where to save the map (default: {DEFAULT_MAP_FILE})")
    parser.add_argument("--plot-file", help="also save the path plot as an image (CLI mode only)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every GPS fix")
    args = parser.parse_args(argv)
    if args.speed is not None and args.speed <= 0:
        parser.error("--speed must be positive")
    if args.rate < 0:
        parser.error("--rate must not be negative")
    return args


def run_cli(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    result = simulate_default_trip(args.speed, args.rate, rng)

    print("\nSimulation results")
    print(result.summary())
    print("\nPayment receipt")
    print(issue_receipt(result, rng).as_text())

    map_path = save_route_map(result, args.map_file)
    print(f"\nMap saved to {map_path}")
    if args.plot_file:
        create_path_figure(result).savefig(args.plot_file, dpi=150)
        print(f"Plot saved to {args.plot_file}")


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    if args.seed is not None:
        random.seed(args.seed)

    if args.cli:
        run_cli(args)
    else:
        # Imported here so --cli works on machines without Tk installed.
        from gps_toll.gui import run_app

        run_app(args.speed, args.rate, args.map_file)


if __name__ == "__main__":
    main()
