-- Validate any database that received an earlier draft of 0001 without
-- rebuilding analysis_jobs (analysis_reports already references it).
CREATE TABLE `__analysis_player_slot_guard` (
  `player_slot` integer NOT NULL,
  CONSTRAINT `analysis_player_slot_guard` CHECK(
    (`player_slot` BETWEEN 0 AND 4) OR (`player_slot` BETWEEN 128 AND 132)
  )
);--> statement-breakpoint
INSERT INTO `__analysis_player_slot_guard` (`player_slot`)
SELECT `player_slot` FROM `analysis_jobs`;--> statement-breakpoint
DROP TABLE `__analysis_player_slot_guard`;--> statement-breakpoint
CREATE TRIGGER `analysis_jobs_player_slot_insert_guard`
BEFORE INSERT ON `analysis_jobs`
WHEN NOT ((NEW.`player_slot` BETWEEN 0 AND 4) OR (NEW.`player_slot` BETWEEN 128 AND 132))
BEGIN
  SELECT RAISE(ABORT, 'invalid Dota player slot');
END;--> statement-breakpoint
CREATE TRIGGER `analysis_jobs_player_slot_update_guard`
BEFORE UPDATE OF `player_slot` ON `analysis_jobs`
WHEN NOT ((NEW.`player_slot` BETWEEN 0 AND 4) OR (NEW.`player_slot` BETWEEN 128 AND 132))
BEGIN
  SELECT RAISE(ABORT, 'invalid Dota player slot');
END;
