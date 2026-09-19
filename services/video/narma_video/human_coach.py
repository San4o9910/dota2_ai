"""Explicit student grants, human-authored guidance, no model or payment calls."""
import hashlib
import secrets
from datetime import datetime
from urllib.parse import urlsplit
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from . import player_profile
from .db import database
from .hero_pool import valid_report
from .owner_dashboard import require_owner
from .portal_access import Reauthenticate, reauthenticated
from .web import account_required, csrf, json_body, origin, rate_limit, reject


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='after')
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            if not value.strip() or any(ord(c) < 32 and c not in '\n\t' for c in value):
                raise ValueError('Empty or invalid text')
            return value.strip()
        return value


class Application(Body):
    display_name: str = Field(min_length=2, max_length=60)
    experience: str = Field(min_length=20, max_length=1500)


class Approval(Reauthenticate):
    status: Literal['approved','suspended']
    expected_revision: int = Field(ge=1, strict=True)


class InviteToken(Body):
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class Acceptance(InviteToken):
    student_name: str = Field(min_length=2, max_length=60)


class Consent(Body):
    share_profile: bool = Field(strict=True)


class Share(Body):
    job_id: UUID


class Task(Body):
    id: UUID
    title: str = Field(min_length=3, max_length=100)
    instruction: str = Field(min_length=10, max_length=2000)
    criterion: str = Field(min_length=5, max_length=600)


class TaskUpdate(Body):
    expected_revision: int = Field(ge=1, strict=True)
    action: Literal['submit','complete','revise','archive']
    note: str = Field(min_length=3, max_length=2000)
    job_id: UUID | None = None


class Message(Body):
    id: UUID
    body: str = Field(min_length=1, max_length=2000)
    job_id: UUID | None = None
    evidence_id: str | None = Field(default=None, min_length=1, max_length=100)


class Meeting(Body):
    expected_revision: int = Field(ge=0, strict=True)
    url: str | None = Field(default=None, max_length=500)
    starts_at: datetime | None = None

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        if value is not None:
            parsed=urlsplit(value)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Only HTTPS meeting links without credentials')
        return value

    @field_validator('starts_at')
    @classmethod
    def aware_date(cls,value):
        if value is not None and value.tzinfo is None:
            raise ValueError('Timezone required')
        return value


class Seen(Body):
    seq: int = Field(ge=0, le=9223372036854775807, strict=True)


def missing():
    reject(404, 'COACH_NOT_FOUND', 'Материал недоступен. Возможно, доступ отозван.')


def digest(token):
    return hashlib.sha256(('human-coach\0' + token).encode()).hexdigest()


def coach(connection, owner_id, *, approved=False):
    row = connection.execute('SELECT * FROM human_coaches WHERE owner_id=%s FOR SHARE', (owner_id,)).fetchone()
    if approved and (not row or row['status'] != 'approved'):
        reject(403, 'COACH_APPROVAL', 'Сначала дождись подтверждения заявки тренера владельцем платформы.')
    return row


def link(connection, owner_id, link_id):
    # Profile -> relationship is the common lock order, including suspension.
    found = connection.execute('SELECT coach_id FROM coaching_links WHERE id=%s', (link_id,)).fetchone()
    if not found:
        missing()
    approved = coach(connection, found['coach_id'])
    row = connection.execute('SELECT * FROM coaching_links WHERE id=%s FOR UPDATE', (link_id,)).fetchone()
    if not row or row['status'] != 'active' or owner_id not in (row['coach_id'],row['student_id']):
        missing()
    if owner_id == row['coach_id'] and approved['status'] != 'approved':
        missing()
    return row


def role(row, owner_id, expected):
    if row[expected + '_id'] != owner_id:
        reject(403, 'COACH_ROLE', 'Это действие доступно другой стороне обучения.')


def report(connection, student_id, job_id):
    row = connection.execute('''SELECT r.id,r.match_id,r.account_id,r.source_sha256,r.result_payload,
        encode(sha256(convert_to(r.result_payload::text,'UTF8')),'hex') AS report_sha256
        FROM replay_jobs r JOIN portal_dota_profiles p ON p.owner_id=r.owner_id AND p.account_id=r.account_id
        WHERE r.id=%s AND r.owner_id=%s AND r.state='ready' FOR SHARE OF r''', (job_id,student_id)).fetchone()
    if not row or not valid_report(row):
        missing()
    return row


def shared_report(connection, row, job_id):
    grant = connection.execute('SELECT * FROM coaching_shares WHERE link_id=%s AND job_id=%s', (row['id'],job_id)).fetchone()
    if not grant:
        missing()
    result = report(connection,row['student_id'],job_id)
    if result['report_sha256'] != grant['report_sha256']:
        reject(409,'COACH_REPORT_CHANGED','Разбор обновился. Ученик должен заново открыть доступ к этой версии.')
    return result


def pick(value, keys):
    return {key:value[key] for key in keys if key in value} if isinstance(value,dict) else {}


def projection(row):
    # No raw replay, account IDs, nickname, questionnaire or AI chat context.
    source = row['result_payload']
    advice = source.get('coaching') or {}
    return {'job_id':row['id'],'match_id':row['match_id'],'report_sha256':row['report_sha256'],
        'hero':source.get('player',{}).get('hero'),
        'metrics':pick(source.get('metrics'),('duration_seconds','kills','deaths','assists','last_hits','total_earned_gold','xp')),
        'evidence':[pick(e,('id','type','time','item','ability')) for e in source.get('evidence',[])[:500]],
        'ai_summary':advice.get('summary') if isinstance(advice.get('summary'),str) else None,
        'ai_points':[pick(p,('title','observation','decision_question','reasoning','alternative','when_to_apply','when_not_to_apply','evidence_ids'))
                     for p in advice.get('points',[])[:12] if isinstance(p,dict)],
        'source':'match_facts_and_ai_draft'}


def dashboard(owner_id):
    with database() as con:
        profile = con.execute('SELECT display_name,experience,status,revision FROM human_coaches WHERE owner_id=%s',(owner_id,)).fetchone()
        rows = con.execute('''SELECT l.id,l.student_name,l.status,l.share_profile,c.display_name AS coach_name,
            c.status AS coach_status,l.expires_at,l.updated_at,
            CASE WHEN l.coach_id=%s THEN 'coach' ELSE 'student' END AS role,
            (SELECT count(*) FROM coaching_tasks t WHERE t.link_id=l.id AND t.state='submitted') AS awaiting_review,
            (SELECT count(*) FROM coaching_shares s WHERE s.link_id=l.id AND s.reviewed_at IS NULL) AS new_reports,
            (SELECT count(*) FROM coaching_messages m WHERE m.link_id=l.id AND m.author_id<>%s
                AND m.seq>CASE WHEN l.coach_id=%s THEN l.coach_seen ELSE l.student_seen END) AS unread
            FROM coaching_links l JOIN human_coaches c ON c.owner_id=l.coach_id
            WHERE (l.student_id=%s OR l.coach_id=%s) AND l.status<>'revoked'
              AND (l.status='active' OR l.expires_at>now()) ORDER BY l.updated_at DESC LIMIT 100''',
            (owner_id,owner_id,owner_id,owner_id,owner_id)).fetchall()
        choices = con.execute('''SELECT r.id,r.match_id,r.result_payload#>>'{player,hero}' AS hero
            FROM replay_jobs r JOIN portal_dota_profiles p ON p.owner_id=r.owner_id AND p.account_id=r.account_id
            WHERE r.owner_id=%s AND r.state='ready' ORDER BY r.created_at DESC LIMIT 100''',(owner_id,)).fetchall()
    return {'coach_profile':profile,'relationships':rows,'reports':choices}


def apply(owner_id, body):
    with database() as con:
        con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,4))',(owner_id,))
        existing=coach(con,owner_id)
        if existing:
            if existing['display_name']==body.display_name and existing['experience']==body.experience:
                return {'saved':True}
            reject(409,'COACH_APPLICATION_EXISTS','Заявка уже отправлена. Её статус показан в кабинете.')
        con.execute('INSERT INTO human_coaches(owner_id,display_name,experience) VALUES (%s,%s,%s)',
                    (owner_id,body.display_name,body.experience))
    return {'saved':True}


def approve(request, account, target, body):
    rate_limit(request,'coach_approval',account['email'])
    with database() as con:
        require_owner(con,account['owner_id'])
        reauthenticated(con,request,account,body.current_password,owner_only=True)
        row=con.execute('SELECT * FROM human_coaches WHERE owner_id=%s FOR UPDATE',(target,)).fetchone()
        if not row:
            missing()
        if row['revision']!=body.expected_revision:
            reject(409,'COACH_CHANGED','Заявка уже изменена. Обнови список.')
        con.execute('''UPDATE human_coaches SET status=%s,revision=revision+1,reviewed_by=%s,reviewed_at=now()
            WHERE owner_id=%s''',(body.status,account['owner_id'],target))
        if body.status=='suspended':
            con.execute("UPDATE coaching_links SET status='revoked',token_hash=NULL WHERE coach_id=%s AND status='invited'",(target,))
    return {'saved':True}


def invite(owner_id):
    token=secrets.token_urlsafe(32)
    with database() as con:
        con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,4))',(owner_id,))
        coach(con,owner_id,approved=True)
        if con.execute("SELECT count(*) AS n FROM coaching_links WHERE coach_id=%s AND (status='active' OR (status='invited' AND expires_at>now()))",(owner_id,)).fetchone()['n']>=25:
            reject(409,'COACH_CAPACITY','Лимит — 25 действующих приглашений и учеников.')
        row=con.execute('INSERT INTO coaching_links(id,coach_id,token_hash) VALUES (%s,%s,%s) RETURNING id,expires_at',
                        (uuid4(),owner_id,digest(token))).fetchone()
    return {**row,'url':origin()+'/human-coach#coach_invite='+token}


def preview(token):
    with database() as con:
        row=con.execute('''SELECT c.display_name,c.experience FROM coaching_links l JOIN human_coaches c ON c.owner_id=l.coach_id
            WHERE l.token_hash=%s AND l.status='invited' AND l.expires_at>now() AND c.status='approved' ''',(digest(token),)).fetchone()
    if not row:
        missing()
    return {'coach':row}


def accept(owner_id, body):
    with database() as con:
        found=con.execute('SELECT coach_id FROM coaching_links WHERE token_hash=%s',(digest(body.token),)).fetchone()
        if not found:
            missing()
        coach(con,found['coach_id'],approved=True)
        # Serializes acceptance of distinct invites to the same trainer.
        con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,4))',(owner_id,))
        row=con.execute("SELECT * FROM coaching_links WHERE token_hash=%s AND status='invited' AND expires_at>now() FOR UPDATE",(digest(body.token),)).fetchone()
        if not row:
            missing()
        if row['coach_id']==owner_id:
            reject(409,'COACH_SELF','Нельзя принять своё приглашение.')
        if con.execute("SELECT 1 FROM coaching_links WHERE coach_id=%s AND student_id=%s AND status='active'",(row['coach_id'],owner_id)).fetchone():
            reject(409,'COACH_CONNECTED','Ты уже занимаешься с этим тренером.')
        con.execute("UPDATE coaching_links SET student_id=%s,student_name=%s,status='active',token_hash=NULL,updated_at=now() WHERE id=%s",(owner_id,body.student_name,row['id']))
    return {'id':row['id']}


def workspace(owner_id, link_id, *, before=None):
    with database() as con:
        row=link(con,owner_id,link_id)
        grants=con.execute('SELECT * FROM coaching_shares WHERE link_id=%s ORDER BY shared_at DESC LIMIT 100',(link_id,)).fetchall()
        reports=[]
        visible={}
        for grant in grants:
            try:
                source=shared_report(con,row,grant['job_id'])
                reports.append({**projection(source),'reviewed_at':grant['reviewed_at']})
                visible[str(grant['job_id'])]=source['report_sha256']
            except HTTPException as error:
                if error.status_code not in (404,409):
                    raise
                reports.append({'job_id':grant['job_id'],'unavailable':True})
        tasks=con.execute('''SELECT id,title,instruction,criterion,state,revision,student_note,report_job_id,
            report_sha256,coach_feedback,created_at,updated_at FROM coaching_tasks WHERE link_id=%s
            ORDER BY created_at DESC LIMIT 100''',(link_id,)).fetchall()
        for task in tasks:
            task['report_available']=bool(task['report_job_id'] and visible.get(str(task['report_job_id']))==task['report_sha256'])
        # A revoked report also hides its anchored conversation; unanchored messages remain.
        messages=con.execute('''SELECT m.seq,m.id,m.body,m.job_id,m.evidence_id,m.created_at,
            CASE WHEN m.author_id=%s THEN 'coach' ELSE 'student' END AS author
            FROM coaching_messages m WHERE m.link_id=%s AND (%s::bigint IS NULL OR m.seq<%s)
            AND (m.job_id IS NULL OR EXISTS (SELECT 1 FROM coaching_shares s JOIN replay_jobs r ON r.id=s.job_id
                JOIN portal_dota_profiles p ON p.owner_id=r.owner_id AND p.account_id=r.account_id
                WHERE s.link_id=m.link_id AND s.job_id=m.job_id AND r.owner_id=%s AND r.state='ready'
                AND s.report_sha256=m.report_sha256
                AND encode(sha256(convert_to(r.result_payload::text,'UTF8')),'hex')=s.report_sha256))
            ORDER BY m.seq DESC LIMIT 51''',(row['coach_id'],link_id,before,before,row['student_id'])).fetchall()
        more=len(messages)>50
        messages=messages[:50]
        info=con.execute('SELECT display_name,status FROM human_coaches WHERE owner_id=%s',(row['coach_id'],)).fetchone()
        # Only selected coaching preferences; never account identifiers or chat turns.
        preferences=player_profile.public(player_profile.read(con,row['student_id'])) if row['share_profile'] else None
    return {'id':row['id'],'role':'coach' if owner_id==row['coach_id'] else 'student',
        'student_name':row['student_name'],'coach_name':info['display_name'],'coach_status':info['status'],
        'meeting':{'url':row['meeting_url'],'starts_at':row['meeting_at'],'revision':row['meeting_revision']},
        'share_profile':row['share_profile'],'player_profile':preferences,'reports':reports,'tasks':tasks,
        'messages':list(reversed(messages)), 'older_before':messages[-1]['seq'] if more else None}


def revoke(owner_id, link_id):
    with database() as con:
        found=con.execute('SELECT coach_id FROM coaching_links WHERE id=%s',(link_id,)).fetchone()
        if not found:
            missing()
        coach(con,found['coach_id'])
        row=con.execute('SELECT * FROM coaching_links WHERE id=%s FOR UPDATE',(link_id,)).fetchone()
        if owner_id not in (row['coach_id'],row['student_id']):
            missing()
        con.execute("UPDATE coaching_links SET status='revoked',token_hash=NULL,share_profile=false,updated_at=now() WHERE id=%s",(link_id,))
        con.execute('DELETE FROM coaching_shares WHERE link_id=%s',(link_id,))
    return {'revoked':True}


def consent(owner_id, link_id, body):
    with database() as con:
        row=link(con,owner_id,link_id);role(row,owner_id,'student')
        con.execute('UPDATE coaching_links SET share_profile=%s,updated_at=now() WHERE id=%s',(body.share_profile,link_id))
    return {'saved':True}


def share(owner_id, link_id, job_id, *, remove=False, reviewed=False):
    with database() as con:
        row=link(con,owner_id,link_id);role(row,owner_id,'coach' if reviewed else 'student')
        if remove:
            con.execute('DELETE FROM coaching_shares WHERE link_id=%s AND job_id=%s',(link_id,job_id))
        elif reviewed:
            shared_report(con,row,job_id)
            con.execute('UPDATE coaching_shares SET reviewed_at=now() WHERE link_id=%s AND job_id=%s',(link_id,job_id))
        else:
            source=report(con,row['student_id'],job_id)
            if con.execute('SELECT count(*) AS n FROM coaching_shares WHERE link_id=%s',(link_id,)).fetchone()['n']>=100 and not con.execute('SELECT 1 FROM coaching_shares WHERE link_id=%s AND job_id=%s',(link_id,job_id)).fetchone():
                reject(409,'COACH_SHARE_LIMIT','Оставь до 100 актуальных разборов в этом кабинете.')
            con.execute('''INSERT INTO coaching_shares(link_id,job_id,report_sha256) VALUES (%s,%s,%s)
                ON CONFLICT(link_id,job_id) DO UPDATE SET report_sha256=excluded.report_sha256,
                reviewed_at=CASE WHEN coaching_shares.report_sha256=excluded.report_sha256 THEN coaching_shares.reviewed_at ELSE NULL END,
                shared_at=now()''',(link_id,job_id,source['report_sha256']))
        con.execute('UPDATE coaching_links SET updated_at=now() WHERE id=%s',(link_id,))
    return {'saved':True}


def create_task(owner_id, link_id, body):
    with database() as con:
        row=link(con,owner_id,link_id);role(row,owner_id,'coach')
        existing=con.execute('SELECT * FROM coaching_tasks WHERE id=%s',(body.id,)).fetchone()
        if existing:
            if existing['link_id']==link_id and all(existing[k]==getattr(body,k) for k in ('title','instruction','criterion')):
                return {'id':body.id}
            reject(409,'COACH_TASK_EXISTS','Это задание уже сохранено. Обнови кабинет.')
        if con.execute("SELECT 1 FROM coaching_tasks WHERE link_id=%s AND state IN ('assigned','submitted','changes_requested')",(link_id,)).fetchone():
            reject(409,'COACH_TASK_ACTIVE','Сначала заверши или архивируй текущую тренировку.')
        con.execute('''INSERT INTO coaching_tasks(id,link_id,title,instruction,criterion) VALUES (%s,%s,%s,%s,%s)''',
                    (body.id,link_id,body.title,body.instruction,body.criterion))
        con.execute('UPDATE coaching_links SET updated_at=now() WHERE id=%s',(link_id,))
    return {'id':body.id}


def update_task(owner_id, link_id, task_id, body):
    with database() as con:
        row=link(con,owner_id,link_id)
        role(row,owner_id,'student' if body.action=='submit' else 'coach')
        task=con.execute('SELECT * FROM coaching_tasks WHERE id=%s AND link_id=%s FOR UPDATE',(task_id,link_id)).fetchone()
        if not task:
            missing()
        if task['revision']!=body.expected_revision:
            reject(409,'COACH_TASK_CHANGED','Задание изменилось. Обнови кабинет перед отправкой.')
        if body.action=='submit':
            if task['state'] not in ('assigned','changes_requested'):
                reject(409,'COACH_TASK_STATE','Это задание сейчас нельзя отправить на проверку.')
            source=shared_report(con,row,body.job_id) if body.job_id else None
            con.execute("""UPDATE coaching_tasks SET state='submitted',student_note=%s,report_job_id=%s,report_sha256=%s,
                revision=revision+1,updated_at=now() WHERE id=%s""",(body.note,body.job_id,source['report_sha256'] if source else None,task_id))
        else:
            if body.job_id is not None:
                reject(400,'COACH_TASK_FIELDS','Матч для проверки выбирает ученик.')
            if task['state'] in ('completed','archived') or (body.action in ('complete','revise') and task['state']!='submitted'):
                reject(409,'COACH_TASK_STATE','Сначала ученик должен отправить результат на проверку.')
            desired={'complete':'completed','revise':'changes_requested','archive':'archived'}[body.action]
            con.execute('UPDATE coaching_tasks SET state=%s,coach_feedback=%s,revision=revision+1,updated_at=now() WHERE id=%s',
                        (desired,body.note,task_id))
        con.execute('UPDATE coaching_links SET updated_at=now() WHERE id=%s',(link_id,))
    return {'saved':True}


def send(owner_id, link_id, body):
    with database() as con:
        row=link(con,owner_id,link_id)
        if body.evidence_id and not body.job_id:
            reject(400,'COACH_ANCHOR','Сначала выбери разбор.')
        source=shared_report(con,row,body.job_id) if body.job_id else None
        if body.evidence_id and not any(e.get('id')==body.evidence_id for e in source['result_payload'].get('evidence',[])):
            reject(400,'COACH_ANCHOR','Эпизод не найден в доступной версии разбора.')
        existing=con.execute('SELECT * FROM coaching_messages WHERE id=%s',(body.id,)).fetchone()
        if existing:
            if existing['link_id']==link_id and existing['author_id']==owner_id and existing['body']==body.body and existing['job_id']==body.job_id and existing['evidence_id']==body.evidence_id:
                return {'saved':True}
            reject(409,'COACH_MESSAGE_EXISTS','Это сообщение уже сохранено. Обнови кабинет.')
        if con.execute("SELECT count(*) AS n FROM coaching_messages WHERE link_id=%s AND author_id=%s AND created_at>now()-interval '1 hour'",(link_id,owner_id)).fetchone()['n']>=60:
            reject(429,'COACH_MESSAGE_LIMIT','До 60 сообщений в час. Продолжи немного позже.')
        con.execute('''INSERT INTO coaching_messages(id,link_id,author_id,body,job_id,report_sha256,evidence_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',(body.id,link_id,owner_id,body.body,body.job_id,source['report_sha256'] if source else None,body.evidence_id))
        con.execute('UPDATE coaching_links SET updated_at=now() WHERE id=%s',(link_id,))
    return {'saved':True}


def seen(owner_id, link_id, body):
    with database() as con:
        row=link(con,owner_id,link_id)
        if body.seq and not con.execute('SELECT 1 FROM coaching_messages WHERE link_id=%s AND seq=%s',(link_id,body.seq)).fetchone():
            missing()
        column='coach_seen' if owner_id==row['coach_id'] else 'student_seen'
        con.execute(f'UPDATE coaching_links SET {column}=greatest({column},%s) WHERE id=%s',(body.seq,link_id))
    return {'saved':True}


def meeting(owner_id,link_id,body):
    with database() as con:
        row=link(con,owner_id,link_id);role(row,owner_id,'coach')
        if row['meeting_revision']!=body.expected_revision:
            reject(409,'COACH_MEETING_CHANGED','Встреча уже изменена. Обнови кабинет.')
        con.execute('''UPDATE coaching_links SET meeting_url=%s,meeting_at=%s,meeting_revision=meeting_revision+1,
            updated_at=now() WHERE id=%s''',(body.url,body.starts_at,link_id))
    return {'saved':True}


async def body_for(request, model):
    try:
        return await json_body(request,model)
    except HTTPException as error:
        if error.status_code==400:
            reject(400,'COACH_FIELDS','Проверь заполнение полей и длину текста.')
        raise


def attach_human_coach(app):
    router=APIRouter(prefix='/api/human-coach')

    @router.get('')
    def get(account=Depends(account_required)):
        return dashboard(account['owner_id'])

    @router.post('/application',dependencies=[Depends(csrf)])
    async def application(request:Request,account=Depends(account_required)):
        return await run_in_threadpool(apply,account['owner_id'],await body_for(request,Application))

    @router.get('/applications')
    def applications(account=Depends(account_required)):
        with database() as con:
            require_owner(con,account['owner_id'])
            return {'applications':con.execute('SELECT owner_id,display_name,experience,status,revision FROM human_coaches ORDER BY created_at LIMIT 100').fetchall()}

    @router.put('/applications/{target}',dependencies=[Depends(csrf)])
    async def approval(target:str,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(approve,request,account,target,await body_for(request,Approval))

    @router.post('/invitations',dependencies=[Depends(csrf)])
    def invitation(account=Depends(account_required)):
        return invite(account['owner_id'])

    @router.post('/invitation-preview',dependencies=[Depends(csrf)])
    async def invitation_preview(request:Request,account=Depends(account_required)):
        # Token stays in POST body, never in path, query, referrer or server logs.
        body=await body_for(request,InviteToken)
        return await run_in_threadpool(preview,body.token)

    @router.post('/accept',dependencies=[Depends(csrf)])
    async def acceptance(request:Request,account=Depends(account_required)):
        return await run_in_threadpool(accept,account['owner_id'],await body_for(request,Acceptance))

    @router.get('/links/{link_id:uuid}')
    def detail(link_id:UUID,before:int|None=Query(default=None,ge=1,le=9223372036854775807),account=Depends(account_required)):
        return workspace(account['owner_id'],link_id,before=before)

    @router.delete('/links/{link_id:uuid}',dependencies=[Depends(csrf)])
    def disconnect(link_id:UUID,account=Depends(account_required)):
        return revoke(account['owner_id'],link_id)

    @router.put('/links/{link_id:uuid}/consent',dependencies=[Depends(csrf)])
    async def profile_consent(link_id:UUID,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(consent,account['owner_id'],link_id,await body_for(request,Consent))

    @router.put('/links/{link_id:uuid}/reports/{job_id:uuid}',dependencies=[Depends(csrf)])
    def share_report(link_id:UUID,job_id:UUID,account=Depends(account_required)):
        return share(account['owner_id'],link_id,job_id)

    @router.delete('/links/{link_id:uuid}/reports/{job_id:uuid}',dependencies=[Depends(csrf)])
    def unshare_report(link_id:UUID,job_id:UUID,account=Depends(account_required)):
        return share(account['owner_id'],link_id,job_id,remove=True)

    @router.post('/links/{link_id:uuid}/reports/{job_id:uuid}/reviewed',dependencies=[Depends(csrf)])
    def reviewed_report(link_id:UUID,job_id:UUID,account=Depends(account_required)):
        return share(account['owner_id'],link_id,job_id,reviewed=True)

    @router.post('/links/{link_id:uuid}/tasks',dependencies=[Depends(csrf)],status_code=201)
    async def task(link_id:UUID,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(create_task,account['owner_id'],link_id,await body_for(request,Task))

    @router.put('/links/{link_id:uuid}/tasks/{task_id:uuid}',dependencies=[Depends(csrf)])
    async def task_update(link_id:UUID,task_id:UUID,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(update_task,account['owner_id'],link_id,task_id,await body_for(request,TaskUpdate))

    @router.post('/links/{link_id:uuid}/messages',dependencies=[Depends(csrf)],status_code=201)
    async def message(link_id:UUID,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(send,account['owner_id'],link_id,await body_for(request,Message))

    @router.post('/links/{link_id:uuid}/seen',dependencies=[Depends(csrf)])
    async def mark_seen(link_id:UUID,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(seen,account['owner_id'],link_id,await body_for(request,Seen))

    @router.put('/links/{link_id:uuid}/meeting',dependencies=[Depends(csrf)])
    async def set_meeting(link_id:UUID,request:Request,account=Depends(account_required)):
        return await run_in_threadpool(meeting,account['owner_id'],link_id,await body_for(request,Meeting))

    app.include_router(router)
