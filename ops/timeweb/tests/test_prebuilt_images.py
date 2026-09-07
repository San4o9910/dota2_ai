"""Offline regression tests for image integrity, streaming and pinned rollback."""
import hashlib
import io
import json
from pathlib import Path
import sys
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


def info(identifier):
    return {"id": identifier, "os": "linux", "architecture": "amd64"}


def manifest(data):
    return {"schema": 1, "release": RELEASE, "source_tree": "b" * 40,
        "images": {tag: info(REPLAY_ID if tag == "narma-video-replay-worker" else VIDEO_ID)
                   for tag in images.TAGS},
        "archive_sha256": hashlib.sha256(data).hexdigest(), "archive_bytes": len(data)}


class Stream(io.BytesIO):
    def read(self, amount=-1):
        if not 0 < amount <= 1024**2:
            raise AssertionError("The archive must be consumed in bounded chunks")
        return super().read(amount)


class PrebuiltImagesTest(unittest.TestCase):
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
            with patch.object(images, "release_path", return_value=root), \
                    patch.object(images, "checkpoint_path", return_value=checkpoint), \
                    patch.object(images, "image_info", side_effect=image_info), \
                    patch.object(images, "run", side_effect=run), \
                    patch.object(snapshot, "state_path", return_value=state), \
                    patch.object(snapshot, "inspect_service", return_value=None):
                with self.assertRaisesRegex(images.ImageError, "prebuilt_loaded_image_mismatch"):
                    images.install_bundle(RELEASE)
            self.assertFalse((root / "images-validated.json").exists())
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["images"], {tag: OLD_ID for tag in images.TAGS})
            self.assertEqual(checkpoint.stat().st_mode & 0o777, 0o600)

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
            self.assertEqual(commands[:4], [["docker", "image", "tag", OLD_ID, tag] for tag in images.TAGS])
            self.assertEqual(len(commands), 5)
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
