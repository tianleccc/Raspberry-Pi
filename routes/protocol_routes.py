from flask import Blueprint, jsonify, request


def create_protocol_blueprint(protocol_service):
    bp = Blueprint("protocols", __name__)

    @bp.get("/api/protocols")
    def get_protocols():
        return jsonify({"protocols": protocol_service.get_all_protocols()})

    @bp.post("/api/protocols/save")
    def save_protocol():
        payload = request.get_json(silent=True) or {}

        name = payload.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Protocol name is required"}), 400

        protocol_id = payload.get("id")
        if not protocol_id or protocol_id == "custom":
            protocol_id = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")

        protocol = {
            "id": protocol_id,
            "name": name,
            "temperature_c": payload.get("temperature_c"),
            "duration_min": payload.get("duration_min"),
            "warmup_min": payload.get("warmup_min"),
            "read_interval_s": payload.get("read_interval_s")
        }

        protocol_service.save_custom_protocol(protocol)
        return jsonify({"ok": True, "message": f"Protocol saved: {name}", "protocol": protocol})

    return bp