"""Opt-in CI check against a real, isolated runner Docker daemon (no network)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from test_image_retention import old_image, retention, images
from test_prebuilt_images import cache_host, RELEASE, info


@unittest.skipUnless(os.environ.get("NARMA_DOCKER_STORAGE_TESTS") == "1", "requires CI Docker daemon")
class DockerRetentionTest(unittest.TestCase):
    def test_real_docker_preserves_stopped_tagged_rollback_and_unrelated_images(self):
        created = []
        containers = []
        tags = []

        def docker(*args):
            return subprocess.check_output(["docker", *args], stderr=subprocess.PIPE, timeout=60).decode().strip()

        try:
            with tempfile.TemporaryDirectory() as temporary, cache_host() as (root, checks, current, previous):
                context = Path(temporary)
                (context / "Dockerfile").write_text('FROM scratch\nCOPY payload /payload\nCMD ["/payload"]\n')
                for _ in range(5):
                    (context / "payload").write_text(uuid.uuid4().hex)
                    built = docker("build", "--quiet", str(context))
                    created.append(docker("image", "inspect", "--format", "{{.Id}}", built))
                protected, stopped, tagged, retired, unrelated = created
                containers.append(docker("container", "create", stopped))
                tag = "narma-retention-test-" + uuid.uuid4().hex + ":fixture"
                docker("image", "tag", tagged, tag)
                tags.append(tag)
                for release in (current, previous):
                    old_image(root, release, protected)
                checkpoint = checks / ("images-before-" + current + ".json")
                saved = json.loads(checkpoint.read_text())
                saved["images"] = {name: protected for name in images.TAGS}
                checkpoint.write_text(json.dumps(saved))
                for release, identifier in zip(("d" * 40, "e" * 40, "f" * 40, "1" * 40),
                                               (protected, stopped, tagged, retired)):
                    old_image(root, release, identifier)
                with patch.object(images.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
                    result = retention.reclaim_retired_images(RELEASE, 1000)
                self.assertEqual(result["removed_images"], 1)
                self.assertEqual(result["cleanup_status"], "completed")
                for identifier in (protected, stopped, tagged, unrelated):
                    self.assertEqual(docker("image", "inspect", "--format", "{{.Id}}", identifier), identifier)
                self.assertEqual(docker("container", "inspect", "--format", "{{.State.Status}}", containers[0]), "created")
                with self.assertRaises(subprocess.CalledProcessError):
                    docker("image", "inspect", retired)
        finally:
            # Remove only synthetic objects created by this test, never prune.
            for identifier in containers:
                subprocess.run(["docker", "container", "rm", identifier], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            for identifier in tags + created:
                subprocess.run(["docker", "image", "rm", "--no-prune", identifier], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
