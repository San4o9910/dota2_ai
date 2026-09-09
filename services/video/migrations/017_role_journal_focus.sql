-- Extend the existing personal journal without rewriting saved assessments.
ALTER TABLE hero_pool_match_notes
    DROP CONSTRAINT hero_pool_match_notes_focus_check;
ALTER TABLE hero_pool_match_notes
    ADD CONSTRAINT hero_pool_match_notes_focus_check
    CHECK (focus IN ('item_plan', 'farm_checkpoint', 'safe_return', 'lane_support', 'rotation_window'));
