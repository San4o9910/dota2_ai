"""Synthetic multi-account human coaching; PostgreSQL, no model/network calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID, uuid4
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from narma_video import human_coach as hc, player_profile
from narma_video.db import database
from test_web import portal, setup, PASSWORD
from test_portal_access import guest
from test_portal_registration import register
from test_hero_pool import report as fixture_report

P='/api/human-coach'

@pytest.fixture
def actors(portal):
    hc.attach_human_coach(portal.app);player_profile.attach_player_profile(portal.app)
    setup(portal)
    coach=guest(portal);student=guest(portal);other=guest(portal)
    for client,email in ((coach,'coach@example.test'),(student,'student@example.test'),(other,'other@example.test')):
        assert register(client,email).status_code==201
    with database() as con:
        ids={r['email'].split('@')[0]:r['owner_id'] for r in con.execute('SELECT owner_id,email FROM portal_accounts').fetchall()}
        for name,number in (('student',1000),('other',2000)):
            con.execute('''INSERT INTO portal_dota_profiles(owner_id,account_id,nickname,match_id,hero_name,side,source_sha256)
                VALUES (%s,%s,'Private nickname','8963624400','npc_dota_hero_axe','radiant',%s)''',(ids[name],number,'a'*64))
    return portal,coach,student,other,ids


def approved(actors):
    owner,coach,student,other,ids=actors
    application={'display_name':'Synthetic coach','experience':'Five years of synthetic coaching. No real qualification claim.'}
    assert coach.post(P+'/application',json=application).status_code==200
    assert owner.put(P+'/applications/'+ids['coach'],json={'status':'approved','expected_revision':1,'current_password':PASSWORD}).status_code==200
    return actors


def connected(actors):
    approved(actors)
    owner,coach,student,other,ids=actors
    invitation=coach.post(P+'/invitations').json()
    token=parse_qs(urlsplit(invitation['url']).fragment)['coach_invite'][0]
    response=student.post(P+'/accept',json={'token':token,'student_name':'Synthetic student'})
    assert response.status_code==200,response.text
    return response.json()['id'],token


def seed(owner,account=1000):
    job=uuid4();payload=fixture_report(account=account)
    payload['player']['nickname']='PRIVATE NICKNAME'
    payload['coaching']={'summary':'Review this decision.','context':{'private':'PRIVATE CONTEXT'},'points':[
        {'title':'One signal','observation':'Observed death.','reasoning':'Check map context.','alternative':'Look at support first.',
         'when_to_apply':'Before moving out','when_not_to_apply':'Urgent defense','evidence_ids':['e10']}]}
    with database() as con:
        con.execute('''INSERT INTO replay_jobs(id,owner_id,filename,size_bytes,requested_nickname,nickname,match_id,account_id,
            source_sha256,state,progress,result_payload) VALUES (%s,%s,'private.dem',20,'Private','Private','8963624400',%s,%s,'ready',100,%s)''',
            (job,owner,account,'a'*64,Jsonb(payload)))
    return str(job)


def task(coach,base,**overrides):
    return coach.post(base+'/tasks',json={'id':str(uuid4()),'title':'Map check','instruction':'Check support before crossing the river.',
        'criterion':'Explain one decision and its available information.',**overrides})


def test_owner_verification_is_required_and_scoped(actors):
    owner,coach,student,other,ids=actors
    assert coach.post(P+'/invitations').status_code==403
    assert coach.post(P+'/application',json={'display_name':'Coach','experience':'Synthetic review of qualifications.','status':'approved'}).status_code==400
    assert coach.post(P+'/application',json={'display_name':'Coach','experience':'Synthetic review of qualifications.'}).status_code==200
    assert other.get(P+'/applications').status_code==403
    body={'status':'approved','expected_revision':1,'current_password':PASSWORD}
    assert coach.put(P+'/applications/'+ids['coach'],json=body).status_code==403
    assert owner.put(P+'/applications/'+ids['coach'],json={**body,'current_password':'incorrect password'}).status_code==403
    assert owner.put(P+'/applications/'+ids['coach'],json=body).status_code==200
    assert owner.put(P+'/applications/'+ids['coach'],json=body).status_code==409
    assert coach.post(P+'/invitations').status_code==200


def test_invitation_is_single_use_expiring_and_not_automatic_data_access(actors):
    approved(actors);owner,coach,student,other,ids=actors
    invitation=coach.post(P+'/invitations').json();token=parse_qs(urlsplit(invitation['url']).fragment)['coach_invite'][0]
    preview=student.post(P+'/invitation-preview',json={'token':token})
    assert preview.status_code==200 and preview.json()['coach']['display_name']=='Synthetic coach'
    assert coach.post(P+'/accept',json={'token':token,'student_name':'Coach'}).status_code==409
    with database() as con:
        saved=con.execute('SELECT * FROM coaching_links WHERE id=%s',(invitation['id'],)).fetchone()
        assert saved['token_hash']!=token and token not in str(saved)
    accepted=student.post(P+'/accept',json={'token':token,'student_name':'Student'});assert accepted.status_code==200
    assert other.post(P+'/accept',json={'token':token,'student_name':'Other'}).status_code==404
    base=P+'/links/'+accepted.json()['id'];data=coach.get(base).json()
    assert data['reports']==[] and data['player_profile'] is None
    assert other.get(base).status_code==404 and owner.get(base).status_code==404
    invite=coach.post(P+'/invitations').json();token=parse_qs(urlsplit(invite['url']).fragment)['coach_invite'][0]
    with database() as con:con.execute("UPDATE coaching_links SET expires_at=now()-interval '1 minute' WHERE id=%s",(invite['id'],))
    assert student.post(P+'/accept',json={'token':token,'student_name':'Student'}).status_code==404


def test_session_csrf_body_limits_and_no_provider_calls(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    assert guest(owner).get(P).status_code==401
    assert student.put(base+'/consent',json={'share_profile':True},headers={'Origin':'https://foreign.example'}).status_code==403
    for body in ({'share_profile':'true'},{'share_profile':True,'owner_id':ids['other']}):
        assert student.put(base+'/consent',json=body).status_code==400
    assert student.post(base+'/messages',content='x'*9000,headers={'Content-Type':'application/json'}).status_code==413
    assert student.get(base).headers['cache-control']=='no-store'
    assert student.get(base+'?before=9223372036854775808').status_code==422
    with database() as con:
        assert con.execute('SELECT count(*) AS n FROM openai_api_calls WHERE owner_id=ANY(%s)',(list(ids.values()),)).fetchone()['n']==0


def test_student_consent_controls_current_profile_and_reset(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    assert student.put('/api/player-profile',json={'expected_revision':0,'answers':{'goal':'decisions','goal_note':'Private preference'}}).status_code==200
    assert coach.get(base).json()['player_profile'] is None
    assert coach.put(base+'/consent',json={'share_profile':True}).status_code==403
    assert student.put(base+'/consent',json={'share_profile':True}).status_code==200
    assert coach.get(base).json()['player_profile']['profile']['answers']['goal']=='decisions'
    assert student.delete('/api/player-profile').status_code==200
    assert coach.get(base).json()['player_profile']['profile']['answers']=={}
    assert student.put(base+'/consent',json={'share_profile':False}).status_code==200
    assert coach.get(base).json()['player_profile'] is None


def test_only_owned_current_shared_reports_and_allowed_fields(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    mine=seed(ids['student']);foreign=seed(ids['other'],2000)
    assert student.put(base+'/reports/'+foreign).status_code==404
    assert coach.put(base+'/reports/'+mine).status_code==403
    assert student.put(base+'/reports/'+mine).status_code==200
    detail=coach.get(base).json();view=detail['reports'][0]
    assert view['ai_points'][0]['alternative']=='Look at support first.'
    assert 'PRIVATE' not in str(detail) and 'account_id' not in str(detail) and 'private.dem' not in str(detail)
    assert coach.post(base+'/reports/'+mine+'/reviewed').status_code==200
    assert coach.get(base).json()['reports'][0]['reviewed_at'] is not None
    message={'id':str(uuid4()),'body':'Review this episode','job_id':mine,'evidence_id':'e10'}
    assert coach.post(base+'/messages',json={**message,'evidence_id':'invented'}).status_code==400
    assert coach.post(base+'/messages',json=message).status_code==201
    assert coach.post(base+'/messages',json=message).status_code==201
    assert len(student.get(base).json()['messages'])==1
    with database() as con:
        con.execute("UPDATE replay_jobs SET result_payload=jsonb_set(result_payload,'{metrics,kills}','99') WHERE id=%s",(mine,))
    data=coach.get(base).json();assert data['reports'][0]['unavailable'] and data['messages']==[]
    assert coach.post(base+'/messages',json={**message,'id':str(uuid4())}).status_code==409
    assert student.put(base+'/reports/'+mine).status_code==200
    assert coach.get(base).json()['reports'][0]['metrics']['kills']==99
    assert coach.get(base).json()['reports'][0]['reviewed_at'] is None
    assert student.delete(base+'/reports/'+mine).status_code==200
    assert coach.get(base).json()['reports']==[]
    assert student.get(P).json()['relationships'][0]['unread']==0
    assert coach.post(base+'/messages',json={**message,'id':str(uuid4())}).status_code==404


def test_deleting_replay_and_changing_bound_player_remove_access(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    mine=seed(ids['student']);student.put(base+'/reports/'+mine)
    with database() as con:con.execute("UPDATE replay_jobs SET state='deleted' WHERE id=%s",(mine,))
    assert coach.get(base).json()['reports'][0]['unavailable']
    with database() as con:
        con.execute("UPDATE replay_jobs SET state='ready' WHERE id=%s",(mine,))
        con.execute('UPDATE portal_dota_profiles SET account_id=9999 WHERE owner_id=%s',(ids['student'],))
    assert coach.get(base).json()['reports'][0]['unavailable']


def test_one_human_task_student_submission_and_explicit_human_review(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    created=task(coach,base);assert created.status_code==201,created.text
    tid=created.json()['id'];assert task(coach,base).status_code==409
    assert task(student,base).status_code==403
    assert task(coach,base,id=tid).json()['id']==tid
    path=base+'/tasks/'+tid
    submit={'expected_revision':1,'action':'submit','note':'I checked support before moving.'}
    assert coach.put(path,json=submit).status_code==403
    assert student.put(path,json=submit).status_code==200
    assert student.put(path,json=submit).status_code==409
    assert student.put(path,json={'expected_revision':2,'action':'complete','note':'Approve myself.'}).status_code==403
    assert coach.put(path,json={'expected_revision':2,'action':'revise','note':'Add the information you had.'}).status_code==200
    assert student.put(path,json={**submit,'expected_revision':3}).status_code==200
    assert coach.put(path,json={'expected_revision':4,'action':'complete','note':'Decision explained; next check in a similar situation.'}).status_code==200
    result=student.get(base).json()['tasks'][0]
    assert result['state']=='completed' and result['revision']==5
    assert task(coach,base).status_code==201


def test_revocation_closes_every_route_and_suspension_blocks_trainer(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    mine=seed(ids['student']);student.put(base+'/reports/'+mine)
    assert student.put(base+'/consent',json={'share_profile':True}).status_code==200
    assert owner.put(P+'/applications/'+ids['coach'],json={'status':'suspended','expected_revision':2,'current_password':PASSWORD}).status_code==200
    assert coach.get(base).status_code==404 and coach.post(P+'/invitations').status_code==403
    assert coach.get(P).json()['relationships']==[]
    assert student.get(base).status_code==200
    assert other.delete(base).status_code==404
    assert student.delete(base).status_code==200
    for actor in (coach,student):
        assert actor.get(base).status_code==404
        assert actor.put(base+'/reports/'+mine).status_code==404
        assert task(actor,base).status_code==404
        assert actor.post(base+'/messages',json={'id':str(uuid4()),'body':'closed'}).status_code==404
    with database() as con:
        assert not con.execute('SELECT share_profile FROM coaching_links WHERE id=%s',(lid,)).fetchone()['share_profile']
        assert con.execute('SELECT count(*) AS n FROM coaching_shares WHERE link_id=%s',(lid,)).fetchone()['n']==0


def test_concurrent_tasks_and_revocation_have_one_serialized_boundary(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;barrier=Barrier(2)
    def create(n):
        barrier.wait(timeout=10)
        try:
            hc.create_task(ids['coach'],UUID(lid),hc.Task(id=uuid4(),title='Synthetic task',instruction='Check one available signal.',criterion='Explain the chosen signal.'))
            return 201
        except HTTPException as error:return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(create,(1,2)))==[201,409]
    hc.revoke(ids['student'],UUID(lid))
    with pytest.raises(HTTPException) as error:hc.workspace(ids['coach'],UUID(lid))
    assert error.value.status_code==404


def test_messages_pagination_acknowledgment_and_safe_meeting(actors):
    lid,_=connected(actors);owner,coach,student,other,ids=actors;base=P+'/links/'+lid
    for n in range(52):
        response=student.post(base+'/messages',json={'id':str(uuid4()),'body':f'Synthetic message {n}'})
        assert response.status_code==201,response.text
    view=coach.get(base).json();assert len(view['messages'])==50 and view['older_before']
    old=coach.get(base+'?before='+str(view['older_before'])).json();assert len(old['messages'])==2
    assert coach.post(base+'/seen',json={'seq':view['messages'][-1]['seq']}).status_code==200
    assert coach.get(P).json()['relationships'][0]['unread']==0
    for value in ('javascript:alert(1)','http://call.example','https://name:pass@call.example'):
        assert coach.put(base+'/meeting',json={'expected_revision':0,'url':value}).status_code==400
    body={'expected_revision':0,'url':'https://call.example/room','starts_at':'2026-10-01T12:00:00Z'}
    assert student.put(base+'/meeting',json=body).status_code==403
    assert coach.put(base+'/meeting',json=body).status_code==200
    assert coach.put(base+'/meeting',json=body).status_code==409
    assert student.get(base).json()['meeting']['url']=='https://call.example/room'
