"""Read-only verification of the published learning and hero-build catalog."""
import argparse
from collections import Counter
import json
from urllib.request import urlopen


def verify(origin):
    def fetch(path):
        with urlopen(origin.rstrip("/") + path, timeout=30) as response:
            body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("Public catalog exceeds its response limit")
        return json.loads(body)

    heroes = fetch("/api/explore/heroes")["heroes"]
    workshop = fetch("/api/explore/workshop-builds")
    guides = workshop["guides"]
    known = {row["slug"] for row in heroes}
    covered = {row["hero_slug"] for row in guides}
    missing = sorted(known - covered)
    if missing:
        raise ValueError("No public Workshop build for: " + ", ".join(missing))
    assert guides and all(0 < len(row["final_items"]) <= 6 for row in guides)
    assert all(row["source_url"].startswith("https://steamcommunity.com/sharedfiles/filedetails/?id=") for row in guides)
    assert all(row["source_patch"] and row["source_updated_at"] and row["author"] for row in guides)

    lesson_ids = set()
    for position in range(1, 6):
        lessons = fetch("/api/explore/learning?position=" + str(position))["lessons"]
        assert len(lessons) == 3 and all(row["position"] == position for row in lessons)
        assert {stage for row in lessons for stage in row["stage_ids"]} == {"lane", "risk", "map", "decisions", "items", "fights"}
        assert all(len(row["worked_example"]["steps"]) >= 3 and len(row["self_check"]) >= 2 for row in lessons)
        lesson_ids.update(row["id"] for row in lessons)
    assert len(lesson_ids) == 15

    scenarios = fetch("/assets/practice-scenarios.json")["scenarios"]
    assert len(scenarios) >= 120
    counts = Counter((position, row["difficulty"], row["topic"]) for row in scenarios for position in row["positions"])
    topics = {row["topic"] for row in scenarios}
    for position in range(1, 6):
        for difficulty in ("foundations", "application", "advanced"):
            for topic in topics:
                if counts[position, difficulty, topic] < 5:
                    raise ValueError(f"Insufficient cases for role {position}, {difficulty}, {topic}")
    return {"event": "public_deep_learning_ready", "lesson_count": len(lesson_ids),
            "scenario_count": len(scenarios), "hero_count": len(known),
            "workshop_guide_count": len(guides), "workshop_status_counts": dict(Counter(row["status"] for row in guides)),
            "workshop_patch": workshop.get("latest_patch"), "model_calls_created": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.origin), ensure_ascii=False))
