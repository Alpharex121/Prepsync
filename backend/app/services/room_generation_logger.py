import json
from pathlib import Path
from typing import Any


class RoomGenerationLogger:
    def __init__(self) -> None:
        self._base_dir = Path(__file__).resolve().parents[2] / "logs"

    def _room_dir(self, room_id: str) -> Path:
        folder = self._base_dir / room_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_json(self, room_id: str, filename: str, payload: Any) -> None:
        try:
            path = self._room_dir(room_id) / filename
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception:
            return

    def write_text(self, room_id: str, filename: str, text: str) -> None:
        try:
            path = self._room_dir(room_id) / filename
            with path.open("w", encoding="utf-8") as handle:
                handle.write(text)
        except Exception:
            return


room_generation_logger = RoomGenerationLogger()
