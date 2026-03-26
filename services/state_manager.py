import threading
from datetime import datetime


class StateManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset_all()

    def reset_all(self):
        with self._lock:
            self.running = False
            self.run_id = None
            self.protocol = None
            self.frames_captured = 0
            self.last_file = ""
            self.current_time_min = 0.0
            self.current_temp_c = None
            self.heater_status = "idle"
            self.assay_status = "idle"
            self.chambers = []
            self.logs = []
            self.image_dir = None
            self.log_file = None

    def add_log(self, text: str):
        with self._lock:
            stamp = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{stamp}] {text}")
            self.logs = self.logs[-300:]

    def set_running(self, value: bool):
        with self._lock:
            self.running = value

    def set_run_meta(self, run_id: str, protocol: dict, image_dir: str, log_file: str):
        with self._lock:
            self.run_id = run_id
            self.protocol = protocol
            self.image_dir = image_dir
            self.log_file = log_file

    def update_capture(self, frames_captured: int, last_file: str, current_time_min: float):
        with self._lock:
            self.frames_captured = frames_captured
            self.last_file = last_file
            self.current_time_min = current_time_min

    def update_temperature(self, temp_c: float | None, heater_status: str):
        with self._lock:
            self.current_temp_c = temp_c
            self.heater_status = heater_status

    def update_assay_status(self, status: str):
        with self._lock:
            self.assay_status = status

    def update_chambers(self, chambers: list):
        with self._lock:
            self.chambers = chambers

    def snapshot(self):
        with self._lock:
            return {
                "running": self.running,
                "run_id": self.run_id,
                "protocol": self.protocol,
                "frames_captured": self.frames_captured,
                "last_file": self.last_file,
                "current_time_min": self.current_time_min,
                "current_temp_c": self.current_temp_c,
                "heater_status": self.heater_status,
                "assay_status": self.assay_status,
                "chambers": self.chambers,
                "log": list(self.logs),
                "image_dir": self.image_dir,
                "log_file": self.log_file
            }