"""Offline regression tests for image integrity, streaming and pinned rollback."""
import hashlib
import io
import json
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
LAYER_A = "sha256:" + "a" * 64
LAYER_B = "sha256:" + "b" * 64
CONFIGS = [
    {"os": "linux", "architecture": "amd64", "config": {"Cmd": ["video"]},
     "rootfs": {"type": "layers", "diff_ids": [LAYER_A, LAYER_B]}},
    {"os": "linux", "architecture": "amd64", "config": {"Cmd": ["replay"]},
     "rootfs": {"type": "layers", "diff_ids": [LAYER_B, LAYER_A]}},
]


def info(identifier):
    return {"id": identifier, "os": "linux", "architecture": "amd64"}


def manifest(data):
    contents = {}
    for config, aliases in zip(CONFIGS, images.SOURCES.values()):
        digest = "sha256:" + hashlib.sha256(json.dumps(config).encode()).hexdigest()
        for tag in aliases:
            contents[tag] = {**info(REPLAY_ID if tag == "narma-video-replay-worker" else VIDEO_ID),
                "config_digest": digest, "rootfs_diff_ids": config["rootfs"]["diff_ids"]}
    return {"schema": 2, "release": RELEASE, "source_tree": "b" * 40,
        "images": contents,
        "archive_sha256": hashlib.sha256(data).hexdigest(), "archive_bytes": len(data)}


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
        tags = aliases[1 - index] if swap_tags else aliases[index]
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
        with patch.object(images, "image_info", side_effect=[info(VIDEO_ID)] * 4 + [info(REPLAY_ID)]), \
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
