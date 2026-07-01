import math
import random
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
    owner: str = ""
    pid: int = 0


class WindowProvider:
    def list_windows(self):
        if sys.platform == "darwin":
            return self._list_windows_macos()
        if sys.platform.startswith("win"):
            return self._list_windows_windows()
        raise RuntimeError("지원하지 않는 운영체제입니다. macOS와 Windows만 지원합니다.")

    def get_window_bounds(self, wid):
        windows = self.list_windows()
        for window in windows:
            if window.wid == wid:
                return window
        return None

    def activate_window(self, wid):
        if sys.platform == "darwin":
            return self._activate_window_macos(wid)
        if sys.platform.startswith("win"):
            return self._activate_window_windows(wid)
        return False

    @staticmethod
    def _list_windows_macos():
        try:
            import Quartz
        except Exception as exc:
            raise RuntimeError(
                "Quartz를 사용할 수 없습니다. pyobjc-framework-Quartz를 설치해 주세요."
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
                    owner=owner,
                    pid=int(item.get("kCGWindowOwnerPID", 0) or 0),
                )
            )

        return results

    @staticmethod
    def _list_windows_windows():
        try:
            import pygetwindow as gw
        except Exception as exc:
            raise RuntimeError(
                "pygetwindow를 사용할 수 없습니다. Windows 지원을 위해 pygetwindow를 설치해 주세요."
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

    def _activate_window_macos(self, wid):
        window = self.get_window_bounds(wid)
        if not window or window.pid <= 0:
            return False

        try:
            from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
        except Exception:
            return False

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(window.pid)
        if not app:
            return False
        try:
            return bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
        except Exception:
            return False

    @staticmethod
    def _activate_window_windows(wid):
        try:
            import pygetwindow as gw
        except Exception:
            return False

        for window in gw.getAllWindows():
            if int(getattr(window, "_hWnd", 0) or 0) != wid:
                continue
            try:
                window.activate()
                return True
            except Exception:
                return False
        return False


class CaptureApp:
    def __init__(self, root):
        self.root = root
        self.root.title("화면 캡처 도구")
        self.root.geometry("780x460")

        self.provider = WindowProvider()
        self.windows_by_label = {}

        self.running = threading.Event()
        self.capture_thread = None
        self.capture_index = 0

        self.window_var = tk.StringVar()
        self.delay_var = tk.StringVar(value="2")
        self.action_var = tk.StringVar(value="없음")
        self.page_mode_var = tk.StringVar(value="양면(2페이지)")
        self.total_pages_var = tk.StringVar(value="1")
        self.folder_var = tk.StringVar(value=str(Path.home() / "captures"))
        self.plan_count_var = tk.StringVar(value="총 캡처 횟수: -")
        self.estimate_var = tk.StringVar(value="예상시간(최소/평균/최대): -")
        self.status_var = tk.StringVar(value="대기 중")

        self._build_ui()
        self.refresh_windows()
        self.delay_var.trace_add("write", self._on_plan_input_change)
        self.page_mode_var.trace_add("write", self._on_plan_input_change)
        self.total_pages_var.trace_add("write", self._on_plan_input_change)
        self._update_plan_info()

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="창 선택").grid(row=0, column=0, sticky="w", pady=5)
        self.window_combo = ttk.Combobox(frame, textvariable=self.window_var, state="readonly")
        self.window_combo.grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(frame, text="새로고침", command=self.refresh_windows).grid(
            row=0, column=2, sticky="ew", padx=(8, 0), pady=5
        )

        ttk.Label(frame, text="딜레이(초)").grid(row=1, column=0, sticky="w", pady=5)
        self.delay_combo = ttk.Combobox(
            frame,
            textvariable=self.delay_var,
            state="readonly",
            values=[str(i) for i in range(1, 61)],
        )
        self.delay_combo.grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(
            frame,
            text="안내: 선택값 N이면 실제 대기는 N-1.0초 ~ N+1.0초 사이에서 랜덤(밀리초 포함)",
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(0, 5))

        ttk.Label(frame, text="캡처 후 동작").grid(row=3, column=0, sticky="w", pady=5)
        self.action_combo = ttk.Combobox(
            frame,
            textvariable=self.action_var,
            state="readonly",
            values=["없음", "오른쪽 화살표", "아래쪽 화살표", "Page Down"],
        )
        self.action_combo.grid(row=3, column=1, sticky="ew", pady=5)

        ttk.Label(frame, text="페이지 모드").grid(row=4, column=0, sticky="w", pady=5)
        self.page_mode_combo = ttk.Combobox(
            frame,
            textvariable=self.page_mode_var,
            state="readonly",
            values=["단면(1페이지)", "양면(2페이지)"],
        )
        self.page_mode_combo.grid(row=4, column=1, sticky="ew", pady=5)

        ttk.Label(frame, text="총 페이지").grid(row=5, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.total_pages_var).grid(row=5, column=1, sticky="ew", pady=5)

        ttk.Label(frame, textvariable=self.plan_count_var).grid(row=6, column=0, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Label(frame, textvariable=self.estimate_var).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 4))

        ttk.Label(frame, text="저장 폴더").grid(row=8, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.folder_var).grid(row=8, column=1, sticky="ew", pady=5)
        ttk.Button(frame, text="폴더 선택", command=self.pick_folder).grid(
            row=8, column=2, sticky="ew", padx=(8, 0), pady=5
        )

        controls = ttk.Frame(frame)
        controls.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        ttk.Button(controls, text="시작", command=self.start_capture).pack(side="left")
        ttk.Button(controls, text="정지", command=self.stop_capture).pack(side="left", padx=8)
        ttk.Button(controls, text="1회 캡처", command=self.capture_once).pack(side="left")
        ttk.Button(controls, text="로그 지우기", command=self.clear_log).pack(side="left", padx=8)

        ttk.Label(frame, textvariable=self.status_var).grid(row=10, column=0, columnspan=3, sticky="w", pady=6)

        self.log_box = tk.Text(frame, height=14, state="disabled")
        self.log_box.grid(row=11, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        frame.rowconfigure(11, weight=1)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, text):
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] {text}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.log("로그를 지웠습니다")

    def pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or str(Path.home()))
        if folder:
            self.folder_var.set(folder)

    def refresh_windows(self):
        try:
            windows = self.provider.list_windows()
        except Exception as exc:
            messagebox.showerror("창 목록 조회 실패", str(exc))
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

        self.log(f"창 목록 새로고침 완료: {len(labels)}개")

    def _selected_window(self):
        label = self.window_var.get().strip()
        if not label:
            return None
        return self.windows_by_label.get(label)

    def _on_plan_input_change(self, *_args):
        self._update_plan_info()

    @staticmethod
    def _format_seconds(total_seconds):
        total_seconds = max(0.0, float(total_seconds))
        seconds_int = int(total_seconds)
        hours = seconds_int // 3600
        minutes = (seconds_int % 3600) // 60
        seconds = seconds_int % 60
        if hours > 0:
            return f"{hours}시간 {minutes}분 {seconds}초"
        if minutes > 0:
            return f"{minutes}분 {seconds}초"
        return f"{total_seconds:.1f}초"

    def _pages_per_capture(self):
        return 1 if self.page_mode_var.get().startswith("단면") else 2

    def _update_plan_info(self):
        try:
            delay = int(self.delay_var.get().strip())
            total_pages = int(self.total_pages_var.get().strip())
            if delay < 1 or total_pages < 1:
                raise ValueError()
        except Exception:
            self.plan_count_var.set("총 캡처 횟수: -")
            self.estimate_var.set("예상시간(최소/평균/최대): -")
            return

        pages_per_capture = self._pages_per_capture()
        capture_count = math.ceil(total_pages / pages_per_capture)
        wait_count = max(0, capture_count - 1)
        min_wait = wait_count * max(0.0, delay - 1.0)
        avg_wait = wait_count * delay
        max_wait = wait_count * (delay + 1.0)

        self.plan_count_var.set(
            f"총 캡처 횟수: {capture_count}회 (총 {total_pages}페이지, {self.page_mode_var.get()})"
        )
        self.estimate_var.set(
            "예상시간(최소/평균/최대): "
            f"{self._format_seconds(min_wait)} / {self._format_seconds(avg_wait)} / {self._format_seconds(max_wait)}"
        )

    def _validate_inputs(self):
        selected = self._selected_window()
        if not selected:
            raise ValueError("먼저 캡처할 창을 선택해 주세요.")

        try:
            delay = int(self.delay_var.get().strip())
        except ValueError as exc:
            raise ValueError("딜레이는 정수(초)로 입력해 주세요.") from exc

        if delay < 1:
            raise ValueError("딜레이는 1초 이상이어야 합니다.")

        try:
            total_pages = int(self.total_pages_var.get().strip())
        except ValueError as exc:
            raise ValueError("총 페이지는 정수로 입력해 주세요.") from exc

        if total_pages < 1:
            raise ValueError("총 페이지는 1 이상이어야 합니다.")

        pages_per_capture = self._pages_per_capture()
        capture_count = math.ceil(total_pages / pages_per_capture)

        folder = Path(self.folder_var.get().strip()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)

        return selected.wid, delay, folder, capture_count, total_pages, pages_per_capture

    @staticmethod
    def _pick_random_delay(base_delay):
        # 선택한 값 N을 기준으로 N-1.0 ~ N+1.0 구간에서 밀리초 단위로 랜덤 대기한다.
        lower = max(0.0, base_delay - 1.0)
        upper = base_delay + 1.0
        return random.uniform(lower, upper)

    def _focus_target_window(self, wid):
        if self.provider.activate_window(wid):
            # Allow OS focus change to settle so subsequent key press reaches the target app.
            time.sleep(0.12)
            return True
        return False

    def _perform_action(self, wid):
        action = self.action_var.get()
        if action == "없음":
            return

        focused = self._focus_target_window(wid)
        if not focused:
            self.log("경고: 대상 창 자동 활성화 실패. 캡처 후 동작 키 입력이 적용되지 않을 수 있습니다")

        if action == "오른쪽 화살표":
            pyautogui.press("right")
        elif action == "아래쪽 화살표":
            pyautogui.press("down")
        elif action == "Page Down":
            pyautogui.press("pagedown")

    def _capture_window(self, wid, folder):
        w = self.provider.get_window_bounds(wid)
        if not w:
            raise RuntimeError("대상 창을 찾을 수 없습니다. 새로고침 후 다시 선택해 주세요.")

        if w.width <= 0 or w.height <= 0:
            raise RuntimeError("대상 창 크기가 올바르지 않습니다.")

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
            wid, _delay, folder, _capture_count, _total_pages, _pages_per_capture = self._validate_inputs()
            output = self._capture_window(wid, folder)
            self._perform_action(wid)
            self.status_var.set(f"캡처 완료: {output.name}")
            self.log(f"캡처 완료: {output}")
        except Exception as exc:
            self.status_var.set("캡처 실패")
            self.log(f"오류: {exc}")
            messagebox.showerror("캡처 실패", str(exc))

    def start_capture(self):
        if self.running.is_set():
            return

        try:
            wid, delay, folder, capture_count, total_pages, pages_per_capture = self._validate_inputs()
        except Exception as exc:
            messagebox.showerror("입력값 오류", str(exc))
            return

        self.running.set()
        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(wid, delay, folder, capture_count),
            daemon=True,
        )
        self.capture_thread.start()
        self.status_var.set("실행 중")
        self.log(
            f"캡처 반복 시작 (기준 딜레이: {delay}초, 실제 대기: {max(0.0, delay - 1.0):.1f}~{delay + 1.0:.1f}초 랜덤)"
        )
        self.log(
            f"자동 정지 목표: {capture_count}회 (총 {total_pages}페이지, 캡처당 {pages_per_capture}페이지)"
        )

    def stop_capture(self):
        if not self.running.is_set():
            return
        self.running.clear()
        self.status_var.set("정지 중...")
        self.log("캡처 반복 정지 요청")

    def _capture_loop(self, wid, delay, folder, target_count):
        done_count = 0
        while self.running.is_set():
            try:
                output = self._capture_window(wid, folder)
                done_count += 1
                self.root.after(0, lambda p=output: self.status_var.set(f"캡처 완료: {p.name}"))
                self.root.after(0, lambda p=output, c=done_count, t=target_count: self.log(f"캡처 완료 ({c}/{t}): {p}"))
                self._perform_action(wid)
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set("캡처 반복 실패"))
                self.root.after(0, lambda e=exc: self.log(f"오류: {e}"))
                self.running.clear()
                break

            if done_count >= target_count:
                self.root.after(0, lambda: self.log("목표 캡처 횟수에 도달하여 자동 정지합니다"))
                self.root.after(0, self.root.bell)
                self.running.clear()
                break

            wait_seconds = self._pick_random_delay(delay)
            self.root.after(
                0,
                lambda s=wait_seconds: self.log(
                    f"다음 캡처까지 대기: {s:.3f}초 (랜덤 선택)"
                ),
            )

            # 정지 버튼 반응성을 위해 짧게 나눠서 대기한다.
            elapsed = 0.0
            while self.running.is_set() and elapsed < wait_seconds:
                step = min(0.2, wait_seconds - elapsed)
                time.sleep(step)
                elapsed += step

        self.root.after(0, lambda: self.status_var.set("대기 중"))
        self.root.after(0, lambda: self.log("캡처 반복이 정지되었습니다"))

    def on_close(self):
        self.running.clear()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = CaptureApp(root)
    app.log("앱 준비 완료")
    root.mainloop()


if __name__ == "__main__":
    main()
