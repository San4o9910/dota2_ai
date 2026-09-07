"""Transfer tested CI images to the existing host without registry access there.

Only image IDs, platform and source hashes enter the manifest. Image archives are
streamed through files; no credential, environment dump or user media is exported.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
MAX_ARCHIVE_BYTES = 4 * 1024**3
SOURCES = {
    "narma-video-check": ("narma-video-api", "narma-video-migrate", "narma-video-worker"),
    "narma-replay-check": ("narma-video-replay-worker",),
}
TAGS = tuple(tag for aliases in SOURCES.values() for tag in aliases)


class ImageError(RuntimeError):
    pass


def run(arguments, *, timeout=30):
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ImageError("prebuilt_command_failed") from None
    if result.returncode:
        raise ImageError("prebuilt_command_failed")
    return result.stdout


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def image_info(tag):
    if tag not in TAGS and tag not in SOURCES and tag != "postgres:17-bookworm" and not IMAGE_ID.fullmatch(tag):
        raise ImageError("prebuilt_image_reference_invalid")
    template = '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}'
    try:
        value = json.loads(run(["docker", "image", "inspect", "--format", template, tag]))
    except (ValueError, TypeError):
        raise ImageError("prebuilt_image_metadata_invalid") from None
    if (set(value) != {"id", "os", "architecture"}
            or not IMAGE_ID.fullmatch(value.get("id", ""))
            or value.get("os") != "linux" or value.get("architecture") != "amd64"):
        raise ImageError("prebuilt_image_platform_invalid")
    return value


def validate_manifest(value, release):
    if not SHA.fullmatch(release):
        raise ImageError("prebuilt_release_invalid")
    if not isinstance(value, dict) or set(value) != {
            "schema", "release", "source_tree", "images", "archive_sha256", "archive_bytes"}:
        raise ImageError("prebuilt_manifest_invalid")
    if (value["schema"] != 1 or value["release"] != release
            or not SHA.fullmatch(value.get("source_tree", ""))
            or not DIGEST.fullmatch(value.get("archive_sha256", ""))
            or type(value["archive_bytes"]) is not int
            or not 0 < value["archive_bytes"] <= MAX_ARCHIVE_BYTES
            or not isinstance(value["images"], dict) or set(value["images"]) != set(TAGS)):
        raise ImageError("prebuilt_manifest_invalid")
    for info in value["images"].values():
        if (not isinstance(info, dict) or set(info) != {"id", "os", "architecture"}
                or not IMAGE_ID.fullmatch(info.get("id", ""))
                or info["os"] != "linux" or info["architecture"] != "amd64"):
            raise ImageError("prebuilt_manifest_invalid")
    if len({value["images"][tag]["id"] for tag in SOURCES["narma-video-check"]}) != 1:
        raise ImageError("prebuilt_manifest_invalid")
    return value


def save_archive(path):
    """Pipe docker save through gzip into a mode-0600 file with bounded waits."""
    producer = compressor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as destination, tempfile.TemporaryFile() as errors:
            producer = subprocess.Popen(["docker", "image", "save", *TAGS],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors)
            compressor = subprocess.Popen(["gzip", "-1"], stdin=producer.stdout,
                stdout=destination, stderr=errors)
            producer.stdout.close()
            if producer.wait(timeout=600) or compressor.wait(timeout=120):
                raise ImageError("prebuilt_export_failed")
            destination.flush(); os.fsync(destination.fileno())
        if not 0 < Path(path).stat().st_size <= MAX_ARCHIVE_BYTES:
            raise ImageError("prebuilt_export_size_invalid")
    except (OSError, subprocess.TimeoutExpired):
        raise ImageError("prebuilt_export_failed") from None
    finally:
        for process in (producer, compressor):
            if process is not None and process.poll() is None:
                process.kill(); process.wait(timeout=10)


def prepare_bundle(release, directory):
    """Called only after the same workflow has tested both local image tags."""
    if not SHA.fullmatch(release):
        raise ImageError("prebuilt_release_invalid")
    if run(["git", "rev-parse", "HEAD"]).decode().strip() != release:
        raise ImageError("prebuilt_source_release_mismatch")
    run(["git", "diff", "--quiet", "HEAD", "--"])
    tree = run(["git", "rev-parse", "HEAD^{tree}"]).decode().strip()
    if not SHA.fullmatch(tree):
        raise ImageError("prebuilt_source_tree_invalid")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    images = {}
    for source, aliases in SOURCES.items():
        info = image_info(source)
        for alias in aliases:
            # Tag the inspected immutable ID, never a tag that could move mid-export.
            run(["docker", "image", "tag", info["id"], alias])
            images[alias] = info
    archive = directory / "images.tar.gz"
    save_archive(archive)
    if any(image_info(tag) != info for tag, info in images.items()):
        raise ImageError("prebuilt_export_image_changed")
    value = validate_manifest({"schema": 1, "release": release, "source_tree": tree,
        "images": images, "archive_sha256": file_hash(archive), "archive_bytes": archive.stat().st_size}, release)
    from snapshot_worker_state import write_private
    manifest = directory / "images-manifest.json"
    write_private(manifest, value)
    return archive, manifest, value


def release_path(release):
    if not SHA.fullmatch(release):
        raise ImageError("prebuilt_release_invalid")
    return Path("/opt/narma/releases") / release


def read_manifest(release):
    path = release_path(release) / "images-manifest.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16384:
        raise ImageError("prebuilt_manifest_invalid")
    try:
        return validate_manifest(json.loads(path.read_text()), release)
    except (ValueError, TypeError):
        raise ImageError("prebuilt_manifest_invalid") from None


def receive_archive(release, stream):
    manifest = read_manifest(release)
    root = release_path(release)
    if shutil.disk_usage(root).free < manifest["archive_bytes"] + 4 * 1024**3:
        raise ImageError("prebuilt_storage_insufficient")
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".images-upload-", delete=False) as output:
            name = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            digest = hashlib.sha256(); received = 0
            while block := stream.read(min(1024**2, manifest["archive_bytes"] - received + 1)):
                received += len(block)
                if received > manifest["archive_bytes"]:
                    raise ImageError("prebuilt_archive_size_mismatch")
                output.write(block); digest.update(block)
            output.flush(); os.fsync(output.fileno())
        if received != manifest["archive_bytes"] or digest.hexdigest() != manifest["archive_sha256"]:
            raise ImageError("prebuilt_archive_integrity")
        name.replace(root / "images.tar.gz")
    finally:
        if name is not None: name.unlink(missing_ok=True)


def checkpoint_path(release):
    return Path("/opt/narma/checks") / ("images-before-" + release + ".json")


def install_bundle(release):
    from snapshot_worker_state import inspect_service, state_path, write_private
    root = release_path(release)
    manifest = read_manifest(release)
    # Require the existing worker/account/budget snapshot BEFORE any image tag changes.
    if json.loads(state_path(release).read_text()).get("release") != release:
        raise ImageError("prebuilt_snapshot_missing")
    archive = root / "images.tar.gz"
    if (not archive.is_file() or archive.is_symlink() or archive.stat().st_size != manifest["archive_bytes"]
            or file_hash(archive) != manifest["archive_sha256"]):
        raise ImageError("prebuilt_archive_integrity")
    previous = {}
    for tag in TAGS:
        try: previous[tag] = image_info(tag)["id"]
        except ImageError: pass  # First deployment may not have this optional service image.
    current = Path("/opt/narma/current")
    old_release = current.resolve().name if current.is_symlink() else None
    if old_release is not None and not SHA.fullmatch(old_release):
        raise ImageError("prebuilt_previous_release_invalid")
    write_private(checkpoint_path(release), {"release": release, "images": previous,
        "api": inspect_service("api"), "previous_release": old_release})
    run(["docker", "image", "load", "--quiet", "--input", str(archive)], timeout=600)
    verify_images(manifest)
    # The existing database image stays local and untouched; no implicit registry pull.
    try: image_info("postgres:17-bookworm")
    except ImageError:
        raise ImageError("prebuilt_database_image_missing") from None
    write_private(root / "images-validated.json", {"release": release,
        "manifest_sha256": file_hash(root / "images-manifest.json")})


def verify_images(manifest):
    if any(image_info(tag) != info for tag, info in manifest["images"].items()):
        raise ImageError("prebuilt_loaded_image_mismatch")


def validate_installed(release):
    root = release_path(release)
    manifest = read_manifest(release)
    try: marker = json.loads((root / "images-validated.json").read_text())
    except (OSError, ValueError):
        raise ImageError("prebuilt_validation_missing") from None
    if marker != {"release": release, "manifest_sha256": file_hash(root / "images-manifest.json")}:
        raise ImageError("prebuilt_validation_mismatch")
    verify_images(manifest)


def rollback_images(release):
    from snapshot_worker_state import CONFIG, compose, inspect_service, write_private
    release_path(release)
    path = checkpoint_path(release)
    if not path.is_file():
        return  # Nothing was loaded before this attempt failed.
    saved = json.loads(path.read_text())
    if saved.get("release") != release or not isinstance(saved.get("images"), dict):
        raise ImageError("prebuilt_rollback_snapshot_invalid")
    for tag, identifier in saved["images"].items():
        if tag not in TAGS or not IMAGE_ID.fullmatch(identifier):
            raise ImageError("prebuilt_rollback_snapshot_invalid")
        image_info(identifier)
        run(["docker", "image", "tag", identifier, tag])
    previous = saved.get("api")
    if previous and previous.get("running"):
        if (previous.get("service") != "api" or not CONFIG.fullmatch(previous.get("config", ""))
                or not IMAGE_ID.fullmatch(previous.get("image", ""))
                or not DIGEST.fullmatch(previous.get("id", ""))):
            raise ImageError("prebuilt_rollback_snapshot_invalid")
        current = inspect_service("api")
        if current and current["id"] == previous["id"] and current["image"] == previous["image"]:
            if not current["running"]: run(["docker", "start", previous["id"]])
        else:
            with tempfile.TemporaryDirectory(prefix="narma-api-rollback-") as folder:
                override = Path(folder) / "image.json"
                write_private(override, {"services": {"api": {"image": previous["image"]}}})
                run(compose(previous["config"]) + ["--file", str(override), "up", "-d",
                    "--no-deps", "--no-build", "--pull", "never", "api"], timeout=90)
        restored = inspect_service("api")
        if not restored or not restored["running"] or restored["image"] != previous["image"]:
            raise ImageError("prebuilt_api_rollback_failed")
    old_release = saved.get("previous_release")
    if old_release is not None:
        if not SHA.fullmatch(old_release) or not release_path(old_release).is_dir():
            raise ImageError("prebuilt_previous_release_invalid")
        temporary = Path("/opt/narma/current.rollback")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(release_path(old_release), target_is_directory=True)
        temporary.replace("/opt/narma/current")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("receive", "install", "validate", "rollback"))
    parser.add_argument("release")
    args = parser.parse_args()
    try:
        if args.action == "receive": receive_archive(args.release, sys.stdin.buffer)
        elif args.action == "install": install_bundle(args.release)
        elif args.action == "validate": validate_installed(args.release)
        else: rollback_images(args.release)
        print(json.dumps({"event": "prebuilt_images_" + args.action, "release": args.release}), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, ImageError) else "prebuilt_operation_failed"
        print(json.dumps({"event": "prebuilt_images_failed", "code": code}), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
