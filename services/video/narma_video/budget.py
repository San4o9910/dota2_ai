"""Global, durable Gemini allowance. Micro-USD arithmetic; no automatic resets."""
import json
from psycopg.types.json import Jsonb
from .db import database

MODEL = "gemini-3.8-flash"
POLICY = "gemini-3.8-flash-standard-2026-09-07"
RESERVATION = 1_200_000
MAX_ALLOWANCE = 10_000_000


def reserve(connection, job, frames, model, *, replay=False):
    if type(replay) is not bool:
        raise ValueError('VIDEO_BUDGET_CALL_KIND_INVALID')
    return _reserve(connection, job, frames, model, kind='replay' if replay else 'video')


def reserve_hermes(connection, task, model):
    """One durable provider attempt per task, charged to the existing allowance.

    The broker authorizes the short-lived credential before this call. Repeat the
    task and owner checks here so a second caller cannot evade the attempt cap.
    Commit this transaction before starting the provider request.
    """
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (task['owner_id'],))
    active = connection.execute("""SELECT id FROM hermes_tasks WHERE id=%s AND owner_id=%s
        AND state='running' AND lease_token=%s AND lease_until>clock_timestamp() FOR UPDATE""",
        (task['id'], task['owner_id'], task['lease_token'])).fetchone()
    if not active:
        raise ValueError('HERMES_LEASE_EXPIRED')
    calls = connection.execute('SELECT count(*) AS calls FROM video_provider_calls WHERE hermes_task_id=%s',
                               (task['id'],)).fetchone()
    if calls['calls']:
        raise ValueError('HERMES_REQUEST_BUDGET_EXCEEDED')
    call_id = _reserve(connection, task, [{'frame_id': 0}], model, kind='hermes')
    # A contended shared budget row can outlive the task deadline. Raising here
    # rolls back the uncommitted reservation instead of dispatching a stale call.
    valid = connection.execute('SELECT lease_until>clock_timestamp() AS valid FROM hermes_tasks WHERE id=%s',
                               (task['id'],)).fetchone()
    if not valid or not valid['valid']:
        raise ValueError('HERMES_LEASE_EXPIRED')
    return call_id


def _reserve(connection, job, frames, model, *, kind):
    # Serialize the shared per-owner cap for every caller, including replay jobs.
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))',(job['owner_id'],))
    daily=connection.execute("SELECT count(*) AS calls FROM video_provider_calls WHERE owner_id=%s AND created_at>now()-interval '1 day'",(job['owner_id'],)).fetchone()
    if daily['calls'] >= 250:
        raise ValueError('VIDEO_REQUEST_BUDGET_EXCEEDED')
    row = connection.execute("SELECT *,expires_at>now() AND expires_at<='2027-01-01T00:00:00Z'::timestamptz AS price_valid FROM video_ai_budget WHERE id=1 FOR UPDATE").fetchone()
    if not row or not row['enabled']:
        raise ValueError('VIDEO_GLOBAL_BUDGET_DISABLED')
    if model != MODEL or row['model'] != MODEL or row['price_policy'] != POLICY or not row['price_valid']:
        raise ValueError('VIDEO_BUDGET_PRICE_POLICY_EXPIRED')
    if not 0 < row['limit_microusd'] <= MAX_ALLOWANCE:
        raise ValueError('VIDEO_GLOBAL_BUDGET_INVALID')
    if row['spent_microusd'] + row['reserved_microusd'] + RESERVATION > row['limit_microusd']:
        raise ValueError('VIDEO_GLOBAL_BUDGET_EXCEEDED')
    if kind == 'hermes':
        call = connection.execute("""INSERT INTO video_provider_calls
            (hermes_task_id,call_kind,owner_id,first_frame,last_frame,budget_id,model,price_policy,reserved_microusd,billing_status)
            VALUES (%s,'hermes',%s,0,0,1,%s,%s,%s,'reserved') RETURNING id""",
            (job['id'],job['owner_id'],MODEL,POLICY,RESERVATION)).fetchone()
    elif kind == 'replay':
        # Static SQL branch: callers cannot supply a table or column name.
        call = connection.execute("""INSERT INTO video_provider_calls
            (replay_job_id,call_kind,owner_id,first_frame,last_frame,budget_id,model,price_policy,reserved_microusd,billing_status)
            VALUES (%s,'replay',%s,0,0,1,%s,%s,%s,'reserved') RETURNING id""",
            (job['id'],job['owner_id'],MODEL,POLICY,RESERVATION)).fetchone()
    else:
        call = connection.execute("""INSERT INTO video_provider_calls
            (job_id,owner_id,first_frame,last_frame,budget_id,model,price_policy,reserved_microusd,billing_status)
            VALUES (%s,%s,%s,%s,1,%s,%s,%s,'reserved') RETURNING id""",
            (job['id'],job['owner_id'],frames[0]['frame_id'],frames[-1]['frame_id'],MODEL,POLICY,RESERVATION)).fetchone()
    connection.execute("UPDATE video_ai_budget SET reserved_microusd=reserved_microusd+%s,updated_at=now() WHERE id=1",(RESERVATION,))
    return call['id']


def normalize_usage(usage):
    if usage is None:
        return None, None
    fields = ('total_input_tokens','total_output_tokens','total_thought_tokens','total_tokens',
              'total_cached_tokens','total_tool_use_tokens')
    raw = usage if isinstance(usage,dict) else usage.model_dump(mode='json',exclude_none=True)
    details = ('cached_tokens_by_modality','input_tokens_by_modality','output_tokens_by_modality',
               'tool_use_tokens_by_modality','grounding_tool_count')
    if set(raw)-set(fields)-set(details):
        raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
    for name in details:
        items=raw.get(name) or []
        if not isinstance(items,list) or len(items)>16:
            raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
        for item in items:
            count_key='count' if name=='grounding_tool_count' else 'tokens'
            if not isinstance(item,dict) or type(item.get(count_key)) is not int or not 0<=item[count_key]<=2_000_000:
                raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
            if name in ('grounding_tool_count','tool_use_tokens_by_modality'):
                if item[count_key]:
                    raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
            elif item.get('modality') not in ('text','image') or (name=='output_tokens_by_modality' and item.get('modality')!='text'):
                raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
    values = {}
    for field in fields:
        value = raw.get(field)
        if value is not None:
            if type(value) is not int or not 0 <= value <= 2_000_000:
                raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
            values[field] = value
    required = fields[:4]
    if any(field not in values for field in required):
        raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
    inp,out,thought,total = (values[field] for field in required)
    if total != inp+out+thought or values.get('total_cached_tokens',0)>inp or values.get('total_tool_use_tokens',0):
        raise ValueError('VIDEO_BUDGET_USAGE_INVALID')
    # Charge all input at the full rate, including any implicitly cached tokens.
    cost = (3*inp + 15*(out+thought) + 3)//4
    if inp>1_048_576 or out>4096 or thought>65_536:
        values['bounds_exceeded'] = True
    values['provider_usage']=raw
    return values, cost


def settle(call_id, usage):
    """Commit accounting even after invalid model output, cancellation or lease loss."""
    invalid = False
    try:
        values, cost = normalize_usage(usage)
    except (ValueError,TypeError,AttributeError):
        values,cost,invalid = None,None,True
    frozen = False
    with database() as connection:
        budget = connection.execute('SELECT * FROM video_ai_budget WHERE id=1 FOR UPDATE').fetchone()
        call = connection.execute('SELECT * FROM video_provider_calls WHERE id=%s FOR UPDATE',(call_id,)).fetchone()
        if not budget or not call or call['budget_id'] != 1:
            raise ValueError('VIDEO_BUDGET_ACCOUNTING_FAILED')
        if call['billing_status'] in ('settled','breach','unknown'):
            return  # Settlement is idempotent; uncertain attempts stay reserved.
        if cost is None:
            try:
                raw=usage if isinstance(usage,dict) else usage.model_dump(mode='json',exclude_none=True) if usage is not None else None
                encoded=json.dumps(raw)
                raw=raw if len(encoded)<=16384 else {'invalid_usage':'oversized'}
            except (TypeError,ValueError,AttributeError):
                raw={'invalid_usage':'unserializable'}
            connection.execute("UPDATE video_provider_calls SET billing_status='unknown',usage=%s,finished_at=now() WHERE id=%s",(Jsonb(raw),call_id))
            if invalid:
                connection.execute("UPDATE video_ai_budget SET enabled=false,frozen_reason='INVALID_PROVIDER_USAGE',updated_at=now() WHERE id=1")
                frozen = True
        else:
            frozen = cost>call['reserved_microusd'] or bool(values.get('bounds_exceeded'))
            connection.execute("""UPDATE video_ai_budget SET reserved_microusd=reserved_microusd-%s,
                spent_microusd=spent_microusd+%s,enabled=enabled AND NOT %s,
                frozen_reason=CASE WHEN %s THEN 'PROVIDER_PRICE_BOUND_EXCEEDED' ELSE frozen_reason END,updated_at=now() WHERE id=1""",
                (call['reserved_microusd'],cost,frozen,frozen))
            connection.execute("""UPDATE video_provider_calls SET charged_microusd=%s,usage=%s,billing_status=%s,
                finished_at=now() WHERE id=%s""",(cost,Jsonb(values),'breach' if frozen else 'settled',call_id))
    print(json.dumps({'event':'video_provider_accounting','call_id':call_id,
        'charged_microusd':cost,'reservation_retained':cost is None,'budget_frozen':frozen}),flush=True)
    if frozen:
        # Raise after the transaction commits, preserving the frozen state.
        raise ValueError('VIDEO_BUDGET_RECONCILIATION_REQUIRED')


def status(connection=None):
    if connection is None:
        with database() as connection:
            return status(connection)
    row = connection.execute("SELECT *,expires_at>now() AND expires_at<='2027-01-01T00:00:00Z'::timestamptz AS price_valid FROM video_ai_budget WHERE id=1").fetchone()
    if not row:
        return {'enabled':False,'reason':'not_configured'}
    valid = row['enabled'] and row['price_valid'] and row['model']==MODEL and row['price_policy']==POLICY and 0<row['limit_microusd']<=MAX_ALLOWANCE
    return {'enabled':valid, 'model':row['model'],
        'limit_microusd':row['limit_microusd'],'spent_microusd':row['spent_microusd'],
        'reserved_microusd':row['reserved_microusd'],
        'available_microusd':max(0,row['limit_microusd']-row['spent_microusd']-row['reserved_microusd']),
        'accounting_rub_per_usd':row['accounting_rub_per_usd'],'frozen_reason':row['frozen_reason']}


if __name__ == '__main__':
    print(json.dumps({'event':'video_budget_status',**status()}))
