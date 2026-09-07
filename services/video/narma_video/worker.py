import argparse
import hashlib
import json
import os
import shutil
import time
from uuid import uuid4
from uuid import UUID

from psycopg.types.json import Jsonb
from .config import job_directory
from .db import database
from .frames import probe, decode, batches
from .gemini import GeminiVision
from . import budget as ai_budget

def heartbeat(model):
    with database() as connection:
        connection.execute("INSERT INTO video_workers(id,model) VALUES ('vision',%s) ON CONFLICT(id) DO UPDATE SET model=excluded.model,last_seen=now()", (model,))

def cleanup_deleted():
    with database() as connection:
        rows=connection.execute("SELECT id FROM video_jobs WHERE state='deleted' AND storage_deleted_at IS NULL LIMIT 20").fetchall()
    for row in rows:
        try:
            directory=job_directory(row['id'])
            if directory.exists():
                shutil.rmtree(directory)
            with database() as connection:
                connection.execute("UPDATE video_jobs SET storage_deleted_at=now() WHERE id=%s AND state='deleted'",(row['id'],))
        except OSError:
            pass  # Preserve quota reservation until removal actually succeeds.

def claim(job_id=None):
    with database() as connection:
        connection.execute("UPDATE video_jobs SET state='failed',failure_code='ATTEMPTS_EXHAUSTED',lease_token=NULL,lease_expires_at=NULL WHERE state='processing' AND lease_expires_at<now() AND attempt>=3")
        token=uuid4()
        return connection.execute("""UPDATE video_jobs SET state='processing',attempt=attempt+1,lease_token=%s,
            lease_expires_at=now()+interval '10 minutes',updated_at=now()
            WHERE id=(SELECT id FROM video_jobs WHERE (state='queued' OR (state='processing' AND lease_expires_at<now()))
              AND attempt<3 AND (%s::uuid IS NULL OR id=%s::uuid) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *""", (token,job_id,job_id)).fetchone()

def renew(job):
    with database() as connection:
        result=connection.execute("UPDATE video_jobs SET lease_expires_at=now()+interval '10 minutes',updated_at=now() WHERE id=%s AND state='processing' AND lease_token=%s AND lease_expires_at>now() RETURNING id", (job["id"],job["lease_token"])).fetchone()
        if not result:
            raise ValueError("VIDEO_LEASE_LOST")

def save_batch(job, frames, result):
    payload=result.model_dump()
    payload["frames"]=[{key:value for key,value in frame.items() if key!="image"} for frame in frames]
    with database() as connection:
        row=connection.execute("SELECT processed_frames,state,lease_token FROM video_jobs WHERE id=%s AND lease_expires_at>now() FOR UPDATE", (job["id"],)).fetchone()
        if not row or row["state"]!="processing" or row["lease_token"]!=job["lease_token"]:
            raise ValueError("VIDEO_LEASE_LOST")
        if row["processed_frames"] != frames[0]["frame_id"]:
            raise ValueError("VIDEO_FRAME_COVERAGE_MISMATCH")
        connection.execute("INSERT INTO video_batches(job_id,first_frame,last_frame,first_pts_seconds,last_pts_seconds,payload) VALUES (%s,%s,%s,%s,%s,%s)",
            (job["id"],frames[0]["frame_id"],frames[-1]["frame_id"],frames[0]["pts_seconds"],frames[-1]["pts_seconds"],Jsonb(payload)))
        connection.execute("UPDATE video_jobs SET processed_frames=%s,updated_at=now(),lease_expires_at=now()+interval '10 minutes' WHERE id=%s", (frames[-1]["frame_id"]+1,job["id"]))

def reserve_provider_call(job, frames, model):
    # Reserve before dispatch. Crashes and provider failures still consume budget.
    job_limit=int(os.environ.get('VIDEO_REQUEST_BUDGET','250'))
    daily_limit=int(os.environ.get('VIDEO_OWNER_DAILY_REQUEST_BUDGET','1000'))
    with database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))",(job['owner_id'],))
        active=connection.execute("SELECT id FROM video_jobs WHERE id=%s AND state='processing' AND lease_token=%s AND lease_expires_at>now() FOR UPDATE",(job['id'],job['lease_token'])).fetchone()
        if not active:
            raise ValueError('VIDEO_LEASE_LOST')
        limits=connection.execute("SELECT count(*) FILTER(WHERE job_id=%s) AS job_calls,count(*) FILTER(WHERE created_at>now()-interval '1 day') AS daily_calls FROM video_provider_calls WHERE owner_id=%s",(job['id'],job['owner_id'])).fetchone()
        if limits['job_calls']>=job_limit or limits['daily_calls']>=daily_limit:
            raise ValueError('VIDEO_REQUEST_BUDGET_EXCEEDED')
        return ai_budget.reserve(connection,job,frames,model)

def run_job(job, vision):
    source=job_directory(job["id"])/"source"
    with source.open("rb") as stream:
        if hashlib.file_digest(stream,"sha256").hexdigest()!=job["source_sha256"]:
            raise ValueError("VIDEO_SOURCE_CHANGED")
    metadata=probe(source); renew(job)
    # A cost ceiling rejects the whole job before inference; it never samples it.
    budget=int(os.environ.get('VIDEO_FRAME_BUDGET','3600'))
    if budget<1 or budget>432000 or metadata['frame_count']>budget:
        raise ValueError('VIDEO_FRAME_BUDGET_EXCEEDED')
    with database() as connection:
        previous=connection.execute("SELECT payload FROM video_batches WHERE job_id=%s ORDER BY first_frame DESC LIMIT 1", (job["id"],)).fetchone()
        current=connection.execute("UPDATE video_jobs SET frame_count=%s,duration_seconds=%s,first_pts_seconds=%s,model=%s WHERE id=%s AND state='processing' AND lease_token=%s AND (frame_count IS NULL OR frame_count=%s) AND (model IS NULL OR model=%s) AND schema_version=1 RETURNING id", (metadata["frame_count"],metadata["duration_seconds"],metadata["first_pts_seconds"],vision.model,job["id"],job["lease_token"],metadata["frame_count"],vision.model)).fetchone()
        if not current:
            raise ValueError("VIDEO_SOURCE_OR_MODEL_CHANGED")
    continuity=previous["payload"]["continuity"] if previous else ""
    decoded=decode(source,metadata)
    try:
        for group in batches(decoded,after_frame=job["processed_frames"]-1):
            renew(job); heartbeat(vision.model)
            call_id=reserve_provider_call(job,group,vision.model)
            vision.last_usage=None
            try:
                result=vision.analyze(group,job["nickname"],continuity)
            finally:
                ai_budget.settle(call_id,vision.last_usage)
            save_batch(job,group,result)
            continuity=result.continuity
    finally:
        decoded.close()
    with database() as connection:
        completed=connection.execute("UPDATE video_jobs SET state='ready',lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE id=%s AND state='processing' AND lease_token=%s AND lease_expires_at>now() AND processed_frames=frame_count RETURNING id", (job["id"],job["lease_token"])).fetchone()
        if not completed:
            raise ValueError("VIDEO_FRAME_COVERAGE_MISMATCH")

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--once",action="store_true");parser.add_argument('--job-id',type=UUID);args=parser.parse_args()
    if args.job_id and not args.once:
        parser.error('--job-id requires --once')
    vision=GeminiVision()  # Fail before claiming jobs when credentials are absent.
    while True:
        cleanup_deleted(); heartbeat(vision.model); job=claim(args.job_id)
        if job:
            try:
                run_job(job,vision)
            except Exception as error:
                # Provider errors may contain request data. Never log raw exceptions.
                known=isinstance(error,ValueError) and str(error).startswith(("VIDEO_","GEMINI_"))
                code=str(error) if known else "VIDEO_PROVIDER_OR_PROCESS_FAILURE"
                provider_status=getattr(error,'code',None)
                if type(provider_status) is not int or not 100<=provider_status<=599:
                    provider_status=None
                # Class/status and fixed categories diagnose integration errors without
                # logging provider text, prompts, headers or API keys.
                category='unknown'
                description=str(error).lower()
                for pattern,label in [('service_tier','service_tier'),('servicetier','service_tier'),
                    ('thinking_level','thinking_level'),('thinkinglevel','thinking_level'),
                    ('response_json_schema','response_schema'),('responsejsonschema','response_schema'),
                    ('api key','api_key'),('permission','permission'),('quota','quota'),
                    ('not found','not_found'),('timed out','timeout')]:
                    if pattern in description: category=label;break
                print(json.dumps({'event':'video_provider_failure','class':type(error).__name__,
                    'status':provider_status,'category':category}),flush=True)
                print(json.dumps({"event":"video_attempt_failed","id":str(job["id"]),"code":code}),flush=True)
                with database() as connection:
                    connection.execute("UPDATE video_jobs SET state=%s,failure_code=%s,lease_token=NULL,lease_expires_at=NULL,updated_at=now() WHERE id=%s AND state='processing' AND lease_token=%s", ("failed" if known or job["attempt"]>=3 else "queued",code,job["id"],job["lease_token"]))
                if not known and not args.once:
                    time.sleep(30)
        elif not args.once:
            time.sleep(5)
        if args.once:
            break

if __name__=="__main__":
    main()
