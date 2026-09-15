"""Observed practice changes and personal replay exercises, without inference."""
from statistics import mean
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from . import curriculum, learning
from .coach_chat import _current, _locks
from .db import database
from .hero_pool import finite, timestamp, TREND_METRICS
from .web import account_required, csrf, json_body, reject

METRICS = {'l1': 'last_hits_10', 'l2': 'last_hits_10', 'r1': 'deaths_per_30',
           'r2': 'repeated_deaths', 'i1': 'item_delay_seconds', 'i2': 'item_delay_seconds'}


def assess(plan, history):
    """Measure a recorded indicator; never turn it into a correctness score."""
    source = next((r for r in history if r['match_id'] == plan['source_match_id']), None)
    metric = METRICS.get(plan['exercise_id'])
    if plan.get('position') in (4, 5) and metric == 'last_hits_10':
        metric = None
    result = {'status': 'needs_review', 'metric': metric, 'matches': [],
              'note': 'Для этого задания нужен твой разбор решения. Автоматической оценки правильности нет.'}
    if not source or plan['validity'] != 'current' or not metric:
        return result
    result['label'], result['unit'], _ = TREND_METRICS[metric]
    result['baseline'] = source['metrics'].get(metric)
    baseline_time = timestamp(source.get('played_at'))
    baseline_build = source.get('engine_build')
    for fact in sorted(history, key=lambda r: r['chronology_at'], reverse=True):
        if (fact['hero'], fact['position']) != (plan['hero'], plan['position']):
            continue
        if fact['match_id'] == source['match_id'] or fact.get('report_is_previous'):
            continue
        # Deleted, duplicate, undated and pre-plan games are excluded by the
        # canonical owned history and chronology contract already used by plans.
        when = learning.chronology(plan, fact)
        if when != 'after_plan' or not baseline_time or timestamp(fact.get('played_at')) <= baseline_time:
            continue
        if baseline_build is not None and fact.get('engine_build') is not None and str(baseline_build) != str(fact['engine_build']):
            continue
        value = fact['metrics'].get(metric)
        if not finite(value):
            continue
        result['matches'].append({'job_id': fact['job_id'], 'match_id': fact['match_id'], 'value': value,
            'report_sha256': fact['report_sha256'],
            'date_source': fact['date_source'], 'build_known': baseline_build is not None and fact.get('engine_build') is not None,
            'evidence': [e for e in fact['evidence'] if e['type'] in ('death', 'item_use')][:8]})
        if len(result['matches']) == 5:
            break
    if not finite(result['baseline']) or not result['matches']:
        result.update(status='waiting', note='Нужны новые датированные матчи на том же герое и позиции с доступным показателем.')
        return result
    recent = round(mean(row['value'] for row in result['matches']), 2)
    result.update(status='measured', recent_mean=recent, delta=round(recent-result['baseline'], 2),
        note='Изменился показатель, а не доказанное качество решения. Сравни условия и эпизоды; режим игры не подтверждён.')
    if not all(row['build_known'] for row in result['matches']):
        result['note'] += ' Версия части игр неизвестна.'
    return result


def progress(owner_id):
    data = learning.get_learning(owner_id)
    return {'plans': [{**{k: p[k] for k in ('id', 'hero_label', 'position', 'exercise', 'status', 'validity')},
                       'review': assess(p, data['history'])} for p in data['plans'] if p['status'] == 'active']}


class BoundReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    report_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Feedback(BoundReport):
    reason: Literal['context', 'role', 'generic', 'facts', 'helpful']
    point_index: int | None = Field(default=None, ge=0, le=100)
    comment: str = Field(default='', max_length=1500)


class Attempt(BoundReport):
    exercise_id: str = Field(pattern=r'^[a-z0-9_-]{1,60}$')
    evidence_id: str = Field(min_length=1, max_length=160)
    answer: str = Field(min_length=10, max_length=1500)

    @field_validator('answer')
    @classmethod
    def clean(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError('Explain your choice')
        return value


def current_report(connection, owner_id, job_id, digest=None):
    _locks(connection, owner_id)
    row = _current(connection, owner_id, job_id)
    if not row:
        reject(404, 'GROWTH_SOURCE', 'Готовый разбор не найден.')
    if digest is not None and row['report_sha256'] != digest:
        reject(409, 'GROWTH_CHANGED', 'Разбор обновился. Открой его заново.')
    return row


def scenarios(current):
    position = current['current_position']
    if position not in (1, 2, 3, 4, 5):
        return []
    result = []
    for exercise in curriculum.get_catalog(position)['exercises']:
        anchors = curriculum.evidence_candidates(current['result_payload'], exercise['id'], position)
        if anchors:
            result.append({'exercise_id': exercise['id'], 'title': exercise['title'],
                'question': exercise['decision_question'], 'episode': anchors[0]})
    return result[:6]


def practice(owner_id, job_id):
    with database() as connection:
        current = current_report(connection, owner_id, job_id)
        rows = connection.execute('''SELECT id,exercise_id,evidence_id,answer,created_at FROM replay_practice_attempts
            WHERE owner_id=%s AND job_id=%s AND report_sha256=%s AND position=%s ORDER BY created_at DESC LIMIT 20''',
            (owner_id, job_id, current['report_sha256'], current['current_position'])).fetchall()
        return {'report_sha256': current['report_sha256'], 'scenarios': scenarios(current), 'attempts': rows,
                'position_required': current['current_position'] is None}


def submit_attempt(owner_id, job_id, body):
    with database() as connection:
        current = current_report(connection, owner_id, job_id, body.report_sha256)
        exercise = curriculum.get_exercise(body.exercise_id, current['current_position'])
        anchors = curriculum.evidence_candidates(current['result_payload'], body.exercise_id, current['current_position'])
        if current['current_position'] is None or not exercise or body.evidence_id not in {e['evidence_id'] for e in anchors}:
            reject(400, 'GROWTH_EPISODE', 'Выбери доступное упражнение и эпизод своего матча.')
        previous = connection.execute('SELECT * FROM replay_practice_attempts WHERE id=%s', (body.id,)).fetchone()
        if previous:
            if (previous['owner_id'] != owner_id or str(previous['job_id']) != str(job_id)
                    or previous['report_sha256'] != body.report_sha256 or previous['position'] != current['current_position']
                    or previous['exercise_id'] != body.exercise_id or previous['evidence_id'] != body.evidence_id or previous['answer'] != body.answer):
                reject(409, 'GROWTH_CONFLICT', 'Эта попытка уже сохранена с другим ответом.')
        else:
            count = connection.execute('SELECT count(*) AS n FROM replay_practice_attempts WHERE owner_id=%s AND job_id=%s', (owner_id, job_id)).fetchone()['n']
            if count >= 40:
                reject(429, 'GROWTH_LIMIT', 'Для этого матча сохранено достаточно попыток. Продолжи на следующей игре.')
            connection.execute('''INSERT INTO replay_practice_attempts
                (id,owner_id,job_id,report_sha256,position,exercise_id,evidence_id,answer) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                (body.id, owner_id, job_id, body.report_sha256, current['current_position'], body.exercise_id, body.evidence_id, body.answer))
    return {'saved': True, 'reflection': {key: exercise[key] for key in ('action', 'why', 'exception', 'measurement')},
            'note': 'Это ориентир для самостоятельной проверки, а не оценка твоего ответа нейросетью.'}


def save_feedback(owner_id, job_id, body):
    with database() as connection:
        current = current_report(connection, owner_id, job_id, body.report_sha256)
        coaching = current['result_payload'].get('coaching') or {}
        context = coaching.get('context') or {}
        if coaching.get('status') != 'ready' or context.get('position', current['current_position']) != current['current_position']:
            reject(409, 'FEEDBACK_SOURCE', 'Актуального совета ИИ для отзыва нет.')
        if body.point_index is not None and body.point_index >= len(coaching.get('points') or []):
            reject(400, 'FEEDBACK_POINT', 'Совет не найден.')
        previous = connection.execute('SELECT * FROM coaching_feedback WHERE id=%s', (body.id,)).fetchone()
        if previous:
            if (previous['owner_id'] != owner_id or str(previous['job_id']) != str(job_id)
                    or any(previous[key] != getattr(body, key) for key in ('report_sha256', 'reason', 'point_index', 'comment'))):
                reject(409, 'FEEDBACK_CONFLICT', 'Этот отзыв уже сохранён с другим содержанием.')
        else:
            count = connection.execute("SELECT count(*) AS n FROM coaching_feedback WHERE owner_id=%s AND created_at>now()-interval '1 day'", (owner_id,)).fetchone()['n']
            if count >= 30:
                reject(429, 'FEEDBACK_LIMIT', 'На сегодня достаточно отзывов. Спасибо за помощь.')
            connection.execute('''INSERT INTO coaching_feedback
                (id,owner_id,job_id,report_sha256,position,point_index,reason,comment) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                (body.id, owner_id, job_id, body.report_sha256, current['current_position'], body.point_index, body.reason, body.comment))
    return {'saved': True}


def attach_growth(app):
    router = APIRouter()

    @router.get('/api/learning/progress')
    def get_progress(account=Depends(account_required)):
        return progress(account['owner_id'])

    @router.get('/api/replays/{job_id}/practice')
    def get_practice(job_id: UUID, account=Depends(account_required)):
        return practice(account['owner_id'], job_id)

    @router.post('/api/replays/{job_id}/practice')
    async def post_practice(job_id: UUID, request: Request, account=Depends(account_required)):
        csrf(request)
        body = await json_body(request, Attempt)
        return await run_in_threadpool(submit_attempt, account['owner_id'], job_id, body)

    @router.post('/api/replays/{job_id}/feedback')
    async def post_feedback(job_id: UUID, request: Request, account=Depends(account_required)):
        csrf(request)
        body = await json_body(request, Feedback)
        return await run_in_threadpool(save_feedback, account['owner_id'], job_id, body)

    app.include_router(router)
