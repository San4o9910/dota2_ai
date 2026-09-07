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
import tarfile
import tempfile

SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_METADATA_BYTES = 16 * 1024**2
CONFIG_PATH = re.compile(r"(?:blobs/sha256/)?([0-9a-f]{64})(?:\.json)?")
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
    if (value["schema"] != 2 or value["release"] != release
            or not SHA.fullmatch(value.get("source_tree", ""))
            or not DIGEST.fullmatch(value.get("archive_sha256", ""))
            or type(value["archive_bytes"]) is not int
            or not 0 < value["archive_bytes"] <= MAX_ARCHIVE_BYTES
            or not isinstance(value["images"], dict) or set(value["images"]) != set(TAGS)):
        raise ImageError("prebuilt_manifest_invalid")
    for info in value["images"].values():
        if (not isinstance(info, dict) or set(info) != {
                    "id", "os", "architecture", "config_digest", "rootfs_diff_ids"}
                or not IMAGE_ID.fullmatch(info.get("id", ""))
                or not IMAGE_ID.fullmatch(info.get("config_digest", ""))
                or not isinstance(info.get("rootfs_diff_ids"), list)
                or not 0 < len(info["rootfs_diff_ids"]) <= 256
                or any(not isinstance(item, str) or not IMAGE_ID.fullmatch(item)
                       for item in info["rootfs_diff_ids"])
                or info["os"] != "linux" or info["architecture"] != "amd64"):
            raise ImageError("prebuilt_manifest_invalid")
    if any(value["images"][tag] != value["images"]["narma-video-api"]
           for tag in SOURCES["narma-video-check"]):
        raise ImageError("prebuilt_manifest_invalid")
    return value


def archive_image_contents(path):
    """Read canonical config hashes from docker-save metadata without extracting.

    Docker's classic store reports a config digest as .Id; its containerd store
    can report a manifest/index digest instead. The exact immutable config bytes
    (which include ordered layer DiffIDs) survive export/load across both stores.
    Only small metadata members are retained; image layers stay in the stream.
    """
    metadata = {}; total = 0; members = 0
    try:
        with tarfile.open(path, mode="r|gz") as archive:
            for member in archive:
                members += 1
                if members > 4096:
                    raise ImageError("prebuilt_archive_metadata_invalid")
                if member.name != "manifest.json" and not CONFIG_PATH.fullmatch(member.name):
                    continue
                if member.size > 1024**2:
                    if member.name == "manifest.json":
                        raise ImageError("prebuilt_archive_metadata_invalid")
                    continue  # Large content-addressed blobs are image layers.
                if not member.isfile() or member.name in metadata:
                    raise ImageError("prebuilt_archive_metadata_invalid")
                total += member.size
                if total > MAX_METADATA_BYTES:
                    raise ImageError("prebuilt_archive_metadata_invalid")
                stream = archive.extractfile(member)
                data = stream.read(1024**2 + 1)
                if len(data) != member.size:
                    raise ImageError("prebuilt_archive_metadata_invalid")
                metadata[member.name] = data
        entries = json.loads(metadata["manifest.json"])
        if not isinstance(entries, list) or not 0 < len(entries) <= 64:
            raise ImageError("prebuilt_archive_metadata_invalid")
        result = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ImageError("prebuilt_archive_metadata_invalid")
            tags = entry.get("RepoTags")
            if tags is None or tags == []:
                continue  # Untagged attestations cannot select an application image.
            if not isinstance(tags, list) or not 0 < len(tags) <= len(TAGS):
                raise ImageError("prebuilt_archive_metadata_invalid")
            config_path = entry.get("Config")
            if not isinstance(config_path, str) or not CONFIG_PATH.fullmatch(config_path):
                raise ImageError("prebuilt_archive_metadata_invalid")
            config_data = metadata[config_path]
            digest = hashlib.sha256(config_data).hexdigest()
            if CONFIG_PATH.fullmatch(config_path).group(1) != digest:
                raise ImageError("prebuilt_archive_config_integrity")
            config = json.loads(config_data)
            rootfs = config.get("rootfs", {}) if isinstance(config, dict) else {}
            if not isinstance(rootfs, dict):
                raise ImageError("prebuilt_archive_platform_invalid")
            layers = rootfs.get("diff_ids")
            if (not isinstance(config, dict) or config.get("os") != "linux"
                    or config.get("architecture") != "amd64" or rootfs.get("type") != "layers"
                    or not isinstance(layers, list) or not 0 < len(layers) <= 256
                    or any(not isinstance(item, str) or not IMAGE_ID.fullmatch(item) for item in layers)):
                raise ImageError("prebuilt_archive_platform_invalid")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ImageError("prebuilt_archive_tags_invalid")
                # Docker stores may export familiar or fully qualified names.
                # Only Docker Hub's canonical spelling of these exact tags is
                # equivalent; another registry or namespace is never accepted.
                familiar = tag.removeprefix("docker.io/library/")
                if familiar not in {item + ":latest" for item in TAGS}:
                    raise ImageError("prebuilt_archive_tags_invalid")
                alias = familiar.removesuffix(":latest")
                if alias in result:
                    raise ImageError("prebuilt_archive_tags_invalid")
                result[alias] = {"config_digest": "sha256:" + digest,
                    "os": config["os"], "architecture": config["architecture"],
                    "rootfs_diff_ids": layers}
        if set(result) != set(TAGS):
            raise ImageError("prebuilt_archive_tags_invalid")
        return result
    except (OSError, tarfile.TarError, ValueError, KeyError, TypeError):
        raise ImageError("prebuilt_archive_metadata_invalid") from None


def save_archive(path, *, export_timeout=600):
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
            if producer.wait(timeout=export_timeout) or compressor.wait(timeout=120):
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
    contents = archive_image_contents(archive)
    images = {tag: {**info, **contents[tag]} for tag, info in images.items()}
    value = validate_manifest({"schema": 2, "release": release, "source_tree": tree,
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
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 128 * 1024:
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
    local_images = verify_images(manifest)
    # The existing database image stays local and untouched; no implicit registry pull.
    try: image_info("postgres:17-bookworm")
    except ImageError:
        raise ImageError("prebuilt_database_image_missing") from None
    write_private(root / "images-validated.json", {"release": release,
        "manifest_sha256": file_hash(root / "images-manifest.json"), "images": local_images})


def verify_images(manifest):
    # Capture local IDs, but do not trust them until canonical content is verified.
    before = {tag: image_info(tag) for tag in TAGS}
    with tempfile.TemporaryDirectory(prefix="narma-image-proof-") as directory:
        archive = Path(directory) / "loaded-images.tar.gz"
        save_archive(archive, export_timeout=180)
        contents = archive_image_contents(archive)
    if any(image_info(tag) != info for tag, info in before.items()):
        raise ImageError("prebuilt_loaded_image_changed")
    if any(contents[tag] != {key: value for key, value in info.items() if key != "id"}
           for tag, info in manifest["images"].items()):
        raise ImageError("prebuilt_loaded_image_mismatch")
    return before


def validate_installed(release):
    root = release_path(release)
    manifest = read_manifest(release)
    try: marker = json.loads((root / "images-validated.json").read_text())
    except (OSError, ValueError):
        raise ImageError("prebuilt_validation_missing") from None
    if (not isinstance(marker, dict) or set(marker) != {"release", "manifest_sha256", "images"}
            or marker["release"] != release
            or marker["manifest_sha256"] != file_hash(root / "images-manifest.json")
            or not isinstance(marker["images"], dict) or set(marker["images"]) != set(TAGS)):
        raise ImageError("prebuilt_validation_mismatch")
    # The root-owned marker pins IDs whose full config/layers were already proved.
    if any(image_info(tag) != info for tag, info in marker["images"].items()):
        raise ImageError("prebuilt_loaded_image_changed")


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
