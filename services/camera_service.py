import os
import time
from datetime import datetime
from pathlib import Path

from gpiozero import Device, DigitalOutputDevice
from gpiozero.pins.lgpio import LGPIOFactory
from picamera2 import Picamera2
from libcamera import controls


def slugify_protocol_name(name: str) -> str:
    s = "".join(ch.lower() if ch.isalnum() else "_" for ch in name)
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_") or "run"


def make_run_id(protocol_name: str):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{slugify_protocol_name(protocol_name)}_{stamp}"


def prepare_run_dirs(image_root: str, log_root: str, protocol_name: str):
    run_id = make_run_id(protocol_name)
    image_dir = Path(image_root) / run_id
    log_file = Path(log_root) / f"{run_id}.json"

    image_dir.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    return run_id, str(image_dir), str(log_file)


class CameraService:
    def __init__(self, led_gpio: int, active_low: bool):
        Device.pin_factory = LGPIOFactory()
        self.led = DigitalOutputDevice(
            pin=led_gpio,
            active_high=(not active_low),
            initial_value=False
        )
        self.cam = None

    def start(self):
        self.cam = Picamera2()
        self.cam.configure(self.cam.create_still_configuration())
        self.cam.start()
        time.sleep(1.0)
        self.cam.set_controls({
            "AfMode": controls.AfModeEnum.Manual,
            "LensPosition": 11.5,
            "AeEnable": True,
            "AwbEnable": True
        })

    def led_on(self):
        self.led.on()

    def led_off(self):
        self.led.off()

    def capture(self, image_dir: str, index: int, warmup_sec: float):
        self.led_on()
        time.sleep(max(0.0, warmup_sec))

        filename = f"{index:04d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = os.path.join(image_dir, filename)
        self.cam.capture_file(path)

        self.led_off()
        return path, filename

    def stop(self):
        try:
            self.led_off()
        except Exception:
            pass
        try:
            if self.cam:
                self.cam.stop()
        except Exception:
            pass
        try:
            self.led.close()
        except Exception:
            pass