"""Owner-only service quality and metered provider cost; no provider calls."""
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .db import database
from .portal_access import Reauthenticate, reauthenticated
from .web import account_required, csrf, json_body, rate_limit, reject


LEDGER = '''SELECT owner_id,kind,charged_microusd,
    CASE WHEN billing_status IN ('reserved','unknown') THEN reserved_microusd ELSE 0 END AS held_microusd,
    billing_status,created_at FROM openai_api_calls
    UNION ALL SELECT owner_id,call_kind AS kind,charged_microusd,
    CASE WHEN billing_status IN ('reserved','unknown') THEN reserved_microusd ELSE 0 END AS held_microusd,
    billing_status,created_at FROM video_provider_calls'''


def enforce_limit(connection, owner_id, reservation):
    # Both providers already serialize reservations under this owner lock.
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (owner_id,))
    cap = connection.execute('SELECT limit_microusd FROM owner_ai_limits WHERE owner_id=%s', (owner_id,)).fetchone()
    if cap and cap['limit_microusd'] is not None:
        usage = connection.execute('SELECT coalesce(sum(coalesce(charged_microusd,0)+held_microusd),0) AS total FROM (' + LEDGER + ') calls WHERE owner_id=%s', (owner_id,)).fetchone()['total']
        if usage + reservation > cap['limit_microusd']:
            raise ValueError('OWNER_AI_LIMIT')


def require_owner(connection, owner_id):
    if not connection.execute('SELECT 1 FROM portal_accounts WHERE owner_id=%s AND is_platform_owner', (owner_id,)).fetchone():
        reject(403, 'PORTAL_OWNER_REQUIRED', 'Этот раздел доступен владельцу платформы.')


def dashboard(owner_id):
    with database() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        require_owner(connection, owner_id)
        users = connection.execute('''WITH costs AS (SELECT owner_id,
            coalesce(sum(charged_microusd),0) AS spent_microusd,
            coalesce(sum(held_microusd),0) AS held_microusd,
            count(*) FILTER(WHERE billing_status='unknown') AS unknown_calls FROM (''' + LEDGER + ''') ledger GROUP BY owner_id)
            SELECT a.owner_id,a.email,coalesce(c.spent_microusd,0) AS spent_microusd,
            coalesce(c.held_microusd,0) AS held_microusd,coalesce(c.unknown_calls,0) AS unknown_calls,
            l.limit_microusd FROM portal_accounts a LEFT JOIN costs c USING(owner_id)
            LEFT JOIN owner_ai_limits l USING(owner_id) ORDER BY a.email''').fetchall()
        costs = connection.execute('''SELECT kind,count(*) AS calls,coalesce(sum(charged_microusd),0) AS spent_microusd,
            coalesce(sum(held_microusd),0) AS held_microusd,
            count(*) FILTER(WHERE billing_status='unknown') AS unknown_calls
            FROM (''' + LEDGER + ''') ledger GROUP BY kind ORDER BY kind''').fetchall()
        jobs = connection.execute('''SELECT kind,count(*) FILTER(WHERE state='ready') AS ready,
            count(*) FILTER(WHERE state='failed') AS failed,count(*) FILTER(WHERE state='queued') AS queued,
            count(*) FILTER(WHERE state='processing') AS processing,
            avg(extract(epoch FROM updated_at-created_at)) FILTER(WHERE state='ready') AS mean_completion_seconds
            FROM (SELECT 'replay' AS kind,state,created_at,updated_at FROM replay_jobs
                  UNION ALL SELECT 'video',state,created_at,updated_at FROM video_jobs) jobs
            WHERE created_at>now()-interval '7 days' GROUP BY kind''').fetchall()
        feedback = connection.execute('''SELECT f.id,f.reason,f.comment,f.point_index,f.created_at,a.email
            FROM coaching_feedback f JOIN portal_accounts a USING(owner_id)
            JOIN replay_jobs r ON r.id=f.job_id AND r.owner_id=f.owner_id
            WHERE r.state<>'deleted' ORDER BY f.created_at DESC LIMIT 50''').fetchall()
        global_budget = connection.execute('SELECT enabled,limit_microusd,spent_microusd,reserved_microusd,expires_at FROM openai_api_budget WHERE id=1').fetchone()
    return {'users': users, 'costs': costs, 'jobs': jobs, 'feedback': feedback, 'openai_budget': global_budget,
        'cost_note': 'Учёт приложения по ответам провайдеров. Расходы на сервер и комиссии не включены. Неизвестная стоимость остаётся в резерве.',
        'window_note': 'Задания за 7 дней; расходы и лимиты накопительные. Время до готовности включает загрузку и ожидание.'}


class SetLimit(Reauthenticate):
    limit_microusd: int | None = Field(ge=0, le=1_000_000_000, strict=True)


def set_limit(request, account, target, body):
    rate_limit(request, 'invite', account['email'])
    with database() as connection:
        require_owner(connection, account['owner_id'])
        reauthenticated(connection, request, account, body.current_password, owner_only=True)
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))', (target,))
        if not connection.execute('SELECT 1 FROM portal_accounts WHERE owner_id=%s', (target,)).fetchone():
            reject(404, 'OWNER_USER', 'Аккаунт не найден.')
        connection.execute('''INSERT INTO owner_ai_limits(owner_id,limit_microusd) VALUES (%s,%s)
            ON CONFLICT(owner_id) DO UPDATE SET limit_microusd=excluded.limit_microusd,updated_at=now()''', (target, body.limit_microusd))
    return {'saved': True}


def attach_owner_dashboard(app):
    router = APIRouter(prefix='/api/owner')

    @router.get('/dashboard')
    def get_dashboard(account=Depends(account_required)):
        return dashboard(account['owner_id'])

    @router.put('/users/{target}/ai-limit')
    async def put_limit(target: str, request: Request, account=Depends(account_required)):
        csrf(request)
        body = await json_body(request, SetLimit)
        return await run_in_threadpool(set_limit, request, account, target, body)

    app.include_router(router)
