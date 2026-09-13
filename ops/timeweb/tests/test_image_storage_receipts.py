"""Only bounded aggregate disk evidence may leave the authenticated transfer."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot


def receipt(**changes):
    return {"event": "prebuilt_storage_check", "required_bytes": 5 * 1024**3,
        "free_before_bytes": 1024**3, "free_after_bytes": 6 * 1024**3,
        "reclaimed_bytes": 5 * 1024**3, "reclaimed_archives": 10,
        "eligible_bytes": 5 * 1024**3, "eligible_archives": 10,
        "cleanup_status": "completed", "capacity_ok": True, **changes}


class ImageStorageReceiptsTest(unittest.TestCase):
    def test_valid_success_and_insufficient_capacity_are_visible(self):
        for item in (receipt(), receipt(free_after_bytes=2 * 1024**3, capacity_ok=False,
                reclaimed_bytes=1024**3, reclaimed_archives=2, cleanup_status="bounded"),
                receipt(free_after_bytes=1024**3, capacity_ok=False, reclaimed_bytes=0,
                    reclaimed_archives=0, eligible_bytes=0, eligible_archives=0,
                    cleanup_status="unavailable")):
            with self.subTest(status=item["cleanup_status"]), patch.object(pilot, "event") as event:
                pilot.emit_image_failure(json.dumps(item))
                event.assert_called_once_with("prebuilt_storage_check",
                    **{key: value for key, value in item.items() if key != "event"})

    def test_untrusted_or_malformed_receipts_are_not_forwarded(self):
        invalid = [None, [], "unexpected", receipt(path="private server path"),
            receipt(raw_output="unfiltered content"), receipt(required_bytes=True),
            receipt(required_bytes=9 * 1024**3), receipt(free_before_bytes=-1),
            receipt(eligible_archives=257), receipt(reclaimed_archives=11),
            receipt(reclaimed_bytes=6 * 1024**3), receipt(capacity_ok="true"),
            receipt(capacity_ok=False), receipt(cleanup_status="private error")]
        for item in invalid:
            with self.subTest(item=item), patch.object(pilot, "event") as event:
                pilot.emit_image_failure(json.dumps(item))
                event.assert_not_called()

    def test_failed_transfer_keeps_storage_evidence_but_hides_raw_output(self):
        storage = receipt(free_after_bytes=1024**3, capacity_ok=False, reclaimed_bytes=0,
            reclaimed_archives=0, eligible_bytes=0, eligible_archives=0,
            cleanup_status="unavailable")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "images.tar.gz"
            archive.write_bytes(b"fixture")
            def run(command, **options):
                options["stdout"].write(("private stdout\n" + json.dumps(storage) + "\n" +
                    json.dumps({"event": "prebuilt_images_failed", "code": "prebuilt_storage_insufficient"}) + "\n").encode())
                options["stderr"].write(b"private stderr\n")
                return SimpleNamespace(returncode=1)
            with patch.object(pilot.subprocess, "run", side_effect=run), patch.object(pilot, "event") as event:
                with self.assertRaisesRegex(pilot.CheckError, "prebuilt_archive_transfer_failed"):
                    pilot.transfer_image_archive(["ssh", "fixture"], archive)
                self.assertEqual(event.call_count, 2)
                self.assertEqual(event.call_args_list[0].args, ("prebuilt_storage_check",))
                self.assertEqual(event.call_args_list[0].kwargs,
                    {key: value for key, value in storage.items() if key != "event"})
                self.assertEqual(event.call_args_list[1].kwargs, {"code": "prebuilt_storage_insufficient"})


if __name__ == "__main__":
    unittest.main()
