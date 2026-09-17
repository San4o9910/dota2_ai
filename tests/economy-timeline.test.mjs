import assert from 'node:assert/strict';
import test,{after} from 'node:test';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createAnalysisVite,makeOpenDotaMatch} from './analysis-test-helpers.mjs';
const vite=await createAnalysisVite();after(()=>vite.close());
const timeline=await vite.ssrLoadModule('/lib/replay/economy-timeline.ts');
const {normalizeOpenDotaMatch}=await vite.ssrLoadModule('/lib/analysis/normalizer.ts');
const {default:Chart}=await vite.ssrLoadModule('/components/narma/match-economy-timeline.tsx');
const {worldToPercent}=await vite.ssrLoadModule('/lib/replay/map-state.ts');
const {FIGHTS,GOLD_ADV,XP_ADV,MATCH}=await vite.ssrLoadModule('/app/data/demo-match.ts');
const fights=FIGHTS.map((f,i)=>({id:`fight.${String(i).padStart(4,'0')}`,startSeconds:f.start,endSeconds:f.end,radiant:{...f.radiant,goldDelta:f.radiant.gold,xpDelta:f.radiant.xp},dire:{...f.dire,goldDelta:f.dire.gold,xpDelta:f.dire.xp}}));

test('fight result keeps each team delta separate from the difference between teams',()=>{
 const f=fights.find(f=>f.startSeconds===2100);assert.deepEqual(timeline.fightGoldResult(f),{radiant:800,dire:1200,difference:-400,side:'Dire'});
 assert.equal(timeline.fightGoldResult({...f,radiant:{...f.radiant,goldDelta:null}}).difference,null);
 assert.equal(timeline.fightAtTime(fights,400),null);assert.equal(timeline.fightAtTime(fights,490).startSeconds,480);assert.equal(timeline.fightAtTime(fights,510).startSeconds,480);
});
test('rendered fight marker and cursor use timestamps rather than evenly spaced fight indexes',()=>{
 const samples=GOLD_ADV.map((v,i)=>({timeSeconds:i*60,radiantGoldAdvantage:v,radiantXpAdvantage:XP_ADV[i]}));
 const html=renderToStaticMarkup(React.createElement(Chart,{samples,fights,duration:MATCH.duration,time:2100,onSeek(){}}));
 const marker=html.match(/data-fight-start="2100" data-fight-end="2130" x="([^"]+)"[^>]*width="([^"]+)"/);assert.ok(marker);
 assert.ok(Math.abs(Number(marker[1])-(58+2100/2400*842))<.01);assert.ok(Math.abs(Number(marker[2])-30/2400*842)<.01);
 assert.match(html,/35:00–35:30/);assert.match(html,/40:00/);assert.match(html,/35:00<\/text>/);assert.match(html,/К началу · 35:00/);assert.match(html,/К концу · 35:30/);
 const text=html.replaceAll(/\s| /g,'');assert.match(text,/\+800/);assert.match(text,/\+1200/);assert.match(text,/400/);assert.doesNotMatch(text,/\+400/);
 assert.match(html,/Выбрать драку по времени/);assert.match(html,/Приблизить драку/);
});
test('minute snapshots remain honest while the cursor moves between measured samples',()=>{
 const samples=[{timeSeconds:420,radiantGoldAdvantage:12,radiantXpAdvantage:15},{timeSeconds:480,radiantGoldAdvantage:30,radiantXpAdvantage:25}];
 assert.equal(timeline.sampleAtTime(samples,461).timeSeconds,420);assert.equal(timeline.sampleAtTime(samples,419),null);
 assert.equal(timeline.timeFraction(2400,0,2400),1);assert.ok(timeline.timelineTicks(0,2400).includes(2400));
});
test('normalization retains exactly mapped fight gold per hero and preserves unavailable values',()=>{
 const raw=makeOpenDotaMatch();raw.teamfights[0].players[0].gold_delta=null;
 const match=normalizeOpenDotaMatch(raw);assert.equal(match.fights[0].players.length,10);
 assert.deepEqual(match.fights[0].players[0],{playerSlot:0,heroId:1,goldDelta:null,xpDelta:100});
 assert.deepEqual(match.fights[0].players[5],{playerSlot:128,heroId:6,goldDelta:-200,xpDelta:-100});
 assert.doesNotMatch(JSON.stringify(match.fights),/SECRET|personaname|account_id/);
});
test('game map is the unchanged source raster and independent gate anchors stay aligned',async()=>{
 const calibration=JSON.parse(await readFile(new URL('../lib/replay/game-map-calibration.json',import.meta.url),'utf8'));
 const image=await readFile(new URL('../public/maps/7.41/game-map.jpg',import.meta.url));assert.equal(createHash('sha256').update(image).digest('hex'),calibration.thumbnailSha256);
 for(const a of calibration.holdoutAnchors){const point=worldToPercent(a.worldX,a.worldY);const error=Math.hypot(point.left/100*2166-a.pixelX,point.top/100*2048-a.pixelY);assert.ok(error<6,`${a.id}: ${error}px`);}
});
