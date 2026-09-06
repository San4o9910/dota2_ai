import assert from "node:assert/strict";
import test,{after} from "node:test";
import {createServer} from "vite";
import {analysisRoot,jsonResponse,makeOpenDotaMatch} from "./analysis-test-helpers.mjs";
import {database} from "./sqlite-d1.mjs";
import {metadataFixture} from "./demo-metadata-fixture.mjs";
const vite=await createServer({appType:"custom",configFile:false,root:analysisRoot,resolve:{alias:{"@":analysisRoot}},server:{middlewareMode:true},plugins:[{
  name:"metadata-env",enforce:"pre",resolveId(id){if(id==="cloudflare:workers")return "\0metadata-env";},load(id){if(id==="\0metadata-env")return "export const env={};";},
}]});after(()=>vite.close());
const {bindProfileFromReplay}=await vite.ssrLoadModule("/lib/replay/bind-profile.ts");
const {D1PlayerBindingStore}=await vite.ssrLoadModule("/lib/dota/player-binding.ts");
const {PlayerMatchRequestSchema,ProfileBindingRequestSchema}=await vite.ssrLoadModule("/lib/dota/player-identity.ts");
const replayId="00000000-0000-4000-8000-000000000001",matchId="8963624400";
async function setup(options={}){
  const db=await database();
  db.sqlite.prepare("INSERT INTO users(id,display_name) VALUES ('owner','Owner'),('other','Other')").run();
  const {file}=metadataFixture(options);const reads=[];
  db.sqlite.prepare("INSERT INTO replay_uploads(id,user_id,filename,object_key,size_bytes,state,upload_id) VALUES (?,'owner','untrusted-name.dem','owned-key',?,'uploaded','completed-multipart')").run(replayId,file.length);
  const bucket={async head(key){assert.equal(key,"owned-key");return {size:file.length,etag:"stable"};},async get(key,options){assert.equal(key,"owned-key");assert.equal(options.onlyIf.etagMatches,"stable");reads.push(options.range);const {offset,length}=options.range;return {body:true,arrayBuffer:async()=>file.subarray(offset,offset+length)};}};
  return {...db,file,reads,bucket,store:new D1PlayerBindingStore(db.d1)};
}
const input={replayId,matchId,nickname:"player_0"};
function noAnalysis(sqlite){for(const table of ["dota_match_targets","analysis_jobs","entitlement_ledger","source_matches"])assert.equal(sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n,0);}
test("owned completed upload binds profile without OpenDota, a slot, gameplay state or credit reservation",async()=>{
  const db=await setup();const original=globalThis.fetch;globalThis.fetch=async()=>{throw Error("OpenDota must not be called");};
  try{
    const result=await bindProfileFromReplay(db.d1,db.bucket,"owner",input);
    assert.equal(result.profile.accountId,1000);assert.equal(result.target,null);assert.equal(result.status,"awaiting_replay_parse");
    assert.ok(!JSON.stringify(result).includes("Player_1"));assert.equal(db.reads.length,3);noAnalysis(db.sqlite);
    assert.equal(db.sqlite.prepare("SELECT state FROM replay_uploads").get().state,"uploaded");
    await assert.rejects(db.store.resolve("owner",{matchId}),e=>e.code==="OPENDOTA_UNAVAILABLE");noAnalysis(db.sqlite);
  }finally{globalThis.fetch=original;db.sqlite.close();}
});
test("only profile endpoint accepts replay IDs; caller-supplied identities and slots stay forbidden",()=>{
  assert.equal(ProfileBindingRequestSchema.safeParse(input).success,true);
  assert.equal(PlayerMatchRequestSchema.safeParse(input).success,false);
  for(const key of ["playerSlot","accountId","heroId"])assert.equal(ProfileBindingRequestSchema.safeParse({...input,[key]:1}).success,false);
});
test("foreign, deleted, unfinished, compressed and wrong-match uploads never bind",async()=>{
  for(const scenario of ["foreign","deleted","uploading","compressed","mismatch","changed"]){
    const db=await setup();try{
      if(["deleted","uploading"].includes(scenario))db.sqlite.prepare("UPDATE replay_uploads SET state=?").run(scenario);
      if(scenario==="compressed")db.sqlite.prepare("UPDATE replay_uploads SET filename='file.dem.bz2'").run();
      if(scenario==="changed")db.bucket.get=async()=>({etag:"changed"});
      await assert.rejects(bindProfileFromReplay(db.d1,db.bucket,scenario==="foreign"?"other":"owner",{...input,matchId:scenario==="mismatch"?"8963624401":matchId}));
      assert.equal(await db.store.get("owner"),null);noAnalysis(db.sqlite);
      if(["foreign","deleted","uploading","compressed"].includes(scenario))assert.equal(db.reads.length,0);
    }finally{db.sqlite.close();}
  }
});
test("immutable binding wins a race between replay metadata and OpenDota; renamed nick cannot change the ID",async()=>{
  const db=await setup();try{
    const raw=makeOpenDotaMatch();raw.players.forEach((p,i)=>{p.account_id=1000+i;p.personaname=`Player_${i}`;});
    const results=await Promise.allSettled([bindProfileFromReplay(db.d1,db.bucket,"owner",input),db.store.resolve("owner",{matchId,nickname:"Player_1"},{fetch:async()=>jsonResponse(raw)})]);
    assert.equal(results.filter(r=>r.status==="fulfilled").length,1);
    assert.equal(results.find(r=>r.status==="rejected").reason.code,"DOTA_PROFILE_LOCKED");
    const profile=await db.store.get("owner");
    const result=await bindProfileFromReplay(db.d1,db.bucket,"owner",{...input,nickname:"Player_8"});
    assert.equal(result.profile.accountId,profile.accountId);
  }finally{db.sqlite.close();}
});
test("ready replay resolves the canonical slot for a metadata-bound profile",async()=>{
  const db=await setup();try{
    await bindProfileFromReplay(db.d1,db.bucket,"owner",input);
    const identities=makeOpenDotaMatch().players.map((p,i)=>({accountId:1000+i,nickname:`Renamed_${i}`,heroId:p.hero_id,playerSlot:p.player_slot}));
    [identities[0].accountId,identities[9].accountId]=[identities[9].accountId,identities[0].accountId];
    db.sqlite.prepare("UPDATE replay_uploads SET state='ready',match_id=?,identity_payload=?").run(matchId,JSON.stringify(identities));
    const target=await db.store.resolve("owner",{matchId},{fetch:async()=>{throw Error("No API needed");}});
    assert.equal(target.accountId,1000);assert.equal(target.playerSlot,132);
  }finally{db.sqlite.close();}
});
test("duplicate nickname remains ambiguous; metadata lookup shares the profile request budget",async()=>{
  const db=await setup({mutate:p=>{p[1].nickname="Player_0";}});try{
    await assert.rejects(bindProfileFromReplay(db.d1,db.bucket,"owner",input),e=>e.code==="DOTA_PLAYER_AMBIGUOUS");
    assert.equal(await db.store.get("owner"),null);
    for(let i=1;i<12;i++)await db.store.takeLookupBudget("owner");
    await assert.rejects(bindProfileFromReplay(db.d1,db.bucket,"owner",input),e=>e.code==="DOTA_LOOKUP_RATE_LIMITED");
    noAnalysis(db.sqlite);
  }finally{db.sqlite.close();}
});
