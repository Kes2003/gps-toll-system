"""Tkinter front end for the GPS toll simulation."""

from __future__ import annotations

import logging
import tkinter as tk
import webbrowser
from tkinter import messagebox
from typing import Optional

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from gps_toll.billing import Receipt, issue_receipt
from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VEHICLE_CLASSES, VehicleClass
from gps_toll.simulation import TripResult, simulate_default_trip
from gps_toll.visualization import DEFAULT_MAP_FILE, create_path_figure, save_route_map

logger = logging.getLogger(__name__)

BACKGROUND = "#87CEEB"  # sky blue
BUTTON_FONT = ("Helvetica", 16)


class TollSimulatorApp:
    def __init__(
        self,
        root: tk.Tk,
        speed_kmh: Optional[float] = None,
        vehicle_class: VehicleClass = DEFAULT_VEHICLE_CLASS,
        toll_rate_per_km: Optional[float] = None,
        map_file: str = DEFAULT_MAP_FILE,
    ) -> None:
        self.root = root
        self.speed_kmh = speed_kmh
        self.toll_rate_per_km = toll_rate_per_km
        self.map_file = map_file
        self.result: Optional[TripResult] = None
        self.receipt: Optional[Receipt] = None

        root.title("GPS Toll Simulation")
        root.configure(bg=BACKGROUND)

        tk.Label(root, text="GPS Toll Simulation", font=("Helvetica", 24), bg=BACKGROUND).pack(pady=20)

        vehicle_row = tk.Frame(root, bg=BACKGROUND)
        vehicle_row.pack()
        tk.Label(vehicle_row, text="Vehicle type:", font=("Helvetica", 14), bg=BACKGROUND).pack(side=tk.LEFT)
        self._vehicles_by_label = {self._vehicle_label(vc): vc for vc in VEHICLE_CLASSES.values()}
        self.vehicle = tk.StringVar(value=self._vehicle_label(vehicle_class))
        vehicle_menu = tk.OptionMenu(vehicle_row, self.vehicle, *self._vehicles_by_label)
        vehicle_menu.config(font=("Helvetica", 14), width=38)
        vehicle_menu.pack(side=tk.LEFT, padx=10)

        buttons = tk.Frame(root, bg=BACKGROUND)
        buttons.pack()
        self.start_btn = self._button(buttons, "Start Simulation", self.start_simulation)
        self.end_btn = self._button(buttons, "End Simulation", self.end_simulation, enabled=False)
        self.receipt_btn = self._button(buttons, "Toll Bill", self.show_receipt, enabled=False)

        self.status = tk.StringVar(value="Press 'Start Simulation' to send a car down the highway.")
        tk.Label(root, textvariable=self.status, font=("Helvetica", 12), bg=BACKGROUND, justify=tk.LEFT).pack(padx=20)

        tk.Label(
            root, text="GPS TOLL BASED SIMULATION USING PYTHON", font=("Helvetica", 24), bg=BACKGROUND
        ).pack(pady=50)

    @staticmethod
    def _vehicle_label(vehicle_class: VehicleClass) -> str:
        return f"{vehicle_class.name} ({vehicle_class.rate_per_km:.2f} INR/km)"

    def _button(self, parent: tk.Widget, text: str, command, enabled: bool = True) -> tk.Button:
        button = tk.Button(
            parent, text=text, command=command, font=BUTTON_FONT, width=20, height=2,
            state=tk.NORMAL if enabled else tk.DISABLED,
        )
        button.pack(side=tk.LEFT, padx=20, pady=50)
        return button

    def start_simulation(self) -> None:
        # Every run starts from a fresh simulation so repeated clicks don't mix trips.
        vehicle_class = self._vehicles_by_label[self.vehicle.get()]
        self.result = simulate_default_trip(self.speed_kmh, vehicle_class, self.toll_rate_per_km)
        self.receipt = issue_receipt(self.result)
        logger.info("Simulation results:\n%s", self.result.summary())

        self.status.set(self.result.summary())
        self.end_btn.config(state=tk.NORMAL)
        self.receipt_btn.config(state=tk.NORMAL)
        messagebox.showinfo("Simulation", "Simulation complete. Press 'End Simulation' to see the results.")

    def end_simulation(self) -> None:
        if self.result is None:
            return
        messagebox.showinfo("Simulation", f"Total Toll Amount: {self.result.toll_amount:.2f} INR")
        self.show_plot()
        self.open_map()

    def show_plot(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Car Path")
        canvas = FigureCanvasTkAgg(create_path_figure(self.result), master=window)
        canvas.draw()
        NavigationToolbar2Tk(canvas, window).update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def open_map(self) -> None:
        path = save_route_map(self.result, self.map_file)
        logger.info("Map saved to %s", path)
        webbrowser.open(path.as_uri())

    def show_receipt(self) -> None:
        if self.receipt is None:
            return
        window = tk.Toplevel(self.root)
        window.title("Payment Receipt")
        window.configure(bg=BACKGROUND)
        tk.Label(window, text="Payment Receipt", font=("Helvetica", 18), bg=BACKGROUND).pack(pady=10)
        tk.Label(window, text=self.receipt.as_text(), font=("Helvetica", 14), bg=BACKGROUND, justify=tk.LEFT).pack(
            padx=20, pady=10
        )
        tk.Button(window, text="Close", command=window.destroy, font=("Helvetica", 14), width=10).pack(pady=10)


def run_app(
    speed_kmh: Optional[float] = None,
    vehicle_class: VehicleClass = DEFAULT_VEHICLE_CLASS,
    toll_rate_per_km: Optional[float] = None,
    map_file: str = DEFAULT_MAP_FILE,
) -> None:
    root = tk.Tk()
    TollSimulatorApp(root, speed_kmh, vehicle_class, toll_rate_per_km, map_file)
    root.mainloop()
