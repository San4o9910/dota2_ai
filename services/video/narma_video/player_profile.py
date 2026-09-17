"""Owned self-reports and preferences, never diagnoses or evidence of match events."""
from copy import deepcopy
from typing import Literal
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.concurrency import run_in_threadpool
from psycopg.types.json import Jsonb
from .db import database
from .web import account_required, csrf, json_body, reject

VERSION = 'narma.player-profile.v1'
GOALS = {'consistency': 'Играть стабильнее', 'new_role': 'Освоить роль',
         'returning': 'Вернуться после перерыва', 'ranked': 'Подготовиться к рейтингу',
         'decisions': 'Лучше понимать решения', 'custom': 'Своя цель'}
CORE = {'goal', 'position', 'rank_band', 'experience', 'matches_per_week', 'practice_minutes', 'explanation'}


class ScenarioAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    choice: Literal['act', 'wait', 'alternative', 'unknown']
    reason: str = Field(default='', max_length=300)


class Answers(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    goal: Literal['consistency','new_role','returning','ranked','decisions','custom'] | None = None
    goal_note: str = Field(default='', max_length=160)
    position: int | None = Field(default=None, ge=1, le=5)
    heroes: list[str] = Field(default_factory=list, max_length=3)
    rank_band: Literal['unranked','unknown','under1000','1000_2000','2000_3000','3000_5000','5000_8000','over8000'] | None = None
    experience: Literal['beginner','regular','returning'] | None = None
    matches_per_week: Literal['rare','steady','frequent','intensive','variable'] | None = None
    practice_minutes: Literal[0,5,10,20] | None = None
    explanation: Literal['short','detailed','question'] | None = None
    tone: Literal['calm','direct'] | None = None
    after_losses: Literal['steady','rush','switch','pause','varies','skip'] | None = None
    learning_obstacle: Literal['understanding','noticing','execution','unsure'] | None = None
    communication: Literal['solo','friends','mixed'] | None = None
    focus_skill: Literal['laning','resources','vision','fights','items','after_fight','unknown'] | None = None
    feedback_format: Literal['episode','checklist','practice'] | None = None
    scenarios: dict[Literal['lane','map','fight'], ScenarioAnswer] = Field(default_factory=dict, max_length=3)

    @field_validator('practice_minutes', mode='before')
    @classmethod
    def numeric_practice(cls, value):
        if isinstance(value, bool):
            raise ValueError('invalid duration')
        return value

    @field_validator('heroes')
    @classmethod
    def clean_heroes(cls, value):
        if any(not name.strip() or len(name) > 40 or any(ord(c) < 32 for c in name) for name in value):
            raise ValueError('invalid hero label')
        return list(dict.fromkeys(name.strip() for name in value))

    @field_validator('goal_note')
    @classmethod
    def clean_note(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError('invalid note')
        return value.strip()


class Update(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=0, le=2147483646)
    last_step: int = Field(default=0, ge=0, le=16)
    action: Literal['save','finish','skip'] = 'save'
    answers: Answers = Field(default_factory=Answers)


def read(connection, owner_id):
    row = connection.execute('SELECT * FROM player_coaching_profiles WHERE owner_id=%s', (owner_id,)).fetchone()
    return ({'revision': 0, 'state': 'not_started', 'last_step': 0, 'answers': {},
             'questionnaire_version': VERSION, 'updated_at': None} if not row else
            {key: row[key] for key in ('revision','state','last_step','answers','questionnaire_version','updated_at')})


def snapshot(profile):
    """Only bounded, declared coaching answers; no account or report identifiers."""
    answers = profile['answers']
    keys = ('goal','position','rank_band','experience','matches_per_week','practice_minutes',
            'explanation','tone','after_losses','learning_obstacle','communication','focus_skill','feedback_format',
            'goal_note','heroes','scenarios')
    clean = {key: answers[key] for key in keys if answers.get(key) is not None and answers.get(key) not in ('', [], {})}
    if clean.get('after_losses') == 'skip':
        clean.pop('after_losses')
    if not clean:
        return {}
    return {'revision': profile['revision'], 'classification': 'self_report_not_match_evidence',
            'preferences': clean}


def guidance(profile):
    answers = snapshot(profile).get('preferences', {})
    if not answers:
        return None
    goal = answers.get('goal_note') if answers.get('goal') == 'custom' and answers.get('goal_note') else GOALS.get(answers.get('goal'), 'Выбрать одно действие')
    focus = answers.get('focus_skill')
    if focus in (None, 'unknown'):
        focus = {'new_role':'laning','returning':'items','ranked':'resources','consistency':'vision'}.get(answers.get('goal'))
    practice = answers.get('practice_minutes')
    focus_copy = {
        'laning': ('План одной волны', 'Перед следующей волной назови задачу своего героя и одно условие, при котором изменишь план.'),
        'resources': ('Цена перемещения', 'Перед уходом с линии назови ожидаемую пользу и ресурс, который можешь потерять.'),
        'vision': ('Проверка перед выходом', 'Перед выходом за реку проверь видимых соперников, поддержку и путь отхода.'),
        'fights': ('Своя задача в бою', 'До начала боя назови одно полезное действие своего героя и условие для отхода.'),
        'items': ('Предмет под задачу', 'Перед покупкой объясни, какое следующее действие станет доступно и при каких условиях.'),
        'after_fight': ('Действие после боя', 'После боя проверь живых героев, линии и ресурсы, затем назови одну доступную цель.'),
    }
    title, action = focus_copy.get(focus, ('Пауза перед решением', 'Перед одним важным решением назови цель, доступную информацию и запасной вариант.'))
    if practice == 0:
        dose = 'Один подходящий эпизод в следующем матче. Отдельная тренировка не нужна.'
    elif practice:
        dose = f'До {practice} минут отдельной практики: сначала один эпизод, затем повтор только если остаётся время.'
    else:
        dose = 'Один эпизод в удобном темпе; длительность можно настроить в профиле.'
    obstacle = {
        'understanding': 'Сначала объясни совет своими словами и уточни непонятный термин.',
        'noticing': 'Заранее выбери один сигнал, по которому вспомнишь о действии во время игры.',
        'execution': 'Повтори само действие в спокойных условиях, затем проверь в одном матче.',
    }.get(answers.get('learning_obstacle'), 'После игры запиши, удалось ли применить действие и что помешало.')
    explanations = {
        'short': 'Короткий вывод и одно действие.',
        'detailed': 'Вывод, объяснение, условие и исключение.',
        'question': 'Сначала вопрос о твоём решении, затем варианты.',
    }
    basis = [f'Твоя цель: {goal}.']
    if answers.get('experience') == 'returning':
        basis.append('Ты возвращаешься после перерыва: начнём с одного привычного героя и уточнения изменившихся условий.')
    elif answers.get('experience') == 'beginner':
        basis.append('Ты начинаешь: новые понятия объясняем по одному, без требований к рейтингу.')
    if answers.get('position'):
        basis.append(f"Основная позиция — {answers['position']}; в конкретном матче используем указанную для него роль.")
    if answers.get('matches_per_week') == 'rare':
        basis.append('При небольшом числе матчей проверяем следующий удобный матч, без ежедневного плана.')
    if answers.get('after_losses') == 'rush':
        basis.append('Ты отмечал спешку после поражений: перед следующей игрой можно сделать паузу и оставить один фокус.')
    if answers.get('communication') == 'friends':
        basis.append('Для игры с друзьями можно заранее согласовать один сигнал к действию; результат всё равно оцениваем по твоему решению.')
    if answers.get('feedback_format') == 'checklist':
        obstacle += ' Запиши три пункта: сигнал, действие, условие отмены.'
    elif answers.get('feedback_format') == 'episode':
        obstacle += ' Начни с одного таймкода своего реплея.'
    elif answers.get('feedback_format') == 'practice':
        obstacle += ' Начни с короткого повторения выбранного действия.'
    if answers.get('scenarios'):
        basis.append('Выбор в учебных ситуациях — повод обсудить основания решения в чате, а не оценка навыка. Можно спросить тренера, когда выбранный вариант подходит.')
    return {'revision': profile['revision'], 'goal': goal, 'title': title, 'action': action,
            'dose': dose, 'preparation': obstacle, 'explanation': explanations.get(answers.get('explanation'), explanations['detailed']),
            'tone': 'Прямо и уважительно' if answers.get('tone') == 'direct' else 'Спокойно и уважительно',
            'basis': basis, 'source': 'player_self_report',
            'measurement': 'После матча отметь, какое решение ты проверил и что получилось. Это самооценка, а не автоматическая оценка навыка.',
            'exception': 'Срочная защита или новая информация могут изменить решение; действие не универсально.',
            'limitation': 'Предварительная практика по твоим ответам. Навыки и причины событий проверяем по собственным матчам.'}


def public(profile):
    return {'profile': profile, 'guidance': guidance(profile)}


def lock(connection, owner_id):
    # Shared ordering with chat and learning updates prevents stale snapshots.
    for scope in (0, 1):
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,%s))', (owner_id, scope))


def save(owner_id, body):
    patch = body.answers.model_dump(exclude_unset=True)
    with database() as connection:
        lock(connection, owner_id)
        current = read(connection, owner_id)
        answers = current['answers'] | patch
        complete = CORE.issubset(answers) and all(answers.get(k) is not None for k in CORE - {'position'})
        desired = 'skipped' if body.action == 'skip' else 'ready' if body.action == 'finish' or (current['state'] == 'ready' and complete) else 'partial'
        if body.action == 'finish':
            if not complete:
                reject(400, 'PLAYER_PROFILE_INCOMPLETE', 'Ответь на основные вопросы или выбери «Настроить позже».')
            if answers['goal'] == 'custom' and not answers.get('goal_note'):
                reject(400, 'PLAYER_PROFILE_GOAL', 'Коротко опиши свою цель.')
        if body.expected_revision != current['revision']:
            if current['state'] == desired and current['last_step'] == body.last_step and all(current['answers'].get(k) == v for k,v in patch.items()):
                return public(current)  # Safe retry after a lost successful response.
            reject(409, 'PLAYER_PROFILE_CHANGED', 'Профиль изменён в другой вкладке. Обнови его перед сохранением.')
        row = connection.execute('''INSERT INTO player_coaching_profiles(owner_id,answers,state,last_step)
            VALUES (%s,%s,%s,%s) ON CONFLICT(owner_id) DO UPDATE SET
            answers=excluded.answers,state=excluded.state,last_step=excluded.last_step,
            revision=player_coaching_profiles.revision+1,updated_at=now() RETURNING revision''',
            (owner_id,Jsonb(answers),desired,body.last_step)).fetchone()
        assert row['revision'] > current['revision']
        return public(read(connection, owner_id))


def reset(owner_id):
    with database() as connection:
        lock(connection, owner_id)
        connection.execute('''INSERT INTO player_coaching_profiles(owner_id,answers,state) VALUES (%s,'{}','skipped')
            ON CONFLICT(owner_id) DO UPDATE SET answers='{}',state='skipped',last_step=0,
            revision=player_coaching_profiles.revision+1,updated_at=now()''', (owner_id,))
        connection.execute("UPDATE learning_plans SET coaching_profile='{}' WHERE owner_id=%s", (owner_id,))
        connection.execute("""UPDATE coach_chat_turns SET coaching_profile='{}',input_data=NULL,
            error_code=CASE WHEN state='running' THEN 'COACH_CHAT_CHANGED' ELSE error_code END,
            finished_at=CASE WHEN state='running' THEN now() ELSE finished_at END,
            state=CASE WHEN state='running' THEN 'failed' ELSE state END
            WHERE owner_id=%s AND coaching_profile<>'{}'""", (owner_id,))
        return public(read(connection, owner_id))


def adapt_exercise(exercise, saved):
    """An immutable plan snapshot changes practice delivery, never source evidence."""
    result = deepcopy(exercise)
    if not saved or not result:
        return result
    guide = guidance({'answers': saved.get('preferences', {}), 'revision': saved.get('revision', 0)})
    if guide:
        result['personalization'] = guide
    return result


def attach_player_profile(app):
    router = APIRouter(prefix='/api/player-profile')

    @router.get('')
    def get(account=Depends(account_required)):
        with database() as connection:
            return public(read(connection, account['owner_id']))

    @router.put('', dependencies=[Depends(csrf)])
    async def put(request: Request, account=Depends(account_required)):
        try:
            body = await json_body(request, Update)
        except HTTPException as error:
            if error.status_code == 400:
                reject(400, 'PLAYER_PROFILE_FIELDS', 'Проверь ответы: они слишком длинные или содержат неподходящие значения.')
            raise
        return await run_in_threadpool(save, account['owner_id'], body)

    @router.delete('', dependencies=[Depends(csrf)])
    def delete(account=Depends(account_required)):
        return reset(account['owner_id'])

    app.include_router(router)
