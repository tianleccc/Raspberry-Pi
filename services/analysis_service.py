import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


def robust_std(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return 0.0
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    return float(1.4826 * mad)


def load_coordinates(coords_file: str):
    with open(coords_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    coords = data.get("coordinates", [])
    if not coords:
        raise ValueError("No ROI coordinates found.")
    return coords


def analyze_green_intensity(img_path: str, coordinates, green_low, green_high, intensity_scale):
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {img_path}")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    intensities = []

    for region in coordinates:
        center = tuple(map(int, region["center"]))
        radius = int(region["radius"])

        mask = np.zeros(hsv.shape[:2], np.uint8)
        cv2.circle(mask, center, radius, 255, -1)

        green_mask = cv2.inRange(hsv, green_low, green_high)
        roi_mask = cv2.bitwise_and(green_mask, green_mask, mask=mask)

        v_channel = hsv[:, :, 2][roi_mask == 255]
        intensity = float(np.sum(v_channel) * intensity_scale) if v_channel.size else 0.0
        intensities.append(intensity)

    return intensities


@dataclass
class ChamberState:
    chamber_id: int
    warmup_min: float
    ema_alpha: float
    noise_points: int
    start_consec: int
    end_consec: int
    min_rise_duration_min: float
    noise_k: float
    min_start_amp: float
    min_start_slope: float
    end_slope_fraction: float
    neg_slope_end: float
    min_net_rise: float
    reject_flatten_value: float

    t_all: list = field(default_factory=list)
    raw_all: list = field(default_factory=list)
    smooth_all: list = field(default_factory=list)
    baseline_all: list = field(default_factory=list)
    corrected_all: list = field(default_factory=list)
    corrected_display: list = field(default_factory=list)
    slope_all: list = field(default_factory=list)

    noise_ready: bool = False
    start_amp_threshold: float = np.nan
    start_slope_threshold: float = np.nan

    state: str = "WARMUP"
    rise_count: int = 0
    end_count: int = 0
    candidate_start_idx: int | None = None
    candidate_end_idx: int | None = None
    rise_reference_slope: float | None = None
    threshold_time: float = np.nan
    completion_time: float = np.nan
    confirmed: bool = False
    rejected_segments: int = 0
    status_text: str = "warm-up"

    def _estimate_thresholds(self):
        if self.noise_ready:
            return
        warm_idx = [i for i, t in enumerate(self.t_all) if t >= self.warmup_min]
        if len(warm_idx) < self.noise_points:
            return

        idx0 = warm_idx[0]
        idx1 = idx0 + self.noise_points

        corr_segment = np.asarray(self.corrected_all[idx0:idx1], dtype=float)
        slope_segment = np.asarray(self.slope_all[idx0:idx1], dtype=float)

        amp_noise = robust_std(corr_segment)
        slope_noise = robust_std(slope_segment)

        self.start_amp_threshold = max(self.min_start_amp, self.noise_k * amp_noise)
        self.start_slope_threshold = max(self.min_start_slope, self.noise_k * slope_noise)
        self.noise_ready = True

        if self.state == "WARMUP":
            self.state = "SEARCH"
            self.status_text = "searching"

    def _flatten_rejected_segment(self, start_idx: int, end_idx: int):
        for j in range(start_idx, end_idx + 1):
            self.corrected_display[j] = self.reject_flatten_value

    def update(self, t_min: float, raw_value: float):
        self.t_all.append(float(t_min))
        self.raw_all.append(float(raw_value))

        if not self.smooth_all:
            smooth = float(raw_value)
        else:
            smooth = self.ema_alpha * float(raw_value) + (1.0 - self.ema_alpha) * self.smooth_all[-1]
        self.smooth_all.append(smooth)

        if not self.baseline_all:
            baseline = smooth
        else:
            baseline = min(self.baseline_all[-1], smooth)
        self.baseline_all.append(baseline)

        corrected = max(0.0, smooth - baseline)
        self.corrected_all.append(corrected)
        self.corrected_display.append(corrected)

        if len(self.corrected_all) < 2:
            slope = 0.0
        else:
            dt = max(1e-9, self.t_all[-1] - self.t_all[-2])
            slope = (self.corrected_all[-1] - self.corrected_all[-2]) / dt
        self.slope_all.append(slope)

        if t_min < self.warmup_min:
            self.state = "WARMUP"
            self.status_text = "warm-up"
            return

        self._estimate_thresholds()
        if not self.noise_ready:
            self.status_text = "noise model"
            return

        if self.confirmed:
            self.state = "CONFIRMED"
            self.status_text = f"confirmed @ {self.threshold_time:.1f} min"
            return

        if self.state in ("SEARCH", "WARMUP"):
            amp_ok = corrected >= self.start_amp_threshold
            slope_ok = slope >= self.start_slope_threshold

            if amp_ok and slope_ok:
                self.rise_count += 1
            else:
                self.rise_count = 0

            if self.rise_count >= self.start_consec:
                self.candidate_start_idx = len(self.t_all) - self.start_consec
                start = self.candidate_start_idx
                ref_slice = self.slope_all[start: len(self.t_all)]
                self.rise_reference_slope = float(np.nanmedian(ref_slice)) if ref_slice else slope
                self.state = "TRACK"
                self.end_count = 0
                self.status_text = "tracking rise"
            else:
                self.status_text = "searching"
            return

        if self.state == "TRACK":
            start_idx = self.candidate_start_idx
            if start_idx is None:
                self.state = "SEARCH"
                self.status_text = "searching"
                return

            rise_duration = t_min - self.t_all[start_idx]
            ref_slope = max(self.start_slope_threshold, self.rise_reference_slope or self.start_slope_threshold)
            end_slope_threshold = self.end_slope_fraction * ref_slope

            slope_change = (slope <= end_slope_threshold) or (slope <= self.neg_slope_end)
            enough_duration = rise_duration >= self.min_rise_duration_min

            if enough_duration and slope_change:
                self.end_count += 1
            else:
                self.end_count = 0

            if self.end_count >= self.end_consec:
                self.candidate_end_idx = len(self.t_all) - self.end_consec
                end_idx = self.candidate_end_idx
                net_rise = self.corrected_all[end_idx] - self.corrected_all[start_idx]

                if net_rise >= self.min_net_rise:
                    self.threshold_time = self.t_all[start_idx]
                    self.completion_time = self.t_all[end_idx]
                    self.confirmed = True
                    self.state = "CONFIRMED"
                    self.status_text = f"confirmed @ {self.threshold_time:.1f} min"
                else:
                    self._flatten_rejected_segment(start_idx, end_idx)
                    self.rejected_segments += 1
                    self.candidate_start_idx = None
                    self.candidate_end_idx = None
                    self.rise_reference_slope = None
                    self.rise_count = 0
                    self.end_count = 0
                    self.state = "SEARCH"
                    self.status_text = f"rejected x{self.rejected_segments}"
            else:
                self.status_text = "tracking rise"

    def to_dict(self):
        return {
            "chamber_id": self.chamber_id,
            "t_all": self.t_all,
            "corrected_display": self.corrected_display,
            "status_text": self.status_text,
            "threshold_time": None if not np.isfinite(self.threshold_time) else float(self.threshold_time),
            "completion_time": None if not np.isfinite(self.completion_time) else float(self.completion_time),
            "confirmed": self.confirmed,
            "rejected_segments": self.rejected_segments
        }


class AnalysisService:
    def __init__(self, analysis_cfg: dict, coords_file: str):
        self.cfg = analysis_cfg
        self.coordinates = load_coordinates(coords_file)
        self.green_low = np.array(self.cfg["green_low"])
        self.green_high = np.array(self.cfg["green_high"])
        self.intensity_scale = float(self.cfg["intensity_scale"])
        self.chambers = [
            ChamberState(
                chamber_id=i + 1,
                warmup_min=float(self.cfg["warmup_min"]),
                ema_alpha=float(self.cfg["ema_alpha"]),
                noise_points=int(self.cfg["noise_points"]),
                start_consec=int(self.cfg["start_consec"]),
                end_consec=int(self.cfg["end_consec"]),
                min_rise_duration_min=float(self.cfg["min_rise_duration_min"]),
                noise_k=float(self.cfg["noise_k"]),
                min_start_amp=float(self.cfg["min_start_amp"]),
                min_start_slope=float(self.cfg["min_start_slope"]),
                end_slope_fraction=float(self.cfg["end_slope_fraction"]),
                neg_slope_end=float(self.cfg["neg_slope_end"]),
                min_net_rise=float(self.cfg["min_net_rise"]),
                reject_flatten_value=float(self.cfg["reject_flatten_value"])
            )
            for i in range(len(self.coordinates))
        ]

    def process_image(self, image_path: str, t_min: float):
        vals = analyze_green_intensity(
            image_path,
            self.coordinates,
            self.green_low,
            self.green_high,
            self.intensity_scale
        )
        for chamber, raw_val in zip(self.chambers, vals):
            chamber.update(t_min=t_min, raw_value=raw_val)

    def get_state(self):
        return [c.to_dict() for c in self.chambers]