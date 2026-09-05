import assert from 'node:assert/strict';
import test,{after} from 'node:test';
import {createServer} from 'vite';
import {fileURLToPath} from 'node:url';
import {database} from './sqlite-d1.mjs';
import {makeOpenDotaMatch,makeReport} from './analysis-test-helpers.mjs';
import {createReplayMetadata,acceptReplayEvent,assembleReplayMatch} from '../ops/replay-adapter.mjs';
const root=fileURLToPath(new URL('..',import.meta.url));
const key='__REPLAY_PIPELINE_TEST__';
const vite=await createServer({appType:'custom',configFile:false,root,resolve:{alias:{'@':root}},plugins:[{
  name:'replay-test-bindings',enforce:'pre',resolveId(source){
    if(source==='cloudflare:workers')return '\0replay-env';
    if(source==='@/lib/auth/api-account'||source.startsWith(`${root}/lib/auth/api-account`))return '\0replay-account';
  },load(id){
    if(id==='\0replay-env')return `export const env=new Proxy({}, {get(_t,p){return globalThis.${key}.env[p]}});`;
    if(id==='\0replay-account')return `export class AccountApiError extends Error{constructor(message,status){super(message);this.status=status;}}
      export async function requireApiAccount(){const s=globalThis.${key};if(!s.owner)throw new AccountApiError('auth',401);return {account:{id:s.owner},db:s.env.DB};}
      export function accountJson(body,status=200){return Response.json(body,{status});}
      export function accountApiError(error){return accountJson({error:error.message},error.status??503);}`;
  },
}],server:{middlewareMode:true,hmr:false,ws:false}});
after(async()=>{await vite.close();delete globalThis[key];});
const modules=await Promise.all(['/app/api/replays/route.ts','/app/api/replays/[id]/route.ts','/app/api/replay-worker/claim/route.ts','/app/api/replay-worker/[id]/route.ts','/lib/replay/map-state.ts','/lib/analysis/normalizer.ts','/lib/analysis/grounding.ts'].map(p=>vite.ssrLoadModule(p)));
const [uploads,file,claim,worker,map,normalizer,grounding]=modules;
const token='test-worker-token-with-more-than-thirty-two-characters';
function bucketMock(){
  const objects=new Map(),sessions=new Map();let partCalls=0;
  const bucket={objects,sessions,failAbort:false,blockPart:null,get partCalls(){return partCalls;},
    async createMultipartUpload(key){const uploadId=crypto.randomUUID();sessions.set(uploadId,{key,parts:new Map()});return this.resumeMultipartUpload(key,uploadId);},
    resumeMultipartUpload(key,uploadId){return {uploadId,async uploadPart(number,bytes){partCalls++;if(bucket.blockPart)await bucket.blockPart;const s=sessions.get(uploadId);if(!s)throw new Error('NoSuchUpload');s.parts.set(number,new Uint8Array(bytes));return {partNumber:number,etag:`etag-${number}-${partCalls}`};},async complete(parts){const s=sessions.get(uploadId);if(!s)throw new Error('NoSuchUpload');const bytes=Buffer.concat(parts.map(p=>s.parts.get(p.partNumber)));objects.set(key,bytes);sessions.delete(uploadId);},async abort(){if(bucket.failAbort)throw new Error('temporary storage error');if(!sessions.delete(uploadId))throw new Error('NoSuchUpload');}};},
    async head(key){const bytes=objects.get(key);return bytes?{size:bytes.length}:null;},
    async get(key){const bytes=objects.get(key);return bytes?{size:bytes.length,body:new Response(bytes).body}:null;},async delete(key){objects.delete(key);},
  };return bucket;
}
async function setup(){const {sqlite,d1}=await database();sqlite.exec("INSERT INTO users(id,display_name) VALUES ('owner','Owner'),('other','Other')");const bucket=bucketMock();globalThis[key]={owner:'owner',env:{DB:d1,REPLAYS:bucket,REPLAY_WORKER_TOKEN:token}};return {sqlite,bucket};}
const context=id=>({params:Promise.resolve({id})});
const req=(path,method='GET',body,headers={})=>new Request(`https://example.test${path}`,{method,headers:{...(body&&!(body instanceof Uint8Array)?{'Content-Type':'application/json'}:{}),...headers},...(body?{body:body instanceof Uint8Array?body:JSON.stringify(body)}:{})});
async function init(id=crypto.randomUUID()){const r=await uploads.POST(req('/api/replays','POST',{filename:'match.dem',sizeBytes:16},{'Idempotency-Key':id}));assert.equal(r.status,201,await r.clone().text());return (await r.json()).id;}
const bytes=new Uint8Array([...new TextEncoder().encode('PBDEMS2\0'),...Array(8).fill(0)]);
async function finish(id){assert.equal((await file.PUT(req(`/api/replays/${id}?part=1`,'PUT',bytes),context(id))).status,200);assert.equal((await file.POST(req(`/api/replays/${id}`,'POST'),context(id))).status,200);}
const machine=(lease,method='POST',body)=>req('/worker',method,body,{Authorization:`Bearer ${token}`,...(lease?{'x-replay-lease':lease}:{})});

test('init retry reuses one owner session and rejects a different file snapshot',async()=>{
 const {sqlite}=await setup();try{const id=await init();const r=await uploads.POST(req('/api/replays','POST',{filename:'match.dem',sizeBytes:16},{'Idempotency-Key':id}));assert.equal(r.status,200);assert.equal((await r.json()).id,id);assert.equal(sqlite.prepare('SELECT COUNT(*) AS n FROM replay_uploads').get().n,1);
 const conflict=await uploads.POST(req('/api/replays','POST',{filename:'different.dem',sizeBytes:16},{'Idempotency-Key':id}));assert.equal(conflict.status,409);
 }finally{sqlite.close();}
});
test('failed parsing continues to consume storage quota',async()=>{
 const {sqlite}=await setup();try{for(let i=0;i<2;i++)sqlite.prepare("INSERT INTO replay_uploads(id,user_id,filename,object_key,size_bytes,state) VALUES (?,'owner','bad.dem',?,536870912,'failed')").run(crypto.randomUUID(),`key${i}`);
 const r=await uploads.POST(req('/api/replays','POST',{filename:'match.dem',sizeBytes:16},{'Idempotency-Key':crypto.randomUUID()}));assert.equal(r.status,429);
 }finally{sqlite.close();}
});
test('part writes serialize and a different owner cannot read or mutate the upload',async()=>{
 const {sqlite,bucket}=await setup();try{const id=await init();globalThis[key].owner='other';assert.equal((await file.GET(req('/'),context(id))).status,404);globalThis[key].owner='owner';
 let unblock;bucket.blockPart=new Promise(resolve=>{unblock=resolve;});const first=file.PUT(req('/?part=1','PUT',bytes),context(id));
 while(!bucket.partCalls)await new Promise(r=>setImmediate(r));
 assert.equal((await file.PUT(req('/?part=1','PUT',bytes),context(id))).status,409);unblock();assert.equal((await first).status,200);assert.equal(bucket.partCalls,1);
 assert.equal((await file.POST(req('/','POST'),context(id))).status,200);assert.equal((await file.POST(req('/','POST'),context(id))).status,200);
 }finally{sqlite.close();}
});
test('cleanup retains quota on abort failure, then supports retry and expired worker leases',async()=>{
 const {sqlite,bucket}=await setup();try{const id=await init();bucket.failAbort=true;assert.equal((await file.DELETE(req('/','DELETE'),context(id))).status,503);assert.equal(sqlite.prepare('SELECT failure_code FROM replay_uploads WHERE id=?').get(id).failure_code,'DELETE_PENDING');bucket.failAbort=false;assert.equal((await file.DELETE(req('/','DELETE'),context(id))).status,200);
 for(const state of ['uploading','processing']){const orphan=crypto.randomUUID();sqlite.prepare("INSERT INTO replay_uploads(id,user_id,filename,object_key,size_bytes,state,lease_token,lease_expires_at) VALUES (?,'owner','x.dem',?,16,?,'dead',datetime('now','-1 minute'))").run(orphan,orphan,state);assert.equal((await file.DELETE(req('/','DELETE'),context(orphan))).status,200);}
 }finally{sqlite.close();}
});
test('worker claims and result callbacks survive duplicate delivery without exposing files to another owner',async()=>{
 const {sqlite}=await setup();try{const id=await init();await finish(id);assert.equal((await claim.POST(req('/','POST'))).status,401);
 const claimKey=crypto.randomUUID();const request=()=>req('/','POST',undefined,{Authorization:`Bearer ${token}`,'Idempotency-Key':claimKey});const a=await(await claim.POST(request())).json(),b=await(await claim.POST(request())).json();assert.equal(a.job.id,id);assert.equal(b.job.id,id);assert.equal(sqlite.prepare('SELECT attempt FROM replay_uploads WHERE id=?').get(id).attempt,1);
 const payload={match:makeOpenDotaMatch({patch:'7.41'})};const first=await worker.POST(machine(claimKey,'POST',payload),context(id));assert.equal(first.status,200,await first.clone().text());assert.equal((await worker.POST(machine(claimKey,'POST',payload),context(id))).status,200);assert.equal((await worker.POST(machine(claimKey,'POST',{match:makeOpenDotaMatch({duration:1801,patch:'7.41'})}),context(id))).status,409);
 globalThis[key].owner='other';assert.equal((await file.GET(req('/'),context(id))).status,404);globalThis[key].owner='owner';assert.equal((await file.DELETE(req('/','DELETE'),context(id))).status,200);
 }finally{sqlite.close();}
});
test('map coordinates, pregame wards and rewind use replay facts',()=>{
 assert.deepEqual(map.worldToPercent(-10464,10400),{left:0,top:0});assert.deepEqual(map.worldToPercent(10400,-10464),{left:100,top:100});assert.deepEqual(map.gridToWorld(128,128),{x:0,y:0});
 const ward={placedAt:-30,removedAt:400};assert.equal(map.wardStateAt(ward,-31),'not_placed');assert.equal(map.wardStateAt(ward,0),'active');assert.equal(map.wardStateAt(ward,400),'removed');assert.equal(map.wardStateAt({...ward,removedAt:null},900),'unknown');
 const key='npc_dota_goodguys_tower1_mid',events=[{key,destroyedAt:800}];assert.equal(map.buildingStateAt(key,events,800,true).state,'destroyed');assert.equal(map.buildingStateAt(key,events,799,true).state,'standing');assert.equal(map.buildingStateAt(key,[],0,false).state,'unknown');
 assert.equal(map.buildingStateAt('npc_dota_goodguys_tower4_top',[{key:'npc_dota_goodguys_tower4',destroyedAt:1000}],1200,true).state,'unknown');
});
test('pregame objective survives normalization and valid numeric evidence cannot launder invented vision advice',async()=>{
 const match=normalizer.normalizeOpenDotaMatch(makeOpenDotaMatch({objectives:[{time:-30,type:'CHAT_MESSAGE_FIRSTBLOOD',slot:0,team:2}]}));assert.equal(match.objectives[0].timeSeconds,-30);
 const {evidenceBundle,evidenceHash}=await normalizer.buildEvidenceBundle(match);const report=makeReport(evidenceHash);report.items[0].time={type:"point",seconds:-30};report.items[0].body='Вы погибли из-за отсутствия вижена. Нужно было нажать BKB.';
 const compiled=await grounding.validateGroundedReport(report,evidenceBundle,{evidenceHash,playerSlot:0});assert.doesNotMatch(JSON.stringify(compiled),/погибли из-за|нажать BKB/);
});
function replayState(){const s=createReplayMetadata();acceptReplayEvent(s,{type:'epilogue',key:JSON.stringify({gameInfo_:{dota_:{matchId_:8963624400,gameWinner_:2,gameMode_:22}}})});for(let i=0;i<10;i++){acceptReplayEvent(s,{type:'player_slot',key:String(i),value:i<5?i:128+i-5});acceptReplayEvent(s,{type:'interval',slot:i,hero_id:i+1,time:0,x:128,y:128,life_state:0,kills:i,lh:10,networth:1000+i,xp:500+i});}acceptReplayEvent(s,{type:'DOTA_COMBATLOG_GAME_STATE',time:1800,value:6});return s;}
test('adapter requires complete metadata, preserves stats and leaves missing economy samples empty',()=>{
 const state=replayState();const result=assembleReplayMatch(state,{players:Array.from({length:10},()=>({})),version:22});assert.equal(result.duration,1800);assert.equal(result.players[3].kills,3);assert.equal(result.players[3].last_hits,10);assert.equal(result.radiant_gold_adv[0],-25);assert.equal(result.radiant_gold_adv[1],null);assert.equal(result.radiant_gold_adv.length,31);assert.equal(result._narma_hero_positions.length,10);
 state.dota=null;assert.throws(()=>assembleReplayMatch(state,{players:[]}),/REPLAY_INCOMPLETE/);
 const pre=createReplayMetadata();acceptReplayEvent(pre,{type:'interval',slot:0,hero_id:1,time:-60});assert.doesNotThrow(()=>acceptReplayEvent(pre,{type:'interval',slot:0,hero_id:2,time:-30}));assert.throws(()=>acceptReplayEvent(pre,{type:'interval',slot:0,hero_id:3,time:1}),/HERO_CHANGED/);
});
