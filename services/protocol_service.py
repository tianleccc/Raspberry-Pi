import json
from pathlib import Path


class ProtocolService:
    def __init__(self, preset_path: str, saved_path: str):
        self.preset_path = Path(preset_path)
        self.saved_path = Path(saved_path)

    def _read_json(self, path: Path):
        if not path.exists():
            return {"protocols": []}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_all_protocols(self):
        presets = self._read_json(self.preset_path).get("protocols", [])
        saved = self._read_json(self.saved_path).get("protocols", [])
        return presets + saved

    def get_protocol_by_id(self, protocol_id: str):
        for item in self.get_all_protocols():
            if item.get("id") == protocol_id:
                return item
        return None

    def save_custom_protocol(self, protocol: dict):
        data = self._read_json(self.saved_path)
        protocols = data.get("protocols", [])

        protocol_id = protocol.get("id") or "custom"
        existing_idx = None
        for i, p in enumerate(protocols):
            if p.get("id") == protocol_id or p.get("name") == protocol.get("name"):
                existing_idx = i
                break

        if existing_idx is not None:
            protocols[existing_idx] = protocol
        else:
            protocols.append(protocol)

        data["protocols"] = protocols
        self._write_json(self.saved_path, data)
        return protocol