"""One owned practice and an honest next step, using the existing learning contract."""
from uuid import UUID
from fastapi import APIRouter, Depends
from . import learning
from .db import database
from .growth import assess
from .web import account_required, csrf, reject


def remember(connection, owner_id, plan_id):
    connection.execute('''INSERT INTO player_program_focus(owner_id,plan_id) VALUES (%s,%s)
        ON CONFLICT(owner_id) DO UPDATE SET plan_id=excluded.plan_id,updated_at=now()''', (owner_id, plan_id))


def select(owner_id, plan_id):
    with database() as connection:
        profile, history = learning._context(connection, owner_id, write=True)
        plan = next((p for p in learning._plans(connection, owner_id, profile, history)
                     if str(p['id']) == str(plan_id)), None)
        if not plan:
            reject(404, 'PROGRAM_PLAN', 'Задание не найдено.')
        if plan['status'] != 'active' or plan['validity'] != 'current':
            reject(409, 'PROGRAM_STALE', 'Выбери актуальное активное задание.')
        learning._lock_plan_source(connection, owner_id, profile, plan)
        remember(connection, owner_id, plan_id)
    return {'saved': True}


def program(owner_id):
    with database() as connection:
        profile, history = learning._context(connection, owner_id)
        plans = learning._plans(connection, owner_id, profile, history)
        pointer = connection.execute('SELECT plan_id FROM player_program_focus WHERE owner_id=%s', (owner_id,)).fetchone()
        jobs = connection.execute('''SELECT id,state,progress,created_at FROM replay_jobs
            WHERE owner_id=%s AND state IN ('uploading','queued','processing','failed')
            ORDER BY created_at DESC LIMIT 5''', (owner_id,)).fetchall()
    active = [p for p in plans if p['status'] == 'active' and p['validity'] == 'current']
    # Legacy users get their newest eligible plan; an explicitly stale focus is
    # never silently replaced by a different exercise.
    focus = next((p for p in active if str(p['id']) == str(pointer['plan_id'])), None) if pointer else next(iter(active), None)
    review = assess(focus, history) if focus else None
    candidates = []
    if focus:
        checked = {str(c['match_id']) for c in focus['checks'] if c['validity'] == 'current'}
        source = next((h for h in history if h['match_id'] == focus['source_match_id']), {})
        for match in history:
            if ((match['hero'], match['position']) != (focus['hero'], focus['position'])
                    or str(match['match_id']) in checked or match.get('report_is_previous')
                    or learning.chronology(focus, match) != 'after_plan'):
                continue
            a, b = source.get('engine_build'), match.get('engine_build')
            if a is not None and b is not None and str(a) != str(b):
                continue
            candidates.append({'job_id': match['job_id'], 'match_id': match['match_id']})
    return {'focus': focus, 'choices': active, 'review': review, 'check_candidates': candidates,
            'stage': 'check' if candidates else 'practice' if focus else 'choose' if history else 'upload',
            'focus_needs_review': bool(pointer and not focus), 'jobs': jobs,
            'latest_report': history[0]['job_id'] if history else None}


def attach_program(app):
    router = APIRouter(prefix='/api/program')

    @router.get('')
    def get(account=Depends(account_required)):
        return program(account['owner_id'])

    @router.put('/focus/{plan_id:uuid}', dependencies=[Depends(csrf)])
    def put(plan_id: UUID, account=Depends(account_required)):
        return select(account['owner_id'], plan_id)

    app.include_router(router)
