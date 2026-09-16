"""Retired image cleanup must preserve live work, rollback and unknown data."""
import json
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_retention as retention
import prebuilt_images as images
from test_prebuilt_images import cache_host, cached_archive, RELEASE, OLD_ID, VIDEO_ID, info

RETIRED_ID = "sha256:" + "4" * 64
OTHER_ID = "sha256:" + "5" * 64
CONTAINER = "9" * 64


def old_image(root, release="d" * 40, identifier=RETIRED_ID):
    archive = cached_archive(root, release)
    path = archive.parent / "images-validated.json"
    value = json.loads(path.read_text())
    value["images"] = {tag: info(identifier) for tag in images.TAGS}
    path.write_text(json.dumps(value))
    return archive


class Docker:
    def __init__(self, *, used=(), tags=None, digests=None, conflict=False):
        self.used, self.tags, self.digests, self.conflict = used, tags or {}, digests or {}, conflict
        self.removed = []
        self.commands = []

    def run(self, command, **kwargs):
        self.commands.append(command)
        if command[:3] == ["docker", "container", "ls"]:
            return b"" if not self.used else (CONTAINER + "\n").encode()
        if command[:3] == ["docker", "container", "inspect"]:
            return (self.used[0] + "\n").encode()
        if command[:3] == ["docker", "image", "inspect"]:
            identifier = command[-1]
            return json.dumps({"id": identifier, "tags": self.tags.get(identifier, []),
                "digests": self.digests.get(identifier, []), "os": "linux", "architecture": "amd64"}).encode()
        if command[:4] == ["docker", "image", "rm", "--no-prune"] and len(command) == 5:
            if self.conflict:
                raise images.ImageError("prebuilt_command_failed")
            self.removed.append(command[-1])
            return b""
        raise AssertionError("unexpected operation: " + repr(command))


class ImageRetentionTest(unittest.TestCase):
    def collect(self, docker, required=1000):
        with patch.object(images, "run", side_effect=docker.run), \
                patch.object(images.shutil, "disk_usage", side_effect=lambda path:
                    SimpleNamespace(free=1 + 1000 * len(docker.removed))):
            return retention.reclaim_retired_images(RELEASE, required)

    def test_receiver_rechecks_capacity_after_image_cleanup_before_accepting_upload(self):
        with cache_host() as (root, *_):
            old_image(root)
            docker = Docker()
            data = (root / RELEASE / "images.tar.gz").read_bytes()
            needed = images.required_storage(images.read_manifest(RELEASE))
            output = io.StringIO()
            with patch.object(images, "run", side_effect=docker.run), \
                    patch.object(images.shutil, "disk_usage", side_effect=lambda path:
                        SimpleNamespace(free=1 + needed * len(docker.removed))), redirect_stdout(output):
                images.receive_archive(RELEASE, io.BytesIO(data))
            receipts = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(docker.removed, [RETIRED_ID])
            self.assertEqual(receipts[0]["removed_images"], 1)
            self.assertTrue(receipts[-1]["capacity_ok"])
            self.assertEqual((root / RELEASE / "images.tar.gz").read_bytes(), data)

    def test_only_verified_retired_untagged_image_is_removed_and_repeating_is_safe(self):
        with cache_host() as (root, checks, current, previous):
            archive = old_image(root)
            (root / "unrelated.txt").write_text("retain")
            docker = Docker()
            result = self.collect(docker)
            self.assertEqual(docker.removed, [RETIRED_ID])
            self.assertEqual(result["removed_images"], 1)
            self.assertTrue(archive.exists())
            self.assertEqual((root / "unrelated.txt").read_text(), "retain")
            result = self.collect(docker)
            self.assertEqual(result["removed_images"], 0)
            self.assertEqual(docker.removed, [RETIRED_ID])
            self.assertFalse(any("--force" in c or "volume" in c or "prune" in c or "stop" in c for c in docker.commands))

    def test_any_container_including_stopped_and_any_tag_or_digest_protects_image(self):
        for docker in (Docker(used=[RETIRED_ID]), Docker(tags={RETIRED_ID: ["other:latest"]}),
                       Docker(digests={RETIRED_ID: ["registry@sha256:abc"]}), Docker(conflict=True)):
            with self.subTest(docker=vars(docker)), cache_host() as (root, *_):
                old_image(root)
                self.assertEqual(self.collect(docker)["removed_images"], 0)
                self.assertEqual(docker.removed, [])

    def test_current_previous_incoming_and_rollback_ids_are_never_candidates(self):
        for identifier in (VIDEO_ID, OLD_ID):
            with self.subTest(identifier=identifier), cache_host() as (root, *_):
                old_image(root, identifier=identifier)
                docker = Docker()
                self.assertEqual(self.collect(docker)["removed_images"], 0)
                self.assertEqual(docker.commands, [])
        with cache_host() as (root, checks, current, previous):
            old_image(root, previous, RETIRED_ID)
            old_image(root, identifier=RETIRED_ID)
            docker = Docker()
            self.assertEqual(self.collect(docker)["removed_images"], 0)
            self.assertEqual(docker.commands, [])

    def test_stale_incoming_manifest_can_only_add_protection_on_retry(self):
        with cache_host() as (root, *_):
            old_image(root, RELEASE, RETIRED_ID)
            old_image(root, identifier=RETIRED_ID)
            path = root / RELEASE / "images-manifest.json"
            value = json.loads(path.read_text())
            value["archive_sha256"] = "e" * 64
            path.write_text(json.dumps(value))
            docker = Docker()
            self.assertEqual(self.collect(docker)["removed_images"], 0)
            self.assertEqual(docker.commands, [])

    def test_corrupt_unvalidated_or_linked_metadata_never_authorizes_removal(self):
        for mode in ("missing", "hash", "id", "symlink", "hardlink"):
            with self.subTest(mode=mode), cache_host() as (root, *_):
                archive = old_image(root)
                path = archive.parent / "images-validated.json"
                value = json.loads(path.read_text())
                if mode == "missing":
                    path.unlink()
                elif mode in ("symlink", "hardlink"):
                    other = root.parent / "foreign"
                    path.rename(other)
                    path.symlink_to(other) if mode == "symlink" else os.link(other, path)
                else:
                    if mode == "hash": value["manifest_sha256"] = "0" * 64
                    else: value["images"][images.TAGS[0]]["id"] = "unexpected"
                    path.write_text(json.dumps(value))
                docker = Docker()
                self.assertEqual(self.collect(docker)["removed_images"], 0)
                self.assertEqual(docker.commands, [])

    def test_missing_rollback_evidence_or_changed_release_stops_cleanup(self):
        with cache_host() as (root, checks, current, previous):
            old_image(root)
            (checks / ("images-before-" + current + ".json")).unlink()
            docker = Docker()
            self.assertEqual(self.collect(docker)["cleanup_status"], "unavailable")
            self.assertEqual(docker.commands, [])
        with cache_host() as (root, *_):
            old_image(root)
            original = retention.protected_state
            calls = 0
            def changed(incoming):
                nonlocal calls
                value = original(incoming)
                calls += 1
                return value if calls == 1 else (set(), set(), ())
            docker = Docker()
            with patch.object(retention, "protected_state", side_effect=changed):
                self.assertEqual(self.collect(docker)["cleanup_status"], "unavailable")
            self.assertEqual(docker.commands, [])

    def test_unknown_container_inventory_fails_closed(self):
        with cache_host() as (root, *_):
            old_image(root)
            with patch.object(images, "run", return_value=b"invalid\n"), \
                    patch.object(images.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
                result = retention.reclaim_retired_images(RELEASE, 1000)
            self.assertEqual(result["cleanup_status"], "unavailable")
            self.assertEqual(result["removed_images"], 0)

    def test_cleanup_work_is_bounded_even_when_it_does_not_free_enough_space(self):
        with cache_host() as (root, *_):
            old_image(root)
            old_image(root, "e" * 40, OTHER_ID)
            docker = Docker()
            with patch.object(retention, "MAX_IMAGES", 1):
                result = self.collect(docker, required=5000)
            self.assertEqual(result["removed_images"], 1)
            self.assertEqual(result["cleanup_status"], "bounded")


if __name__ == "__main__":
    unittest.main()
