import heroCatalog from "../app/data/hero-catalog.json" with {type:"json"};
const SLOTS=[0,1,2,3,4,128,129,130,131,132];
export function parseReplayEpilogue(source) {
  return JSON.parse(source,(key,value,context)=>key==="steamid_" && typeof value==="number" ? context?.source??null : value);
}
function protoText(value) {
  if(typeof value==="string")return value;
  const bytes=value?.bytes;
  if(!Array.isArray(bytes)||bytes.length>1024||bytes.some(n=>!Number.isInteger(n)||n< -128||n>255))return null;
  try{return new TextDecoder("utf-8",{fatal:true}).decode(Uint8Array.from(bytes,n=>n&255));}catch{return null;}
}
export function replayPlayerIdentity(dota,heroId,playerSlot) {
  const slug=heroCatalog[String(heroId)]?.slug;
  const rows=Array.isArray(dota?.playerInfo_)?dota.playerInfo_:[];
  const matches=rows.filter(p=>!p.isFakeClient_ && protoText(p.heroName_)===`npc_dota_hero_${slug}` && p.gameTeam_===(playerSlot<128?2:3));
  if(!slug||matches.length!==1)return {account_id:null,personaname:null};
  const player=matches[0];
  if(typeof player.steamid_!=="string"||!/^\d{17}$/.test(player.steamid_))return {account_id:null,personaname:null};
  const id=BigInt(player.steamid_)-76561197960265728n;
  if(id<1n||id>=4294967295n)return {account_id:null,personaname:null};
  return {account_id:Number(id),personaname:protoText(player.playerName_)?.slice(0,128)??null};
}
export function createReplayMetadata(){return {dota:null,end:null,slots:new Map(),heroes:new Map(),latest:new Map(),economy:new Map(),positions:[],samplePeriod:5};}
export function acceptReplayEvent(state,event){
  if(event.type==="epilogue"){
    const dota=parseReplayEpilogue(event.key)?.gameInfo_?.dota_;
    if(!dota || (state.dota && String(state.dota.matchId_)!==String(dota.matchId_)))throw new Error("REPLAY_EPILOGUE_INVALID");state.dota=dota;
  }
  if(event.type==="DOTA_COMBATLOG_GAME_STATE" && event.value===6 && Number.isFinite(event.time))state.end=event.time;
  if(event.type==="player_slot" && Number.isInteger(Number(event.key)) && SLOTS.includes(event.value))state.slots.set(Number(event.key),event.value);
  if(event.type==="interval" && Number.isInteger(event.slot) && Number.isInteger(event.hero_id) && event.hero_id>0){
    const previous=state.heroes.get(event.slot);
    if(previous && previous!==event.hero_id && event.time>=0)throw new Error("REPLAY_HERO_CHANGED");
    state.heroes.set(event.slot,event.hero_id);
    if(Number.isFinite(event.time) && event.time>=0 && (state.end===null || event.time<=state.end)) {
      const last=state.latest.get(event.slot);if(!last || last.time<=event.time)state.latest.set(event.slot,event);
    }
    if(Number.isInteger(event.time)&&event.time>=0&&event.time%60===0) {
      const minute=state.economy.get(event.time)??new Map();minute.set(event.slot,{gold:event.networth,xp:event.xp});state.economy.set(event.time,minute);
    }
    if(Number.isInteger(event.time)&&event.time>=-600&&event.time%state.samplePeriod===0&&Number.isFinite(event.x)&&Number.isFinite(event.y)){
      state.positions.push({slot:event.slot,time:event.time,x:event.x,y:event.y,alive:event.life_state===0});
      if(state.positions.length>5000){state.samplePeriod*=2;state.positions=state.positions.filter(p=>p.time%state.samplePeriod===0);}
    }
  }
}
export function assembleReplayMatch(state,blob){
  if(!state.dota || !/^[1-9]\d{7,11}$/.test(String(state.dota.matchId_)) || ![2,3].includes(state.dota.gameWinner_) || !Number.isInteger(state.end) || state.end<=0 || state.end>43200)throw new Error("REPLAY_INCOMPLETE");
  if(!Array.isArray(blob.players)||blob.players.length!==10)throw new Error("REPLAY_PLAYERS_INCOMPLETE");
  const ordinals=SLOTS.map(slot=>[...state.slots].find(([,value])=>value===slot)?.[0]);
  if(ordinals.some(o=>o===undefined||o<0||o>9||!state.heroes.has(o))||new Set(ordinals).size!==10)throw new Error("REPLAY_SLOTS_INCOMPLETE");
  const advantage=field=>Array.from({length:Math.floor(state.end/60)+1},(_,minute)=>{
    const samples=state.economy.get(minute*60);if(!samples||ordinals.some(o=>!Number.isFinite(samples.get(o)?.[field])))return null;
    return ordinals.reduce((sum,o,i)=>sum+(i<5?1:-1)*samples.get(o)[field],0);
  });
  const objectives=(blob.objectives??[]).map(e=>({...e,player_slot:state.slots.get(e.slot)??null}));
  const teamfights=(blob.teamfights??[]).map(f=>({...f,players:ordinals.map(o=>f.players?.[o])}));
  return {...blob,radiant_gold_adv:advantage("gold"),radiant_xp_adv:advantage("xp"),_narma_gold_basis:"net_worth",match_id:String(state.dota.matchId_),duration:state.end,radiant_win:state.dota.gameWinner_===2,game_mode:state.dota.gameMode_??null,
    players:ordinals.map((o,i)=>{
      const stats=state.latest.get(o);const values={};
      if(stats && stats.time<=state.end)for(const [source,target] of Object.entries({kills:"kills",deaths:"deaths",assists:"assists",lh:"last_hits",denies:"denies",level:"level",networth:"net_worth"})) {
        if(Number.isSafeInteger(stats[source])&&stats[source]>=0)values[target]=stats[source];
      }
      const heroId=state.heroes.get(o);
      const uniqueHero=ordinals.filter(other=>state.heroes.get(other)===heroId && (state.slots.get(other)<128)===(SLOTS[i]<128)).length===1;
      const identity=uniqueHero?replayPlayerIdentity(state.dota,heroId,SLOTS[i]):{account_id:null,personaname:null};
      return {...blob.players[o],...values,...identity,player_slot:SLOTS[i],hero_id:heroId};
    }),objectives,teamfights,
    _narma_hero_positions:state.positions.filter(p=>p.time<=state.end).map(p=>({playerSlot:state.slots.get(p.slot),time:p.time,x:p.x,y:p.y,alive:p.alive})),
  };
}
