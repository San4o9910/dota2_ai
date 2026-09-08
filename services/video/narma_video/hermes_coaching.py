"""Customer projection of runtime reviews; measured pool statistics stay separate."""
from .replay_report import display_unit


def coaching_for(review, selected):
    if not review or review.get("runtime_verified") is not True:
        return None
    matches = {row["match_id"]: row for row in selected}
    observations = {row["match_id"]: row for row in review["snapshot"]["observations"]}
    patterns = []
    for pattern in review["review"]["patterns"]:
        cited_matches = {ref["match_id"] for ref in pattern["evidence"]}
        # A filtered hero/position view must not silently remove contrary context.
        if not cited_matches <= matches.keys():
            continue
        evidence, identities = [], set()
        for ref in pattern["evidence"]:
            match = matches[ref["match_id"]]
            event = next(event for event in observations[ref["match_id"]]["evidence"]
                         if event["id"] == ref["evidence_id"])
            evidence.append({**ref, "job_id": match["job_id"],
                             "time": event["time"], "type": event["type"]})
            identities.add((match["hero"], match["position"]))
        patterns.append({key: pattern[key] for key in ("id", "title", "observation", "confidence")} | {
            "heroes": [{"hero": hero, "label": display_unit(hero), "position": position}
                       for hero, position in sorted(identities, key=lambda value: (value[0], value[1] or 0))],
            "evidence": evidence,
            "goals": [{key: goal[key] for key in
                       ("id", "action", "success_criterion", "evaluate_after_matches")}
                      for goal in review["review"]["goals"] if goal["pattern_id"] == pattern["id"]],
        })
    if not patterns:
        return None
    return {"updated_at": review["created_at"], "patterns": patterns}
