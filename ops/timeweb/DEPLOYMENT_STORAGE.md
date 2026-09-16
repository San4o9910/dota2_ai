# Deployment storage recovery

The 2026-09-15 deployment failed before transfer with 1,610,260,480 bytes
free. The preceding attempt admitted a 599 MB compressed bundle with only
4,962,369,536 bytes free, then failed the 2 GiB activation headroom gate after
Docker import. Services were restored. The generic transfer error obscured
the later `prebuilt_storage_insufficient` error.

New bundles use schema 3 and record the installed sizes of distinct Docker
images. Admission reserves twice the compressed archive size, twice the
installed image size, and 4 GiB of operating headroom. This covers transport,
verification export, import staging and extracted layers conservatively;
shared layers are not discounted. Schema 2 receipts remain readable for
rollback and retention, but cannot admit a new transfer.

When archive retention is insufficient, the receiver can remove up to 24
retired image IDs, using `docker image rm --no-prune` without force. Each
candidate needs a matching release manifest and validated local image receipt.
Current, previous, incoming and checkpoint rollback images are protected.
Every container, including stopped containers, protects its image. Any tag,
registry digest, missing provenance or changed protected state prevents removal.
Volumes, containers, application data, unrelated images and Docker build caches
are never cleaned by this operation. Actual free space is rechecked before
accepting the archive; insufficient space stops deployment before service changes.

GitHub logs show bounded aggregate `prebuilt_image_retention` and
`prebuilt_storage_check` receipts, and preserve the receiver's sanitized error
code. Raw host command output and application configuration remain private.

After merging this fix, start a **new Run workflow** for **Timeweb pilot** on
`codex/openai-video-coach`, using the existing deployment settings. Re-running
an older failed run still uses that run's old commit. Successful CI validates
the change but does not prove the production host has enough reclaimable space.
If the new run still reports insufficient storage or unavailable cleanup,
inspect host disk usage and provenance before deciding on further cleanup or
capacity changes. Do not bypass the headroom gate or run a broad Docker prune.

Validation: offline tests cover provenance, symlinks/hardlinks, rollback,
container/tag protection, concurrent state changes, bounded work and receiver
admission. CI additionally exercises removal against real Docker with only
synthetic scratch images and an unstarted container, without pulling images.
