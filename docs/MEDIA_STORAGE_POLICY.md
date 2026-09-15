# Media storage on the standalone Timeweb service

The PostgreSQL backup includes completed reports, account data and job metadata.
It does **not** include `.dem` or video source files on the VPS. Users must keep
their own source copies. These files are working inputs, not a backed-up archive.
The application discloses this beside upload controls and returns
`storage_policy` in the authenticated replay/video list API.

Sources are removed only by an explicit owner action (or a retry of that same
requested deletion). There is no new age-based cleanup or deletion on quota
exhaustion. For ready replay reports, “remove source” frees the input while
preserving the report and training history. Deleting an entire analysis removes
its report as well. Video deletion currently removes its analysis too.

## Limits and admission

| Scope | Limit |
| --- | --- |
| Video source | 2 GiB per file, 8 GiB per owner, 4 new jobs per 24 hours |
| Replay source | 512 MiB per file, 2 GiB per owner, 4 GiB across replay jobs |
| Replay queue | 8 new jobs per 24 hours, 2 active jobs per owner |
| All media | 16 GiB reserved source bytes across videos, replays and temporary profile uploads |
| Physical disk | 2 GiB free headroom, plus unwritten upload bytes, assembly copies and one retry chunk |

The existing PostgreSQL job records are durable source reservations. Their
declared size continues to count after failure or logical deletion until
`storage_deleted_at` confirms that physical removal succeeded. Already uploaded
files and existing reports are not changed during deployment. If retained data
already exceeds a new global limit, new admission stops; existing valid uploads
can continue if physical disk headroom permits.

A shared transaction advisory lock serializes admission, chunk writes and source
assembly across every account and media type. Callers acquire it before owner
and job locks. It protects aggregate checks across multiple API processes, rather
than depending on a process-local mutex. Temporary profile uploads share the
same quota and disk gate; their full reservation is conservatively held until
the temporary file is removed.

Chunk sizes must match the declared file size. Accepted chunk content is
immutable across retries. Assembly verifies each part's size and SHA-256, then
flushes the source before queueing it. Both APIs recheck free space on writes and
completion, accounting for all pending uploads and the extra source-sized
assembly copy. Disk exhaustion after a check returns HTTP 507 and leaves the job
uncompleted, so the owner can retry without accepting a truncated source.

The source quota does not count PostgreSQL, container images, logs or temporary
worker output as retained source bytes. Their consumption is covered by the
physical disk check and operational disk monitoring. Quota increases require
checking those other consumers and capacity first; there is no client-supplied
quota override.

## Validation

`services/video/tests/test_media_storage.py` covers mixed-media concurrent
admission, conflicts between repeated chunk writes, existing-file reservations,
profile reservations, disk exhaustion at admission/write/assembly, simulated
ENOSPC after a successful space check, and corrupt/oversized source parts.
Its database tests require an explicit isolated `TEST_DATABASE_URL` and must run
in native CI before release. They do not use a live application database, paid
models or real player data.
