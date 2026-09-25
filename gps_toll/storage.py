"""SQLite history of trips, their toll charges and receipts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

from gps_toll.billing import Receipt
from gps_toll.simulation import TripResult

DEFAULT_DB_FILE = "trips.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   INTEGER NOT NULL,
    recorded_at      TEXT    NOT NULL,
    registration     TEXT    NOT NULL,
    vehicle_class    TEXT    NOT NULL,
    national_permit  INTEGER NOT NULL,
    origin           TEXT    NOT NULL,
    destination      TEXT    NOT NULL,
    distance_km      REAL    NOT NULL,
    duration_min     REAL    NOT NULL,
    tolled_km        REAL    NOT NULL,
    free_km          REAL    NOT NULL,
    gnss_toll        REAL    NOT NULL,
    fastag_toll      REAL    NOT NULL,
    payment_mode     TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS toll_charges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id         INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    toll_plaza      TEXT    NOT NULL,
    entry_km        REAL    NOT NULL,
    exit_km         REAL    NOT NULL,
    entry_time_min  REAL    NOT NULL,
    exit_time_min   REAL    NOT NULL,
    distance_km     REAL    NOT NULL,
    free_km         REAL    NOT NULL,
    rate_per_km     REAL    NOT NULL,
    amount          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS toll_charges_trip ON toll_charges(trip_id);
"""


@dataclass(frozen=True)
class StoredTrip:
    id: int
    transaction_id: int
    recorded_at: str
    registration: str
    vehicle_class: str
    national_permit: bool
    origin: str
    destination: str
    distance_km: float
    duration_min: float
    tolled_km: float
    free_km: float
    gnss_toll: float
    fastag_toll: float
    payment_mode: str


@dataclass(frozen=True)
class StoredCharge:
    toll_plaza: str
    entry_km: float
    exit_km: float
    entry_time_min: float
    exit_time_min: float
    distance_km: float
    free_km: float
    rate_per_km: float
    amount: float


@dataclass(frozen=True)
class HistoryTotals:
    trips: int
    distance_km: float
    gnss_toll: float
    fastag_toll: float


class TripStore:
    """Keeps every simulated trip, its per-zone charges and receipt details in SQLite."""

    def __init__(self, path: Union[str, Path] = DEFAULT_DB_FILE) -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def __enter__(self) -> "TripStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def save(self, result: TripResult, receipt: Receipt) -> int:
        vehicle, bill = result.vehicle, result.bill
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO trips (transaction_id, recorded_at, registration, vehicle_class, national_permit,"
                " origin, destination, distance_km, duration_min, tolled_km, free_km, gnss_toll, fastag_toll,"
                " payment_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.transaction_id,
                    receipt.issued_at.isoformat(timespec="seconds"),
                    vehicle.registration,
                    vehicle.vehicle_class.key,
                    int(vehicle.national_permit),
                    result.trip.origin.name,
                    result.trip.destination.name,
                    result.distance_km,
                    result.duration_min,
                    bill.tolled_km,
                    bill.free_km,
                    receipt.amount_inr,
                    receipt.fastag_amount_inr,
                    receipt.payment_mode,
                ),
            )
            trip_id = cursor.lastrowid
            self.connection.executemany(
                "INSERT INTO toll_charges (trip_id, toll_plaza, entry_km, exit_km, entry_time_min, exit_time_min,"
                " distance_km, free_km, rate_per_km, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        trip_id,
                        line.passage.zone.plaza.name,
                        line.passage.entry.km,
                        line.passage.exit.km,
                        line.passage.entry.time_min,
                        line.passage.exit.time_min,
                        line.passage.distance_km,
                        line.free_km,
                        line.rate_per_km,
                        round(line.amount, 2),
                    )
                    for line in bill.lines
                ],
            )
        return trip_id

    def recent_trips(self, limit: int = 20) -> List[StoredTrip]:
        rows = self.connection.execute(
            "SELECT id, transaction_id, recorded_at, registration, vehicle_class, national_permit, origin,"
            " destination, distance_km, duration_min, tolled_km, free_km, gnss_toll, fastag_toll, payment_mode"
            " FROM trips ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [StoredTrip(*row[:5], bool(row[5]), *row[6:]) for row in rows]

    def charges(self, trip_id: int) -> List[StoredCharge]:
        rows = self.connection.execute(
            "SELECT toll_plaza, entry_km, exit_km, entry_time_min, exit_time_min, distance_km, free_km,"
            " rate_per_km, amount FROM toll_charges WHERE trip_id = ? ORDER BY entry_km",
            (trip_id,),
        ).fetchall()
        return [StoredCharge(*row) for row in rows]

    def totals(self) -> HistoryTotals:
        row = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(distance_km), 0), COALESCE(SUM(gnss_toll), 0),"
            " COALESCE(SUM(fastag_toll), 0) FROM trips"
        ).fetchone()
        return HistoryTotals(*row)
