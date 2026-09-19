"""Offline regression tests for image integrity, streaming and pinned rollback."""
import hashlib
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prebuilt_images as images
import pilot
import snapshot_worker_state as snapshot

RELEASE = "a" * 40
OLD_ID = "sha256:" + "1" * 64
VIDEO_ID = "sha256:" + "2" * 64
REPLAY_ID = "sha256:" + "3" * 64
HERMES_ID = "sha256:" + "6" * 64
LAYER_A = "sha256:" + "a" * 64
LAYER_B = "sha256:" + "b" * 64
CONFIGS = [
    {"os": "linux", "architecture": "amd64", "config": {"Cmd": ["video"]},
     "rootfs": {"type": "layers", "diff_ids": [LAYER_A, LAYER_B]}},
    {"os": "linux", "architecture": "amd64", "config": {"Cmd": ["replay"]},
     "rootfs": {"type": "layers", "diff_ids": [LAYER_B, LAYER_A]}},
    {"os": "linux", "architecture": "amd64", "config": {"Cmd": ["hermes"]},
     "rootfs": {"type": "layers", "diff_ids": [LAYER_A]}},
]


def info(identifier):
    return {"id": identifier, "os": "linux", "architecture": "amd64"}


def manifest(data):
    contents = {}
    for config, aliases in zip(CONFIGS, images.SOURCES.values()):
        digest = "sha256:" + hashlib.sha256(json.dumps(config).encode()).hexdigest()
        for tag in aliases:
            contents[tag] = {**info(REPLAY_ID if tag == "narma-video-replay-worker" else HERMES_ID if tag == "narma-video-hermes-runner" else VIDEO_ID),
                "config_digest": digest, "rootfs_diff_ids": config["rootfs"]["diff_ids"]}
    return {"schema": 3, "release": RELEASE, "source_tree": "b" * 40,
        "images": contents,
        "archive_sha256": hashlib.sha256(data).hexdigest(), "archive_bytes": len(data),
        "unpacked_bytes": len(data) * 3}


def cached_archive(root, release, data=b"authenticated transport cache"):
    directory = root / release
    directory.mkdir(exist_ok=True)
    archive = directory / "images.tar.gz"
    archive.write_bytes(data)
    value = {**manifest(data), "release": release}
    manifest_path = directory / "images-manifest.json"
    manifest_path.write_text(json.dumps(value))
    (directory / "images-validated.json").write_text(json.dumps({"release": release,
        "manifest_sha256": images.file_hash(manifest_path),
        "images": {tag: info(VIDEO_ID) for tag in images.TAGS}}))
    return archive


@contextmanager
def cache_host():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "releases"
        root.mkdir()
        checks = Path(temporary) / "checks"
        checks.mkdir()
        current, previous = "b" * 40, "c" * 40
        for release in (RELEASE, current, previous):
            cached_archive(root, release)
        pointer = Path(temporary) / "current"
        pointer.symlink_to(root / current)
        (checks / ("images-before-" + current + ".json")).write_text(json.dumps({
            "release": current, "images": {tag: OLD_ID for tag in images.TAGS},
            "api": None, "previous_release": previous}))
        with patch.object(images, "RELEASES_ROOT", root), \
                patch.object(images, "CURRENT_RELEASE", pointer), \
                patch.object(images, "CHECKS_ROOT", checks):
            yield root, checks, current, previous


def image_archive(configs=None, *, layout="classic", swap_tags=False, bad_hash=False,
                  duplicate_manifest=False, link_config=False, canonical_tags=False):
    output = io.BytesIO()
    entries = []; members = []
    aliases = list(images.SOURCES.values())
    for index, config in enumerate(configs or CONFIGS):
        raw = json.dumps(config).encode()
        digest = hashlib.sha256(raw).hexdigest()
        if bad_hash and index == 0: digest = "f" * 64
        name = ("blobs/sha256/" + digest) if layout == "containerd" else digest + ".json"
        members.append((name, raw))
        tags = aliases[1 - index] if swap_tags and index < 2 else aliases[index]
        entries.append({"Config": name, "RepoTags": [("docker.io/library/" if canonical_tags else "") + tag + ":latest" for tag in tags],
            "Layers": ["synthetic-layer.tar"]})
    members.append(("manifest.json", json.dumps(entries).encode()))
    if duplicate_manifest: members.append(members[-1])
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for index, (name, raw) in enumerate(members):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            if link_config and index == 0:
                member.type = tarfile.SYMTYPE; member.linkname = "/etc/passwd"; member.size = 0
            archive.addfile(member, io.BytesIO(raw))
    return output.getvalue()


class Stream(io.BytesIO):
    def read(self, amount=-1):
        if not 0 < amount <= 1024**2:
            raise AssertionError("The archive must be consumed in bounded chunks")
        return super().read(amount)


class PrebuiltImagesTest(unittest.TestCase):
    def test_storage_covers_import_verification_and_operating_reserve(self):
        value = {**manifest(b"fixture"), "archive_bytes": 600_000_000, "unpacked_bytes": 3_000_000_000}
        self.assertEqual(images.required_storage(value), 7_200_000_000 + 4 * 1024**3)
        # This is the failure observed in production: ~4.96 GB passed the
        # compressed-size-only check, then import left less than 2 GiB free.
        self.assertGreater(images.required_storage(value), 4_962_369_536)

    def test_legacy_manifests_remain_readable_but_cannot_size_a_new_transfer(self):
        value = manifest(b"legacy")
        value["schema"] = 2
        value.pop("unpacked_bytes")
        self.assertEqual(images.validate_manifest(value, RELEASE), value)
        with self.assertRaisesRegex(images.ImageError, "prebuilt_storage_estimate_missing"):
            images.required_storage(value)
        for size in (None, True, -1, 0, images.MAX_UNPACKED_BYTES + 1):
            with self.subTest(size=size), self.assertRaises(images.ImageError):
                images.validate_manifest({**manifest(b"new"), "unpacked_bytes": size}, RELEASE)

    def test_installed_size_uses_distinct_immutable_images_not_alias_count(self):
        with patch.object(images, "run", return_value=b"3000000000\n") as run:
            self.assertEqual(images.installed_size([VIDEO_ID, VIDEO_ID, REPLAY_ID]), 6_000_000_000)
        self.assertEqual(run.call_count, 2)
        self.assertEqual({call.args[0][-1] for call in run.call_args_list}, {VIDEO_ID, REPLAY_ID})
        for raw in (b"-1", b"0", b"secret text", b"9999999999999"):
            with patch.object(images, "run", return_value=raw), self.assertRaises(images.ImageError):
                images.installed_size([VIDEO_ID])

    def test_retention_keeps_current_previous_incoming_and_unrelated_files_and_is_idempotent(self):
        with cache_host() as (root, checks, current, previous):
            old = cached_archive(root, "d" * 40)
            old_bytes = old.stat().st_size
            unrelated = root / "operator-copy.tar.gz"
            unrelated.write_bytes(b"not a transport-cache candidate")
            source = old.parent / "source.py"
            source.write_text("retained release source")
            result = images.reclaim_retired_archives(RELEASE)
            self.assertEqual(result, {"reclaimed_bytes": old_bytes, "reclaimed_archives": 1,
                "eligible_bytes": old_bytes, "eligible_archives": 1, "cleanup_status": "completed"})
            self.assertFalse(old.exists())
            for release in (RELEASE, current, previous):
                self.assertTrue((root / release / "images.tar.gz").is_file())
            self.assertTrue(source.is_file())
            self.assertTrue(unrelated.is_file())
            self.assertTrue((old.parent / "images-manifest.json").is_file())
            self.assertTrue((old.parent / "images-validated.json").is_file())
            self.assertEqual(images.reclaim_retired_archives(RELEASE)["reclaimed_archives"], 0)

    def test_unknown_current_or_rollback_evidence_disables_reclamation(self):
        for failure in ("missing_checkpoint", "invalid_checkpoint", "unknown_previous", "self_previous", "current_outside", "no_current"):
            with self.subTest(failure=failure), cache_host() as (root, checks, current, previous):
                old = cached_archive(root, "d" * 40)
                checkpoint = checks / ("images-before-" + current + ".json")
                if failure == "missing_checkpoint":
                    checkpoint.unlink()
                elif failure == "invalid_checkpoint":
                    checkpoint.write_text('{"release": "wrong"}')
                elif failure in ("unknown_previous", "self_previous"):
                    value = json.loads(checkpoint.read_text())
                    value["previous_release"] = current if failure == "self_previous" else "f" * 40
                    checkpoint.write_text(json.dumps(value))
                else:
                    images.CURRENT_RELEASE.unlink()
                    if failure == "current_outside":
                        images.CURRENT_RELEASE.symlink_to(root.parent)
                result = images.reclaim_retired_archives(RELEASE)
                self.assertEqual(result["cleanup_status"], "unavailable")
                self.assertEqual(result["reclaimed_archives"], 0)
                self.assertTrue(old.is_file())

    def test_retention_skips_corrupt_unvalidated_symlink_hardlink_and_foreign_cache(self):
        for failure in ("hash", "size", "manifest", "marker_hash", "marker_images", "unvalidated",
                "archive_symlink", "archive_hardlink", "directory_symlink", "manifest_symlink", "marker_hardlink"):
            with self.subTest(failure=failure), cache_host() as (root, checks, current, previous):
                old = cached_archive(root, "d" * 40)
                marker = old.parent / "images-validated.json"
                manifest_path = old.parent / "images-manifest.json"
                if failure == "hash":
                    old.write_bytes(b"X" * old.stat().st_size)
                elif failure == "size":
                    old.write_bytes(b"short")
                elif failure == "manifest":
                    value = json.loads(manifest_path.read_text())
                    value["release"] = "e" * 40
                    manifest_path.write_text(json.dumps(value))
                elif failure in ("marker_hash", "marker_images"):
                    value = json.loads(marker.read_text())
                    value["manifest_sha256" if failure == "marker_hash" else "images"] = "invalid"
                    marker.write_text(json.dumps(value))
                elif failure == "unvalidated":
                    marker.unlink()
                elif failure == "directory_symlink":
                    original = old.parent
                    foreign = root.parent / "foreign-release"
                    original.rename(foreign)
                    original.symlink_to(foreign)
                else:
                    target = manifest_path if failure == "manifest_symlink" else marker if failure == "marker_hardlink" else old
                    foreign = root.parent / "foreign-file"
                    target.rename(foreign)
                    if failure.endswith("symlink"):
                        target.symlink_to(foreign)
                    else:
                        os.link(foreign, target)
                result = images.reclaim_retired_archives(RELEASE)
                self.assertEqual(result["reclaimed_archives"], 0)
                self.assertTrue(old.exists())

    def test_reclaimed_cache_restores_capacity_without_lowering_reserve(self):
        data = b"incoming archive"
        with cache_host() as (root, checks, current, previous):
            old = cached_archive(root, "d" * 40, b"x" * 200)
            required = images.required_storage(manifest(data))
            def disk_usage(path):
                return SimpleNamespace(free=required - 100 + (0 if old.exists() else 200))
            output = io.StringIO()
            with patch.object(images, "read_manifest", return_value=manifest(data)), \
                    patch.object(images.shutil, "disk_usage", side_effect=disk_usage), redirect_stdout(output):
                images.receive_archive(RELEASE, Stream(data))
            event = json.loads(output.getvalue())
            self.assertEqual(event, {"event": "prebuilt_storage_check", "required_bytes": required,
                "free_before_bytes": required - 100, "free_after_bytes": required + 100,
                "reclaimed_bytes": 200, "reclaimed_archives": 1, "eligible_bytes": 200,
                "eligible_archives": 1, "cleanup_status": "completed", "capacity_ok": True})
            self.assertEqual((root / RELEASE / "images.tar.gz").read_bytes(), data)

    def test_insufficient_capacity_after_retention_emits_evidence_before_reading_stream(self):
        class Unreadable:
            def read(self, *args):
                raise AssertionError("insufficient capacity must refuse before reading")
        with cache_host() as (root, checks, current, previous):
            old = cached_archive(root, "d" * 40)
            previous_incoming = (root / RELEASE / "images.tar.gz").read_bytes()
            output = io.StringIO()
            with patch.object(images.shutil, "disk_usage", return_value=SimpleNamespace(free=1)), redirect_stdout(output):
                with self.assertRaisesRegex(images.ImageError, "prebuilt_storage_insufficient"):
                    images.receive_archive(RELEASE, Unreadable())
            self.assertFalse(old.exists())
            self.assertFalse(json.loads(output.getvalue().splitlines()[-1])["capacity_ok"])
            self.assertEqual((root / RELEASE / "images.tar.gz").read_bytes(), previous_incoming)
            self.assertEqual(list((root / RELEASE).glob(".images-upload-*")), [])

    def test_retention_hash_and_entry_work_is_bounded(self):
        with cache_host() as (root, checks, current, previous):
            old = [cached_archive(root, digit * 40, b"x" * 100) for digit in ("d", "e", "f")]
            with patch.object(images, "MAX_RETENTION_BYTES", 150):
                result = images.reclaim_retired_archives(RELEASE)
            self.assertEqual(result["cleanup_status"], "bounded")
            self.assertEqual(result["reclaimed_archives"], 1)
            self.assertEqual(sum(path.exists() for path in old), 2)
            with patch.object(images, "MAX_RETENTION_ENTRIES", 0):
                result = images.reclaim_retired_archives(RELEASE)
            self.assertEqual(result["cleanup_status"], "bounded")
            self.assertEqual(result["reclaimed_archives"], 0)

    def test_changed_current_release_before_unlink_stops_reclamation(self):
        with cache_host() as (root, checks, current, previous):
            old = cached_archive(root, "d" * 40)
            original = images._protected_cache_releases
            calls = 0
            def protection(incoming):
                nonlocal calls
                calls += 1
                if calls == 2:
                    images.CURRENT_RELEASE.unlink()
                    images.CURRENT_RELEASE.symlink_to(root / previous)
                return original(incoming)
            with patch.object(images, "_protected_cache_releases", side_effect=protection):
                result = images.reclaim_retired_archives(RELEASE)
            self.assertEqual(result["cleanup_status"], "unavailable")
            self.assertEqual(result["reclaimed_archives"], 0)
            self.assertTrue(old.is_file())

    def test_streamed_receive_checks_hash_size_and_keeps_previous_file_on_failure(self):
        data = b"synthetic-image-block" * 120000
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(images, "read_manifest", return_value=manifest(data)), \
                    patch.object(images, "release_path", return_value=root), \
                    patch.object(images.shutil, "disk_usage", return_value=SimpleNamespace(free=20 * 1024**3)):
                images.receive_archive(RELEASE, Stream(data))
                archive = root / "images.tar.gz"
                self.assertEqual(archive.read_bytes(), data)
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
                for damaged in (data[:-1], data + b"x", b"X" + data[1:]):
                    with self.subTest(length=len(damaged)):
                        with self.assertRaises(images.ImageError):
                            images.receive_archive(RELEASE, Stream(damaged))
                        self.assertEqual(archive.read_bytes(), data)
                        self.assertEqual(list(root.glob(".images-upload-*")), [])

    def test_loaded_image_mismatch_never_creates_validation_marker_and_keeps_checkpoint(self):
        data = b"synthetic archive"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "images.tar.gz").write_bytes(data)
            (root / "images-manifest.json").write_text(json.dumps(manifest(data)))
            state = root / "workers-before.json"
            state.write_text(json.dumps({"release": RELEASE}))
            checkpoint = root / "images-before.json"
            loaded = False
            def image_info(tag):
                return info(VIDEO_ID if loaded else OLD_ID)
            def run(command, **options):
                nonlocal loaded
                self.assertEqual(command[:4], ["docker", "image", "load", "--quiet"])
                loaded = True
                return b""
            def export(path, **options):
                path.write_bytes(image_archive(swap_tags=True))
            with patch.object(images, "release_path", return_value=root), \
                    patch.object(images, "checkpoint_path", return_value=checkpoint), \
                    patch.object(images, "image_info", side_effect=image_info), \
                    patch.object(images, "run", side_effect=run), \
                    patch.object(images, "save_archive", side_effect=export), \
                    patch.object(snapshot, "state_path", return_value=state), \
                    patch.object(snapshot, "inspect_service", return_value=None):
                with self.assertRaisesRegex(images.ImageError, "prebuilt_loaded_image_mismatch"):
                    images.install_bundle(RELEASE)
            self.assertFalse((root / "images-validated.json").exists())
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["images"], {tag: OLD_ID for tag in images.TAGS})
            self.assertEqual(checkpoint.stat().st_mode & 0o777, 0o600)

    def test_cross_store_ids_may_differ_only_after_exact_exported_config_proof(self):
        expected = manifest(b"source archive")
        for layout in ("classic", "containerd"):
            with self.subTest(destination_store=layout):
                exported = []
                def export(path, **options):
                    self.assertEqual(options["export_timeout"], 180)
                    exported.append(path)
                    path.write_bytes(image_archive(layout=layout, canonical_tags=layout == "containerd"))
                local = {tag: info("sha256:" + ("4" if "replay" in tag else "5") * 64)
                         for tag in images.TAGS}
                with patch.object(images, "image_info", side_effect=lambda tag: local[tag]), \
                        patch.object(images, "save_archive", side_effect=export):
                    self.assertEqual(images.verify_images(expected), local)
                self.assertTrue(all(not path.exists() and not path.parent.exists() for path in exported))

    def test_full_config_not_only_platform_and_layers_is_verified(self):
        changed = json.loads(json.dumps(CONFIGS))
        changed[0]["config"]["Cmd"] = ["unexpected command"]
        self.assertEqual(changed[0]["rootfs"], CONFIGS[0]["rootfs"])
        with patch.object(images, "image_info", return_value=info(VIDEO_ID)), \
                patch.object(images, "save_archive", side_effect=lambda path, **_: path.write_bytes(image_archive(changed))):
            with self.assertRaisesRegex(images.ImageError, "prebuilt_loaded_image_mismatch"):
                images.verify_images(manifest(b"source"))

    def test_swapped_tags_and_reordered_layers_are_rejected(self):
        reordered = json.loads(json.dumps(CONFIGS))
        reordered[0]["rootfs"]["diff_ids"].reverse()
        for data in (image_archive(swap_tags=True), image_archive(reordered)):
            with self.subTest(archive_hash=hashlib.sha256(data).hexdigest()):
                with patch.object(images, "image_info", return_value=info(VIDEO_ID)), \
                        patch.object(images, "save_archive", side_effect=lambda path, **_: path.write_bytes(data)):
                    with self.assertRaisesRegex(images.ImageError, "prebuilt_loaded_image_mismatch"):
                        images.verify_images(manifest(b"source"))

    def test_export_rejects_tag_change_and_removes_temporary_archive(self):
        exported = []
        def export(path, **options):
            exported.append(path)
            path.write_bytes(image_archive())
        with patch.object(images, "image_info", side_effect=[info(VIDEO_ID)] * len(images.TAGS) + [info(REPLAY_ID)]), \
                patch.object(images, "save_archive", side_effect=export):
            with self.assertRaisesRegex(images.ImageError, "prebuilt_loaded_image_changed"):
                images.verify_images(manifest(b"source"))
        self.assertTrue(all(not path.parent.exists() for path in exported))

    def test_archive_rejects_wrong_config_digest_symlink_duplicate_and_platform(self):
        wrong_platform = json.loads(json.dumps(CONFIGS))
        wrong_platform[0]["architecture"] = "arm64"
        for data in (image_archive(bad_hash=True), image_archive(link_config=True),
                     image_archive(duplicate_manifest=True), image_archive(wrong_platform)):
            with tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / "images.tar.gz"
                archive.write_bytes(data)
                with self.assertRaises(images.ImageError):
                    images.archive_image_contents(archive)

    def test_validation_pins_proved_local_ids_and_manifest_without_reexport(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = root / "images-manifest.json"
            manifest_path.write_text(json.dumps(manifest(b"archive")))
            local = {tag: info(OLD_ID) for tag in images.TAGS}
            marker = {"release": RELEASE, "manifest_sha256": images.file_hash(manifest_path), "images": local}
            (root / "images-validated.json").write_text(json.dumps(marker))
            with patch.object(images, "release_path", return_value=root), \
                    patch.object(images, "save_archive") as export, \
                    patch.object(images, "image_info", return_value=info(OLD_ID)):
                images.validate_installed(RELEASE)
                export.assert_not_called()
            with patch.object(images, "release_path", return_value=root), \
                    patch.object(images, "image_info", return_value=info(VIDEO_ID)):
                with self.assertRaisesRegex(images.ImageError, "prebuilt_loaded_image_changed"):
                    images.validate_installed(RELEASE)

    def test_rollback_restores_preexisting_image_ids_and_api_without_build_or_pull(self):
        previous = {"service": "api", "id": "4" * 64, "image": OLD_ID, "running": True,
            "config": "/opt/narma/releases/" + "c" * 40 + "/services/video/compose.yaml"}
        current = {**previous, "id": "5" * 64, "image": VIDEO_ID}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text(json.dumps({"release": RELEASE,
                "images": {tag: OLD_ID for tag in images.TAGS}, "api": previous, "previous_release": None}))
            commands = []
            def run(command, **options):
                commands.append(command)
                if "up" in command:
                    override = Path(command[command.index("--file", command.index("--file") + 1) + 1])
                    self.assertEqual(json.loads(override.read_text()), {"services": {"api": {"image": OLD_ID}}})
                    self.assertIn("--no-build", command)
                    self.assertEqual(command[command.index("--pull") + 1], "never")
                return b""
            with patch.object(images, "release_path", return_value=root), \
                    patch.object(images, "checkpoint_path", return_value=checkpoint), \
                    patch.object(images, "image_info", return_value=info(OLD_ID)), \
                    patch.object(images, "run", side_effect=run), \
                    patch.object(snapshot, "inspect_service", side_effect=[current, previous]):
                images.rollback_images(RELEASE)
            self.assertEqual(commands[:len(images.TAGS)], [["docker", "image", "tag", OLD_ID, tag] for tag in images.TAGS])
            self.assertEqual(len(commands), len(images.TAGS) + 1)
            self.assertFalse(any("prune" in command or "rm" in command for command in commands))

    def test_ssh_transfer_uses_file_stdin_and_does_not_forward_raw_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "images.tar.gz"
            archive.write_bytes(b"synthetic payload")
            def run(command, **options):
                self.assertNotIn("input", options)
                self.assertEqual(options["stdin"].read(1024), b"synthetic payload")
                options["stdout"].write(b"untrusted raw output must stay private\n")
                options["stderr"].write(b"untrusted raw stderr must stay private\n")
                return SimpleNamespace(returncode=1)
            with patch.object(pilot.subprocess, "run", side_effect=run), \
                    patch.object(pilot, "event") as event:
                with self.assertRaisesRegex(pilot.CheckError, "prebuilt_archive_transfer_failed"):
                    pilot.transfer_image_archive(["ssh", "synthetic"], archive)
                event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
