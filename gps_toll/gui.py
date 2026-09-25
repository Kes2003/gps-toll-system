"""Tkinter front end for the GPS toll simulation."""

from __future__ import annotations

import logging
import random
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import List, Optional

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from gps_toll.billing import Receipt, issue_receipt
from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VEHICLE_CLASSES, VehicleClass
from gps_toll.simulation import (
    DEFAULT_DESTINATION,
    DEFAULT_ORIGIN,
    SimulationSettings,
    TripResult,
    NATIONAL_PERMIT_CLASSES,
    format_duration,
    load_default_route,
    load_default_zones,
    simulate,
)
from gps_toll.storage import DEFAULT_DB_FILE, TripStore
from gps_toll.visualization import (
    DEFAULT_MAP_FILE,
    create_route_figure,
    create_toll_figure,
    create_traffic_figure,
    save_route_map,
)

logger = logging.getLogger(__name__)

BACKGROUND = "#87CEEB"  # sky blue
BUTTON_FONT = ("Helvetica", 14)
LABEL_FONT = ("Helvetica", 12)
MAX_TRAFFIC = 50

RESULT_COLUMNS = [
    ("vehicle", "Vehicle", 120),
    ("type", "Type", 230),
    ("from", "From", 120),
    ("to", "To", 120),
    ("km", "km", 60),
    ("tolled", "Tolled km", 80),
    ("gnss", "GNSS INR", 90),
    ("fastag", "FASTag INR", 90),
]


class TollSimulatorApp:
    def __init__(
        self,
        root: tk.Tk,
        speed_kmh: Optional[float] = None,
        vehicle_class: VehicleClass = DEFAULT_VEHICLE_CLASS,
        settings: SimulationSettings = SimulationSettings(),
        map_file: str = DEFAULT_MAP_FILE,
        db_file: Optional[str] = DEFAULT_DB_FILE,
        origin: str = DEFAULT_ORIGIN,
        destination: str = DEFAULT_DESTINATION,
        traffic: int = 0,
        national_permit: Optional[bool] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.root = root
        self.speed_kmh = speed_kmh
        self.settings = settings
        self.map_file = map_file
        self.db_file = db_file
        self.rng = rng or random.Random()
        self.route = load_default_route()
        self.zones = load_default_zones()
        self.results: List[TripResult] = []
        self.receipts: List[Receipt] = []
        self.selected = 0

        root.title("GPS Toll Simulation")
        root.configure(bg=BACKGROUND)

        tk.Label(root, text="GPS Toll Simulation", font=("Helvetica", 24), bg=BACKGROUND).pack(pady=(15, 5))
        tk.Label(root, text=f"{self.route.name}, {self.route.length_km:.0f} km, {len(self.zones)} toll plazas",
                 font=LABEL_FONT, bg=BACKGROUND).pack()

        form = tk.Frame(root, bg=BACKGROUND)
        form.pack(pady=10)
        self._vehicles_by_label = {vc.name: vc for vc in VEHICLE_CLASSES.values()}
        self.vehicle = tk.StringVar(value=vehicle_class.name)
        self.origin = tk.StringVar(value=origin)
        self.destination = tk.StringVar(value=destination)
        self.traffic = tk.IntVar(value=traffic)
        self.gps_noise = tk.DoubleVar(value=settings.gps_noise_m)
        if national_permit is None:
            national_permit = vehicle_class.key in NATIONAL_PERMIT_CLASSES
        self.national_permit = tk.BooleanVar(value=national_permit)
        # Heavy goods vehicles normally carry a National Permit; follow the chosen type.
        self.vehicle.trace_add("write", lambda *_: self.national_permit.set(
            self._vehicles_by_label[self.vehicle.get()].key in NATIONAL_PERMIT_CLASSES))
        places = [p.name for p in self.route.places]

        self._field(form, "Vehicle type", 0, 0, tk.OptionMenu(form, self.vehicle, *self._vehicles_by_label), width=34)
        self._field(form, "From", 0, 2, tk.OptionMenu(form, self.origin, *places), width=13)
        self._field(form, "To", 0, 4, tk.OptionMenu(form, self.destination, *places), width=13)
        self._field(form, "Other traffic", 1, 0, tk.Spinbox(form, from_=0, to=MAX_TRAFFIC, textvariable=self.traffic,
                                                            width=5, font=LABEL_FONT))
        self._field(form, "GPS noise (m)", 1, 2, tk.Spinbox(form, from_=0, to=100, increment=5,
                                                            textvariable=self.gps_noise, width=5, font=LABEL_FONT))
        tk.Checkbutton(form, text="National Permit", variable=self.national_permit, font=LABEL_FONT,
                       bg=BACKGROUND, activebackground=BACKGROUND).grid(row=1, column=4, columnspan=2, sticky="w")

        buttons = tk.Frame(root, bg=BACKGROUND)
        buttons.pack(pady=10)
        self.start_btn = self._button(buttons, "Start Simulation", self.start_simulation)
        self.end_btn = self._button(buttons, "End Simulation", self.end_simulation, enabled=False)
        self.receipt_btn = self._button(buttons, "Toll Bill", self.show_receipt, enabled=False)
        self.history_btn = self._button(buttons, "Trip History", self.show_history, enabled=db_file is not None)

        table_frame = tk.Frame(root, bg=BACKGROUND)
        table_frame.pack(padx=20, fill=tk.X)
        self.table = ttk.Treeview(table_frame, columns=[c[0] for c in RESULT_COLUMNS], show="headings", height=6)
        for key, heading, width in RESULT_COLUMNS:
            self.table.heading(key, text=heading)
            self.table.column(key, width=width, anchor=tk.E if width <= 90 else tk.W)
        self.table.tag_configure("mine", font=("Helvetica", 10, "bold"))
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.table.bind("<<TreeviewSelect>>", self._on_select)

        self.status = tk.StringVar(value="Choose a vehicle and route, then press 'Start Simulation'.")
        tk.Label(root, textvariable=self.status, font=("Courier", 10), bg=BACKGROUND, justify=tk.LEFT,
                 anchor="w").pack(padx=20, pady=10, fill=tk.X)

        tk.Label(root, text="GPS TOLL BASED SIMULATION USING PYTHON", font=("Helvetica", 20),
                 bg=BACKGROUND).pack(pady=(5, 15))

    def _field(self, parent: tk.Widget, label: str, row: int, column: int, widget: tk.Widget, width: int = 0) -> None:
        tk.Label(parent, text=f"{label}:", font=LABEL_FONT, bg=BACKGROUND).grid(
            row=row, column=column, sticky="e", padx=(10, 4), pady=4
        )
        if isinstance(widget, tk.OptionMenu):
            widget.config(font=LABEL_FONT, width=width)
        widget.grid(row=row, column=column + 1, sticky="w", pady=4)

    def _button(self, parent: tk.Widget, text: str, command, enabled: bool = True) -> tk.Button:
        button = tk.Button(
            parent, text=text, command=command, font=BUTTON_FONT, width=16, height=2,
            state=tk.NORMAL if enabled else tk.DISABLED,
        )
        button.pack(side=tk.LEFT, padx=12, pady=10)
        return button

    def _read_traffic(self) -> int:
        try:
            return min(max(int(self.traffic.get()), 0), MAX_TRAFFIC)
        except (tk.TclError, ValueError):
            return 0

    def _read_noise(self) -> float:
        try:
            return max(float(self.gps_noise.get()), 0.0)
        except (tk.TclError, ValueError):
            return self.settings.gps_noise_m

    def start_simulation(self) -> None:
        origin, destination = self.route.place(self.origin.get()), self.route.place(self.destination.get())
        if destination.km <= origin.km:
            messagebox.showerror(
                "Simulation", f"{destination.name} must come after {origin.name} on the way to {self.route.places[-1].name}."
            )
            return

        settings = SimulationSettings(
            gps_interval_s=self.settings.gps_interval_s,
            gps_noise_m=self._read_noise(),
            speed_variation=self.settings.speed_variation,
            rate_override=self.settings.rate_override,
            free_km_per_day=self.settings.free_km_per_day,
        )
        # Every run starts from a fresh simulation so repeated clicks don't mix trips.
        self.results = simulate(
            vehicle_class=self._vehicles_by_label[self.vehicle.get()],
            speed_kmh=self.speed_kmh,
            origin=origin.name,
            destination=destination.name,
            national_permit=self.national_permit.get(),
            traffic=self._read_traffic(),
            settings=settings,
            rng=self.rng,
            route=self.route,
            zones=self.zones,
        )
        self.receipts = [issue_receipt(result, self.rng) for result in self.results]
        self._save_history()

        self.table.delete(*self.table.get_children())
        for i, result in enumerate(self.results):
            self.table.insert("", tk.END, iid=str(i), tags=("mine",) if i == 0 else (), values=(
                result.vehicle.registration,
                result.vehicle.vehicle_class.name,
                result.trip.origin.name,
                result.trip.destination.name,
                f"{result.distance_km:.1f}",
                f"{result.bill.tolled_km:.1f}",
                f"{result.bill.gnss_total:.2f}",
                f"{result.bill.fastag_total:.2f}",
            ))
        self.table.selection_set("0")
        self._select(0)

        self.end_btn.config(state=tk.NORMAL)
        self.receipt_btn.config(state=tk.NORMAL)
        messagebox.showinfo(
            "Simulation",
            f"Simulation complete: {len(self.results)} vehicle(s). Select a vehicle in the table, "
            "then press 'End Simulation' for its charts and map or 'Toll Bill' for its receipt.",
        )

    def _save_history(self) -> None:
        if self.db_file is None:
            return
        with TripStore(self.db_file) as store:
            for result, receipt in zip(self.results, self.receipts):
                store.save(result, receipt)

    def _on_select(self, _event=None) -> None:
        selection = self.table.selection()
        if selection:
            self._select(int(selection[0]))

    def _select(self, index: int) -> None:
        self.selected = index
        self.status.set(self.results[index].summary())

    def end_simulation(self) -> None:
        if not self.results:
            return
        result = self.results[self.selected]
        messagebox.showinfo(
            "Simulation",
            f"{result.vehicle.registration}: GNSS toll {result.bill.gnss_total:.2f} INR "
            f"(FASTag would be {result.bill.fastag_total:.2f} INR)",
        )
        self.show_charts()
        self.open_map()

    def show_charts(self) -> None:
        window = tk.Toplevel(self.root)
        window.title(f"Charts - {self.results[self.selected].vehicle.registration}")
        notebook = ttk.Notebook(window)
        notebook.pack(fill=tk.BOTH, expand=True)
        figures = [
            ("Route", create_route_figure(self.route, self.zones, self.results, self.selected)),
            ("Traffic", create_traffic_figure(self.route, self.zones, self.results, self.selected)),
            ("Toll by plaza", create_toll_figure(self.results[self.selected])),
        ]
        for title, figure in figures:
            tab = tk.Frame(notebook)
            notebook.add(tab, text=title)
            canvas = FigureCanvasTkAgg(figure, master=tab)
            canvas.draw()
            NavigationToolbar2Tk(canvas, tab).update()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def open_map(self) -> None:
        path = save_route_map(self.route, self.zones, self.results, self.map_file, self.selected)
        logger.info("Map saved to %s", path)
        webbrowser.open(path.as_uri())

    def show_receipt(self) -> None:
        if not self.receipts:
            return
        receipt = self.receipts[self.selected]
        window = tk.Toplevel(self.root)
        window.title(f"Payment Receipt - {receipt.registration}")
        window.configure(bg=BACKGROUND)
        tk.Label(window, text="Payment Receipt", font=("Helvetica", 18), bg=BACKGROUND).pack(pady=10)
        tk.Label(window, text=receipt.as_text(), font=("Courier", 11), bg=BACKGROUND, justify=tk.LEFT).pack(
            padx=20, pady=10
        )
        tk.Button(window, text="Close", command=window.destroy, font=("Helvetica", 14), width=10).pack(pady=10)

    def show_history(self) -> None:
        if self.db_file is None:
            return
        with TripStore(self.db_file) as store:
            trips = store.recent_trips(200)
            totals = store.totals()

        window = tk.Toplevel(self.root)
        window.title("Trip History")
        window.configure(bg=BACKGROUND)
        tk.Label(
            window,
            text=f"{totals.trips} trips, {totals.distance_km:,.0f} km, GNSS tolls {totals.gnss_toll:,.2f} INR "
                 f"(FASTag would be {totals.fastag_toll:,.2f} INR)",
            font=LABEL_FONT, bg=BACKGROUND,
        ).pack(padx=20, pady=10)

        columns = [("id", "#", 50), ("time", "Recorded", 165), ("vehicle", "Vehicle", 120), ("type", "Type", 90),
                   ("route", "Route", 220), ("km", "km", 60), ("time_taken", "Time", 90), ("gnss", "GNSS INR", 90),
                   ("fastag", "FASTag INR", 95), ("txn", "Transaction ID", 120)]
        frame = tk.Frame(window)
        frame.pack(padx=20, pady=(0, 10), fill=tk.BOTH, expand=True)
        table = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=15)
        for key, heading, width in columns:
            table.heading(key, text=heading)
            table.column(key, width=width, anchor=tk.W if key in ("time", "vehicle", "type", "route") else tk.E)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        for trip in trips:
            table.insert("", tk.END, values=(
                trip.id, trip.recorded_at.replace("T", " "), trip.registration, trip.vehicle_class,
                f"{trip.origin} -> {trip.destination}", f"{trip.distance_km:.1f}", format_duration(trip.duration_min),
                f"{trip.gnss_toll:.2f}", f"{trip.fastag_toll:.2f}", trip.transaction_id,
            ))
        tk.Button(window, text="Close", command=window.destroy, font=("Helvetica", 14), width=10).pack(pady=10)


def run_app(**kwargs) -> None:
    """Open the GUI. Keyword arguments are passed to :class:`TollSimulatorApp`."""
    root = tk.Tk()
    TollSimulatorApp(root, **kwargs)
    root.mainloop()
