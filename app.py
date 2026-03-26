import json
from pathlib import Path

from flask import Flask, send_from_directory

from routes.experiment_routes import create_experiment_blueprint
from routes.protocol_routes import create_protocol_blueprint
from services.heater_service import HeaterService
from services.protocol_service import ProtocolService
from services.state_manager import StateManager


BASE_DIR = Path(__file__).resolve().parent


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_app():
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static")
    )

    device_cfg = load_json(BASE_DIR / "config" / "device_config.json")
    analysis_cfg = load_json(BASE_DIR / "config" / "analysis_config.json")

    protocol_service = ProtocolService(
        preset_path=str(BASE_DIR / "config" / "protocols.json"),
        saved_path=str(BASE_DIR / "data" / "saved_protocols.json")
    )
    state_manager = StateManager()
    heater_service = HeaterService(device_cfg["heater"], state_manager)

    app.register_blueprint(
        create_protocol_blueprint(protocol_service)
    )
    app.register_blueprint(
        create_experiment_blueprint(
            device_cfg=device_cfg,
            analysis_cfg=analysis_cfg,
            protocol_service=protocol_service,
            state_manager=state_manager,
            heater_service=heater_service
        )
    )

    @app.route("/")
    def index():
        return send_from_directory(app.template_folder, "index.html")

    return app, device_cfg


if __name__ == "__main__":
    app, device_cfg = create_app()
    app.run(
        host=device_cfg["host"],
        port=int(device_cfg["port"]),
        debug=False,
        threaded=True
    )