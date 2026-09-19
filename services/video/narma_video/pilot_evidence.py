"""Read-only, aggregate pilot evidence. Never returns identities or model text.

Run inside the API container with ``python -m narma_video.pilot_evidence``.
The terminal job timestamp is mutable in the current schema: its duration is
explicitly a proxy, never parser runtime or an immutable end-to-end SLA.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import re

from .db import database


LEDGER = """
    SELECT 'openai' AS provider,kind,id::text AS call_id,
        coalesce(job_id,video_job_id,task_id) AS source_id,owner_id,source_sha256,
        state,billing_status,charged_microusd,reserved_microusd,created_at,
        started_at,finished_at,error_code
    FROM openai_api_calls
    UNION ALL
    SELECT 'gemini',call_kind,id::text,coalesce(replay_job_id,job_id),owner_id,NULL,
        NULL,billing_status,charged_microusd,reserved_microusd,created_at,
        NULL,finished_at,NULL
    FROM video_provider_calls
"""
JOBS = """
    SELECT 'replay' AS kind,id,owner_id,source_sha256,state,failure_code,
        created_at,updated_at,result_payload->'coaching' AS coaching
    FROM replay_jobs
    UNION ALL
    SELECT 'video',id,owner_id,source_sha256,state,failure_code,created_at,
        updated_at,video_coaching FROM video_jobs
"""


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat().replace('+00:00', 'Z')
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _code(value):
    # Only bounded application codes; no arbitrary provider body/free text.
    return value if isinstance(value, str) and re.fullmatch(
        r'(?:REPLAY|OPENAI|VIDEO|GEMINI|HERMES)_[A-Z0-9_]{1,60}', value) else 'OTHER'


def collect(connection, *, since: datetime, until: datetime):
    """Collect in an already-open transaction. The transaction becomes read-only.

    No migration/configuration/settlement/retry is performed. Cohort costs use
    *all* calls for jobs created in [since, until), including later settlement.
    Calls are grouped before joining jobs: multiple Gemini stages cannot
    multiply the single OpenAI coaching charge.
    """
    if (since.tzinfo is None or until.tzinfo is None or since >= until
            or until - since > timedelta(days=366)):
        raise ValueError('PILOT_EVIDENCE_WINDOW_INVALID')
    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    connection.execute("SET LOCAL statement_timeout='15s'")
    snapshot = connection.execute('SELECT transaction_timestamp() AS at').fetchone()['at']
    states = connection.execute(f"""WITH jobs AS ({JOBS})
        SELECT kind,state,count(*) AS jobs FROM jobs
        WHERE created_at>=%s AND created_at<%s GROUP BY kind,state ORDER BY kind,state
        """, (since, until)).fetchall()
    reports = connection.execute(f"""WITH jobs AS ({JOBS}), ledger AS ({LEDGER})
        SELECT j.kind,count(*) AS ready_reports,
            count(*) FILTER (WHERE coaching->>'status'='ready') AS coaching_ready_reports,
            count(*) FILTER (WHERE coaching->>'status'='unavailable') AS coaching_unavailable_reports,
            count(*) FILTER (WHERE coaching->>'status'='ready'
                AND coaching->>'provider'='openai' AND coaching->>'usage_kind'='openai_api' AND EXISTS (
                SELECT 1 FROM ledger c WHERE c.provider='openai' AND c.kind=j.kind
                    AND c.source_id=j.id AND c.owner_id=j.owner_id
                    AND c.source_sha256=j.source_sha256
                    AND c.call_id=coaching->>'call_id'
                    AND c.state='succeeded' AND c.billing_status='settled'
                    AND c.charged_microusd IS NOT NULL)) AS ready_with_confirmed_openai_call
        FROM jobs j WHERE j.created_at>=%s AND j.created_at<%s AND j.state='ready'
        GROUP BY j.kind ORDER BY j.kind""", (since, until)).fetchall()
    timings = connection.execute(f"""WITH jobs AS ({JOBS})
        SELECT kind,count(*) AS samples,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM updated_at-created_at)) AS p50_seconds,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM updated_at-created_at)) AS p95_seconds
        FROM jobs WHERE created_at>=%s AND created_at<%s AND state='ready'
            AND updated_at>=created_at GROUP BY kind ORDER BY kind""", (since, until)).fetchall()
    calls = connection.execute(f"""WITH ledger AS ({LEDGER})
        SELECT provider,kind,state,billing_status,count(*) AS calls,
            count(charged_microusd) AS calls_with_recorded_charge,
            coalesce(sum(charged_microusd),0) AS recorded_charge_microusd,
            coalesce(sum(reserved_microusd) FILTER (WHERE billing_status IN ('reserved','unknown')),0)
                AS retained_reservation_microusd,
            count(*) FILTER (WHERE billing_status='unknown') AS unknown_calls,
            count(*) FILTER (WHERE started_at IS NOT NULL AND finished_at>=started_at) AS timed_calls,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at-started_at))
                FILTER (WHERE started_at IS NOT NULL AND finished_at>=started_at) AS p50_call_seconds,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at-started_at))
                FILTER (WHERE started_at IS NOT NULL AND finished_at>=started_at) AS p95_call_seconds
        FROM ledger WHERE created_at>=%s AND created_at<%s
        GROUP BY provider,kind,state,billing_status ORDER BY provider,kind,state,billing_status
        """, (since, until)).fetchall()
    costs = connection.execute(f"""WITH jobs AS ({JOBS}), ledger AS ({LEDGER}),
        per_source AS (
            SELECT kind,source_id,owner_id,count(*) AS calls,
                count(charged_microusd) AS charged_calls,
                coalesce(sum(charged_microusd),0) AS recorded,
                coalesce(sum(reserved_microusd) FILTER (WHERE billing_status IN ('reserved','unknown')),0) AS held
            FROM ledger WHERE kind IN ('replay','video') GROUP BY kind,source_id,owner_id
        )
        SELECT j.kind,count(*) AS jobs,
            count(*) FILTER (WHERE c.calls IS NULL) AS jobs_without_provider_calls,
            count(*) FILTER (WHERE c.calls>c.charged_calls) AS jobs_with_unresolved_cost,
            coalesce(sum(c.recorded),0) AS recorded_charge_microusd,
            coalesce(sum(c.held),0) AS retained_reservation_microusd,
            count(*) FILTER (WHERE j.state='ready' AND c.calls=c.charged_calls) AS ready_fully_priced_jobs,
            avg(c.recorded) FILTER (WHERE j.state='ready' AND c.calls=c.charged_calls) AS ready_mean_recorded_microusd,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY c.recorded)
                FILTER (WHERE j.state='ready' AND c.calls=c.charged_calls) AS ready_p50_recorded_microusd,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY c.recorded)
                FILTER (WHERE j.state='ready' AND c.calls=c.charged_calls) AS ready_p95_recorded_microusd
        FROM jobs j LEFT JOIN per_source c ON c.kind=j.kind AND c.source_id=j.id AND c.owner_id=j.owner_id
        WHERE j.created_at>=%s AND j.created_at<%s GROUP BY j.kind ORDER BY j.kind
        """, (since, until)).fetchall()
    failures = connection.execute(f"""WITH jobs AS ({JOBS}), ledger AS ({LEDGER})
        SELECT source,code,count(*) AS occurrences FROM (
            SELECT 'job' AS source,failure_code AS code FROM jobs
                WHERE created_at>=%s AND created_at<%s AND failure_code IS NOT NULL
            UNION ALL SELECT 'coaching',coaching->>'failure_code' FROM jobs
                WHERE created_at>=%s AND created_at<%s AND coaching->>'failure_code' IS NOT NULL
            UNION ALL SELECT 'openai_call',error_code FROM ledger
                WHERE created_at>=%s AND created_at<%s AND error_code IS NOT NULL
        ) errors GROUP BY source,code ORDER BY occurrences DESC,source LIMIT 30
        """, (since, until, since, until, since, until)).fetchall()
    for row in failures:
        row['code'] = _code(row['code'])
    budgets = []
    for provider, table, calls_table in (
            ('openai', 'openai_api_budget', 'openai_api_calls'),
            ('gemini', 'video_ai_budget', 'video_provider_calls')):
        row = connection.execute(f"""SELECT enabled,expires_at,expires_at>now() AS unexpired,
            limit_microusd,spent_microusd,reserved_microusd,frozen_reason,
            greatest(0,limit_microusd-spent_microusd-reserved_microusd) AS remaining_ceiling_microusd,
            (SELECT coalesce(sum(charged_microusd),0) FROM {calls_table}) AS ledger_recorded_microusd,
            (SELECT coalesce(sum(reserved_microusd),0) FROM {calls_table}
                WHERE billing_status IN ('reserved','unknown')) AS ledger_held_microusd
            FROM {table} WHERE id=1""").fetchone()
        if row:
            # A delta can be a documented historical adjustment, not necessarily corruption.
            row['spend_minus_call_ledger_microusd'] = row['spent_microusd'] - row['ledger_recorded_microusd']
            row['reserve_minus_call_ledger_microusd'] = row['reserved_microusd'] - row['ledger_held_microusd']
            row['frozen'] = bool(row.pop('frozen_reason'))
            budgets.append({'provider': provider, **row})
    integrity = connection.execute(f"""WITH jobs AS ({JOBS}), ledger AS ({LEDGER})
        SELECT count(*) FILTER (WHERE j.id IS NULL) AS calls_without_owned_job,
            count(*) FILTER (WHERE j.id IS NOT NULL AND c.provider='openai'
                AND c.source_sha256 IS DISTINCT FROM j.source_sha256) AS openai_source_mismatches
        FROM ledger c LEFT JOIN jobs j ON c.kind=j.kind AND c.source_id=j.id AND c.owner_id=j.owner_id
        WHERE c.kind IN ('replay','video') AND c.created_at>=%s AND c.created_at<%s
        """, (since, until)).fetchone()
    return _jsonable({
        'schema_version': 1, 'snapshot_at': snapshot,
        'window': {'since_inclusive': since, 'until_exclusive': until},
        'scope': 'aggregate_recorded_database_evidence_no_quality_certification',
        'jobs_by_state': states, 'ready_reports': reports,
        'ready_upload_to_last_update_proxy': timings,
        'calls_created_in_window': calls, 'job_cohort_recorded_costs': costs,
        'failures': failures, 'current_cumulative_budgets': budgets,
        'ledger_link_integrity': integrity,
        'limitations': [
            'Ready parsing alone does not confirm a usable OpenAI coaching response.',
            'Ready coaching must name OpenAI API and its exact succeeded settled owner/source-bound call for confirmation.',
            'Legacy or carried-forward text without explicit provider and call identity is excluded from confirmed OpenAI reports.',
            'Job timing includes upload, queue and later updates; immutable processing timings are unavailable.',
            'Per-job costs sum stored Gemini and OpenAI charges; calls without charges retain unknown cost.',
            'No-provider jobs are excluded from paid unit-cost averages; Hermes overhead is reported separately in calls.',
            'Recorded ledger charges may use conservative pricing and are not reconciled provider invoices.',
            'Deleted reports and historical refreshes are not a complete event history.',
            'No gameplay quality, server throughput or future capacity is inferred from these aggregates.',
        ],
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=7, choices=range(1, 367), metavar='1..366')
    args = parser.parse_args()
    until = datetime.now(timezone.utc)
    with database() as connection:
        result = collect(connection, since=until-timedelta(days=args.days), until=until)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
