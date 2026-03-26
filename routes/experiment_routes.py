import json
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from services.analysis_service import AnalysisService
from services.camera_service import CameraService, prepare_run_dirs


def create_experiment_blueprint(device_cfg, analysis_cfg, protocol_service, state_manager, heater_service):
    bp = Blueprint("experiment", __name__)
    stop_event = threading.Event()
    worker_thread = {"thread": None}

    @bp.get("/api/state")
    def get_state():
        return jsonify(state_manager.snapshot())

    @bp.post("/api/reset")
    def reset_state():
        if state_manager.snapshot()["running"]:
            return jsonify({"ok": False, "error": "Cannot reset while running"}), 400
        state_manager.reset_all()
        return jsonify({"ok": True, "message": "State reset"})

    @bp.post("/api/start")
    def start_experiment():
        if state_manager.snapshot()["running"]:
            return jsonify({"ok": False, "error": "Experiment already running"}), 400

        payload = request.get_json(silent=True) or {}
        protocol_id = payload.get("protocol_id", "lamp45")

        protocol = protocol_service.get_protocol_by_id(protocol_id)
        if protocol is None and protocol_id == "custom":
            protocol = payload.get("custom_protocol")

        if protocol is None:
            return jsonify({"ok": False, "error": "Protocol not found"}), 404

        stop_event.clear()

        run_id, image_dir, log_file = prepare_run_dirs(
            device_cfg["camera"]["image_root"],
            device_cfg["camera"]["log_root"],
            protocol["name"]
        )

        state_manager.reset_all()
        state_manager.set_running(True)
        state_manager.set_run_meta(run_id, protocol, image_dir, log_file)
        state_manager.update_assay_status("starting")
        state_manager.add_log(f"Run created: {run_id}")
        state_manager.add_log(f"Image folder: {image_dir}")

        def worker():
            camera = None
            try:
                coords_file = device_cfg["camera"]["coords_file"]
                analysis = AnalysisService(analysis_cfg, coords_file)
                camera = CameraService(
                    led_gpio=int(device_cfg["camera"]["led_gpio"]),
                    active_low=bool(device_cfg["camera"]["active_low"])
                )
                camera.start()

                heater_service.start(
                    target_c=float(protocol["temperature_c"]),
                    csv_path=log_file
                )

                total_frames = int((float(protocol["duration_min"]) * 60) / float(protocol["read_interval_s"]))
                interval_s = float(protocol["read_interval_s"])
                warmup_sec = float(device_cfg["camera"]["warmup_sec"])

                state_manager.update_assay_status("running")
                state_manager.add_log(f"Protocol loaded: {protocol['name']}")

                for idx in range(1, total_frames + 1):
                    if stop_event.is_set():
                        break

                    loop_t0 = time.time()
                    img_path, filename = camera.capture(image_dir, idx, warmup_sec)

                    t_min = ((idx - 1) * interval_s) / 60.0
                    analysis.process_image(img_path, t_min)

                    state_manager.update_capture(idx, filename, t_min)
                    state_manager.update_chambers(analysis.get_state())
                    state_manager.add_log(f"Frame {idx:03d} captured: {filename}")

                    elapsed = time.time() - loop_t0
                    sleep_left = interval_s - elapsed
                    if idx < total_frames and sleep_left > 0:
                        time.sleep(sleep_left)

                with open(log_file, "w", encoding="utf-8") as f:
                    json.dump(state_manager.snapshot(), f, indent=2, ensure_ascii=False)

                state_manager.update_assay_status("finished")
                state_manager.add_log("Experiment finished")

            except Exception as e:
                state_manager.update_assay_status("error")
                state_manager.add_log(f"Experiment error: {e}")
            finally:
                heater_service.stop()
                if camera:
                    camera.stop()
                state_manager.set_running(False)

        thread = threading.Thread(target=worker, daemon=True)
        worker_thread["thread"] = thread
        thread.start()

        return jsonify({
            "ok": True,
            "message": "Experiment started",
            "run_id": run_id,
            "image_dir": image_dir
        })

    @bp.post("/api/stop")
    def stop_experiment():
        if not state_manager.snapshot()["running"]:
            return jsonify({"ok": False, "error": "Experiment is not running"}), 400

        stop_event.set()
        heater_service.stop()
        state_manager.add_log("Stop requested")
        state_manager.update_assay_status("stopping")
        return jsonify({"ok": True, "message": "Stop requested"})

    return bp