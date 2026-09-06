import assert from "node:assert/strict";
import test, { after } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { analysisRoot } from "./analysis-test-helpers.mjs";

const vite=await createServer({appType:"custom",configFile:false,root:analysisRoot,
  resolve:{alias:{"@":analysisRoot}},esbuild:{jsx:"automatic"},server:{middlewareMode:true}});
after(()=>vite.close());
const {activeWardsAt,worldToPercent}=await vite.ssrLoadModule("/lib/replay/map-state.ts");
const {normalizeReplayMap}=await vite.ssrLoadModule("/lib/replay/normalize-map.ts");
const {MAP_CAMPS}=await vite.ssrLoadModule("/lib/replay/map-camps.ts");
const {default:ReplayMapView}=await vite.ssrLoadModule("/components/narma/replay-map.tsx");
const ward=(id,overrides={})=>({id,kind:"observer",side:"radiant",x:0,y:0,placedAt:100,removedAt:460,...overrides});

test("wards disappear exactly when removed and return only when rewinding into their lifetime",()=>{
  const wards=[ward("normal"),ward("dewarded",{removedAt:120}),ward("unknown",{removedAt:null}),ward("enemy",{side:"dire",kind:"sentry"})];
  const ids=(time,side="all")=>activeWardsAt(wards,time,side).map(w=>w.id);
  assert.deepEqual(ids(99),[]);
  assert.deepEqual(ids(100),["normal","dewarded","enemy"]);
  assert.deepEqual(ids(120),["normal","enemy"]);
  assert.deepEqual(ids(459,"radiant"),["normal"]);
  assert.deepEqual(ids(459,"dire"),["enemy"]);
  assert.deepEqual(ids(460),[]);
  assert.deepEqual(ids(900),[]);
  assert.deepEqual(ids(459),["normal","enemy"]);
  assert.deepEqual(activeWardsAt([ward("zero",{removedAt:100})],100),[]);
});

test("co-located ward lifetimes use entity handles and never guess from coordinates or duration",()=>{
  const map=normalizeReplayMap({duration:1000,version:22,players:[{player_slot:0,
    obs_log:[{x:128,y:128,time:100,ehandle:1},{x:128,y:128,time:200,ehandle:2},{x:128,y:128,time:300,ehandle:3}],
    obs_left_log:[{time:99,ehandle:1},{time:250,ehandle:1},{time:240,ehandle:99},{time:450,ehandle:2}],
    sen_log:[{x:128,y:128,time:100,ehandle:1}],sen_left_log:[{time:130,ehandle:1}],
  }]});
  assert.equal(map.wardLifetimesComplete,false);
  assert.deepEqual(map.wards.filter(w=>w.kind==="observer").map(w=>w.removedAt),[250,450,null]);
  assert.equal(map.wards.find(w=>w.kind==="sentry").removedAt,130);
  assert.equal(activeWardsAt(map.wards,249).length,2);
  assert.equal(activeWardsAt(map.wards,250).length,1);
  assert.equal(activeWardsAt(map.wards,450).length,0);
});

test("map markup has active vector wards only, with no history or unknown-lifetime markers",()=>{
  const data={schemaVersion:"replay-map.v1",terrainVision:"unavailable",wardLifetimesComplete:false,buildingEventsComplete:false,buildings:[],
    wards:[ward("active"),ward("enemy",{side:"dire",kind:"sentry"}),ward("expired",{removedAt:110}),ward("unknown",{removedAt:null})]};
  const render=(time,props={})=>renderToStaticMarkup(createElement(ReplayMapView,{data,time,structures:false,camps:false,...props}));
  const count=html=>(html.match(/class="replay-ward /g)||[]).length;
  const html=render(200);
  assert.equal(count(html),2);
  assert.match(html,/class="replay-ward radiant observer"/);
  assert.match(html,/class="replay-ward dire sentry"/);
  assert.match(html,/class="map-ward-glyph" viewBox="0 0 32 32"/);
  assert.doesNotMatch(html,/История вардов|replay-ward[^"<]*(?:unknown|removed)/);
  assert.equal(count(render(460)),0);
  assert.equal(count(render(200,{perspective:"dire"})),1);
  assert.equal(count(render(200,{wards:false})),0);
  assert.match(html,/туман войны недоступен/);
});

test("all 28 patch-matched camp locations render as vector markers with difficulty metadata",()=>{
  assert.equal(new Set(MAP_CAMPS.map(c=>c.id)).size,28);
  assert.deepEqual(Object.fromEntries(["small","medium","large","ancient"].map(tier=>[tier,MAP_CAMPS.filter(c=>c.tier===tier).length])),{small:6,medium:14,large:6,ancient:2});
  for(const side of ["radiant","dire"])assert.equal(MAP_CAMPS.filter(c=>c.side===side).length,14);
  for(const camp of MAP_CAMPS){const p=worldToPercent(camp.x,camp.y);assert.ok(p.left>0&&p.left<100&&p.top>0&&p.top<100);}
  const data={schemaVersion:"replay-map.v1",terrainVision:"unavailable",wardLifetimesComplete:true,buildingEventsComplete:false,buildings:[],wards:[]};
  const html=renderToStaticMarkup(createElement(ReplayMapView,{data,time:200,structures:false,wards:false}));
  assert.equal((html.match(/class="replay-camp /g)||[]).length,28);
  for(const label of ["Малый лагерь","Средний лагерь","Большой лагерь","Древние крипы"])assert.ok(html.includes(label));
});
