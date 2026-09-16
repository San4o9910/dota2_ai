"""Reclaim only proved retired NARMA images, never containers or data volumes.

An image must have a matching release manifest and local validation receipt,
be absent from protected releases/checkpoints and every container, and have no
tags or registry digest. Docker removal is by exact ID, without force or parent
pruning. Unknown state disables cleanup; it never widens the candidate set.
"""
import json
import os
import stat
import time

import prebuilt_images as images

MAX_IMAGES = 24
MAX_CONTAINERS = 256
MAX_SECONDS = 90


def validated_images(release):
    directory = os.open(images.release_path(release), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        manifest, digest, identity = images._read_cache_metadata(directory, "images-manifest.json")
        images.validate_manifest(manifest, release)
        marker, marker_digest, marker_identity = images._read_cache_metadata(directory, "images-validated.json")
        if (not isinstance(marker, dict) or set(marker) != {"release", "manifest_sha256", "images"}
                or marker["release"] != release or marker["manifest_sha256"] != digest
                or not isinstance(marker["images"], dict) or set(marker["images"]) != set(images.TAGS)):
            raise ValueError("unknown image provenance")
        identifiers = set()
        for value in marker["images"].values():
            if (not isinstance(value, dict) or set(value) != {"id", "os", "architecture"}
                    or not isinstance(value["id"], str) or not images.IMAGE_ID.fullmatch(value["id"])
                    or value["os"] != "linux" or value["architecture"] != "amd64"):
                raise ValueError("unknown image provenance")
            identifiers.add(value["id"])
        return identifiers, (digest, marker_digest, identity, marker_identity)
    finally:
        os.close(directory)


def protected_state(incoming):
    releases, checkpoint_digest = images._protected_cache_releases(incoming)
    protected = set()
    evidence = []
    for release in sorted(releases - {incoming}):
        identifiers, receipt = validated_images(release)
        protected.update(identifiers)
        evidence.append((release, receipt))
    # Preserve IDs required by the active rollback, even when those images are
    # older than the validation receipt or have no currently attached container.
    descriptor = os.open(images.CHECKS_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        current = images.CURRENT_RELEASE.resolve(strict=True).name
        saved, digest, _ = images._read_cache_metadata(descriptor, "images-before-" + current + ".json")
        if digest != checkpoint_digest:
            raise ValueError("changed rollback checkpoint")
        protected.update(saved["images"].values())
        if saved["api"] is not None:
            api = saved["api"]
            if not isinstance(api, dict) or not isinstance(api.get("image"), str) or not images.IMAGE_ID.fullmatch(api["image"]):
                raise ValueError("unknown rollback API image")
            protected.add(api["image"])
    finally:
        os.close(descriptor)
    # A retried incoming release can already have validated images on disk.
    marker = images.release_path(incoming) / "images-validated.json"
    if marker.exists() or marker.is_symlink():
        # Its manifest may just have been replaced for a same-SHA retry.
        # The old receipt may only add protection, never authorize deletion.
        directory = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            saved, digest, identity = images._read_cache_metadata(directory, marker.name)
            if (not isinstance(saved, dict) or saved.get("release") != incoming
                    or not isinstance(saved.get("images"), dict) or set(saved["images"]) != set(images.TAGS)):
                raise ValueError("unknown incoming images")
            for value in saved["images"].values():
                if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not images.IMAGE_ID.fullmatch(value["id"]):
                    raise ValueError("unknown incoming images")
                protected.add(value["id"])
            evidence.append((incoming, (digest, identity)))
        finally:
            os.close(directory)
    return releases, protected, (checkpoint_digest, tuple(evidence))


def container_images():
    raw = images.run(["docker", "container", "ls", "--all", "--quiet", "--no-trunc"], timeout=10)
    identifiers = raw.decode().splitlines()
    if (len(identifiers) > MAX_CONTAINERS
            or any(not images.DIGEST.fullmatch(identifier) for identifier in identifiers)):
        raise ValueError("unknown container inventory")
    if not identifiers:
        return set()
    raw = images.run(["docker", "container", "inspect", "--format", "{{.Image}}", *identifiers], timeout=10)
    values = raw.decode().splitlines()
    if len(values) != len(identifiers) or any(not images.IMAGE_ID.fullmatch(value) for value in values):
        raise ValueError("unknown container images")
    return set(values)


def removable_image(identifier):
    template = '{"id":{{json .Id}},"tags":{{json .RepoTags}},"digests":{{json .RepoDigests}},"os":{{json .Os}},"architecture":{{json .Architecture}}}'
    value = json.loads(images.run(["docker", "image", "inspect", "--format", template, identifier], timeout=10))
    return (isinstance(value, dict) and set(value) == {"id", "tags", "digests", "os", "architecture"}
        and value["id"] == identifier and value["tags"] in (None, []) and value["digests"] in (None, [])
        and value["os"] == "linux" and value["architecture"] == "amd64")


def reclaim_retired_images(incoming, required_bytes):
    result = {"removed_images": 0, "examined_images": 0, "cleanup_status": "not_needed"}
    started = time.monotonic()
    try:
        initial = protected_state(incoming)
        releases, protected, _ = initial
        root = images.RELEASES_ROOT
        device = root.stat().st_dev
        candidates = []
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= images.MAX_RETENTION_ENTRIES:
                    raise ValueError("unbounded release inventory")
                if images.SHA.fullmatch(entry.name) and entry.name not in releases:
                    value = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(value.st_mode) and value.st_dev == device:
                        candidates.append((value.st_mtime_ns, entry.name))
        seen = set()
        for _, release in sorted(candidates):
            try:
                identifiers, receipt = validated_images(release)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                continue
            for identifier in sorted(identifiers - protected - seen):
                if images.shutil.disk_usage(root).free >= required_bytes:
                    return result
                if len(seen) >= MAX_IMAGES or time.monotonic() - started > MAX_SECONDS:
                    result["cleanup_status"] = "bounded"
                    return result
                seen.add(identifier)
                result["examined_images"] += 1
                # Recheck the live/rollback identity and provenance before each
                # deletion; a changed deployment cancels this maintenance pass.
                if protected_state(incoming) != initial or validated_images(release)[1] != receipt:
                    raise ValueError("changed release evidence")
                if identifier in container_images():
                    continue
                try:
                    if not removable_image(identifier):
                        continue
                    images.run(["docker", "image", "rm", "--no-prune", identifier], timeout=15)
                    result["removed_images"] += 1
                    result["cleanup_status"] = "completed"
                except (images.ImageError, ValueError, TypeError):
                    # Missing images or a Docker conflict leave other objects
                    # intact. A concurrent container reference is never forced.
                    continue
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        result["cleanup_status"] = "unavailable"
    return result
