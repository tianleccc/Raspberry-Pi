import argparse
import csv
import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from routes.protocol_routes import create_protocol_blueprint
from services.analysis_service import ChamberState
from services.protocol_service import ProtocolService
from services.state_manager import StateManager


BASE_DIR = Path(__file__).resolve().parent


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_csv_path(csv_path: str):
    path = Path(csv_path).expanduser()
    if path.is_absolute():
        return path

    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path

    return BASE_DIR / path


def find_time_column(fieldnames):
    for name in fieldnames:
        normalized = name.strip().lower()
        if normalized in {"time_min", "time", "t_min", "minute", "minutes"}:
            return name
    return None


def find_chamber_columns(fieldnames):
    columns = []
    for name in fieldnames:
        normalized = name.strip().lower()
        if normalized.startswith("chamber_") or normalized.startswith("chamber "):
            columns.append(name)
        elif normalized.startswith("c") and normalized[1:].isdigit():
            columns.append(name)
    return columns


def read_curve_csv(csv_path: Path, fallback_interval_s: float):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")

        time_col = find_time_column(reader.fieldnames)
        chamber_cols = find_chamber_columns(reader.fieldnames)
        if not chamber_cols:
            raise ValueError("CSV must include chamber columns such as Chamber_1, Chamber_2, or C1.")

        rows = []
        for idx, row in enumerate(reader):
            if time_col:
                t_min = float(row[time_col])
            else:
                t_min = idx * float(fallback_interval_s) / 60.0

            values = []
            for col in chamber_cols:
                raw = (row.get(col) or "").strip()
                values.append(0.0 if raw == "" else float(raw))
            rows.append((t_min, values))

    if not rows:
        raise ValueError("CSV has no data rows.")

    return chamber_cols, rows


def make_chamber(chamber_id: int, analysis_cfg: dict):
    return ChamberState(
        chamber_id=chamber_id,
        warmup_min=float(analysis_cfg["warmup_min"]),
        ema_alpha=float(analysis_cfg["ema_alpha"]),
        noise_points=int(analysis_cfg["noise_points"]),
        start_consec=int(analysis_cfg["start_consec"]),
        end_consec=int(analysis_cfg["end_consec"]),
        min_rise_duration_min=float(analysis_cfg["min_rise_duration_min"]),
        noise_k=float(analysis_cfg["noise_k"]),
        min_start_amp=float(analysis_cfg["min_start_amp"]),
        min_start_slope=float(analysis_cfg["min_start_slope"]),
        end_slope_fraction=float(analysis_cfg["end_slope_fraction"]),
        neg_slope_end=float(analysis_cfg["neg_slope_end"]),
        min_net_rise=float(analysis_cfg["min_net_rise"]),
        reject_flatten_value=float(analysis_cfg["reject_flatten_value"]),
        zero_reject_frac=float(analysis_cfg["zero_reject_frac"]),
        zero_reject_abs=float(analysis_cfg["zero_reject_abs"]),
        zero_reject_consec=int(analysis_cfg["zero_reject_consec"])
    )


def build_illustration_state(csv_path: Path, analysis_cfg: dict, mode: str, fallback_interval_s: float):
    chamber_cols, rows = read_curve_csv(csv_path, fallback_interval_s)
    chambers = [make_chamber(i + 1, analysis_cfg) for i in range(len(chamber_cols))]

    for t_min, values in rows:
        for chamber, value in zip(chambers, values):
            if mode == "raw":
                chamber.update(t_min=t_min, raw_value=value)
            else:
                chamber.update_corrected(t_min=t_min, corrected_value=value)

    for chamber in chambers:
        chamber.finalize()

    return {
        "chambers": [chamber.to_dict() for chamber in chambers],
        "frames": len(rows),
        "last_time_min": rows[-1][0],
        "last_file": csv_path.name,
        "chamber_columns": chamber_cols
    }


def create_app(csv_path: Path, mode: str = "corrected", fallback_interval_s: float = 30.0):
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static")
    )

    analysis_cfg = load_json(BASE_DIR / "config" / "analysis_config.json")
    protocol_service = ProtocolService(
        preset_path=str(BASE_DIR / "config" / "protocols.json"),
        saved_path=str(BASE_DIR / "data" / "saved_protocols.json")
    )
    state_manager = StateManager()

    def load_into_state():
        result = build_illustration_state(csv_path, analysis_cfg, mode, fallback_interval_s)

        state_manager.reset_all()
        state_manager.set_run_meta(
            run_id=f"illustration_{csv_path.stem}",
            protocol={
                "id": "illustration",
                "name": f"Illustration CSV: {csv_path.name}",
                "temperature_c": None,
                "duration_min": result["last_time_min"],
                "warmup_min": analysis_cfg["warmup_min"],
                "read_interval_s": fallback_interval_s
            },
            image_dir="",
            log_file=str(csv_path)
        )
        state_manager.update_capture(result["frames"], result["last_file"], result["last_time_min"])
        state_manager.update_chambers(result["chambers"])
        state_manager.update_assay_status("finished")
        state_manager.add_log(f"Illustration CSV loaded: {csv_path}")
        state_manager.add_log(f"Mode: {mode}")
        state_manager.add_log(f"Chambers: {', '.join(result['chamber_columns'])}")

    load_into_state()
    app.register_blueprint(create_protocol_blueprint(protocol_service))

    @app.route("/")
    def index():
        return send_from_directory(app.template_folder, "index.html")

    @app.get("/api/state")
    def get_state():
        return jsonify(state_manager.snapshot())

    @app.post("/api/start")
    def start_illustration():
        load_into_state()
        return jsonify({
            "ok": True,
            "message": "Illustration data loaded",
            "run_id": state_manager.snapshot()["run_id"]
        })

    @app.post("/api/reset")
    def reset_illustration():
        load_into_state()
        return jsonify({"ok": True, "message": "Illustration data reloaded"})

    @app.post("/api/stop")
    def stop_illustration():
        return jsonify({"ok": True, "message": "Illustration mode has no running hardware"})

    @app.post("/api/illustration/load")
    def load_illustration_csv():
        payload = request.get_json(silent=True) or {}
        requested = payload.get("csv_path")
        if not requested:
            return jsonify({"ok": False, "error": "csv_path is required"}), 400

        nonlocal_csv_path = resolve_csv_path(requested)
        if not nonlocal_csv_path.exists():
            return jsonify({"ok": False, "error": f"CSV not found: {nonlocal_csv_path}"}), 404

        nonlocal csv_path
        csv_path = nonlocal_csv_path
        load_into_state()
        return jsonify({"ok": True, "message": "Illustration CSV loaded"})

    return app


def parse_args():
    parser = argparse.ArgumentParser(description="Run the fluorescence dashboard from CSV data only.")
    parser.add_argument("--csv", default="data/illustration_curve.csv", help="CSV with Time_min and Chamber_1 columns.")
    parser.add_argument(
        "--mode",
        choices=["corrected", "raw"],
        default="corrected",
        help="Use corrected for CSV curve data, or raw to rerun EMA/baseline correction."
    )
    parser.add_argument("--interval-s", type=float, default=30.0, help="Fallback interval if CSV has no Time_min column.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5001)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    path = resolve_csv_path(args.csv)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    app = create_app(path, mode=args.mode, fallback_interval_s=args.interval_s)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
