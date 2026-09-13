# Deployment archive retention

## Observed failure

[Deployment 68](https://github.com/San4o9910/dota2_ai/actions/runs/34783609135)
targeted release `ebbd34dc3707206607b045ce0358665fc44d6700` and stopped with
`prebuilt_storage_insufficient` before receiving its image archive. The archive
was 598,969,749 bytes; receiving it requires that size plus the existing 4 GiB
headroom. The workflow restored provider settings before bootstrap. It did not
switch the running containers to the new release.

The previous implementation retained `images.tar.gz` in every release directory
indefinitely. This is a confirmed accumulation bug, but the failed run did not
measure individual disk categories. Its log does not establish how much of the
host disk is occupied by these archives or whether reclaiming them alone will
be sufficient. Repeating the same failed SHA does not apply this fix.

## Retention contract

Before receiving an archive, the installer inspects its own release archive
cache. It preserves the incoming release, the currently selected release and
the latter's recorded rollback predecessor. If those protections cannot be
established, reclamation is unavailable and no archive is deleted.

Only an obsolete regular `images.tar.gz` is eligible. Its release directory,
manifest and validation marker must be safe to inspect without following links.
The strict manifest and validation marker must agree; the archive's actual size
and SHA-256 must match the manifest. Invalid, unvalidated, linked and unrelated
files are skipped. Scanning, hashing and deletion are bounded per deployment.
The same retention step on subsequent deployments prevents unlimited growth of
this verified transport cache.

Release source files, rollback checkpoints, Docker images and containers,
database volumes, credentials, replay/video media and monetary ledgers are
outside this cleanup. Rollback still selects the previously pinned local image
IDs; it does not need the obsolete transport archives. There is no Docker prune,
server resize, storage purchase or paid model request.

After reclamation, the installer rechecks the original requirement: incoming
compressed archive size plus 4 GiB of free disk. If the requirement is unmet,
the transfer still stops before reading the input stream or switching services.

## Evidence and next deployment

The `prebuilt_storage_check` log event exposes only aggregate byte counts:
required capacity, free capacity before/after, authenticated eligible archive
bytes/count, reclaimed bytes/count, cleanup status and the final capacity result.
The SSH transfer forwards this strict allowlist even when receiving fails;
arbitrary stdout, stderr, paths and file contents remain private.

After merging the fix into `codex/openai-video-coach`, start a **new**
`timeweb-pilot.yml` run from that branch. Keep provider activation checkboxes off
and leave the explicit allowance blank to preserve existing AI configuration.
Inspect `prebuilt_storage_check` and the subsequent release/readiness checks.
Only a successful deployment verifying `/coach` and its JavaScript establishes
that the personal coach update is installed. Offline retention tests establish
the cleanup boundaries, not the amount of reclaimable space on the live host.
