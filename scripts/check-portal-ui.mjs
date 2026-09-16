import {programFixture} from './program-fixtures.mjs';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';

const require=createRequire(import.meta.url);
const roleProfiles=JSON.parse(execFileSync(process.env.NARMA_TEST_PYTHON||'python3',['-c',"import json,sys; sys.path.insert(0,sys.argv[1]); from narma_video.role_context import get_role_context; print(json.dumps([get_role_context(p) for p in range(6)],ensure_ascii=False))",path.resolve('services/video')],{encoding:'utf8'}));
function dependency(name) {
  try { return require(name); }
  catch { const runtime=process.env.PLAYWRIGHT_NODE_MODULES||process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES; if(!runtime) throw Error(`Install ${name} to run the portal check.`); return require(path.join(runtime,name)); }
}
const {chromium}=dependency('playwright');
const root=path.resolve(process.env.NARMA_PORTAL_TEST_ROOT||'services/video/narma_video/static');
const files=Object.fromEntries(['/training','/register','/login','/coach','/replays','/hero-pool','/my-learning','/player','/account','/owner','/setup'].map(route=>[route,['index.html','text/html']]));
Object.assign(files,{'/assets/player-program.js':['player-program.js','text/javascript'],'/assets/billing.js':['billing.js','text/javascript'],'/assets/report-freshness.js':['report-freshness.js','text/javascript'],'/assets/brand-motion.js':['brand-motion.js','text/javascript'],'/assets/growth.js':['growth.js','text/javascript'],'/assets/owner-dashboard.js':['owner-dashboard.js','text/javascript'],'/assets/vision-theme.css':['vision-theme.css','text/css'],'/assets/coach-chat.js':['coach-chat.js','text/javascript'],'/assets/role-guidance.js':['role-guidance.js','text/javascript'],'/assets/portal.js':['portal.js','text/javascript'],'/assets/personal-coach.js':['personal-coach.js','text/javascript'],'/assets/video-workspace.js':['video-workspace.js','text/javascript'],'/assets/portal.css':['portal.css','text/css']});
const server=createServer(async(request,response)=>{
  const file=files[request.url]; if(!file) { response.writeHead(404).end(); return; }
  response.setHeader('Content-Type',file[1]); response.end(await readFile(path.join(root,file[0])));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const screenshotDir=process.env.NARMA_PORTAL_SCREENSHOTS;
if(screenshotDir) await mkdir(screenshotDir,{recursive:true});
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const malicious='<img src=x onerror=alert(1)>';
const profile={account_id:123,nickname:'SyntheticPlayer',match_id:'8984479726'};
const report={
  schema_version:'narma.replay-report.v1',match_id:'8984479726',outcome:'win',
  player:{...profile,hero:'npc_dota_hero_necrolyte',team:'radiant'},
  metrics:{duration_seconds:4721.667,kills:17,deaths:16,assists:20,last_hits:440,denies:2,net_worth:33552,total_earned_gold:45890,xp:64400,confirmed_dead_seconds:1013.834},
  economy:[{time:0,net_worth:600,xp:0,kills:0,deaths:0,assists:0,last_hits:0,denies:0,level:1},{time:600,net_worth:4000,xp:5000,kills:1,deaths:1,assists:2,last_hits:30,denies:1,level:7},{time:4700,net_worth:33552,xp:64400,kills:17,deaths:16,assists:20,last_hits:440,denies:2,level:30}],
  evidence:[{id:'death-1',type:'death',time:600,title:'Смерть выбранного героя',details:'Подтверждено журналом матча.'},{id:'purchase-1',type:'purchase',time:700,title:'Radiance',details:'Покупка зафиксирована в реплее.'}],
  inventory:[{time:700,item:'item_radiance',event_id:'purchase-1'}],
  findings:[{id:'death-review',title:'Смерть на линии',observation:'Герой погиб.',advice:'Проверь позицию перед смертью.',evidence_ids:['death-1']}],
  coaching:{status:'ready',summary:'Начни с эпизода на линии.',next_game:[{title:'Один предмет — один план',action:'Перед покупкой выбери следующий безопасный эпизод.',measure:'После матча проверь первый таймкод применения.',evidence_ids:['purchase-1']}],points:[{title:malicious,observation:'Наблюдение из реплея.',advice:'Совет для проверки.',evidence_ids:['death-1']}]},
  insights:{schema_version:'narma.replay-insights.v1',
    gold:{method:'combat_log',sources:[{key:'creeps',label:'Крипы',gold:1400},{key:'heroes',label:'Герои',gold:400}],recorded_income:1800,recorded_loss:120,total_earned_gold:1800,reconciliation_difference:0,coverage_note:'Источники подтверждены журналом золота.',bins:[{start:600,end:660,income:800,loss:120,by_source:{creeps:600,heroes:200}},{start:660,end:720,income:1000,loss:0,by_source:{creeps:800,heroes:200}}]},
    pace:[{start:600,end:660,last_hits:8,kills:1,deaths:1,assists:2,earned_gold:800,xp:1000},{start:660,end:720,last_hits:12,kills:0,deaths:0,assists:0,earned_gold:1000,xp:1200}],death_intervals:[{start:600,end:630,seconds:30}],
    items:[{id:'key-1',item:'item_radiance',label:'Radiance',time:700,acquisition:'purchase',event_id:'purchase-1',stage:'midgame',timing:{status:'no_reference',label:'Без эталона',basis:'Нет сопоставимого ориентира по герою, роли и рейтингу.'},first_hero_inventory_time:710,first_active_inventory_time:720,realization:{window_seconds:120,observed_seconds:120,first_use_time:null,delay_seconds:null,casts:0,kills:0,assists:1,deaths:0,objectives:0,evidence_ids:['purchase-1'],status:'passive_item',note:'Пассивный предмет: число нажатий не показывает эффективность.'},funding:{start:580,end:700,income:1200,by_source:{creeps:1000,heroes:200},note:'Доход в окне до покупки; это не прямое доказательство оплаты предмета.'}}],
    training_plan:[{id:'next-1',title:'Проверь следующий выход',action:'Перед следующим выходом проверь готовность предметов.',measure:'Найди первое применение после покупки.',evidence_ids:['purchase-1']}]},
  coverage:{complete:true,limits:['Причины решений и видимость не угадываются.']}
};
const heroContext={hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2,position_label:'Позиция 2 · указана тобой',summary:'У Necrophos свой план на затяжной бой.',abilities:[{name:'necrolyte_death_pulse',label:'Death Pulse',casts:42,first_time:-5,last_time:4600}],focus:[{title:'Death Pulse в эпизоде',observation:'Способность записана в журнале.',advice:'Проверь, кому помогло применение.',evidence_ids:['death-1']}],training_plan:[{id:'hero-next',title:'План за Necrophos',action:'Проверь применение Death Pulse в одном эпизоде.',measure:'Найди эпизод и оцени результат.',evidence_ids:['death-1']}],limits:['Число применений не доказывает качество решения.'],sources:[{title:'Necrophos · Dota 2',url:'https://www.dota2.com/hero/necrophos'},{title:'Unsafe link',url:'javascript:alert(1)'}]};
const itemImageUrl='https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/radiance.png';
const blinkImageUrl='https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/blink.png';
const heroImageUrl='https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/necrolyte.png';
report.insights.items.push({id:'key-2',item:'item_blink',label:'Blink',time:1300,acquisition:'purchase',timing:{label:'Без эталона'},first_hero_inventory_time:1310,first_active_inventory_time:1310,realization:{status:'used_soon',observed_seconds:120,first_use_time:1330,delay_seconds:30,casts:2,kills:1,assists:0,deaths:0,evidence_ids:[]}});
const itemImage=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
// Synthetic dense timeline: enough distinct minutes to exercise full match visuals.
const syntheticDuration=report.metrics.duration_seconds;
report.economy=Array.from({length:80},(_,index)=>{
  const time=Math.min(index*60,syntheticDuration), segment=time<=600?time/600:(time-600)/(syntheticDuration-600);
  return {time,net_worth:time<=600?600+3400*segment:4000+29552*segment,xp:time<=600?5000*segment:5000+59400*segment,kills:Math.floor(time/syntheticDuration*17),deaths:Math.floor(time/syntheticDuration*16),assists:Math.floor(time/syntheticDuration*20),last_hits:Math.floor(time/syntheticDuration*440),denies:Math.floor(time/syntheticDuration*2),level:Math.min(30,Math.floor(time/syntheticDuration*29)+1)};
});
report.insights.gold.bins=Array.from({length:79},(_,index)=>{
  const start=index*60,end=Math.min(start+60,syntheticDuration),income=index===11?1000:240+(index%7)*80,heroes=index%11===0?120:0,passive=100*(end-start)/60;
  return {start,end,income,loss:index%15===0?120:0,by_source:{creeps:income-heroes-passive,heroes,passive}};
});
report.insights.gold.sources=[['creeps','Крипы'],['heroes','Герои'],['passive','Пассивный доход']].map(([key,label])=>({key,label,gold:report.insights.gold.bins.reduce((sum,bin)=>sum+bin.by_source[key],0)}));
report.insights.gold.recorded_income=report.insights.gold.bins.reduce((sum,bin)=>sum+bin.income,0);
report.insights.gold.recorded_loss=report.insights.gold.bins.reduce((sum,bin)=>sum+bin.loss,0);
report.insights.gold.total_earned_gold=report.insights.gold.recorded_income;
report.metrics.total_earned_gold=report.insights.gold.recorded_income;
report.insights.pace=report.insights.gold.bins.map((bin,index)=>({...bin,last_hits:3+index%7,kills:index%11===0?1:0,deaths:index%15===0?1:0,assists:index%9===0?1:0,earned_gold:bin.income,xp:bin.income*1.5}));

function personalCoachFixtures() {
  const history=[
    {job_id:'coach-new',match_id:'8984100002',played_at:'2026-09-12T18:00:00Z',outcome:'win'},
    {job_id:'coach-old',match_id:'8984100001',played_at:'2026-09-10T18:00:00Z',outcome:'loss'},
  ].map(match=>({...match,hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2,date_source:'user',chronology_at:match.played_at,report_state:'ready',source_sha256:'a'.repeat(64),report_sha256:(match.job_id==='coach-new'?'b':'c').repeat(64),metrics:{gpm:450,xpm:500,deaths_per_30:5}}));
  const structuredPoint={kind:'review',title:'Возвращение после смерти',observation:malicious,decision_question:'Что проверить перед возвращением на линию?',reasoning:'Смерть записана, но причина требует проверки окружения.',alternative:'Проверь доступные пути возвращения и состояние линии.',when_to_apply:'Перед возвращением после смерти.',when_not_to_apply:'Если команда уже требует срочной защиты базы.',evidence_ids:['coach-new-death']};
  const exercise={id:'coach-risk',stage_id:'risk',title:'Проверка перед возвращением',roles:[2],decision_question:'Что было известно до решения?',signal:'Перед возвращением на линию.',action:'Проверь доступный путь и цель.',why:'Это позволяет заранее оценить риск.',exception:'Срочная защита может изменить план.',drill:'Сравни три возвращения.',measurement:'Запиши информацию, доступную до выбора.',focus_window_matches:3,review_mode:'episode_review',evidence_types:['death'],source_refs:[]};
  const plan={id:'coach-practice',exercise_id:exercise.id,exercise,hero:history[0].hero,hero_label:'Necrophos',position:2,status:'active',validity:'current',can_check:true,source_job_id:'coach-old',source_match_id:'8984100001',created_at:'2026-09-11T18:00:00Z',training_matches:1,reviewed_matches:1,self_report_counts:{applied:0,partial:1,not_applied:0,no_opportunity:0,uncertain:0},checks:[]};
  const catalog={schema_version:'narma.curriculum.v1',version:'narma.curriculum.v1',role_context:roleProfiles[2],position:2,position_required:false,stages:[{id:'risk',title:'Риск и возвращение в игру',order:3,description:'Проверь решение до возвращения.',exercise_ids:[exercise.id]}],exercises:[exercise],sources:[]};
  function detail(id,{unavailable=false}={}) {
    const match=history.find(item=>item.job_id===id);assert.ok(match);
    const event={id:`${id}-death`,type:'death',time:id==='coach-new'?720:600,title:'Возвращение и смерть',details:'Синтетический факт для проверки перехода.'};
    const coaching=id==='coach-new'?{status:'ready',schema_version:'narma.replay-coaching.v3',training_level:'advanced',lesson:{first:'Сравни возвращение с ожиданием.',second:'Проверь доступную информацию перед решением.',third:'При потере цели отмени возвращение.',evidence_ids:[event.id]},summary:'Начни с решения о возвращении на линию.',points:[structuredPoint],next_game:[{title:'Одна проверка до возвращения',action:'До выхода назови цель и безопасный путь.',measure:'После игры проверь три таких решения.',evidence_ids:[event.id]}]}:{status:'ready',summary:'Сохранённый комментарий старого формата.',points:[{title:'Старое наблюдение',observation:'В реплее есть смерть на десятой минуте.',advice:'Проверь положение перед возвращением.',evidence_ids:[event.id]}],next_game:[]};
    coaching.context={position:match.position};
    if(unavailable){coaching.status='unavailable';coaching.failure_code='OPENAI_BUDGET_EXCEEDED';}
    return {replay:{id,state:'ready',progress:100,match_id:match.match_id,nickname:profile.nickname,created_at:match.played_at,source_retained:true},report:{...structuredClone(report),match_id:match.match_id,player:{...report.player,match_id:match.match_id},evidence:[event],coaching,coverage:{...report.coverage,source_sha256:match.source_sha256}},report_sha256:match.report_sha256,hero_context:null,parts:[],archived_report:null,coaching_status:unavailable?{state:'unavailable',provider:'openai_api',verified_openai:false,reason_code:'OPENAI_BUDGET_EXCEEDED',usage:null,billing_state:'none',charged_microusd:null}:{state:'ready',provider:'openai_api',verified_openai:true,reason_code:null,usage:{input_tokens:1000,output_tokens:200,cached_input_tokens:0},billing_state:'settled',charged_microusd:2000}};
  }
  function pool(empty) {
    return {profile:empty?null:profile,role_context:roleProfiles[2],summary:{matches:empty?0:2,wins:empty?0:1,losses:empty?0:1,known_outcomes:empty?0:2,unknown_outcomes:0,winrate_pct:empty?null:50,unknown_positions:0,analysis_dated_matches:0},heroes:empty?[]:[{hero:history[0].hero,label:'Necrophos',position:2,matches:2,wins:1,losses:1,known_outcomes:2,unknown_outcomes:0,winrate_pct:50,favorite:false}],available_heroes:empty?[]:[{hero:history[0].hero,label:'Necrophos'}],history:empty?[]:history,trends:[],patterns:[],coaching:null,goals:[],limitations:['Синтетические данные для проверки интерфейса.']};
  }
  function learning(empty,id=null) {
    const match=history.find(item=>item.job_id===id);
    return {schema_version:'narma.learning.v1',catalog,profile:empty?null:profile,scope:{hero:null,position:null},plans:empty?[]:[plan],history:empty?[]:history,...(match?{job_id:id,requested_job_id:id,match_id:match.match_id,hero:match.hero,hero_label:match.label,position:2,position_required:false,suggestions:[],review_candidates:[{evidence_id:`${id}-death`,type:'death',time:id==='coach-new'?720:600,title:'Возвращение и смерть'}]}:{})};
  }
  return {history,structuredPoint,exercise,plan,detail,pool,learning};
}
try {
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}});
    let authenticated=false, bound=false, job=null, uploaded=false, legacy=false, poolFailed=false, poolSaveFailed=false, learningEmpty=true, learningFailed=false, connectionMissing=false, archivedCoachingState='saved';
    const poolMatches=Array.from({length:8},(_,index)=>({job_id:'pool-'+index,match_id:String(8984000000+index),hero:index===7?'npc_dota_hero_lion':'npc_dota_hero_necrolyte',label:index===7?'Lion':'Necrophos',position:index===7?5:index===6?null:2,outcome:index===6?null:index%2?'loss':'win',played_at:index===6?null:new Date(Date.now()-(50-index*7)*86400000).toISOString(),date_source:index===6?'analysis':'user',chronology_at:new Date(Date.now()-(50-index*7)*86400000).toISOString(),metrics:{deaths_per_30:10-index,gpm:400+index*20,xpm:500+index*20,last_hits_10:30+index,net_worth_10:4000+index*100,item_delay_seconds:index===3?null:120-index*10}}));
    const favorites=new Set(), goals=[], poolWrites=[], externalRequests=[];
    let learningPosition=null, learningAlias=false;
    const learningPlans=[], learningWrites=[];
    const learningStages=[['lane','Линия и ресурсы'],['map','Две следующие задачи'],['risk','Риск и возвращение в игру'],['items','Задача предмета'],['fights','Своя работа в бою'],['decisions','Самостоятельный разбор']].map(([id,title],index)=>({id,title,order:index+1,description:'Один навык — одна проверка.',exercise_ids:[]}));
    const learningExercises=learningStages.map((stage,index)=>({id:stage.id==='risk'?'r1':`fixture-${stage.id}`,stage_id:stage.id,title:stage.id==='risk'?'Проверить риск перед выходом':stage.title,roles:stage.id==='lane'?[1,2,3]:[],decision_question:'Чего я хотел добиться и что знал до решения?',signal:'Перед переходом на следующую задачу.',action:'Назови цель и условие отмены действия.',why:'Так можно заранее заметить опасность.',exception:'Срочная помощь может изменить план.',drill:'Выбери три похожих эпизода.',measurement:'Объясни выбор по информации до действия.',focus_window_matches:3,mini_lesson:'Это учебный пример, не факт о твоём матче.',source_refs:[],review_mode:stage.id==='risk'?'episode_review':'manual_context',evidence_types:stage.id==='risk'?['death']:[]}));
    const learningCatalog=position=>({role_context:roleProfiles[position||0],schema_version:'narma.curriculum.v1',version:'narma.curriculum.v1',stages:learningStages,exercises:learningExercises.filter(exercise=>!exercise.roles.length||exercise.roles.includes(position)),position,position_required:!position,sources:[]});
    const learningMatch=id=>poolMatches.find(match=>match.job_id===id)??{job_id:job?.id,match_id:'8984479726',hero:report.player.hero,position:learningPosition};
    const projectPlan=plan=>({...plan,validity:learningMatch(plan.source_job_id).position===plan.position?'current':'scope_changed',can_check:true,training_matches:0,reviewed_matches:plan.checks.length,self_report_counts:{applied:0,partial:0,not_applied:0,no_opportunity:plan.checks.filter(check=>check.self_assessment==='no_opportunity').length,uncertain:0}});
    function learningReport(id) {if(learningAlias&&id===job?.id)return {...learningReport('pool-1'),requested_job_id:id};const match=learningMatch(id);return {schema_version:'narma.learning.v1',job_id:id,requested_job_id:id,match_id:match.match_id,hero:match.hero,hero_label:'Necrophos',position:match.position,position_required:!match.position,catalog:learningCatalog(match.position),suggestions:[{exercise_id:'r1',kind:'episode_review',observation:'В реплее записана смерть; причина требует проверки.',evidence_ids:['death-1'],episode_time:600,limitation:'Факт смерти не доказывает ошибку.'}],review_candidates:[{evidence_id:'death-1',type:'death',time:id.startsWith('pool-')?600+Number(id.slice(5))*120:600,title:'Смерть героя'}],plans:learningPlans.filter(plan=>plan.hero===match.hero&&plan.position===match.position).map(projectPlan)};}

    const coachReference=index=>({job_id:'pool-'+index,match_id:String(8984000000+index),evidence_id:'death-1',time:600+index*120,type:'death'});
    const coachPatterns=[
      {id:'coach-return',title:'Возвращение на линию',observation:malicious,confidence:'medium',heroes:[{hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2}],evidence:[coachReference(0),coachReference(1)],goals:[{id:'coach-goal',action:'Перед возвращением проверь предмет.',success_criterion:malicious,evaluate_after_matches:2}]},
      {id:'coach-roles',title:'Решения в разных позициях',observation:'Проверь задачу своей позиции в каждом эпизоде.',confidence:'low',heroes:[{hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2},{hero:'npc_dota_hero_lion',label:'Lion',position:5}],evidence:[coachReference(0),coachReference(7)],goals:[]},
    ];
    function poolResponse(url) {
      const query=url.searchParams, hero=query.get('hero'), pos=query.get('position'), period=query.get('window'), favoriteOnly=query.get('favorites_only')==='true';
      const selected=poolMatches.filter(match=>(!hero||match.hero===hero)&&(!pos||String(match.position??'unknown')===pos)&&(!favoriteOnly||favorites.has(match.hero+':'+match.position))&&(period==='all'||Date.parse(match.chronology_at)>=Date.now()-Number(period)*86400000));
      const summarize=rows=>{const wins=rows.filter(r=>r.outcome==='win').length,losses=rows.filter(r=>r.outcome==='loss').length;return {matches:rows.length,wins,losses,known_outcomes:wins+losses,unknown_outcomes:rows.length-wins-losses,winrate_pct:wins+losses?Math.round(wins/(wins+losses)*1000)/10:null,unknown_positions:rows.filter(r=>r.position===null).length,analysis_dated_matches:rows.filter(r=>r.date_source==='analysis').length};};
      const groups=new Map(); for(const match of selected) {const key=match.hero+':'+match.position;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(match);}
      const sameRole=selected.filter(match=>match.hero==='npc_dota_hero_necrolyte'&&match.position===2);
      const selectedIds=new Set(selected.map(match=>match.match_id)), coaching={updated_at:'2026-09-08T06:00:00Z',patterns:coachPatterns.filter(pattern=>pattern.evidence.every(ref=>selectedIds.has(ref.match_id)))};
      return {role_context:roleProfiles[Number(pos)||0],summary:summarize(selected),heroes:[...groups].map(([key,rows])=>({hero:rows[0].hero,label:rows[0].label,position:rows[0].position,favorite:favorites.has(key),...summarize(rows)})),available_heroes:[{hero:'npc_dota_hero_necrolyte',label:'Necrophos'},{hero:'npc_dota_hero_lion',label:'Lion'}],history:selected,trends:sameRole.length===6?[{hero:'npc_dota_hero_necrolyte',position:2,metric:'deaths_per_30',status:'ready',early_n:3,recent_n:3,early_mean:9,recent_mean:6,delta:-3,unit:'смертей'}]:[],patterns:sameRole.length>=3?[{id:'repeat-death',hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2,title:malicious,observation:'Повторная смерть в двух матчах.',action:'Перед возвращением на линию проверь доступные предметы.',occurrences:2,eligible_matches:sameRole.length,evidence:[{job_id:'pool-0',match_id:'8984000000'}]}]:[],coaching:coaching.patterns.length?coaching:null,goals,limitations:['Синтетическая тестовая выборка. Дата разбора не является датой игры.']};
    }
    const errors=[], requests=[];
    const integrationRequests=[];
    const replayCreates=[],chatTurns=[],growthAttempts=[],feedbackWrites=[];
    let releaseReplayCreate,observeFirstReplayCreate;
    const firstReplayCreateGate=new Promise(resolve=>{releaseReplayCreate=resolve;});
    const firstReplayCreateStarted=new Promise(resolve=>{observeFirstReplayCreate=resolve;});
    let chatgpt={provider:'openai-codex',scope:'personal',configured:true,can_connect:true,status:'disconnected',auth_generation:null,connected_at:null,pending:null,last_error_code:null},chatgptPollConnect=false,chatgptRejectSession=false,chatgptDeleteFailed=false,chatgptProviderRejected=false;
    const pendingChatgpt=()=>({...chatgpt,status:'pending',auth_generation:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',pending:{user_code:'ABCD-12345',verification_url:'https://auth.openai.com/codex/device',expires_at:new Date(Date.now()+600000).toISOString(),poll_interval_seconds:5,poll_after_seconds:5}});
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      const url=route.request().url();
      if(url===itemImageUrl||url===blinkImageUrl||/^https:\/\/cdn\.cloudflare\.steamstatic\.com\/apps\/dota2\/images\/dota_react\/heroes\/(necrolyte|lion)\.png$/.test(url)) { if(width===1440) await route.fulfill({contentType:'image/png',body:itemImage}); else await route.abort(); }
      else if(new URL(url).origin!==origin) {externalRequests.push(url);await route.abort();}
      else await route.fallback();
    });
    await page.route('**/api/**',async route=>{if(await programFixture(route))return;
      const request=route.request(), url=new URL(request.url()), endpoint=url.pathname, method=request.method(); requests.push(endpoint);
      let body, status=200, responseHeaders={};
      if(endpoint==='/api/auth/login') { authenticated=true; body={authenticated:true}; }
      else if(endpoint==='/api/auth/logout') {authenticated=false;body={authenticated:false};}
      else if(endpoint==='/api/auth/security') body={recovery_codes_remaining:0};
      else if(endpoint==='/api/session') body={authenticated,setup_required:false,user:authenticated?{email:'fixture@example.test'}:null,coaching:{mode:'personal',personal_connect:true,available:false}};
      else if(endpoint.startsWith('/api/integrations/chatgpt')) {
        integrationRequests.push({method,endpoint,body:request.postDataJSON()});
        if(chatgptRejectSession){status=401;authenticated=false;responseHeaders={'X-Narma-Error':'PORTAL_SIGN_IN'};body={detail:malicious};}
        else if(chatgptProviderRejected&&endpoint.endsWith('/connect')){status=401;responseHeaders={'X-Narma-Error':'CHATGPT_AUTH_REJECTED'};body={detail:malicious};}
        else if(method==='DELETE'&&chatgptDeleteFailed){status=503;body={detail:malicious};}
        else {if(endpoint.endsWith('/connect')){assert.equal(method,'POST');assert.deepEqual(request.postDataJSON(),{});if(chatgpt.status!=='connected')chatgpt=pendingChatgpt();}
        else if(endpoint.endsWith('/poll')){assert.equal(method,'POST');assert.deepEqual(request.postDataJSON(),{auth_generation:chatgpt.auth_generation});if(chatgptPollConnect)chatgpt={...chatgpt,status:'connected',connected_at:new Date().toISOString(),pending:null};}
        else if(method==='DELETE')chatgpt={...chatgpt,status:'disconnected',auth_generation:null,connected_at:null,pending:null};
        body=chatgpt;}
      }
      else if(endpoint==='/api/learning'&&learningFailed) {status=503;body={detail:'Synthetic learning refresh failure.'};}
      else if(endpoint==='/api/learning/progress') body={plans:[]};
      else if(endpoint==='/api/learning') {const hero=url.searchParams.get('hero'),position=Number(url.searchParams.get('position'))||null;body={schema_version:'narma.learning.v1',catalog:learningCatalog(position),profile:bound?profile:null,scope:{hero,position},plans:learningPlans.filter(plan=>(!hero||plan.hero===hero)&&(!position||plan.position===position)).map(projectPlan),history:(learningEmpty?[]:[...poolMatches,...(job?[learningMatch(job.id)]:[])]).filter(match=>(!hero||match.hero===hero)&&(!position||match.position===position))};}
      else if(endpoint.startsWith('/api/learning/reports/')) body=learningReport(endpoint.split('/').at(-1));
      else if(endpoint==='/api/learning/plans'&&method==='POST') {const command=request.postDataJSON(),match=learningMatch(command.job_id);assert.ok(match.position);for(const plan of learningPlans)if(plan.hero===match.hero&&plan.position===match.position)plan.status='paused';const plan={id:`practice-${learningPlans.length+1}`,exercise_id:command.exercise_id,exercise:learningExercises.find(item=>item.id===command.exercise_id),hero:match.hero,hero_label:'Necrophos',position:match.position,status:'active',created_at:new Date().toISOString(),source_job_id:match.job_id,source_match_id:match.match_id,checks:[]};learningPlans.push(plan);body={saved:true,plan:projectPlan(plan)};}
      else if(/^\/api\/learning\/plans\/[^/]+\/checks$/.test(endpoint)&&method==='PUT') {const plan=learningPlans.find(item=>item.id===endpoint.split('/').at(-2)),command=request.postDataJSON();assert.ok(plan);learningWrites.push(command);const match=learningMatch(command.job_id);plan.checks=plan.checks.filter(check=>check.job_id!==command.job_id);plan.checks.push({...command,match_id:match.match_id,source:'player_self_report',validity:'current',chronology_status:command.job_id===plan.source_job_id?'baseline':'predates_plan',is_training:false,checked_at:new Date().toISOString()});body={saved:true,plan:projectPlan(plan)};}
      else if(endpoint.startsWith('/api/learning/plans/')&&method==='PATCH') {const plan=learningPlans.find(item=>item.id===endpoint.split('/').at(-1));plan.status=request.postDataJSON().status;body={saved:true,plan:projectPlan(plan)};}
      else if(job&&endpoint===`/api/hero-pool/matches/${job.id}`&&method==='PUT') {learningPosition=request.postDataJSON().position;body={saved:true};}
      else if(endpoint==='/api/hero-pool') {status=poolFailed?503:200;body=poolFailed?{detail:'Проверка восстановления после ошибки.'}:poolResponse(url);}
      else if(endpoint==='/api/hero-pool/favorites'&&method==='PUT') {const value=request.postDataJSON();favorites.add(value.hero+':'+value.position);body={saved:true};}
      else if(endpoint.startsWith('/api/hero-pool/favorites/')&&method==='DELETE') {const parts=endpoint.split('/');favorites.delete(parts[4]+':'+parts[5]);body={deleted:true};}
      else if(endpoint.startsWith('/api/hero-pool/matches/')&&method==='PUT') {const match=poolMatches.find(item=>item.job_id===endpoint.split('/').at(-1));assert.ok(match);const value=request.postDataJSON();poolWrites.push(value);if(poolSaveFailed&&'note' in value){status=503;body={detail:'Не удалось сохранить дневник (проверка).'};}else{if('position' in value)match.position=value.position;if('played_at' in value){match.played_at=value.played_at;match.date_source=value.played_at?'user':'analysis';match.chronology_at=value.played_at??match.analyzed_at??match.chronology_at;}for(const key of ['focus','reflection','note'])if(key in value)match[key]=value[key];body={saved:true};}}
      else if(endpoint==='/api/hero-pool/goals'&&method==='POST') {const value=request.postDataJSON();goals.push({id:'goal-1',...value,title:'Практика после смерти',action:'Проверь готовность перед возвращением.',status:'active',metric:'repeated_deaths',threshold:0,checks:[{job_id:'pool-0',match_id:'8984000000',value:1,status:'predates_goal',chronology_basis:'user'},{job_id:'pool-1',match_id:'8984000001',value:0,status:'unknown',chronology_basis:'analysis'}]});body={goal:goals[0]};}
      else if(endpoint.startsWith('/api/hero-pool/goals/')&&method==='PATCH') {goals[0].status=request.postDataJSON().status;body={saved:true};}
      else if(endpoint==='/api/profile') body={profile:bound?profile:null};
      else if(/^\/api\/replays\/pool-\d+$/.test(endpoint)) {
        const match=poolMatches.find(row=>row.job_id===endpoint.split('/').at(-1));assert.ok(match);
        const event={id:'death-1',type:'death',time:coachReference(Number(match.job_id.slice(5))).time,title:'Смерть выбранного героя',details:'Синтетический эпизод для проверки ссылки.'};
        body={replay:{id:match.job_id,state:'ready',progress:100,match_id:match.match_id,nickname:profile.nickname,created_at:new Date().toISOString()},report:{...report,match_id:match.match_id,player:{...report.player,hero:match.hero},evidence:[event]},hero_context:null,archived_report:null,parts:[]};
      }
      else if(endpoint.endsWith('/practice')&&endpoint.startsWith('/api/replays/')){
        if(method==='POST'){growthAttempts.push(request.postDataJSON());body={saved:true,reflection:{action:'Сначала назови достижимую цель.',why:'Это позволяет сравнить варианты.',exception:'Срочная защита меняет приоритет.',measurement:'Проверь информацию до решения.'},note:'Ориентир для самостоятельной проверки.'};}
        else body={report_sha256:'c'.repeat(64),position_required:false,attempts:[],scenarios:[{exercise_id:'r1',title:'Решение до смерти',question:'Какую пользу ты ожидал и какие варианты были доступны?',episode:{evidence_id:'death-1',time:600}}]};
      }
      else if(endpoint.endsWith('/feedback')){feedbackWrites.push(request.postDataJSON());body={saved:true};}
      else if(/^\/api\/replays\/[^/]+\/chat$/.test(endpoint)) {
        if(method==='POST'){const value=request.postDataJSON();assert.equal(value.report_sha256,'c'.repeat(64));const turn={...value,state:'succeeded',answer:{answer:'Проверь, какую цель давало возвращение.',next_step:'Перед выходом назови цель.',evidence_ids:['death-1']}};if(!chatTurns.some(item=>item.id===value.id))chatTurns.push(turn);body={turn};}
        else body={turns:chatTurns,report_sha256:'c'.repeat(64),context:{training_level:'advanced'},available:true};
      }
      else if(endpoint==='/api/replays'&&method==='POST') {
        const command=request.postDataJSON(); assert.equal(command.filename,'synthetic.dem'); assert.equal(command.nickname,'SyntheticPlayer'); assert.equal('account_id' in command,false);
        replayCreates.push(command);
        if(replayCreates.length===1){observeFirstReplayCreate();await firstReplayCreateGate;}
        if(replayCreates.length<=2){status=503;body={detail:'Проверка восстановления загрузки.'};}
        else{job={...command,state:'uploading',progress:0,match_id:null,created_at:new Date().toISOString()};status=201;body={replay:job,part_bytes:5*1024**2};}
      }
      else if(endpoint==='/api/replays') body={replays:job?[job]:[],worker_ready:true,max_bytes:512*1024**2};
      else if(job&&endpoint===`/api/replays/${job.id}/parts/1`&&method==='PUT') { uploaded=true; learningEmpty=false; assert.equal(request.postDataBuffer().subarray(0,8).toString('binary'),'PBDEMS2\x00'); body={uploaded:true,part_number:1}; }
      else if(job&&endpoint===`/api/replays/${job.id}/complete`) { assert.equal(uploaded,true); bound=true; job={...job,state:'ready',progress:100,match_id:'8984479726'}; body={replay:job}; }
      else if(job&&endpoint===`/api/replays/${job.id}/source`&&method==='DELETE') {job.source_retained=false;body={source_deleted:true,report_retained:true};}
      else if(job&&endpoint===`/api/replays/${job.id}`) body={replay:job,hero_context:legacy?{...heroContext,hero:'npc_dota_hero_lion',label:'Lion'}:heroContext,parts:uploaded?[1]:[],archived_report:job.state==='ready'?{id:1,created_at:new Date().toISOString(),hero_context:{...heroContext,summary:'Контекст сохранённого разбора.',abilities:[{...heroContext.abilities[0],casts:7}]},report:{...report,metrics:{...report.metrics,kills:9},evidence:[{id:'old-death',type:'death',time:500,title:'Старый эпизод'}],coaching:{status:'ready',summary:'Сохранённый комментарий',points:[{title:'Сохранённый эпизод',observation:'Предыдущий разбор.',evidence_ids:['old-death']}]}}}:null,report:job.state==='ready'?{...report,...(legacy?{insights:undefined,coaching:{status:'unavailable',points:[]}}:{}),...(width===1440?{coaching:{status:'unavailable',summary:'',points:[]}}:{}),...(connectionMissing?{coaching:{status:'unavailable',failure_code:'CHATGPT_NOT_CONNECTED',points:[]}}:{})}:null};
      else throw Error(`Unexpected frontend API request: ${method} ${endpoint}`);
      if(job&&endpoint===`/api/replays/${job.id}`) {
        body.report_sha256='c'.repeat(64);
        body.coaching_status=width===390&&!legacy&&!connectionMissing?{state:'ready',provider:'openai_api',verified_openai:true,reason_code:null,usage:{input_tokens:1200,output_tokens:300,cached_input_tokens:400},billing_state:'settled',charged_microusd:2750}:{state:'unavailable',provider:'openai_api',verified_openai:false,reason_code:connectionMissing?'CHATGPT_NOT_CONNECTED':'OPENAI_BUDGET_EXCEEDED',usage:null,billing_state:'none',charged_microusd:null};
        if(body.archived_report) {
          body.archived_report.coaching_status={state:archivedCoachingState,provider:null,verified_openai:false,reason_code:archivedCoachingState==='context_changed'?'REPLAY_COACH_CONTEXT_CHANGED':null,usage:null,billing_state:'none',charged_microusd:null};
          if(archivedCoachingState==='unavailable'||archivedCoachingState==='context_changed')body.archived_report.report.coaching={status:archivedCoachingState,summary:'',points:[]};
        }
      }
      await route.fulfill({status,json:body,headers:responseHeaders});
    });
    await page.addInitScript(()=>{
      window.__narmaMotion=[];
      document.addEventListener('animationstart',event=>{
        if(event.animationName.startsWith('narma-'))window.__narmaMotion.push({name:event.animationName,parent:event.target.parentElement?.id});
      });
    });
    await page.goto(origin+'/replays');
    assert.equal(await page.evaluate(()=>getComputedStyle(document.body,'::before').animationName),'none');
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>!document.querySelector('.narma-cut-playing'));
    assert.deepEqual(await page.evaluate(()=>({animation:getComputedStyle(document.body,'::before').animationName,transform:getComputedStyle(document.body,'::before').transform,events:getComputedStyle(document.body,'::before').pointerEvents})),{animation:'none',transform:'none',events:'none'},'Personal replay pages respect reduced motion without blocking controls.');
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.reload();
    await page.getByLabel('Email',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>window.__narmaMotion.length),0,'The brand introduction does not repeat on navigation in the same tab.');
    await page.getByLabel('Email',{exact:true}).fill('fixture@example.test');
    await page.getByLabel('Пароль',{exact:true}).fill('Synthetic passphrase 2026');
    await page.getByRole('button',{name:'Войти',exact:true}).click();
    await page.getByRole('heading',{name:'Разбор твоего матча'}).waitFor();
    await page.waitForFunction(()=>window.__narmaMotion.some(event=>event.name==='narma-signature-cut'));
    assert.equal(await page.locator('#workspace-signature').isVisible(),true,'The signed-in player can see and replay the signature.');
    const nicknameBeforeShortcut=await page.locator('#nickname').inputValue();
    await page.locator('#nickname').fill('Unsubmitted fixture draft');
    await page.locator('.workspace-shortcuts a[data-tab="coach"]').click();
    assert.equal(new URL(page.url()).pathname,'/coach');
    await page.locator('.workspace-shortcuts a[data-tab="review"]').click();
    assert.equal(new URL(page.url()).pathname,'/replays');
    assert.equal(await page.locator('#nickname').inputValue(),'Unsubmitted fixture draft','Shortcuts preserve an unfinished upload form.');
    await page.locator('#nickname').fill(nicknameBeforeShortcut);
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-entry.png`)});
    // A new player gets a usable learning section before uploading any match.
    const initialPoolRequests=requests.filter(endpoint=>endpoint==='/api/hero-pool').length;
    await page.locator('nav [data-tab="learning"]').click();
    assert.equal(new URL(page.url()).pathname,'/my-learning');
    await page.locator('#learning .learning-stages').waitFor();
    assert.equal(await page.locator('#learning .learning-stages button').count(),6);
    await page.locator('#learning').getByRole('button',{name:'3 · Риск и возвращение в игру',exact:true}).click();
    await page.locator('#learning .learning-exercise').waitFor();
    assert.equal(await page.locator('#learning .learning-start').count(),0,'No-match learning is readable without inventing a saved training plan.');
    assert.equal(requests.filter(endpoint=>endpoint==='/api/hero-pool').length,initialPoolRequests,'Learning does not depend on first opening the hero pool.');
    await page.locator('#learning-position').selectOption('2');
    await page.locator('#learning .learning-exercise').waitFor();
    assert.equal(await page.locator('#pool-position').inputValue(),'','Learning has its own position filter.');
    await page.locator('nav [data-tab="player"]').click();
    assert.equal(new URL(page.url()).pathname,'/player');
    await page.goBack();
    assert.equal(new URL(page.url()).pathname,'/my-learning');
    assert.equal(await page.locator('#learning').isVisible(),true);
    assert.equal(await page.locator('#learning-position').inputValue(),'2','Back navigation preserves the learning scope.');
    await page.goBack();
    assert.equal(new URL(page.url()).pathname,'/replays');
    assert.equal(await page.locator('#review').isVisible(),true);
    await page.goForward();
    assert.equal(new URL(page.url()).pathname,'/my-learning');
    assert.equal(await page.locator('#learning').isVisible(),true);
    await page.reload();
    await page.locator('#learning .learning-stages').waitFor();
    assert.equal(await page.locator('#learning').isVisible(),true,'The learning URL survives a full reload.');
    await page.locator('nav [data-tab="review"]').click();
    assert.equal(new URL(page.url()).pathname,'/replays');
    assert.equal(await page.getByRole('button',{name:'Загрузить и разобрать'}).isDisabled(),true);
    assert.equal(await page.locator('#replay-file').getAttribute('accept'),'.dem');
    assert.equal(await page.locator('body').innerText().then(text=>/OpenDota|Open Dota|MP4|3\s?600 кадров/.test(text)),false);
    await page.getByLabel('Твой ник в этом матче',{exact:true}).fill('SyntheticPlayer');
    await page.locator('#replay-position').selectOption('5');
    await page.locator('#replay-mmr').fill('1250');
    await page.locator('#replay-training-level').selectOption('foundations');
    await page.locator('#replay-file').setInputFiles({name:'synthetic.dem',mimeType:'application/octet-stream',buffer:Buffer.concat([Buffer.from('PBDEMS2\x00','binary'),Buffer.alloc(32)])});
    assert.equal(await page.getByRole('button',{name:'Загрузить и разобрать'}).isEnabled(),true);
    await page.getByRole('button',{name:'Загрузить и разобрать'}).click();
    await firstReplayCreateStarted;
    for(const selector of ['#replay-submit','#replay-file','#nickname','#replay-position','#replay-mmr','#replay-training-level'])assert.equal(await page.locator(selector).isDisabled(),true,'An active upload freezes its selected context.');
    assert.deepEqual({position:replayCreates[0].position,mmr:replayCreates[0].mmr,training_level:replayCreates[0].training_level},{position:5,mmr:1250,training_level:'foundations'},'The replay create request carries explicit role, MMR and training depth.');
    releaseReplayCreate();
    await page.waitForFunction(()=>document.querySelector('#upload-status').textContent==='Проверка восстановления загрузки.'&&!document.querySelector('#replay-submit').disabled);
    assert.equal(await page.locator('#replay-position').inputValue(),'5');
    assert.equal(await page.locator('#replay-mmr').inputValue(),'1250');
    assert.equal(await page.locator('#replay-training-level').inputValue(),'foundations');
    const retryResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/replays'&&response.request().method()==='POST');
    await page.getByRole('button',{name:'Загрузить и разобрать'}).click();
    await retryResponse;
    await page.waitForFunction(()=>!document.querySelector('#replay-submit').disabled);
    assert.deepEqual(replayCreates[1],replayCreates[0],'Retrying an unchanged upload preserves its idempotency ID and training context.');
    await page.locator('#replay-position').selectOption('2');
    await page.locator('#replay-mmr').fill('6500');
    await page.locator('#replay-training-level').selectOption('advanced');
    await page.getByRole('button',{name:'Загрузить и разобрать'}).click();
    await page.getByRole('heading',{name:'Матч 8984479726',exact:true}).waitFor();
    assert.equal(replayCreates.length,3);
    assert.notEqual(replayCreates[2].id,replayCreates[0].id,'Changing context after a failed upload creates a distinct request.');
    assert.deepEqual({position:replayCreates[2].position,mmr:replayCreates[2].mmr,training_level:replayCreates[2].training_level},{position:2,mmr:6500,training_level:'advanced'});
    await page.getByText('17 / 16 / 20',{exact:true}).waitFor();
    await page.locator('#report-chat').getByRole('button',{name:'Спросить тренера',exact:true}).waitFor();
    await page.locator('#report-chat').getByLabel('Твой вопрос',{exact:true}).fill('Как проверить выкуп?');
    await page.locator('#report-chat').getByRole('button',{name:'Спросить тренера',exact:true}).click();
    await page.locator('#report-chat').getByText('Проверь, какую цель давало возвращение.',{exact:true}).waitFor();
    assert.equal(chatTurns.length,1,'One explicit question creates one chat turn.');
    await page.locator('#report-chat').getByRole('button',{name:'Обновить разговор',exact:true}).click();
    assert.equal(chatTurns.length,1,'Reading saved chat never creates another paid request.');
    await page.locator('#report-chat').getByLabel('Контекст разговора',{exact:true}).selectOption('series');
    await page.locator('#report-chat').getByLabel('Твой вопрос',{exact:true}).fill('Как менялись мои решения в последних матчах?');
    await page.locator('#report-chat').getByRole('button',{name:'Спросить тренера',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#report-chat .chat-question').length===2);
    assert.equal(chatTurns.at(-1).scope,'series');
    const growth=page.locator('#report-growth');
    await growth.getByText('Потренироваться на эпизоде из этого матча',{exact:true}).click();
    await growth.getByLabel('Как бы ты поступил и почему?',{exact:true}).fill('Сначала проверю доступную цель и союзников.');
    assert.equal(await growth.getByText('Сначала назови достижимую цель.',{exact:true}).count(),0);
    await growth.getByRole('button',{name:'Сохранить ответ и разобрать варианты',exact:true}).click();
    await growth.getByText('Сначала назови достижимую цель.',{exact:true}).waitFor();
    assert.equal(growthAttempts.length,1);
    if(width===390){
      await growth.getByText('Оценить совет тренера',{exact:true}).click();
      await growth.getByLabel('Пояснение',{exact:true}).fill('Не учтена защита базы.');
      await growth.getByRole('button',{name:'Сохранить отзыв',exact:true}).click();
      await growth.getByText('Отзыв сохранён. Спасибо!',{exact:false}).waitFor();
      assert.equal(feedbackWrites.length,1);
    }
    await growth.getByText('Карточка для Telegram',{exact:true}).click();
    assert.equal(await growth.getByLabel('Показать мой ник',{exact:true}).isChecked(),false);
    assert.equal(await growth.getByLabel('Показать номер матча',{exact:true}).isChecked(),false);
    await growth.getByRole('button',{name:'Посмотреть карточку',exact:true}).click();
    await growth.locator('.share-preview').waitFor();
    const png=page.waitForEvent('download');await growth.getByRole('button',{name:'Скачать PNG',exact:true}).click();
    assert.equal((await png).suggestedFilename(),'narma-vision-result.png');
    assert.equal(chatTurns.length,2,'Practice, feedback and preview do not silently call the model.');
    await growth.getByText('Потренироваться на эпизоде из этого матча',{exact:true}).click();
    await growth.getByText('Карточка для Telegram',{exact:true}).click();
    if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`portal-${width}-coach-chat.png`),fullPage:true});
    assert.equal(await page.evaluate(()=>window.__narmaMotion.filter(event=>event.parent==='result-signature').length),0,'Opening a saved report is not a new analysis completion.');
    job.state='processing';job.progress=60;
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.locator('#result-state').getByText('Разбираем матч',{exact:true}).waitFor();
    assert.equal(await page.locator('#result-signature').isHidden(),true);
    job.state='ready';job.progress=100;
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.waitForFunction(()=>window.__narmaMotion.some(event=>event.name==='narma-cut-line'&&event.parent==='result-signature'));
    await page.waitForFunction(()=>!document.querySelector('#result-signature.narma-cut-playing'));
    const completedCuts=await page.evaluate(()=>window.__narmaMotion.filter(event=>event.name==='narma-cut-line'&&event.parent==='result-signature').length);
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.locator('#result-state').getByText('Разбор готов',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>window.__narmaMotion.filter(event=>event.name==='narma-cut-line'&&event.parent==='result-signature').length),completedCuts,'Reading a ready result does not repeat the completion animation.');
    if(width===390) {
      assert.match(await page.locator('#report-ai-status').textContent(),/Комментарий OpenAI подтверждён/);
      assert.match(await page.locator('#report-ai-status').textContent(),/Учтено для этого разбора: 1\s?200 токенов на входе · 300 в ответе/);
      assert.match(await page.locator('#report-ai-status').textContent(),/400 из кэша/);
      assert.match(await page.locator('#report-ai-status').textContent(),/\$0,00275/);
    } else {
      assert.match(await page.locator('#report-ai-status').textContent(),/без нового комментария ИИ/);
      assert.match(await page.locator('#report-ai-status').textContent(),/остановлен лимитом расходов/);
      assert.equal(await page.locator('.report-ai-usage').count(),0,'Missing accounting is not displayed as zero token usage.');
    }
    assert.equal(await page.evaluate(()=>{
      const top=id=>document.getElementById(id).getBoundingClientRect().top;
      return top('coaching-heading')<top('next-game-heading')&&top('next-game-plan')<top('report-learning')&&top('next-game-heading')<top('metrics')&&top('metrics')<top('economy-heading');
    }),true,'Grounded coaching and the next-game plan precede raw statistics and charts.');
    if(screenshotDir) {await page.locator('#report-hero').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(screenshotDir,`portal-${width}-hero-header.png`)});}
    assert.equal(await page.locator('#nickname-field').isHidden(),true);
    assert.equal(await page.locator('#timeline-value').textContent(),'78:41');
    await page.locator('#economy-heading').scrollIntoViewIfNeeded();
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-charts.png`)});
    assert.equal(await page.locator('#combat-strip svg').count(),0,'Episode navigation does not depend on tiny overlapping SVG targets.');
    assert.equal(await page.getByRole('button',{name:'Смерти · 1',exact:true,pressed:true}).count(),1);
    await page.locator('.episode-choice').first().focus();await page.locator('.episode-choice').first().press('Enter');
    await page.waitForFunction(()=>window.__narmaMotion.some(event=>event.name==='narma-episode-cut'));
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>!document.querySelector('.narma-episode-playing'));
    assert.equal(await page.locator('.narma-episode-line').count(),0,'Reduced motion removes the active decoration, retaining the selected episode.');
    await page.locator('.episode-choice').first().click();
    assert.equal(await page.locator('.narma-episode-line').count(),0);
    await page.emulateMedia({reducedMotion:'no-preference'});
    assert.equal(await page.locator('#timeline-value').textContent(),'10:00');
    assert.equal(await page.locator('.episode-choice[aria-pressed=true]').count(),1);
    assert.match(await page.locator('.episode-detail').textContent(),/Время вне игры по реплею: 0:30/);
    await page.getByRole('button',{name:'За 30 с до события',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'9:30');
    assert.equal(await page.locator('#timeline').getAttribute('aria-valuetext'),'9:30');
    assert.match(await page.locator('#timeline-snapshot').textContent(),/На графиках: 9:30.*Последняя запись: 9:00.*Убийства:.*Смерти:.*Помощи:/);
    assert.equal(await page.locator('#gold-chart .chart-cursor').getAttribute('x1'),await page.locator('#xp-chart .chart-cursor').getAttribute('x1'));
    await page.getByRole('button',{name:'В момент события',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'10:00');
    if(screenshotDir) await page.locator('.episode-review').screenshot({path:path.join(screenshotDir,`portal-${width}-episodes.png`)});
    await page.getByRole('button',{name:'Убийства · 0',exact:true}).click();
    assert.equal(await page.locator('.episode-choice').count(),0,'Totals do not manufacture missing event timestamps.');
    assert.match(await page.locator('.episode-detail').textContent(),/нет таймкодов/);
    await page.getByRole('button',{name:'Ключевые предметы · 2',exact:true}).click();
    await page.locator('#combat-strip').getByRole('button',{name:'21:40 · Покупка · Blink',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'21:40');
    await page.getByRole('button',{name:'Смерти · 1',exact:true}).click();
    await page.locator('#findings').getByRole('button',{name:'10:00 · Смерть',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'10:00');
    assert.equal(await page.locator('#gold-chart .chart-cursor').getAttribute('x1'),await page.locator('#xp-chart .chart-cursor').getAttribute('x1'));
    assert.match(await page.locator('#gold-value').textContent(),/4\s?000/);
    assert.match(await page.locator('#xp-value').textContent(),/5\s?000/);
    await page.getByLabel('Показать',{exact:true}).selectOption('purchase');
    assert.equal(await page.locator('#events .event-row').count(),1);
    assert.match(await page.locator('#events').textContent(),/Radiance/);
    if(width===390) assert.equal(await page.getByRole('heading',{name:malicious,exact:true}).count(),1);
    else { await page.getByText('Тренерский комментарий временно недоступен. Статистика и эпизоды из реплея доступны.',{exact:true}).waitFor(); assert.equal(await page.locator('#coaching .report-point').count(),0); }
    assert.equal(await page.locator('#coaching img').count(),0);
    assert.equal(await page.locator('#income-chart .chart-bar').count(),79);
    assert.equal(await page.locator('#farm-chart .chart-bar').count(),79);
    assert.equal(await page.locator('#gold-sources .source-row').count(),3);
    const incomeLayout=await page.evaluate(()=>{
      const rect=selector=>{const {x,y,width,height}=document.querySelector(selector).getBoundingClientRect();return {x,y,width,height};};
      return {sources:rect('#gold-sources'),income:rect('.economy-card.income'),farm:rect('.economy-card.farming'),summary:rect('#moment-summary')};
    });
    assert.ok(Math.abs(incomeLayout.income.x-incomeLayout.farm.x)<1,'Income and last hits share one column.');
    assert.ok(Math.abs(incomeLayout.income.width-incomeLayout.farm.width)<1,'Income and last hits have equal widths.');
    assert.ok(Math.abs(incomeLayout.farm.y-incomeLayout.income.y-incomeLayout.income.height-18)<1,'Last hits sit directly below income, without waiting for the source list.');
    assert.ok(incomeLayout.summary.y>=incomeLayout.farm.y+incomeLayout.farm.height,'Selected interval follows both charts.');
    if(width>680) assert.ok(incomeLayout.income.x>=incomeLayout.sources.x+incomeLayout.sources.width,'Both interval charts occupy the right column.');
    else assert.ok(incomeLayout.income.y>=incomeLayout.sources.y+incomeLayout.sources.height,'Income sources and charts stack on mobile.');
    await page.locator('#farm-chart').click();
    assert.equal(await page.locator('#farm-chart .chart-cursor').getAttribute('x1'),await page.locator('#income-chart .chart-cursor').getAttribute('x1'));
    assert.equal(await page.locator('#farm-chart .chart-cursor').getAttribute('x1'),await page.locator('#xp-chart .chart-cursor').getAttribute('x1'));
    if(screenshotDir) await page.locator('[aria-labelledby="income-heading"]').screenshot({path:path.join(screenshotDir,`portal-${width}-income.png`)});
    await page.locator('.legacy-training > summary').click();
    assert.equal(await page.locator('#next-game-plan .training-card').count(),1);
    assert.equal(await page.locator('#item-cards .item-card:visible').count(),1);
    assert.equal(await page.locator('#item-rail .item-chip').count(),2);
    assert.equal(await page.getByRole('button',{name:'11:40 · Radiance',exact:true,pressed:true}).count(),1);
    await page.getByRole('heading',{name:'Разбор за Necrophos',exact:true}).waitFor();
    assert.match(await page.locator('#hero-context').textContent(),/Позиция 2 · указана тобой/);
    assert.match(await page.locator('#hero-context').textContent(),/Death Pulse42 применений−0:05 — 76:40/);
    assert.equal(await page.locator('#hero-context a').count(),1,'Only safe source links are shown.');
    assert.equal(await page.locator('#next-game-plan h4').textContent(),width===390?'Один предмет — один план':'План за Necrophos','A validated personal coaching plan takes priority; the hero template is only the fallback.');
    if(width===390){assert.match(await page.locator('#next-game-plan').textContent(),/Перед покупкой выбери следующий безопасный эпизод/);assert.doesNotMatch(await page.locator('#next-game-plan').textContent(),/Проверь применение Death Pulse/);}
    if(screenshotDir) await page.locator('#hero-context').screenshot({path:path.join(screenshotDir,`portal-${width}-hero-context.png`)});
    const itemCard=page.locator('#item-cards .item-card').first();
    await itemCard.scrollIntoViewIfNeeded();
    assert.equal(await itemCard.locator('.item-image').getAttribute('src'),itemImageUrl);
    assert.equal(await itemCard.locator('.item-image').getAttribute('referrerpolicy'),'no-referrer');
    assert.equal(await itemCard.locator('.item-image').getAttribute('alt'),'');
    if(width===1440) await itemCard.locator('.item-image-loaded').waitFor();
    else {await page.waitForFunction(()=>document.querySelector('#item-cards .item-image').hidden);assert.equal(await itemCard.locator('.item-icon-fallback').isVisible(),true);}
    assert.equal(await itemCard.getByRole('button',{name:'Покупка: 11:40',exact:true}).textContent(),'11:40');
    assert.equal(await itemCard.locator('.item-milestones .item-missing').textContent(),'Нет записи');

    await page.locator('.item-chip').first().click();
    assert.equal(await page.locator('#timeline-value').textContent(),'11:40');
    assert.match(await page.locator('#income-value').textContent(),/1\s?000/);
    await itemCard.getByText('Сравнить со своей целью',{exact:true}).click();
    await itemCard.getByLabel('Личная цель, мин:сек',{exact:true}).fill('10:00');
    const blinkChip=page.locator('#item-rail .item-chip').nth(1);
    await blinkChip.focus(); await blinkChip.press('Enter');
    assert.equal(await blinkChip.getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#item-rail .item-chip[aria-pressed=true]').count(),1);
    assert.equal(await page.locator('#item-cards .item-card:visible').count(),1);
    const selectedCard=page.locator('#item-cards .item-card:visible');
    assert.equal(await selectedCard.locator('h4').textContent(),'Blink');
    assert.equal(await page.locator('#timeline-value').textContent(),'21:40');
    const blinkTop=await blinkChip.boundingBox(); assert.ok(blinkTop&&blinkTop.y>=0&&blinkTop.y<1000,'Selecting an item keeps the item rail in view.');
    assert.equal(await selectedCard.getByRole('button',{name:'Первое применение: 22:10',exact:true}).textContent(),'22:10');
    const singleCardLayout=await page.locator('#item-cards').evaluate(element=>({width:element.getBoundingClientRect().width,card:element.querySelector('.item-card:not([hidden])').getBoundingClientRect().width}));
    assert.ok(Math.abs(singleCardLayout.width-singleCardLayout.card)<1,'The selected item fills the available row.');
    await page.locator('#findings').getByRole('button',{name:'10:00 · Смерть',exact:true}).click();
    assert.equal(await selectedCard.locator('h4').textContent(),'Blink','Seeking another event does not replace the chosen item.');
    await page.locator('#item-rail .item-chip').first().click();
    assert.equal(await itemCard.getByLabel('Личная цель, мин:сек',{exact:true}).inputValue(),'10:00','Unsaved goals survive switching items.');
    assert.equal(await itemCard.locator('.item-goal').getAttribute('open'),'');
    await page.getByRole('button',{name:'Применить',exact:true}).click();
    await page.getByText('Поздний · личная цель',{exact:true}).waitFor();
    assert.match(await itemCard.locator('.item-timing').textContent(),/не с другими игроками/);
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-items.png`)});
    await page.getByRole('button',{name:'Убрать цель',exact:true}).click();
    await itemCard.getByText('Без эталона',{exact:true}).waitFor();
    assert.equal(await page.locator('#income-chart .chart-cursor').getAttribute('x1'),await page.locator('#xp-chart .chart-cursor').getAttribute('x1'));
    const axe=dependency('axe-core'); await page.addScriptTag({content:axe.source});
    const accessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(accessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const originalItemId=report.insights.items[0].item;
    report.insights.items[0].item='item_../../foreign';
    await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#item-cards .item-card:not([hidden]) .item-image')===null);
    assert.equal(await page.locator('#item-rail .item-chip').first().locator('.item-image').count(),0,'Malformed item identifiers cannot create external image URLs.');
    report.insights.items[0].item=originalItemId;
    await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#item-cards .item-image').length===2);
    await page.locator('#item-rail .item-chip').nth(1).click();
    await page.getByRole('button',{name:'Предыдущий тренерский разбор',exact:true}).click();
    await page.getByRole('heading',{name:'Сохранённый эпизод',exact:true}).waitFor();
    assert.match(await page.locator('#report-ai-status').textContent(),/Показан сохранённый комментарий/);
    assert.equal(await page.locator('.report-ai-usage').count(),0,'An archived comment does not inherit the current report call usage.');
    assert.equal(await page.locator('#item-cards .item-card:visible h4').textContent(),'Radiance','An archived report starts with its own first item.');
    assert.match(await page.locator('#hero-context').textContent(),/Контекст сохранённого разбора/);
    assert.match(await page.locator('#hero-context .hero-abilities').textContent(),/7 применений/);
    assert.match(await page.locator('#metrics').textContent(),/9 \/ 16 \/ 20/);
    await page.locator('#coaching').getByRole('button',{name:'8:20 · Смерть',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'8:20');
    assert.equal(await page.locator('#events [data-evidence-id=old-death].selected-event').count(),1);
    await page.locator('#item-rail .item-chip').nth(1).click();
    await page.getByRole('button',{name:'Вернуться к текущему разбору',exact:true}).click();
    assert.equal(await page.locator('#item-cards .item-card:visible h4').textContent(),'Radiance','Current-report selection never inherits the archived selection.');
    assert.equal(await page.locator('#events [data-evidence-id=old-death]').count(),0);
    for(const [archiveState,heading] of [['unavailable','Статистика готова · без нового комментария ИИ'],['context_changed','Контекст изменился · комментарий требует обновления'],['unknown','Источник комментария не подтверждён']]) {
      archivedCoachingState=archiveState;
      const refreshedArchive=page.waitForResponse(response=>new URL(response.url()).pathname===`/api/replays/${job.id}`);
      await page.getByRole('button',{name:'Обновить',exact:true}).click();
      await (await refreshedArchive).finished();
      await page.waitForFunction(label=>document.querySelector('#previous-report-toggle').textContent===label,archiveState==='unknown'?'Предыдущий тренерский разбор':'Предыдущая версия разбора');
      await page.locator('#previous-report-toggle').click();
      assert.equal(await page.locator('#report-ai-status .report-ai-title').textContent(),heading,'Opening an archive preserves its explicit coaching failure/provenance verdict.');
      assert.doesNotMatch(await page.locator('#report-ai-status').textContent(),/Показан сохранённый комментарий|Комментарий OpenAI подтверждён/);
      assert.equal(await page.locator('.report-ai-usage').count(),0);
      if(archiveState!=='unknown')assert.equal(await page.locator('#coaching .report-point').count(),0,'A factual-only or stale-context archive has no ready coaching points.');
      await page.locator('#previous-report-toggle').click();
    }
    archivedCoachingState='saved';
    connectionMissing=true;
    await page.getByRole('button',{name:'Обновить',exact:true}).click();
    const coachingConnect=page.locator('#coaching a.coaching-connect');
    await coachingConnect.waitFor();
    assert.equal(await coachingConnect.getAttribute('href'),'/account','Unavailable coaching explains the next useful action.');
    assert.match(await page.locator('#coaching-summary').textContent(),/Подключи ChatGPT/);
    connectionMissing=false;
    legacy=true; await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.getByText('В этом отчёте нет разбивки золота по источникам. Изменение ценности предметов показано выше.',{exact:true}).waitFor();
    assert.equal(await page.locator('#gold-chart .chart-line').count(),1);
    assert.equal(await page.locator('#item-cards .item-card').count(),1);
    assert.equal(await page.locator('#income-chart .chart-bar').count(),0);
    assert.equal(await page.locator('#hero-context').isHidden(),true,'Context for another hero is never attached to this report.');
    await page.locator('nav [data-tab="hero-pool"]').click();
    await page.getByRole('heading',{name:'Пул героев',exact:true}).waitFor();
    await page.locator('#pool-roster .pool-hero-row').first().waitFor();
    assert.equal(await page.locator('#pool-roster .pool-hero-row').count(),3);
    assert.match(await page.locator('#pool-summary').textContent(),/42,9%/);
    assert.match(await page.locator('#pool-summary').textContent(),/Исход неизвестен1/);
    assert.match(await page.locator('#pool-coverage').textContent(),/нет даты игры/);
    assert.equal(await page.locator('#pool-trend-chart .pool-chart-line').count(),0);
    assert.equal(await page.locator('#pool-patterns img').count(),0);
    assert.equal(await page.getByRole('button',{name:'Скачать пакет для Hermes',exact:true}).count(),0);
    assert.equal(await page.getByRole('heading',{name:'Hermes не подключён',exact:true}).count(),0);
    const coachCards=page.locator('#pool-patterns .pool-coach-card');
    assert.equal(await coachCards.count(),2);
    const coachCard=coachCards.filter({has:page.getByRole('heading',{name:'Возвращение на линию',exact:true})});
    assert.equal(await coachCard.getByText(malicious,{exact:true}).count(),1,'Coach observations remain literal text.');
    assert.equal(await coachCard.getByText('Как проверить: '+malicious,{exact:true}).count(),1,'Goal criteria remain literal text.');
    assert.equal(await coachCard.getByText('Перед возвращением проверь предмет.',{exact:true}).count(),1);
    assert.match(await coachCard.textContent(),/после 2 новых матчей/);
    assert.equal(await coachCards.locator('img,script,iframe').count(),0);
    assert.equal(/Hermes|runtime_connected|snapshot_sha256|token|offline_bridge/.test(await page.locator('#hero-pool').innerText()),false,'Customers see coaching, without operational status or credentials.');
    if(screenshotDir) await page.locator('#pool-patterns').screenshot({path:path.join(screenshotDir,`portal-${width}-coach-patterns.png`)});
    await page.locator('#pool-hero').selectOption('npc_dota_hero_necrolyte');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===1);
    assert.equal(await coachCards.getByRole('heading',{name:'Решения в разных позициях',exact:true}).count(),0,'Filtering a hero hides conclusions that cite another hero.');
    await page.locator('#pool-hero').selectOption('npc_dota_hero_lion');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-roster .pool-hero-row').length===1&&document.querySelector('#pool-roster').textContent.includes('Lion'));
    assert.equal(await coachCards.count(),0,'One matching episode cannot retain a two-match recommendation.');
    await page.locator('#pool-hero').selectOption('');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===2);
    await page.locator('#pool-position').selectOption('2');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===1);
    assert.match(await coachCards.textContent(),/Necrophos · 2 · Мидер/);
    assert.doesNotMatch(await coachCards.textContent(),/Lion/);
    await page.locator('#pool-position').selectOption('5');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-matches .pool-match-row').length===1&&document.querySelector('#pool-matches').textContent.includes('Lion'));
    assert.equal(await coachCards.count(),0,'Position filters cannot turn mixed-context conclusions into same-role advice.');
    assert.equal(await page.locator('#pool-role-guidance').getAttribute('data-position'),'5');
    const supportFocus=page.locator('#pool-focus-pool-7');
    assert.equal(await supportFocus.locator('option[value="farm_checkpoint"]').count(),0,'Support is not offered a personal farm target as its main journal focus.');
    assert.equal(await supportFocus.locator('option[value="lane_support"]').count(),1);
    assert.equal(await supportFocus.locator('option[value="rotation_window"]').count(),1);

    await page.locator('#pool-position').selectOption('');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===2);
    await coachCard.locator('summary').click();
    await coachCard.getByRole('button',{name:'Матч 8984000001 · 12:00',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984000001',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#timeline-value').textContent==='12:00');
    assert.equal(await page.locator('#events [data-evidence-id="death-1"].selected-event').count(),1);
    assert.ok(requests.includes('/api/replays/pool-1'),'A coaching episode opens its own saved report.');
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984479726',exact:true}).waitFor();
    await page.locator('nav [data-tab="hero-pool"]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===2);
    await page.getByRole('button',{name:'Избранное: Necrophos, 2 · Мидер',exact:true}).click();
    await page.locator('#pool-status').filter({hasText:'добавлены в избранное'}).waitFor();
    await page.getByLabel('Только избранные герой и позиция',{exact:true}).check();
    await page.waitForFunction(()=>document.querySelectorAll('#pool-roster .pool-hero-row').length===1);
    assert.equal(await page.locator('#pool-trend-chart .pool-chart-line').count(),5);
    assert.match(await page.locator('#pool-trend-note').textContent(),/Первые 3: 9 → последние 3: 6/);
    await page.getByLabel('Показатель',{exact:true}).selectOption('item_delay_seconds');
    assert.equal(await page.locator('#pool-trend-chart .pool-chart-point').count(),5);
    assert.equal(await page.locator('#pool-trend-chart .pool-chart-line').count(),3);
    await page.getByLabel('Показатель',{exact:true}).selectOption('deaths_per_30');
    await page.getByRole('button',{name:'Взять в практику',exact:true}).click();
    await page.getByRole('heading',{name:'Практика после смерти',exact:true}).waitFor();
    assert.match(await page.locator('#pool-goals').textContent(),/Матч сыгран до начала практики/);
    assert.match(await page.locator('#pool-goals').textContent(),/Нет данных · 0 · дата игры неизвестна/);
    await page.getByRole('button',{name:'Пауза',exact:true}).click();
    await page.getByRole('button',{name:'Продолжить',exact:true}).waitFor();
    await page.getByRole('button',{name:'Продолжить',exact:true}).click();
    await page.getByRole('button',{name:'Пауза',exact:true}).waitFor();
    await page.getByRole('button',{name:'Избранное: Necrophos, 2 · Мидер',exact:true}).click();
    await page.getByRole('heading',{name:'Нет матчей с такими фильтрами',exact:true}).waitFor();
    await page.getByLabel('Только избранные герой и позиция',{exact:true}).uncheck();
    await page.getByLabel('Позиция в матче 8984000006',{exact:true}).waitFor();
    await page.getByLabel('Позиция в матче 8984000006',{exact:true}).selectOption('3');
    await page.locator('#pool-status').filter({hasText:'Позиция в матче 8984000006 сохранена.'}).waitFor();
    assert.equal(await page.getByLabel('Позиция в матче 8984000006',{exact:true}).inputValue(),'3');
    await page.getByText('Указать дату игры',{exact:true}).click();
    await page.getByLabel('Дата и время игры 8984000006',{exact:true}).fill('2020-01-02T15:30');
    await page.getByRole('button',{name:'Сохранить дату матча 8984000006',exact:true}).click();
    await page.locator('#pool-status').filter({hasText:'Дата матча 8984000006 сохранена.'}).waitFor();
    assert.match(poolMatches[6].played_at,/2020-01-02T/);
    assert.equal(poolMatches[6].date_source,'user');
    await page.locator('#pool-position').selectOption('3');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-matches .pool-match-row').length===1);
    assert.equal(await page.locator('#pool-summary .metric dd').nth(1).textContent(),'—');
    await page.locator('#pool-position').selectOption('');
    await page.getByLabel('Период',{exact:true}).selectOption('30');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-matches .pool-match-row').length===4);
    await page.getByLabel('Период',{exact:true}).selectOption('all');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-matches .pool-match-row').length===8);
    const journal=page.locator('.pool-match-row[data-match-id="8984000005"] .pool-journal');
    await journal.locator('summary').click();
    await journal.locator('.pool-focus').selectOption('safe_return');
    await journal.locator('.pool-reflection').selectOption('partial');
    await journal.locator('.pool-note').fill(malicious);
    poolSaveFailed=true;
    await journal.locator('.pool-save').click();
    await journal.locator('.pool-save-status').filter({hasText:'Не удалось сохранить дневник (проверка).'}).waitFor();
    assert.equal(await journal.locator('.pool-note').inputValue(),malicious);
    await page.getByRole('button',{name:'Обновить пул',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#pool-content').getAttribute('aria-busy')==='false');
    assert.equal(await journal.locator('.pool-note').inputValue(),malicious,'Refreshing cannot discard an unsaved reflection.');
    poolSaveFailed=false;
    await journal.locator('.pool-save').click();
    await journal.locator('.pool-save-status').filter({hasText:'Проверка сохранена в аккаунте.'}).waitFor();
    assert.deepEqual(poolWrites.at(-1),{focus:'safe_return',reflection:'partial',note:malicious});
    assert.equal(poolMatches[5].note,malicious);
    assert.equal(await journal.locator('.pool-reflection').inputValue(),'partial');
    assert.equal(await journal.locator('img,script,iframe').count(),0,'Reflection notes remain safe text.');
    for(const src of await page.locator('#hero-pool img').evaluateAll(images=>images.map(image=>image.getAttribute('src'))))assert.match(src,/^https:\/\/cdn\.cloudflare\.steamstatic\.com\/apps\/dota2\/images\/dota_react\/heroes\/(necrolyte|lion)\.png$/,'Only allowlisted Dota portraits appear in the hero pool.');
    assert.match(await page.locator('#pool-practice-summary').textContent(),/1 · частично/);
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-pool.png`),fullPage:true});
    const poolAccessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(poolAccessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    poolFailed=true; await page.getByRole('button',{name:'Обновить пул',exact:true}).click();
    await page.locator('#pool-status').filter({hasText:'Не удалось открыть пул героев'}).waitFor();
    assert.equal(await page.locator('#pool-content').isHidden(),true);
    poolFailed=false; await page.getByRole('button',{name:'Обновить пул',exact:true}).click();
    await page.locator('#pool-content').waitFor();
    await page.locator('nav [data-tab="review"]').click();
    page.once('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'Освободить место',exact:true}).click();
    await page.getByText('Исходный реплей удалён. Разбор и статистика сохранены.',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Освободить место',exact:true}).count(),0);
    assert.equal(await page.locator('#history .history-row').count(),1);
    // Learning remains available for existing saved reports, even after releasing .dem.
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    const learning=page.locator('#report-learning');
    await learning.getByLabel('Моя позиция в этом матче',{exact:true}).waitFor();
    assert.equal(await learning.locator('.learning-start').count(),0,'Unknown roles cannot start a hero/position plan.');
    await learning.getByLabel('Моя позиция в этом матче',{exact:true}).selectOption('2');
    await learning.getByRole('button',{name:'Начать практику · 3–5 игр',exact:true}).waitFor();
    assert.equal(await learning.locator('.learning-exercise').count(),1);
    assert.equal(await learning.locator('.role-guidance > p').first().textContent(),roleProfiles[2].lane_priority);
    await learning.getByRole('button',{name:'Начать практику · 3–5 игр',exact:true}).click();
    await learning.locator('.learning-check-form').waitFor();
    assert.match(await learning.locator('.learning-plan').textContent(),/Новых отмеченных матчей практики пока нет/);
    assert.match(await learning.locator('.learning-check-form').textContent(),/Это твоя оценка решения/);
    await learning.locator('.learning-check-form textarea').fill(malicious);
    await learning.getByLabel('Твоя оценка выполнения',{exact:true}).selectOption('no_opportunity');
    await learning.getByRole('button',{name:'Сохранить личную проверку',exact:true}).click();
    await learning.getByText('Личная проверка сохранена в аккаунте.',{exact:true}).waitFor();
    assert.deepEqual(learningWrites.at(-1),{job_id:job.id,evidence_id:null,answer:malicious,self_assessment:'no_opportunity'});
    await learning.locator('.learning-check-history > summary').click();
    assert.match(await learning.locator('.learning-check-history').textContent(),/Твоя оценка: Подходящей ситуации не было/);
    assert.match(await learning.locator('.learning-check-history').textContent(),/Исходный матч · точка отсчёта/);
    assert.equal(await learning.locator('img,script').count(),0,'Personal answers are rendered as text.');
    assert.equal(learningPlans[0].checks.length,1);
    // A full reload must restore both the selected focus and saved answer from API data.
    await page.reload();
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await learning.locator('.learning-check-form textarea').waitFor();
    await page.waitForFunction(value=>document.querySelector('#report-learning .learning-check-form textarea')?.value===value,malicious);
    assert.equal(await learning.getByLabel('Твоя оценка выполнения',{exact:true}).inputValue(),'no_opportunity');
    await learning.getByLabel('Моя позиция в этом матче',{exact:true}).selectOption('5');
    await page.waitForFunction(()=>document.querySelector('#learning-report-position')?.value==='5'&&!document.querySelector('#report-learning .learning-plan'));
    assert.equal(await learning.locator('.learning-exercise').count(),1,'A role change cannot retain the previous role’s active plan.');
    assert.equal(await learning.locator('.role-guidance > p').first().textContent(),roleProfiles[5].lane_priority,'Changing the saved match role replaces the role guidance.');
    assert.notEqual(roleProfiles[2].lane_priority,roleProfiles[5].lane_priority);
    await learning.getByLabel('Моя позиция в этом матче',{exact:true}).selectOption('2');
    await learning.locator('.learning-plan').waitFor();
    await page.locator('nav [data-tab="learning"]').click();
    assert.equal(new URL(page.url()).pathname,'/my-learning');
    await page.locator('#learning-hero').selectOption('npc_dota_hero_necrolyte');
    await page.locator('#learning-position').selectOption('2');
    const practice=page.locator('#learning #pool-learning');
    await practice.locator('.learning-plan').waitFor();
    assert.equal(await practice.locator('.learning-stages button').count(),6);
    assert.equal(await practice.locator('.learning-stages button[aria-pressed=true]').count(),1);
    const stage=practice.getByRole('button',{name:'4 · Задача предмета',exact:true});await stage.focus();await stage.press('Enter');
    assert.equal(await stage.getAttribute('aria-pressed'),'true');
    assert.equal(await practice.locator('.learning-exercise').count(),1,'Only the selected lesson is expanded.');
    assert.equal(await practice.locator('.learning-plan').count(),1,'One active focus is shown for this hero and position.');
    assert.equal(await practice.locator('.learning-check-form').isHidden(),true,'The pool keeps the personal-check form compact until requested.');
    const checkToggle=practice.getByText('Проверить матч по этому фокусу',{exact:true});await checkToggle.focus();await checkToggle.press('Enter');
    assert.equal(await practice.locator('.learning-check-form').isVisible(),true,'The personal check opens with the keyboard.');
    assert.match(await practice.locator('.learning-check-form').textContent(),/Это твоя оценка решения/);
    const draft='Несохранённое наблюдение перед сменой раздела';
    await practice.locator('.learning-check-form textarea').fill(draft);
    await page.locator('nav [data-tab="player"]').click();
    await page.goBack();
    await page.waitForFunction(()=>!document.querySelector('#learning-refresh').disabled);
    assert.equal(await practice.locator('.learning-check-form textarea').inputValue(),draft,'Back navigation cannot discard an unsaved personal check.');
    assert.equal(await practice.locator('.learning-check-form').isVisible(),true,'Back navigation keeps the opened check form.');
    learningFailed=true;
    await page.locator('nav [data-tab="player"]').click();
    await page.goBack();
    await page.locator('#learning-refresh-notice').waitFor();
    assert.equal(await practice.locator('.learning-check-form textarea').inputValue(),draft,'A failed background refresh cannot erase the current learning draft.');
    learningFailed=false;
    await checkToggle.focus();await checkToggle.press('Enter');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    if(screenshotDir)await practice.screenshot({path:path.join(screenshotDir,`portal-${width}-learning.png`)});
    await page.addScriptTag({content:axe.source});
    const learningAccessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(learningAccessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    // A duplicate upload must navigate to the canonical report before exposing practice.
    learningAlias=true;
    await page.locator('nav [data-tab="review"]').click();
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984000001',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#report-learning .learning-check-form select')?.value==='pool-1');
    assert.match(await learning.getByLabel('Эпизод из разбора',{exact:true}).textContent(),/12:00/);
    await learning.getByLabel('Эпизод из разбора',{exact:true}).selectOption('death-1');
    const canonicalEvent=page.locator('#events [data-evidence-id="death-1"]');
    assert.match(await canonicalEvent.textContent(),/12:00/,'Practice anchors and the visible replay share canonical timestamps.');
    assert.match(await page.locator('#notice').textContent(),/Открыт актуальный сохранённый разбор/);
    await page.locator('nav [data-tab="player"]').click();
    await page.getByRole('heading',{name:'Мой игрок',exact:true}).waitFor();
    assert.match(await page.locator('#player-summary').textContent(),/Steam ID: 123/);
    await page.locator('nav [data-tab="account"]').click();
    await page.getByRole('heading',{name:'Изменить пароль',exact:true}).waitFor();
    const integration=page.locator('#chatgpt-integration');
    await integration.getByRole('button',{name:'Подключить ChatGPT',exact:true}).waitFor();
    assert.equal(integrationRequests.length,1,'ChatGPT settings are fetched only after opening the account.');
    chatgptProviderRejected=true;await integration.getByRole('button',{name:'Подключить ChatGPT',exact:true}).click();await integration.getByText(/Проверь разрешение на вход по коду/).waitFor();
    assert.equal(await page.locator('#workspace').isVisible(),true,'An OpenAI authorization rejection must not log the user out of Narma.');assert.equal(await integration.innerText().then(text=>text.includes(malicious)),false);
    chatgptProviderRejected=false;
    await page.clock.install();
    const connect=integration.getByRole('button',{name:'Подключить ChatGPT',exact:true});await connect.focus();await connect.press('Enter');
    await integration.getByLabel('Код для входа в OpenAI',{exact:true}).waitFor();
    assert.equal(await integration.getByLabel('Код для входа в OpenAI',{exact:true}).inputValue(),'ABCD-12345');
    const openai=integration.getByRole('link',{name:'Открыть OpenAI',exact:true});
    assert.equal(await openai.getAttribute('href'),'https://auth.openai.com/codex/device');
    assert.equal(await openai.getAttribute('target'),'_blank');assert.equal(await openai.getAttribute('rel'),'noopener noreferrer');
    assert.equal(await integration.locator('img,script').count(),0);
    assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes('ABCD-12345')),false,'Login codes are not persisted in browser storage.');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    if(screenshotDir)await integration.screenshot({path:path.join(screenshotDir,`portal-${width}-chatgpt-login.png`)});
    const integrationAccessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(integrationAccessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    await page.locator('nav [data-tab="player"]').click();
    const pausedCount=integrationRequests.length;await page.clock.fastForward(15000);assert.equal(integrationRequests.length,pausedCount,'Leaving account stops OAuth polling.');
    await page.locator('nav [data-tab="account"]').click();await openai.waitFor();
    assert.equal(integrationRequests.filter(request=>request.endpoint.endsWith('/connect')).length,2,'Returning resumes the existing login without another connect request.');
    chatgptPollConnect=true;await page.clock.fastForward(5100);await integration.getByText('ChatGPT подключён',{exact:true}).waitFor();
    assert.match(await integration.innerText(),/Готовность тренерского разбора проверяется отдельно/);
    assert.equal(await integration.getByRole('link').count(),0);assert.equal(await integration.getByLabel('Код для входа в OpenAI').count(),0);
    const connectedCount=integrationRequests.length;await page.clock.fastForward(15000);assert.equal(integrationRequests.length,connectedCount,'Connected accounts no longer poll device auth.');
    const refreshIntegration=async()=>{await page.locator('nav [data-tab="player"]').click();await page.locator('nav [data-tab="account"]').click();await page.waitForFunction(()=>document.getElementById('chatgpt-integration').getAttribute('aria-busy')==='false');};
    chatgpt={...chatgpt,quota_paused:true,available:false,paused_until:null,last_error_code:'CHATGPT_QUOTA'};await refreshIntegration();await integration.getByText(/Время восстановления пока неизвестно/).waitFor();await integration.getByRole('button',{name:'Войти в ChatGPT заново',exact:true}).waitFor();
    chatgptDeleteFailed=true;const failedReconnectStart=integrationRequests.length;
    await integration.getByRole('button',{name:'Войти в ChatGPT заново',exact:true}).click();await integration.getByText('Не удалось проверить подключение. Попробуй ещё раз.',{exact:true}).waitFor();
    assert.deepEqual(integrationRequests.slice(failedReconnectStart).map(request=>[request.method,request.endpoint]),[['DELETE','/api/integrations/chatgpt']],'A failed disconnect must not start a new authorization.');
    chatgptDeleteFailed=false;await refreshIntegration();const reconnectStart=integrationRequests.length;
    await integration.getByRole('button',{name:'Войти в ChatGPT заново',exact:true}).click();await openai.waitFor();
    assert.deepEqual(integrationRequests.slice(reconnectStart).map(request=>[request.method,request.endpoint]),[['DELETE','/api/integrations/chatgpt'],['POST','/api/integrations/chatgpt/connect']],'Explicit reconnect must revoke the previous login before requesting a new code.');
    await page.clock.fastForward(5100);await integration.getByText('ChatGPT подключён',{exact:true}).waitFor();
    await integration.getByRole('button',{name:'Отключить ChatGPT',exact:true}).click();await connect.waitFor();
    chatgpt={...chatgpt,status:'reconnect_required',last_error_code:malicious};await refreshIntegration();
    await integration.getByRole('button',{name:'Войти в ChatGPT заново',exact:true}).waitFor();assert.equal(await integration.innerText().then(text=>text.includes(malicious)),false,'Provider error text is not rendered.');
    chatgpt={...pendingChatgpt(),pending:{...pendingChatgpt().pending,expires_at:new Date(Date.now()-1000).toISOString()}};await refreshIntegration();
    await integration.getByText('Время для входа истекло',{exact:true}).waitFor();assert.equal(await integration.getByRole('link').count(),0);
    const expiredCount=integrationRequests.length;await page.clock.fastForward(10000);assert.equal(integrationRequests.length,expiredCount,'Expired codes never poll or open a stale login URL.');
    for(const verification_url of ['javascript:alert(1)','https://auth.openai.com.evil.test/codex/device','https://auth.openai.com/codex/device?redirect=evil']){
      chatgpt={...pendingChatgpt(),pending:{...pendingChatgpt().pending,verification_url}};await refreshIntegration();assert.equal(await integration.getByRole('link').count(),0);assert.equal(await integration.locator('img,script').count(),0);
    }
    chatgpt={...pendingChatgpt(),pending:{...pendingChatgpt().pending,user_code:malicious}};await refreshIntegration();assert.equal(await integration.getByLabel('Код для входа в OpenAI').count(),0);assert.equal(await integration.locator('img,script').count(),0);
    chatgpt={...chatgpt,status:'unavailable',configured:false,can_connect:false,pending:null};await refreshIntegration();
    assert.equal(await integration.getByRole('button',{name:'Подключить ChatGPT',exact:true}).count(),0);await integration.getByRole('button',{name:'Проверить снова',exact:true}).waitFor();
    chatgptRejectSession=true;await integration.getByRole('button',{name:'Проверить снова',exact:true}).click();await page.getByRole('heading',{name:'Вход в NARMA VISION',exact:true}).waitFor();
    assert.equal(await page.locator('#workspace').isHidden(),true);assert.equal(await page.locator('#chatgpt-content').innerText(),'');
    const unauthorizedCount=integrationRequests.length;await page.clock.fastForward(15000);assert.equal(integrationRequests.length,unauthorizedCount,'Expired Narma sessions stop all OAuth polling.');
    chatgptRejectSession=false;chatgptPollConnect=false;chatgpt={...chatgpt,status:'disconnected',configured:true,can_connect:true,pending:null,last_error_code:null};
    await page.getByLabel('Email',{exact:true}).fill('fixture@example.test');await page.getByLabel('Пароль',{exact:true}).fill('Synthetic passphrase 2026');await page.getByRole('button',{name:'Войти',exact:true}).click();
    await connect.waitFor();await connect.click();await openai.waitFor();
    await page.getByRole('button',{name:'Выйти',exact:true}).click();await page.getByRole('heading',{name:'Вход в NARMA VISION',exact:true}).waitFor();
    const loggedOutCount=integrationRequests.length;await page.clock.fastForward(15000);assert.equal(integrationRequests.length,loggedOutCount,'Logging out stops pending device auth and clears the login code.');
    assert.equal(requests.some(url=>url.startsWith('/api/videos')),false);
    assert.equal(requests.some(url=>url.startsWith('/api/hermes')),false,'The customer portal never requests internal Hermes status or export controls.');
    assert.deepEqual(externalRequests,[],'Synthetic UI fixtures must never contact external providers.');
    assert.deepEqual(errors,[]); await page.close();
  }
  // Account controls use synthetic API responses; credential transaction rules
  // are covered separately by the PostgreSQL suite.
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],commands=[];
    let authenticated=false,owner=true,remaining=0,invites=[],releaseCodes=null,delayCodes=false,releaseInvite=null,delayInvite=false,observeCredential=null;
    const code='01234567-89abcdef-01234567-89abcdef',inviteToken='A'.repeat(43),inviteId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',async route=>{if(await programFixture(route))return;
      const request=route.request(),endpoint=new URL(request.url()).pathname,method=request.method();
      if(method!=='GET')commands.push({endpoint,body:request.postDataJSON()});
      let body;
      if(endpoint==='/api/session')body={authenticated,setup_required:false,user:authenticated?{email:owner?'owner@example.test':'guest@example.test',is_platform_owner:owner}:null,coaching:{mode:'platform',available:true,personal_connect:false}};
      else if(endpoint==='/api/auth/login'){authenticated=true;body={authenticated:true};}
      else if(endpoint==='/api/auth/logout'){authenticated=false;body={authenticated:false};}
      else if(endpoint==='/api/profile')body={profile:null};
      else if(endpoint==='/api/replays')body={replays:[],worker_ready:true};
      else if(endpoint==='/api/auth/security')body={recovery_codes_remaining:remaining};
      else if(endpoint==='/api/auth/recovery-codes'){remaining=5;if(delayCodes)await new Promise(resolve=>{releaseCodes=resolve;observeCredential();});body={codes:Array(5).fill(code)};}
      else if(endpoint==='/api/auth/invitations'&&method==='GET')body={invitations:invites,maximum_accounts:25};
      else if(endpoint==='/api/auth/invitations'&&method==='POST'){invites=[{id:inviteId,email:'guest@example.test',expires_at:'2099-01-01T00:00:00Z'}];body={invitation:invites[0],token:inviteToken};if(delayInvite)await new Promise(resolve=>{releaseInvite=resolve;observeCredential();});}
      else if(endpoint.startsWith('/api/auth/invitations/')&&method==='DELETE'){invites=[];body={revoked:true};}
      else if(endpoint==='/api/auth/accept-invitation'){authenticated=true;owner=false;body={authenticated:true};}
      else if(endpoint==='/api/auth/recover'){remaining--;authenticated=false;body={authenticated:false,password_changed:true};}
      else if(endpoint==='/api/owner/dashboard')body={jobs:[{kind:'replay',ready:2,failed:0,queued:1,processing:0,mean_completion_seconds:120}],costs:[{kind:'chat',calls:2,spent_microusd:12000,held_microusd:3000}],users:[{owner_id:'synthetic-guest',email:'guest@example.test',spent_microusd:12000,held_microusd:3000,unknown_calls:0,limit_microusd:null}],feedback:[],openai_budget:null,window_note:'Задания за 7 дней',cost_note:'Учёт приложения'};
      else if(endpoint==='/api/owner/users/synthetic-guest/ai-limit'&&method==='PUT')body={saved:true};
      else throw Error(`Unexpected account request ${method} ${endpoint}`);
      await route.fulfill({json:body});
    });
    await page.goto(origin+'/account');
    await page.locator('#email').fill('owner@example.test');await page.locator('#password').fill('Synthetic passphrase 2026');await page.locator('#auth-submit').click();
    await page.locator('#pilot-invitations').waitFor();
    await page.locator('#owner-nav').click();
    const dashboard=page.locator('#owner-content');
    await dashboard.getByRole('heading',{name:'Расходы на ИИ',exact:true}).waitFor();
    await dashboard.getByLabel('Общий лимит игрока, $',{exact:true}).fill('2,50');
    await dashboard.getByLabel('Твой пароль для изменения лимита',{exact:true}).fill('Synthetic passphrase 2026');
    await dashboard.getByRole('button',{name:'Сохранить лимит',exact:true}).click();
    await dashboard.getByText('Лимит сохранён. Общий бюджет платформы не изменился.',{exact:true}).waitFor();
    assert.deepEqual(commands.find(command=>command.endpoint==='/api/owner/users/synthetic-guest/ai-limit').body,{limit_microusd:2500000,current_password:'Synthetic passphrase 2026'});
    assert.equal(await dashboard.getByLabel('Твой пароль для изменения лимита',{exact:true}).inputValue(),'');
    await dashboard.getByLabel('Твой пароль для изменения лимита',{exact:true}).fill('Unsaved synthetic credential');
    await page.locator('nav [data-tab=account]').click();
    assert.equal(await dashboard.getByLabel('Твой пароль для изменения лимита',{exact:true}).inputValue(),'');
    await page.locator('#recovery-current-password').fill('Synthetic passphrase 2026');await page.locator('#recovery-generate-form button').click();await page.locator('#recovery-output').waitFor();
    assert.equal(await page.locator('#recovery-code-list').inputValue(),Array(5).fill(code).join('\n'));
    assert.equal(await page.locator('#recovery-current-password').inputValue(),'');
    await page.locator('#recovery-saved').click();assert.equal(await page.locator('#recovery-code-list').inputValue(),'');
    await page.locator('#invitation-email').fill('guest@example.test');await page.locator('#invitation-password').fill('Synthetic passphrase 2026');await page.locator('#invitation-form button').click();await page.locator('#invitation-output').waitFor();
    const link=await page.locator('#invitation-link').inputValue(),url=new URL(link);
    assert.equal(url.search,'');assert.equal(new URLSearchParams(url.hash.slice(1)).get('invite'),inviteToken);
    assert.equal(await page.locator('#invitation-password').inputValue(),'');
    await page.locator('#invitation-list button').click();await page.locator('#invitation-status').getByText('Введи текущий пароль для отзыва.').waitFor();
    await page.locator('#invitation-password').fill('Synthetic passphrase 2026');await page.locator('#invitation-list button').click();await page.waitForFunction(()=>document.querySelector('#invitation-list').children.length===0);
    assert.equal(await page.locator('#invitation-link').inputValue(),'');
    // A delayed response must not put backup credentials back into the DOM
    // after a user has left the account screen.
    const codeStarted=new Promise(resolve=>{observeCredential=resolve;});delayCodes=true;await page.locator('#recovery-current-password').fill('Synthetic passphrase 2026');await page.locator('#recovery-generate-form button').click();
    await codeStarted;await page.locator('nav [data-tab=review]').click();
    const codeFinished=page.waitForResponse(response=>response.url().endsWith('/api/auth/recovery-codes'));releaseCodes();await codeFinished;
    await page.waitForFunction(()=>!document.querySelector('#recovery-generate-form button').disabled);
    assert.equal(await page.locator('#recovery-code-list').inputValue(),'');assert.equal(await page.locator('#recovery-output').isHidden(),true);
    delayCodes=false;await page.locator('nav [data-tab=account]').click();await page.locator('#pilot-invitations').waitFor();
    const inviteStarted=new Promise(resolve=>{observeCredential=resolve;});delayInvite=true;
    await page.locator('#invitation-password').fill('Synthetic passphrase 2026');await page.locator('#invitation-form button').click();await inviteStarted;
    await page.locator('#logout').click();await page.locator('#auth').waitFor();
    const inviteFinished=page.waitForResponse(response=>response.url().endsWith('/api/auth/invitations'));releaseInvite();await inviteFinished;
    await page.waitForFunction(()=>!document.querySelector('#invitation-form button').disabled);
    assert.equal(await page.locator('#invitation-link').inputValue(),'');assert.equal(await page.locator('#invitation-output').isHidden(),true);
    await page.locator('#forgot-password').click();await page.locator('#recovery-email').fill('owner@example.test');await page.locator('#recovery-code').fill(code);await page.locator('#recovery-password').fill('Synthetic changed password');await page.locator('#recovery-form .primary').click();
    await page.locator('#notice').getByText(/Пароль восстановлен/).waitFor();assert.equal(await page.locator('#recovery-code').inputValue(),'');assert.equal(await page.locator('#recovery-password').inputValue(),'');
    await page.goto(link);await page.locator('#auth-title').getByText('Прими приглашение').waitFor();
    assert.equal(new URL(page.url()).hash,'');assert.equal(await page.locator('#email').inputValue(),'guest@example.test');
    await page.locator('#password').fill('Synthetic passphrase 2026');await page.locator('#auth-submit').click();await page.locator('#workspace').waitFor();
    assert.equal(await page.locator('#pilot-invitations').isHidden(),true);
    assert.equal(await page.locator('#owner-nav').isHidden(),true);
    assert.equal(await page.locator('#owner-content').innerText(),'');
    assert.deepEqual(commands.find(command=>command.endpoint==='/api/auth/accept-invitation').body,{email:'guest@example.test',password:'Synthetic passphrase 2026',token:inviteToken});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);await page.close();
  }

  // Public registration: isolated synthetic accounts, no live signup or AI calls.
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],writes=[];
    const fixtures=personalCoachFixtures();
    let authenticated=false,available=true,signupError=true,releaseSignup,signupStarted;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      if(new URL(route.request().url()).origin!==origin)await route.abort();else await route.fallback();
    });
    await page.route('**/api/**',async route=>{if(await programFixture(route))return;
      const request=route.request(),endpoint=new URL(request.url()).pathname;
      let body,status=200;
      if(request.method()!=='GET')writes.push({endpoint,body:request.postDataJSON()});
      if(endpoint==='/api/session')body={authenticated,setup_required:false,registration_available:available,user:authenticated?{email:'new@example.test',is_platform_owner:false}:null,coaching:{mode:'platform',available:false,personal_connect:false}};
      else if(endpoint==='/api/auth/register') {
        if(signupError){status=409;body={detail:'Аккаунт с этой почтой уже существует. Войдите или восстановите доступ.'};}
        else {await new Promise(resolve=>{releaseSignup=resolve;signupStarted();});authenticated=true;status=201;body={authenticated:true};}
      }
      else if(endpoint==='/api/auth/logout'){authenticated=false;body={authenticated:false};}
      else if(endpoint==='/api/auth/login'){authenticated=true;body={authenticated:true};}
      else if(endpoint==='/api/profile')body={profile:null};
      else if(endpoint==='/api/replays')body={replays:[],worker_ready:true};
      else if(endpoint==='/api/hero-pool')body=fixtures.pool(true);
      else if(endpoint==='/api/learning/progress') body={plans:[]};
      else if(endpoint==='/api/learning')body=fixtures.learning(true);
      else throw Error(`Unexpected registration request ${endpoint}`);
      await route.fulfill({status,json:body});
    });
    await page.goto(origin+'/login');
    await page.locator('#auth-switch').getByText('Нет аккаунта? Создать аккаунт').waitFor();
    await page.locator('#auth-switch').click();
    assert.equal(new URL(page.url()).pathname,'/register');
    await page.locator('#auth-title').getByText('Создай аккаунт NARMA VISION').waitFor();
    assert.equal(await page.locator('#password').getAttribute('autocomplete'),'new-password');
    assert.equal(await page.locator('#password-confirmation').isEnabled(),true);
    assert.equal(await page.locator('#forgot-password').isHidden(),true);
    await page.locator('#email').fill('new@example.test');
    await page.locator('#password').fill('Synthetic passphrase 2026');
    await page.locator('#password-confirmation').fill('Synthetic different passphrase');
    await page.locator('#auth-submit').click();
    await page.locator('#notice').getByText('Пароли не совпадают. Проверь повторный ввод.').waitFor();
    assert.equal(writes.length,0);
    await page.locator('#password-confirmation').fill('Synthetic passphrase 2026');
    await page.locator('#auth-submit').click();
    await page.locator('#notice').getByText(/Аккаунт с этой почтой уже существует/).waitFor();
    await page.waitForFunction(()=>!document.querySelector('#auth-submit').disabled);
    assert.deepEqual(writes[0],{endpoint:'/api/auth/register',body:{email:'new@example.test',password:'Synthetic passphrase 2026',password_confirmation:'Synthetic passphrase 2026'}});
    assert.equal(await page.locator('#workspace').isHidden(),true);
    // Browser Back switches to login without leaving a required hidden field.
    await page.goBack();
    assert.equal(new URL(page.url()).pathname,'/login');
    await page.locator('#auth-title').getByText('Вход в NARMA VISION',{exact:true}).waitFor();
    assert.equal(await page.locator('#password-confirmation').isEnabled(),false);
    await page.locator('#forgot-password').click();assert.equal(await page.locator('#auth-switch').isHidden(),true);
    await page.locator('#return-login').click();await page.locator('#auth-switch').waitFor();
    await page.goto(origin+'/register');await page.locator('#auth-submit').waitFor();
    await page.locator('#email').fill('new@example.test');
    await page.locator('#password').fill('Synthetic passphrase 2026');await page.locator('#password-confirmation').fill('Synthetic passphrase 2026');
    signupError=false;const started=new Promise(resolve=>{signupStarted=resolve;});
    await page.locator('#auth-submit').click();await started;
    assert.equal(await page.locator('#auth-submit').isDisabled(),true);
    assert.equal(await page.locator('#auth-switch').isDisabled(),true);
    assert.equal(writes.filter(write=>write.endpoint==='/api/auth/register').length,2);
    releaseSignup();await page.locator('#workspace').waitFor();await page.locator('#training').waitFor();
    assert.equal(new URL(page.url()).pathname,'/training');
    await page.locator('#program-content').getByText('Начнём с твоего матча').waitFor();
    await page.locator('#program-content').getByRole('button',{name:'Разобрать свой матч',exact:true}).click();
    await page.locator('#review').waitFor();
    await page.locator('nav [data-tab=training]').click();await page.locator('#training').waitFor();
    await page.locator('#notice').getByText(/Аккаунт создан/).waitFor();
    assert.equal(await page.locator('#password').inputValue(),'');assert.equal(await page.locator('#password-confirmation').inputValue(),'');
    assert.equal(await page.locator('#pilot-invitations').isHidden(),true);
    await page.locator('#logout').click();await page.locator('#auth').waitFor();
    await page.locator('#password').fill('Synthetic passphrase 2026');await page.locator('#auth-submit').click();await page.locator('#workspace').waitFor();
    assert.deepEqual(writes.find(write=>write.endpoint==='/api/auth/login').body,{email:'new@example.test',password:'Synthetic passphrase 2026'});
    await page.locator('#logout').click();available=false;
    await page.goto(origin+'/register');await page.locator('#registration-unavailable').waitFor();
    assert.equal(await page.locator('#auth-submit').isDisabled(),true);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert.ok(writes.every(write=>['/api/auth/register','/api/auth/login','/api/auth/logout'].includes(write.endpoint)));
    assert.deepEqual(errors,[]);await page.close();
  }

  // Personal coaching is a read-only projection of the owner's saved reports.
  // This independent fixture keeps provider/account/upload mutation scenarios above unchanged.
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}}),fixture=personalCoachFixtures(),errors=[],commands=[],externalRequests=[];
    let authenticated=true,empty=true,unavailable=false,reportChanged=false,delayedReport=null,releaseReport=null,observeReport=null;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      const url=route.request().url();
      if(url===heroImageUrl||url===itemImageUrl||url===blinkImageUrl)await route.fulfill({contentType:'image/png',body:itemImage});
      else if(new URL(url).origin!==origin){externalRequests.push(url);await route.abort();}
      else await route.fallback();
    });
    await page.route('**/api/**',async route=>{if(await programFixture(route))return;
      const request=route.request(),endpoint=new URL(request.url()).pathname,method=request.method();commands.push({method,endpoint});
      let body;
      if(endpoint==='/api/session')body={authenticated,setup_required:false,user:authenticated?{email:'coach-owner@example.test',is_platform_owner:true}:null,coaching:{mode:'platform',available:true,personal_connect:false}};
      else if(endpoint==='/api/auth/logout'){assert.equal(method,'POST');authenticated=false;body={authenticated:false};}
      else {
        assert.equal(method,'GET','Opening or switching saved coach reports must never create provider, upload or practice mutations.');
        if(endpoint==='/api/profile')body={profile:empty?null:profile};
        else if(endpoint==='/api/replays')body={replays:empty?[]:fixture.history.map(match=>fixture.detail(match.job_id).replay),worker_ready:true,max_bytes:512*1024**2};
        else if(endpoint==='/api/hero-pool')body=fixture.pool(empty);
        else if(endpoint==='/api/learning/progress') body={plans:[]};
      else if(endpoint==='/api/learning')body=fixture.learning(empty);
        else if(endpoint.startsWith('/api/learning/reports/'))body=fixture.learning(empty,endpoint.split('/').at(-1));
        else if(endpoint.endsWith('/chat')){const id=endpoint.split('/').at(-2);body={turns:[],report_sha256:fixture.detail(id).report_sha256,context:{},available:false};}
        else if(endpoint.startsWith('/api/replays/')){
          const id=endpoint.split('/').at(-1);body=fixture.detail(id,{unavailable});
          if(reportChanged&&id==='coach-new'){body.report_sha256='d'.repeat(64);body.report.evidence[0].time=1260;}
          if(id===delayedReport){await new Promise(resolve=>{releaseReport=resolve;observeReport();});delayedReport=null;}
        }
        else throw Error(`Unexpected personal coach request ${method} ${endpoint}`);
      }
      await route.fulfill({json:body});
    });
    await page.goto(origin+'/coach');
    await page.locator('#coach-empty').waitFor();
    assert.equal(await page.locator('nav [data-tab]').first().getAttribute('data-tab'),'coach','The personal coach is the first customer tab.');
    assert.equal(await page.locator('nav [data-tab=coach]').getAttribute('aria-current'),'page');
    assert.match(await page.locator('#coach-empty').textContent(),/Загрузи полный \.dem/);
    assert.equal(await page.locator('#coach-decisions,#coach-match-select').count(),0,'An empty account never receives invented match findings.');
    assert.equal(commands.some(command=>/^\/api\/replays\//.test(command.endpoint)),false);
    await page.locator('#coach-empty').getByRole('button',{name:'Загрузить первый реплей',exact:true}).click();
    assert.equal(new URL(page.url()).pathname,'/replays');
    await page.locator('nav [data-tab=coach]').click();
    empty=false;
    await page.locator('#coach-refresh').click();
    await page.locator('#coach-decisions .decision-details').waitFor();
    assert.equal(await page.locator('#coach-match-select').inputValue(),'coach-new');
    assert.equal(await page.locator('#coach-match-detail .mode-step').count(),3);
    await page.locator('#coach-match-detail').getByRole('heading',{name:'Цена альтернативы',exact:true}).waitFor();
    assert.equal(await page.locator('#coach-matches .coach-match-row').count(),2);
    assert.match(await page.locator('#coach-match-detail').textContent(),/Матч 8984100002/);
    assert.match(await page.locator('#coach-next-game').textContent(),/До выхода назови цель и безопасный путь/);
    assert.match(await page.locator('#coach-next-game').textContent(),/После игры проверь три таких решения/);
    assert.match(await page.locator('#coach-practice').textContent(),/Проверка перед возвращением/);
    assert.match(await page.locator('#coach-practice').textContent(),/Подходящих матчей с твоей проверкой: 1/);
    assert.match(await page.locator('#coach-practice').textContent(),/самооценка/);
    const decision=page.locator('#coach-decisions .decision-details');
    await decision.locator('summary').focus();await decision.locator('summary').press('Enter');
    assert.equal(await decision.getAttribute('open'),'','Structured decisions expand using the keyboard.');
    for(const label of ['Факты эпизода','Почему это имеет значение','Другой вариант действия','Когда применять','Когда выбрать другое'])assert.equal(await decision.getByText(label,{exact:true}).isVisible(),true);
    for(const key of ['observation','decision_question','reasoning','alternative','when_to_apply','when_not_to_apply'])assert.equal(await decision.getByText(fixture.structuredPoint[key],{exact:true}).isVisible(),true);
    assert.equal(await page.locator('#coach-decisions img, #coach-decisions script, #coach-decisions iframe').count(),0,'Model prose remains literal text.');
    const axe=dependency('axe-core');await page.addScriptTag({content:axe.source});
    const coachAccessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(coachAccessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'The personal coach fits both mobile and desktop widths.');
    if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`portal-${width}-personal-coach.png`),fullPage:true});
    reportChanged=true;
    await decision.getByRole('button',{name:'12:00 · Смерть',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984100002',exact:true}).waitFor();
    await page.locator('#notice').getByText(/Этот разбор обновился/).waitFor();
    assert.equal(await page.locator('#events .selected-event').count(),0,'A reprocessed report cannot reuse an old evidence ID as proof of the same episode.');
    assert.notEqual(await page.locator('#timeline-value').textContent(),'12:00','Changing the report hash prevents seeking to its old timestamp.');
    assert.match(await page.locator('#events [data-evidence-id=coach-new-death]').textContent(),/21:00/);
    reportChanged=false;
    await page.locator('nav [data-tab=coach]').click();
    await page.locator('#coach-decisions .decision-details').waitFor();
    await decision.locator('summary').click();
    await decision.getByRole('button',{name:'12:00 · Смерть',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984100002',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#timeline-value').textContent==='12:00');
    assert.equal(new URL(page.url()).pathname,'/replays');
    assert.equal(await page.locator('#events [data-evidence-id=coach-new-death].selected-event').count(),1,'An episode opens and seeks its own saved report.');
    assert.equal(await page.locator('#coaching .decision-details').count(),1,'The full report renders the same versioned decision contract.');
    await page.locator('#coaching .decision-details > summary').click();
    assert.equal(await page.locator('#coaching').getByText(fixture.structuredPoint.alternative,{exact:true}).isVisible(),true);
    await page.locator('nav [data-tab=coach]').click();
    await page.locator('#coach-decisions .decision-details').waitFor();
    await page.locator('#coach-match-select').selectOption('coach-old');
    await page.locator('#coach-decisions').getByRole('heading',{name:'Старое наблюдение',exact:true}).waitFor();
    assert.match(await page.locator('#coach-match-detail').textContent(),/Сохранённый разбор в прежнем формате/);
    assert.match(await page.locator('#coach-decisions').textContent(),/Проверь положение перед возвращением/);
    assert.equal(await page.locator('#coach-decisions .decision-field').count(),0,'Legacy advice is not expanded into invented structured fields.');
    assert.equal(await page.locator('#coach-next-game').count(),0,'Selecting an older report clears the other match\'s next-game focus.');
    await page.locator('#coach-practice').getByRole('button',{name:'Продолжить практику',exact:true}).click();
    assert.equal(new URL(page.url()).pathname,'/my-learning');
    await page.locator('#learning .learning-stages').waitFor();
    await page.locator('nav [data-tab=coach]').click();
    await page.locator('#coach-decisions').getByRole('heading',{name:'Старое наблюдение',exact:true}).waitFor();
    unavailable=true;
    await page.locator('#coach-match-select').selectOption('coach-new');
    await page.locator('#coach-match-detail .coach-unavailable').waitFor();
    assert.match(await page.locator('#coach-match-detail').textContent(),/нет готового комментария ИИ/);
    assert.equal(await page.locator('#coach-decisions,#coach-next-game,.coach-summary').count(),0,'An unavailable verdict hides stale model text and goals contained in a saved response.');
    assert.doesNotMatch(await page.locator('#coach-match-detail').textContent(),/Начни с решения о возвращении/);
    assert.match(await page.locator('#coach-practice').textContent(),/Проверка перед возвращением/,'A separately saved practice stays available without a new AI comment.');
    assert.ok(commands.every(command=>command.method==='GET'),'Viewing the coach, old reports, episodes and saved practice creates no mutations.');
    // A response that was authorized before logout must not restore private findings afterwards.
    unavailable=false;delayedReport='coach-old';
    const reportStarted=new Promise(resolve=>{observeReport=resolve;});
    await page.locator('#coach-match-select').selectOption('coach-old');await reportStarted;
    await page.locator('#logout').click();await page.locator('#auth').waitFor();
    const reportFinished=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/replays/coach-old');
    releaseReport();await (await reportFinished).finished();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.locator('#coach-content').innerText(),'');
    assert.equal(await page.locator('#coach-content').isHidden(),true);
    assert.equal(await page.locator('#coach-player').textContent(),'Личный разбор','Logout also clears the selected player name.');
    assert.equal(await page.locator('#coach-decisions,#coach-match-detail').count(),0,'Late selected-report responses cannot repopulate a logged-out session.');
    assert.deepEqual(commands.filter(command=>command.method!=='GET'),[{method:'POST',endpoint:'/api/auth/logout'}]);
    assert.deepEqual(externalRequests,[],'The personal coach fixture never contacts a provider or other external service.');
    assert.deepEqual(errors,[]);await page.close();
  }

  console.log('Personal coach empty/history/structured and legacy reports, episode navigation, saved practice and logout race; visual report income sources, item timings/delivery/realization, personal goals/reset and next-game plan; Portal .dem upload→report with role/MMR/training depth, frozen context and idempotent retry; selected-player binding, shared timeline, safe coaching links, account navigation, reduced motion, mobile layout and WCAG passed (mocked API; no paid calls).');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
