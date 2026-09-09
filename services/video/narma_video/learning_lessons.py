"""Public original reading modules, separate from the private coaching catalog."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

VERSION = "narma.learning-lessons.v1"
PATH = Path(__file__).with_name("static") / "learning-lessons.json"


@lru_cache(maxsize=1)
def _lessons():
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    if payload.get("version") != VERSION or not isinstance(payload.get("lessons"), list):
        raise ValueError("Invalid public learning modules")
    return payload["lessons"]


def get_lessons(position=None):
    rows = _lessons()
    selected = type(position) is int and position in range(1, 6)
    return {
        "lesson_version": VERSION,
        "lesson_library": deepcopy([
            {key: row[key] for key in ("id", "position", "title", "stage_ids", "estimated_minutes", "lead")}
            for row in rows
        ]),
        "lessons": deepcopy([row for row in rows if selected and row["position"] == position]),
    }
