"""One durable four-frame pipeline check, then start the budgeted worker."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from uuid import uuid4

def main():
    os.umask(0o077)
    sha=sys.argv[1]
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError()
    root=Path('/opt/narma/releases')/sha/'services/video'
    compose=['docker','compose','--project-name','narma-video','--env-file','/opt/narma/secrets/video.env','--file',str(root/'compose.yaml')]
    def run(args,timeout=120):
        result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        if result.returncode:
            raise RuntimeError('video_activation_command_failed')
        return result.stdout
    values=dict(line.split('=',1) for line in Path('/opt/narma/secrets/video.env').read_text().splitlines())
    token=values['VIDEO_SERVICE_TOKEN']
    def call(path,method='GET',body=None):
        headers={'Authorization':'Bearer '+token,'X-Narma-Owner':'narma_system_pipeline_check'}
        if isinstance(body,dict):
            headers['Content-Type']='application/json';body=json.dumps(body).encode()
        request=urllib.request.Request('http://127.0.0.1:8080'+path,method=method,data=body,headers=headers)
        with urllib.request.urlopen(request,timeout=30) as response:
            return json.loads(response.read(1024*1024))
    marker=Path('/opt/narma/checks/video-pipeline-v1.json');marker.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if marker.exists():
        if json.loads(marker.read_text()).get('state')!='passed':
            snippet="""import json
from narma_video.db import database
with database() as c:
 rows=c.execute("SELECT usage,billing_status FROM video_provider_calls WHERE owner_id='narma_system_pipeline_check' ORDER BY id DESC LIMIT 1").fetchall()
for row in rows:
 u=row['usage'] or {}; clean={k:v for k,v in u.items() if k.startswith('total_') and (type(v) is int or v is None)}
 for k in ('input_tokens_by_modality','output_tokens_by_modality','cached_tokens_by_modality','tool_use_tokens_by_modality','grounding_tool_count'):
  if isinstance(u.get(k),list): clean[k]=[{a:v for a,v in item.items() if a in ('tokens','count','modality','type') and (type(v) is int or v in ('text','image','audio','video','document','google_search','google_maps','retrieval'))} for item in u[k] if isinstance(item,dict)]
 def numeric_shape(value,depth=0):
  if depth>5: return 'depth_limit'
  if value is None or type(value) in (int,float,bool): return value
  if isinstance(value,list): return [numeric_shape(v,depth+1) for v in value[:20]]
  if isinstance(value,dict): return {k:numeric_shape(v,depth+1) for k,v in list(value.items())[:20] if re.fullmatch('[a-zA-Z_]{1,100}',k)}
  return {'type':type(value).__name__,'length':len(value) if isinstance(value,str) else None}
 import re
 for k in ('model_invocation_token_counts','raw_prompt_token'):
  if k in u: clean[k]=numeric_shape(u[k])
 print(json.dumps({'event':'provider_usage_diagnostic','keys':sorted(u.keys()),'usage':clean,'billing_status':row['billing_status']}))
"""
            diagnostic=run(compose+['exec','-T','api','python','-c',snippet])
            print(diagnostic.decode().strip(),flush=True)
            raise RuntimeError('video_pipeline_previous_attempt_unresolved')
    else:
        job=str(uuid4())
        # This transport fixture is deliberately not a Dota replay/coaching test.
        video=run(compose+['exec','-T','api','ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
            'testsrc2=size=384x216:rate=4','-frames:v','4','-c:v','libx264','-threads','1',
            '-movflags','frag_keyframe+empty_moov','-f','mp4','pipe:1'])
        call('/v1/videos','POST',{'id':job,'filename':'pipeline-fixture.mp4','size_bytes':len(video),
            'account_id':1,'nickname':'NARMA_TRANSPORT_FIXTURE_NOT_A_DOTA_PLAYER'})
        call('/v1/videos/'+job+'/parts/1','PUT',video)
        call('/v1/videos/'+job+'/complete','POST')
        with marker.open('x') as file:
            json.dump({'state':'attempted','job':job,'release':sha},file);file.flush();os.fsync(file.fileno())
        directory_fd=os.open(marker.parent,os.O_DIRECTORY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
        name='narma-pipeline-'+uuid4().hex
        try:
            run(compose+['--profile','analysis','run','--rm','--no-deps','--name',name,'worker',
                'python','-m','narma_video.worker','--once','--job-id',job],timeout=210)
        finally:
            subprocess.run(['docker','rm','--force',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        result=call('/v1/videos/'+job)
        if result['video']['state']!='ready' or result['video']['processed_frames']!=4 or result['video']['frame_count']!=4:
            code=result['video'].get('failure_code')
            if isinstance(code,str) and re.fullmatch('[A-Z_]{1,100}',code):
                print(json.dumps({'event':'video_pipeline_failure','code':code}),flush=True)
            raise RuntimeError('video_pipeline_incomplete')
        if any(batch['payload']['findings'] or batch['payload']['focus_player_visible'] for batch in result['batches']):
            raise RuntimeError('video_pipeline_invented_player')
        # Validate the downloaded bytes through the authenticated Range endpoint.
        request=urllib.request.Request('http://127.0.0.1:8080/v1/videos/'+job+'/source',headers={
            'Authorization':'Bearer '+token,'X-Narma-Owner':'narma_system_pipeline_check','Range':'bytes=0-31'})
        with urllib.request.urlopen(request,timeout=20) as response:
            if response.status!=206 or response.read(64)!=video[:32]:
                raise RuntimeError('video_pipeline_playback_failed')
        call('/v1/videos/'+job,'DELETE')
        temporary=marker.with_suffix('.new');temporary.write_text(json.dumps({'state':'passed','job':job,'release':sha,'frames':4}));temporary.replace(marker)
    run(compose+['--profile','analysis','up','-d','--no-deps','worker'])
    print(json.dumps({'event':'video_pipeline_ready','frames':4,'scope':'synthetic_transport_only','worker_enabled':True}),flush=True)

if __name__=='__main__':
    try: main()
    except Exception as error:
        code=str(error) if isinstance(error,RuntimeError) and re.fullmatch('[a-z_]{1,100}',str(error)) else 'video_activation_failed'
        print(json.dumps({'event':'video_activation_failure','code':code}),flush=True);sys.exit(1)
