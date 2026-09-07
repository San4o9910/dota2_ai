import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from narma_video.frames import probe, decode, batches
from narma_video.gemini import validate_result
from narma_video import worker
from narma_video import budget
from narma_video.api import app
from narma_video.db import migrate, database

@pytest.fixture
def clip(tmp_path):
    target=tmp_path/'clip.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=20','-frames:v','40','-c:v','libx264','-threads','1',str(target)],check=True,timeout=30)
    return target

def test_all_cfr_frames_and_batch_resume(clip):
    metadata=probe(clip)
    frames=list(decode(clip,metadata))
    assert len(frames)==metadata['frame_count']==40
    assert [f['frame_id'] for f in frames]==list(range(40))
    assert frames[-1]['video_seconds']==pytest.approx(1.95)
    assert len({f['sha256'] for f in frames})>30
    assert [len(group) for group in batches(iter(frames),after_frame=15)]==[16,8]
    assert all(f['image'].startswith(b'\xff\xd8') for f in frames)

def test_vfr_preserves_gaps_and_source_pts(tmp_path):
    target=tmp_path/'vfr.mkv'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=128x96:rate=10:duration=1.2',
        '-vf',"select='eq(n,0)+eq(n,1)+eq(n,3)+eq(n,4)+eq(n,7)+eq(n,11)',setpts=PTS+2/TB",'-fps_mode','passthrough','-c:v','ffv1','-threads','1',str(target)],check=True,timeout=30)
    frames=list(decode(target,probe(target)))
    assert len(frames)==6
    assert [f['pts_seconds'] for f in frames]==pytest.approx([2,2.1,2.3,2.4,2.7,3.1])
    assert [f['video_seconds'] for f in frames]==pytest.approx([0,.1,.3,.4,.7,1.1])

def test_reject_corrupt_video_and_incomplete_model_coverage(tmp_path):
    bad=tmp_path/'bad.mp4';bad.write_bytes(b'bad media')
    with pytest.raises(ValueError,match='VIDEO_PROBE'):
        probe(bad)
    frames=[{'frame_id':7},{'frame_id':8}]
    response={'reviewed_frame_ids':[7], 'focus_player_visible':False,'findings':[],'continuity':''}
    with pytest.raises(ValueError,match='COVERAGE'):
        validate_result(response,frames)
    response.update(reviewed_frame_ids=[7,8],focus_player_visible=True,findings=[{'frame_id':9,'observation':'x','advice':'','confidence':'low'}])
    with pytest.raises(ValueError,match='EVIDENCE'):
        validate_result(response,frames)

@pytest.fixture
def api(monkeypatch,tmp_path):
    url=os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set an isolated TEST_DATABASE_URL for PostgreSQL integration')
    monkeypatch.setenv('DATABASE_URL',url)
    monkeypatch.setenv('VIDEO_STORAGE_PATH',str(tmp_path/'media'))
    monkeypatch.setenv('VIDEO_SERVICE_TOKEN','test-only-'+'x'*40)
    monkeypatch.setenv('VIDEO_FRAME_BUDGET','3600')
    monkeypatch.setenv('VIDEO_REQUEST_BUDGET','250')
    monkeypatch.setenv('VIDEO_OWNER_DAILY_REQUEST_BUDGET','1000')
    migrate();migrate()  # Migrations must be idempotent.
    with database() as conn:
        conn.execute("UPDATE video_ai_budget SET enabled=true,model='gemini-3.8-flash',price_policy='gemini-3.8-flash-standard-2026-09-07',expires_at='2027-01-01T00:00:00Z',limit_microusd=10000000,spent_microusd=0,reserved_microusd=0,frozen_reason=NULL WHERE id=1")
    owner='test_'+uuid4().hex
    client=TestClient(app)
    client.headers.update({'Authorization':'Bearer test-only-'+'x'*40,'X-Narma-Owner':owner})
    yield client,owner
    with database() as conn:
        conn.execute('DELETE FROM video_provider_calls WHERE owner_id=%s',(owner,))
        conn.execute('DELETE FROM video_jobs WHERE owner_id=%s',(owner,))

def upload(api,clip):
    client,owner=api
    job=str(uuid4())
    payload={'id':job,'filename':'match.mp4','size_bytes':clip.stat().st_size,'account_id':123,'nickname':'player_test'}
    created=client.post('/v1/videos',json=payload)
    assert created.status_code==201,created.text
    assert client.post('/v1/videos',json=payload).status_code==201
    assert client.put(f'/v1/videos/{job}/parts/1',content=clip.read_bytes()).status_code==200
    assert client.get(f'/v1/videos/{job}').json()['parts']==[1]
    assert client.post(f'/v1/videos/{job}/complete').status_code==200
    return job

class FakeVision:
    model='gemini-3.8-flash'
    def __init__(self,fail_on=None):
        self.seen=[];self.fail_on=fail_on
    def analyze(self,frames,nickname,continuity):
        assert nickname=='player_test'
        if self.fail_on==len(self.seen):
            raise ConnectionError('synthetic provider outage')
        self.last_usage={'total_input_tokens':100,'total_output_tokens':30,'total_thought_tokens':20,'total_tokens':150}
        self.seen.append([f['frame_id'] for f in frames])
        return validate_result({'reviewed_frame_ids':self.seen[-1],'focus_player_visible':True,'findings':[
            {'frame_id':frames[0]['frame_id'],'observation':'SYNTHETIC TEST ONLY','advice':'','confidence':'low'}],'continuity':'test'},frames)

def test_upload_owner_isolation_queue_video_range_and_delete(api,clip):
    client,owner=api;job_id=upload(api,clip)
    assert client.get(f'/v1/videos/{job_id}',headers={'X-Narma-Owner':'another'}).status_code==404
    assert client.get('/v1/videos',headers={'Authorization':'Bearer invalid'}).status_code==401
    claimed=worker.claim();assert str(claimed['id'])==job_id
    model=FakeVision();worker.run_job(claimed,model)
    result=client.get(f'/v1/videos/{job_id}').json()
    assert result['video']['state']=='ready'
    assert result['video']['processed_frames']==result['video']['frame_count']==40
    assert result['video']['identity_status']=='nickname_only'
    assert [f for group in model.seen for f in group]==list(range(40))
    assert result['batches'][1]['payload']['frames'][0]['video_seconds']==pytest.approx(.8)
    response=client.get(f'/v1/videos/{job_id}/source',headers={'Range':'bytes=0-31'})
    assert response.status_code==206 and response.content==clip.read_bytes()[:32]
    assert client.delete(f'/v1/videos/{job_id}').status_code==200
    assert client.get(f'/v1/videos/{job_id}/source').status_code==404
    assert client.delete(f'/v1/videos/{job_id}').status_code==200

def test_resume_preserves_saved_frames_and_rejects_model_change(api,clip):
    client,owner=api;job_id=upload(api,clip)
    claimed=worker.claim()
    with pytest.raises(ConnectionError):
        worker.run_job(claimed,FakeVision(fail_on=1))
    assert client.get(f'/v1/videos/{job_id}').json()['video']['processed_frames']==16
    with database() as conn:
        conn.execute("UPDATE video_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(job_id,))
    resumed=worker.claim();assert resumed['attempt']==2
    wrong=FakeVision();wrong.model='different-model'
    with pytest.raises(ValueError,match='MODEL_CHANGED'):
        worker.run_job(resumed,wrong)
    assert wrong.seen==[]
    model=FakeVision();worker.run_job(resumed,model)
    assert [f for group in model.seen for f in group]==list(range(16,40))
    assert client.get(f'/v1/videos/{job_id}').json()['video']['state']=='ready'

def test_request_budget_stops_before_paid_dispatch(api,clip,monkeypatch):
    client,owner=api;job_id=upload(api,clip)
    monkeypatch.setenv('VIDEO_REQUEST_BUDGET','1')
    claimed=worker.claim();model=FakeVision()
    with pytest.raises(ValueError,match='REQUEST_BUDGET'):
        worker.run_job(claimed,model)
    assert len(model.seen)==1
    assert client.get(f'/v1/videos/{job_id}').json()['video']['processed_frames']==16

def test_global_budget_serializes_competing_transactions(api,clip):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    job_id=upload(api,clip);job=worker.claim()
    with database() as conn:
        conn.execute('UPDATE video_ai_budget SET limit_microusd=%s WHERE id=1',(budget.RESERVATION,))
    barrier=Barrier(2)
    def attempt():
        barrier.wait(timeout=10)
        try:
            with database() as conn:
                budget.reserve(conn,job,[{'frame_id':0}],budget.MODEL)
            return 'reserved'
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(attempt) for _ in range(2)]
        assert sorted(f.result(timeout=30) for f in futures)==['VIDEO_GLOBAL_BUDGET_EXCEEDED','reserved']
    assert budget.status()['reserved_microusd']==budget.RESERVATION

def test_unknown_usage_retains_reservation_and_settlement_is_idempotent(api,clip):
    upload(api,clip);job=worker.claim()
    call=worker.reserve_provider_call(job,[{'frame_id':0}],budget.MODEL)
    budget.settle(call,None)
    assert budget.status()['reserved_microusd']==budget.RESERVATION
    usage={'total_input_tokens':100,'total_output_tokens':30,'total_thought_tokens':20,'total_tokens':150}
    budget.settle(call,usage)  # An uncertain attempt cannot be silently refunded later.
    assert budget.status()['reserved_microusd']==budget.RESERVATION
    second=worker.reserve_provider_call(job,[{'frame_id':0}],budget.MODEL)
    budget.settle(second,usage);budget.settle(second,usage)
    assert budget.status()['spent_microusd']==263
    assert budget.status()['reserved_microusd']==budget.RESERVATION

@pytest.mark.parametrize('extra',[
    {'total_thought_tokens':-1}, {'total_output_tokens':True}, {'total_tokens':201},
    {'grounding_tool_count':[{'type':'google_search','count':1}]},
    {'new_billable_field':1}, {'input_tokens_by_modality':[{'modality':'audio','tokens':100}]},
])
def test_invalid_usage_freezes_budget_without_refund(api,clip,extra):
    upload(api,clip);job=worker.claim()
    call=worker.reserve_provider_call(job,[{'frame_id':0}],budget.MODEL)
    usage={'total_input_tokens':100,'total_output_tokens':100,'total_thought_tokens':0,'total_tokens':200,**extra}
    with pytest.raises(ValueError,match='RECONCILIATION'):
        budget.settle(call,usage)
    assert not budget.status()['enabled']
    assert budget.status()['reserved_microusd']==budget.RESERVATION
    with database() as conn:
        assert conn.execute('SELECT usage FROM video_provider_calls WHERE id=%s',(call,)).fetchone()['usage']==usage

def test_usage_accounted_despite_invalid_result_and_expired_lease(api,clip):
    upload(api,clip);job=worker.claim()
    class InvalidOutput(FakeVision):
        def analyze(self,*args):
            self.last_usage={'total_input_tokens':100,'total_output_tokens':100,'total_thought_tokens':0,'total_tokens':200}
            with database() as conn:
                conn.execute("UPDATE video_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(job['id'],))
            raise ValueError('GEMINI_RESPONSE_INVALID')
    with pytest.raises(ValueError,match='RESPONSE_INVALID'):
        worker.run_job(job,InvalidOutput())
    assert budget.status()['spent_microusd']==450
    assert budget.status()['reserved_microusd']==0

@pytest.mark.parametrize('change',[
    "expires_at=now()-interval '1 second'", "expires_at='2028-01-01'", "model='other'", "limit_microusd=10000001",
])
def test_bad_policy_rejects_before_provider(api,clip,change):
    upload(api,clip);job=worker.claim()
    with database() as conn:
        conn.execute('UPDATE video_ai_budget SET '+change+' WHERE id=1')
    model=FakeVision()
    with pytest.raises(ValueError,match='BUDGET'):
        worker.run_job(job,model)
    assert not model.seen
    assert budget.status()['reserved_microusd']==0

def test_usage_bounds_breach_is_durably_frozen(api,clip):
    upload(api,clip);job=worker.claim()
    call=worker.reserve_provider_call(job,[{'frame_id':0}],budget.MODEL)
    with pytest.raises(ValueError,match='RECONCILIATION'):
        budget.settle(call,{'total_input_tokens':100,'total_output_tokens':500000,'total_thought_tokens':0,'total_tokens':500100})
    state=budget.status()
    assert not state['enabled'] and state['spent_microusd']==1875075
    assert state['reserved_microusd']==0
