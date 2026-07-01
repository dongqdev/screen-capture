import os
import sys
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import mss
import pyautogui


@dataclass
class WindowInfo:
    wid: int
    title: str
    left: int
    top: int
    width: int
    height: int


class WindowProvider:
    def list_windows(self):
        if sys.platform == "darwin":
            return self._list_windows_macos()
        if sys.platform.startswith("win"):
            return self._list_windows_windows()
        raise RuntimeError("Unsupported OS. This demo supports macOS and Windows.")

    def get_window_bounds(self, wid):
        windows = self.list_windows()
        for window in windows:
            if window.wid == wid:
                return window
        return None

    @staticmethod
    def _list_windows_macos():
        try:
            import Quartz
        except Exception as exc:
            raise RuntimeError(
                "Quartz is not available. Install pyobjc-framework-Quartz."
            ) from exc

        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        results = []

        for item in window_list:
            title = item.get("kCGWindowName", "") or ""
            owner = item.get("kCGWindowOwnerName", "") or ""
            layer = int(item.get("kCGWindowLayer", 0) or 0)
            bounds = item.get("kCGWindowBounds", {}) or {}

            left = int(bounds.get("X", 0) or 0)
            top = int(bounds.get("Y", 0) or 0)
            width = int(bounds.get("Width", 0) or 0)
            height = int(bounds.get("Height", 0) or 0)

            # Keep only visible app windows.
            if layer != 0:
                continue
            if width < 40 or height < 40:
                continue
            if not title and not owner:
                continue

            window_title = f"{owner} - {title}".strip(" -")
            wid = int(item.get("kCGWindowNumber", 0) or 0)
            if wid <= 0:
                continue

            results.append(
                WindowInfo(
                    wid=wid,
                    title=window_title,
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                )
            )

        return results

    @staticmethod
    def _list_windows_windows():
        try:
            import pygetwindow as gw
        except Exception as exc:
            raise RuntimeError(
                "pygetwindow is not available. Install pygetwindow for Windows support."
            ) from exc

        results = []
        for w in gw.getAllWindows():
            title = (w.title or "").strip()
            if not title:
                continue
            if w.width <= 40 or w.height <= 40:
                continue
            results.append(
                WindowInfo(
                    wid=int(w._hWnd),
                    title=title,
                    left=int(w.left),
                    top=int(w.top),
                    width=int(w.width),
                    height=int(w.height),
                )
            )

        return results


class CaptureApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Window Capture Tool")
        self.root.geometry("780x460")

        self.provider = WindowProvider()
        self.windows_by_label = {}

        self.running = threading.Event()
        self.capture_thread = None
        self.capture_index = 0

        self.window_var = tk.StringVar()
        self.delay_var = tk.StringVar(value="2.0")
        self.action_var = tk.StringVar(value="None")
        self.folder_var = tk.StringVar(value=str(Path.home() / "captures"))
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()
        self.refresh_windows()

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Window").grid(row=0, column=0, sticky="w", pady=5)
        self.window_combo = ttk.Combobox(frame, textvariable=self.window_var, state="readonly")
        self.window_combo.grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(frame, text="Refresh", command=self.refresh_windows).grid(
            row=0, column=2, sticky="ew", padx=(8, 0), pady=5
        )

        ttk.Label(frame, text="Delay (seconds)").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.delay_var).grid(row=1, column=1, sticky="ew", pady=5)

        ttk.Label(frame, text="After capture action").grid(row=2, column=0, sticky="w", pady=5)
        self.action_combo = ttk.Combobox(
            frame,
            textvariable=self.action_var,
            state="readonly",
            values=["None", "Right Arrow", "Down Arrow", "Page Down"],
        )
        self.action_combo.grid(row=2, column=1, sticky="ew", pady=5)

        ttk.Label(frame, text="Save folder").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.folder_var).grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Button(frame, text="Browse", command=self.pick_folder).grid(
            row=3, column=2, sticky="ew", padx=(8, 0), pady=5
        )

        controls = ttk.Frame(frame)
        controls.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        ttk.Button(controls, text="Start", command=self.start_capture).pack(side="left")
        ttk.Button(controls, text="Stop", command=self.stop_capture).pack(side="left", padx=8)
        ttk.Button(controls, text="Capture Once", command=self.capture_once).pack(side="left")

        ttk.Label(frame, textvariable=self.status_var).grid(row=5, column=0, columnspan=3, sticky="w", pady=6)

        self.log_box = tk.Text(frame, height=14, state="disabled")
        self.log_box.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        frame.rowconfigure(6, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, text):
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] {text}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or str(Path.home()))
        if folder:
            self.folder_var.set(folder)

    def refresh_windows(self):
        try:
            windows = self.provider.list_windows()
        except Exception as exc:
            messagebox.showerror("Window scan failed", str(exc))
            return

        labels = []
        mapping = {}
        for w in windows:
            label = f"[{w.wid}] {w.title} ({w.width}x{w.height})"
            labels.append(label)
            mapping[label] = w

        current = self.window_var.get()
        self.windows_by_label = mapping
        self.window_combo["values"] = labels

        if current in mapping:
            self.window_var.set(current)
        elif labels:
            self.window_var.set(labels[0])
        else:
            self.window_var.set("")

        self.log(f"Window list refreshed: {len(labels)} item(s)")

    def _selected_window(self):
        label = self.window_var.get().strip()
        if not label:
            return None
        return self.windows_by_label.get(label)

    def _validate_inputs(self):
        selected = self._selected_window()
        if not selected:
            raise ValueError("Select a target window first.")

        try:
            delay = float(self.delay_var.get().strip())
        except ValueError as exc:
            raise ValueError("Delay must be a number.") from exc

        if delay < 0:
            raise ValueError("Delay cannot be negative.")

        folder = Path(self.folder_var.get().strip()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)

        return selected.wid, delay, folder

    def _perform_action(self):
        action = self.action_var.get()
        if action == "Right Arrow":
            pyautogui.press("right")
        elif action == "Down Arrow":
            pyautogui.press("down")
        elif action == "Page Down":
            pyautogui.press("pagedown")

    def _capture_window(self, wid, folder):
        w = self.provider.get_window_bounds(wid)
        if not w:
            raise RuntimeError("Target window is not available. Refresh and select again.")

        if w.width <= 0 or w.height <= 0:
            raise RuntimeError("Target window size is invalid.")

        monitor = {
            "left": w.left,
            "top": w.top,
            "width": w.width,
            "height": w.height,
        }

        with mss.mss() as sct:
            shot = sct.grab(monitor)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.capture_index += 1
            filename = folder / f"capture_{self.capture_index:04d}_{timestamp}.png"
            mss.tools.to_png(shot.rgb, shot.size, output=str(filename))
            return filename

    def capture_once(self):
        try:
            wid, _delay, folder = self._validate_inputs()
            output = self._capture_window(wid, folder)
            self._perform_action()
            self.status_var.set(f"Captured: {output.name}")
            self.log(f"Captured: {output}")
        except Exception as exc:
            self.status_var.set("Capture failed")
            self.log(f"Error: {exc}")
            messagebox.showerror("Capture failed", str(exc))

    def start_capture(self):
        if self.running.is_set():
            return

        try:
            wid, delay, folder = self._validate_inputs()
        except Exception as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        self.running.set()
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(wid, delay, folder),
            daemon=True,
        )
        self.capture_thread.start()
        self.status_var.set("Running")
        self.log("Capture loop started")

    def stop_capture(self):
        if not self.running.is_set():
            return
        self.running.clear()
        self.status_var.set("Stopping...")
        self.log("Stopping capture loop")

    def _capture_loop(self, wid, delay, folder):
        while self.running.is_set():
            try:
                output = self._capture_window(wid, folder)
                self.root.after(0, lambda p=output: self.status_var.set(f"Captured: {p.name}"))
                self.root.after(0, lambda p=output: self.log(f"Captured: {p}"))
                self._perform_action()
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set("Capture loop failed"))
                self.root.after(0, lambda e=exc: self.log(f"Error: {e}"))
                self.running.clear()
                break

            # Sleep in small chunks so stop is responsive.
            elapsed = 0.0
            while self.running.is_set() and elapsed < delay:
                step = min(0.2, delay - elapsed)
                time.sleep(step)
                elapsed += step

        self.root.after(0, lambda: self.status_var.set("Idle"))
        self.root.after(0, lambda: self.log("Capture loop stopped"))

    def on_close(self):
        self.running.clear()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = CaptureApp(root)
    app.log("App ready")
    root.mainloop()


if __name__ == "__main__":
    main()
