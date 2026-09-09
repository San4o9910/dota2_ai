from narma_video.learning_lessons import get_lessons

def test_reading_modules_cover_each_role_and_learning_stage():
    all_rows = []
    for position in range(1, 6):
        data = get_lessons(position)
        assert len(data["lesson_library"]) == 15
        rows = data["lessons"]
        assert len(rows) == 3
        assert all(row["position"] == position for row in rows)
        assert {stage for row in rows for stage in row["stage_ids"]} == {"lane", "risk", "map", "decisions", "items", "fights"}
        for row in rows:
            assert len(row["sections"]) >= 3
            assert sum(len(text) for section in row["sections"] for text in section["paragraphs"]) > 1200
            assert len(row["worked_example"]["steps"]) >= 3
            assert len(row["self_check"]) >= 2
            assert len(row["common_errors"]) >= 2
            assert all(row["practice"][key] for key in ("before", "during", "after", "success"))
            assert row["counterexample"]["why_different"] and row["takeaway"]
        all_rows.extend(rows)
    assert len({row["id"] for row in all_rows}) == 15
    assert len({row["worked_example"]["setup"] for row in all_rows}) == 15

def test_unknown_role_does_not_silently_select_carry():
    for position in (None, True, "5", 0, 6):
        data = get_lessons(position)
        assert data["lessons"] == []
        assert len(data["lesson_library"]) == 15

def test_returned_content_cannot_mutate_another_request():
    data = get_lessons(5)
    data["lessons"][0]["title"] = "changed"
    data["lesson_library"][0]["stage_ids"].append("changed")
    other = get_lessons(5)
    assert other["lessons"][0]["title"] != "changed"
    assert "changed" not in other["lesson_library"][0]["stage_ids"]
