import assert from "node:assert/strict";
import test,{after} from "node:test";
import {database} from "./sqlite-d1.mjs";
import {createAnalysisVite,makeOpenDotaMatch,makeReport,jsonResponse} from "./analysis-test-helpers.mjs";
import {parseReplayEpilogue,replayPlayerIdentity} from "../ops/replay-adapter.mjs";
const vite=await createAnalysisVite();after(()=>vite.close());
const identity=await vite.ssrLoadModule("/lib/dota/player-identity.ts");
const {D1PlayerBindingStore}=await vite.ssrLoadModule("/lib/dota/player-binding.ts");
const {D1AnalysisStore}=await vite.ssrLoadModule("/lib/analyses/store.ts");
const {normalizeOpenDotaMatch,buildEvidenceBundle}=await vite.ssrLoadModule("/lib/analysis/normalizer.ts");
const {validateGroundedReport}=await vite.ssrLoadModule("/lib/analysis/grounding.ts");
const {handleCreateAnalysis}=await vite.ssrLoadModule("/lib/analyses/http.ts");
function fixture(matchId="8963624400") {
  const raw=makeOpenDotaMatch({match_id:Number(matchId)});
  raw.players.forEach((p,i)=>{p.account_id=1000+i;p.personaname=`Player_${i}`;});
  return raw;
}
function addUser(sqlite,user="owner") {sqlite.prepare("INSERT INTO users(id,display_name) VALUES (?,?)").run(user,"Test");}
test("nickname resolution ignores case but fails closed on duplicates, missing or hidden identity",()=>{
  const raw=fixture();const roster=identity.extractIdentityRoster(raw.players);
  assert.equal(identity.selectIdentity(roster," player_0 ").accountId,1000);
  assert.throws(()=>identity.selectIdentity(roster,"missing"),error=>error.code==="DOTA_PLAYER_NOT_FOUND");
  roster[1].nickname="PLAYER_0";roster[1].accountId=null;
  assert.throws(()=>identity.selectIdentity(roster,"Player_0"),error=>error.code==="DOTA_PLAYER_AMBIGUOUS");
  roster[1].nickname="Player_1";roster[0].accountId=null;
  assert.throws(()=>identity.selectIdentity(roster,"Player_0"),error=>error.code==="DOTA_IDENTITY_UNAVAILABLE");
  for(const key of ["playerSlot","accountId","heroId"])assert.equal(identity.PlayerMatchRequestSchema.safeParse({matchId:"8963624400",nickname:"Player_0",[key]:1}).success,false);
});
test("two first bindings race: exactly one player wins and identity cannot be switched or unlinked",async()=>{
  const {sqlite,d1}=await database();addUser(sqlite);const store=new D1PlayerBindingStore(d1);
  const fetch=async()=>jsonResponse(fixture());
  const attempts=await Promise.allSettled([store.resolve("owner",{matchId:"8963624400",nickname:"Player_0"},{fetch}),store.resolve("owner",{matchId:"8963624400",nickname:"Player_1"},{fetch})]);
  assert.equal(attempts.filter(r=>r.status==="fulfilled").length,1);
  assert.equal(attempts.find(r=>r.status==="rejected").reason.code,"DOTA_PROFILE_LOCKED");
  const profile=await store.get("owner");const target=await store.target("owner","8963624400");assert.equal(target.accountId,profile.accountId);
  assert.throws(()=>sqlite.prepare("UPDATE dota_player_profiles SET account_id=999 WHERE user_id='owner'").run(),/immutable/);
  assert.throws(()=>sqlite.prepare("DELETE FROM dota_player_profiles WHERE user_id='owner'").run(),/no_unlink/);
  assert.throws(()=>sqlite.prepare("UPDATE dota_match_targets SET player_slot=4 WHERE user_id='owner'").run(),/immutable/);
  const cached=await store.resolve("owner",{matchId:"8963624400",nickname:"somebody_else"},{fetch:async()=>{throw Error("should use locked target");}});
  assert.equal(cached.accountId,profile.accountId);
  assert.equal(await store.get("other"),null);
  sqlite.close();
});
test("renamed player is found by account ID; other matches fail before reserving a credit",async()=>{
  const {sqlite,d1}=await database();addUser(sqlite);const store=new D1PlayerBindingStore(d1);
  await store.resolve("owner",{matchId:"8963624400",nickname:"Player_0"},{fetch:async()=>jsonResponse(fixture())});
  const raw=fixture("8963624401");raw.players[0].personaname="New Nick";
  const result=await store.resolve("owner",{matchId:"8963624401"},{fetch:async()=>jsonResponse(raw)});
  assert.equal(result.accountId,1000);assert.equal(result.playerSlot,0);
  const missing=fixture("8963624402");missing.players[0].account_id=2000;
  await assert.rejects(store.resolve("owner",{matchId:"8963624402"},{fetch:async()=>jsonResponse(missing)}),error=>error.code==="DOTA_PLAYER_NOT_FOUND");
  await assert.rejects(new D1AnalysisStore(d1).create({userId:"owner",matchId:"8963624400",playerSlot:1,idempotencyKey:"forged:slot"}),error=>error.code==="DOTA_TARGET_MISMATCH");
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM analysis_jobs").get().n,0);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM entitlement_ledger").get().n,0);
  const shared=sqlite.prepare("SELECT normalized_payload FROM source_matches WHERE match_id='8963624400'").get().normalized_payload;
  assert.doesNotMatch(shared,/Player_0|account_id|personaname/);
  sqlite.close();
});
test("analysis HTTP rejects client slots before any identity lookup or credit reservation",async()=>{
  let calls=0;
  const response=await handleCreateAnalysis(new Request("https://narma.test/api/analyses",{method:"POST",headers:{Origin:"https://narma.test","Content-Type":"application/json","Idempotency-Key":"forged:target"},body:JSON.stringify({matchId:"8963624400",playerSlot:128})}),{account:{id:"owner",status:"active",deletedAt:null},acceptingJobs:true,resolveTarget:async()=>{calls++;},store:{create:async()=>{calls++;}}});
  assert.equal(response.status,400);assert.equal(calls,0);
});
test("AI evidence contains one personal summary; null-slot claims cannot disguise another player's summary",async()=>{
  const match=normalizeOpenDotaMatch(fixture());
  const scoped=await buildEvidenceBundle(match,0);
  assert.deepEqual(scoped.evidenceBundle.evidence.filter(e=>e.kind==="player").map(e=>e.playerSlot),[0]);
  assert.ok(scoped.evidenceBundle.evidence.some(e=>e.kind==="fight"));
  const all=await buildEvidenceBundle(match);const report=makeReport(all.evidenceHash);
  report.items[0].playerSlot=null;report.items[0].evidenceIds.push("player.128.summary");
  await assert.rejects(validateGroundedReport(report,all.evidenceBundle,{playerSlot:0,evidenceHash:all.evidenceHash}),/другого игрока/);
});
test("replay Steam IDs retain all digits, match hero and team, and decode protobuf byte strings",()=>{
  // Synthetic ID is above Number.MAX_SAFE_INTEGER and would round in plain JSON.parse.
  const steam="76561197960266729";
  const source=`{"gameInfo_":{"dota_":{"playerInfo_":[{"heroName_":"npc_dota_hero_necrolyte","playerName_":"Example","steamid_":${steam},"gameTeam_":2}]}}}`;
  const dota=parseReplayEpilogue(source).gameInfo_.dota_;
  assert.equal(dota.playerInfo_[0].steamid_,steam);
  assert.deepEqual(replayPlayerIdentity(dota,36,0),{account_id:1001,personaname:"Example"});
  assert.deepEqual(replayPlayerIdentity(dota,36,128),{account_id:null,personaname:null});
  dota.playerInfo_[0].steamid_="76561200960265728";
  assert.equal(replayPlayerIdentity(dota,36,0).account_id,3000000000);
  const bytes=text=>({bytes:Array.from(new TextEncoder().encode(text),v=>v>127?v-256:v),hash:0});
  dota.playerInfo_[0].heroName_=bytes("npc_dota_hero_necrolyte");dota.playerInfo_[0].playerName_=bytes("Игрок");
  assert.equal(replayPlayerIdentity(dota,36,4).personaname,"Игрок");
  dota.playerInfo_.push({...dota.playerInfo_[0]});assert.equal(replayPlayerIdentity(dota,36,4).account_id,null);
});
