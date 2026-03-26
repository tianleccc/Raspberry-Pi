import csv
import math
import signal
import statistics
import threading
import time
from datetime import datetime

import board
import busio
from gpiozero import PWMOutputDevice
import adafruit_mlx90614


def ts():
    return datetime.now().strftime("%H:%M:%S")


class PID:
    def __init__(self, kp, ki, kd, setpoint, out_min=0.0, out_max=100.0, i_limit=200.0):
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.setpoint = float(setpoint)
        self.out_min = float(out_min)
        self.out_max = float(out_max)
        self.i_limit = float(i_limit)
        self.last_t = None
        self.last_err = 0.0
        self.i = 0.0

    def update(self, meas, now=None):
        if now is None:
            now = time.monotonic()
        err = self.setpoint - float(meas)
        if self.last_t is None:
            self.last_t = now
            self.last_err = err
            out = self.kp * err
            return max(self.out_min, min(self.out_max, out))

        dt = max(1e-6, now - self.last_t)
        self.last_t = now

        p = self.kp * err
        self.i += err * dt
        self.i = max(-self.i_limit, min(self.i_limit, self.i))
        i = self.ki * self.i
        d = self.kd * (err - self.last_err) / dt
        self.last_err = err

        out = p + i + d
        return max(self.out_min, min(self.out_max, out))


def emissivity_compensate(obj_c, amb_c, emiss):
    try:
        if emiss <= 0 or emiss > 1:
            return obj_c
        obj_k = obj_c + 273.15
        amb_k = amb_c + 273.15
        term = obj_k**4 - ((1.0 - emiss) / emiss) * (amb_k**4)
        if term <= 0:
            return obj_c
        true_k = term ** 0.25
        return true_k - 273.15
    except Exception:
        return obj_c


class HeaterService:
    def __init__(self, cfg: dict, state_manager):
        self.cfg = cfg
        self.state_manager = state_manager
        self.thread = None
        self.stop_event = threading.Event()
        self.latest_temp = None
        self.rows = []
        self.csv_path = None

    def start(self, target_c: float, csv_path: str):
        if self.thread and self.thread.is_alive():
            return

        self.csv_path = csv_path.replace(".json", "_heater.csv")
        self.rows = []
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, args=(target_c,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self, target_c: float):
        cfg = self.cfg

        heater = PWMOutputDevice(
            pin=int(cfg["gpio"]),
            frequency=float(cfg["pwm_freq"]),
            initial_value=0.0,
            active_high=True
        )

        def set_duty(percent: float):
            heater.value = max(0.0, min(1.0, percent / 100.0))

        i2c = busio.I2C(board.SCL, board.SDA, frequency=int(cfg["i2c_hz"]))
        mlx = adafruit_mlx90614.MLX90614(i2c, address=int(str(cfg["addr"]), 0))

        for _ in range(5):
            try:
                _ = mlx.object_temperature
                _ = mlx.ambient_temperature
            except Exception:
                pass
            time.sleep(0.05)

        pid = PID(cfg["kp"], cfg["ki"], cfg["kd"], target_c)
        ema_alpha = max(0.0, min(1.0, float(cfg["ema"])))
        ema_temp = None
        duty_prev = 0.0
        sample_ctr = 0
        t0 = time.monotonic()
        last_print = 0.0

        try:
            while not self.stop_event.is_set():
                t_cycle = time.monotonic()
                cycle = float(cfg["cycle"])
                sampled_this_cycle = False
                last_obj = float("nan")
                last_amb = float("nan")
                last_meas = float("nan")
                last_valid_n = 0

                do_sample = (sample_ctr % int(cfg["sample_every"])) == 0
                sample_ctr += 1

                if do_sample and int(cfg["off_ms"]) > 0:
                    set_duty(0.0)
                    time.sleep(int(cfg["off_ms"]) / 1000.0)

                if do_sample:
                    vals = []
                    ambs = []
                    for _ in range(int(cfg["samples"])):
                        try:
                            obj = float(mlx.object_temperature)
                            amb = float(mlx.ambient_temperature)
                            meas = emissivity_compensate(obj, amb, float(cfg["emiss"]))
                            vals.append(meas)
                            ambs.append(amb)
                            last_obj = obj
                            last_amb = amb
                        except Exception:
                            pass
                        time.sleep(0.01)

                    if vals:
                        t_meas = statistics.median(vals)
                        ema_temp = t_meas if ema_temp is None else (ema_alpha * t_meas + (1 - ema_alpha) * ema_temp)
                        last_meas = t_meas
                        last_valid_n = len(vals)
                    else:
                        t_meas = ema_temp if ema_temp is not None else float("nan")
                        last_meas = t_meas

                    sampled_this_cycle = True
                else:
                    t_meas = ema_temp if ema_temp is not None else float("nan")

                if ema_temp is not None and ema_temp >= float(cfg["cutoff"]):
                    duty = 0.0
                    set_duty(0.0)
                    self.state_manager.add_log(f"SAFETY cutoff reached: {ema_temp:.2f} °C")
                else:
                    if ema_temp is None:
                        duty = max(0.0, min(100.0, float(cfg["min_duty"])))
                    else:
                        if sampled_this_cycle:
                            duty_req = max(0.0, min(100.0, pid.update(ema_temp)))
                            duty_cap = float(cfg["duty_cap"])
                            duty = min(duty_req, duty_cap)
                        else:
                            duty = duty_prev

                        if ema_temp < pid.setpoint:
                            duty = max(duty, max(0.0, min(100.0, float(cfg["min_duty"]))))

                elapsed = time.monotonic() - t_cycle
                on_window = max(0.0, cycle - elapsed)

                if ema_temp is not None and ema_temp >= float(cfg["cutoff"]):
                    set_duty(0.0)
                    if on_window > 0:
                        time.sleep(on_window)
                else:
                    if bool(cfg["burst"]):
                        ton = on_window * max(0.0, min(1.0, duty / 100.0))
                        if ton > 0:
                            set_duty(100.0)
                            time.sleep(ton)
                        toff = on_window - ton
                        if toff > 0:
                            set_duty(0.0)
                            time.sleep(toff)
                    else:
                        if duty > 0.0 and on_window > 0.0:
                            set_duty(duty)
                            time.sleep(on_window)
                        else:
                            set_duty(0.0)
                            if on_window > 0:
                                time.sleep(on_window)

                duty_prev = duty

                if sampled_this_cycle:
                    t_rel = time.monotonic() - t0
                    self.rows.append({
                        "wall_time": datetime.now().isoformat(timespec="milliseconds"),
                        "t_rel_s": f"{t_rel:.3f}",
                        "obj_c": f"{last_obj:.3f}" if not math.isnan(last_obj) else "",
                        "amb_c": f"{last_amb:.3f}" if not math.isnan(last_amb) else "",
                        "t_meas_corr_c": f"{last_meas:.3f}" if not math.isnan(last_meas) else "",
                        "ema_c": f"{ema_temp:.3f}" if ema_temp is not None else "",
                        "setpoint_c": f"{pid.setpoint:.3f}",
                        "duty_pct": f"{duty:.3f}",
                        "valid_samples_n": int(last_valid_n),
                    })

                self.latest_temp = ema_temp
                self.state_manager.update_temperature(ema_temp, "running")

                now = time.monotonic()
                if now - last_print >= 1.0:
                    last_print = now
                    self.state_manager.add_log(
                        f"Heater: T={ema_temp if ema_temp is not None else float('nan'):.2f} °C | Duty={duty:.2f}%"
                    )

        finally:
            try:
                set_duty(0.0)
            except Exception:
                pass
            try:
                heater.close()
            except Exception:
                pass

            if self.rows and self.csv_path:
                with open(self.csv_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(self.rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(self.rows)

            self.state_manager.update_temperature(self.latest_temp, "idle")
            self.state_manager.add_log("Heater stopped")