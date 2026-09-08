import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';

const require=createRequire(import.meta.url);
function dependency(name) {
  try { return require(name); }
  catch { const runtime=process.env.PLAYWRIGHT_NODE_MODULES||process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES; if(!runtime) throw Error(`Install ${name} to run the portal check.`); return require(path.join(runtime,name)); }
}
const {chromium}=dependency('playwright');
const root=path.resolve(process.env.NARMA_PORTAL_TEST_ROOT||'services/video/narma_video/static');
const files={'/':['index.html','text/html'],'/assets/portal.js':['portal.js','text/javascript'],'/assets/portal.css':['portal.css','text/css']};
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
try {
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}});
    let authenticated=false, bound=false, job=null, uploaded=false, legacy=false, poolFailed=false, poolSaveFailed=false;
    const poolMatches=Array.from({length:8},(_,index)=>({job_id:'pool-'+index,match_id:String(8984000000+index),hero:index===7?'npc_dota_hero_lion':'npc_dota_hero_necrolyte',label:index===7?'Lion':'Necrophos',position:index===7?5:index===6?null:2,outcome:index===6?null:index%2?'loss':'win',played_at:index===6?null:new Date(Date.now()-(50-index*7)*86400000).toISOString(),date_source:index===6?'analysis':'user',chronology_at:new Date(Date.now()-(50-index*7)*86400000).toISOString(),metrics:{deaths_per_30:10-index,gpm:400+index*20,xpm:500+index*20,last_hits_10:30+index,net_worth_10:4000+index*100,item_delay_seconds:index===3?null:120-index*10}}));
    const favorites=new Set(), goals=[], poolWrites=[], externalRequests=[];
    let learningPosition=null, learningAlias=false;
    const learningPlans=[], learningWrites=[];
    const learningStages=[['lane','Линия и ресурсы'],['map','Две следующие задачи'],['risk','Риск и возвращение в игру'],['items','Задача предмета'],['fights','Своя работа в бою'],['decisions','Самостоятельный разбор']].map(([id,title],index)=>({id,title,order:index+1,description:'Один навык — одна проверка.',exercise_ids:[]}));
    const learningExercises=learningStages.map((stage,index)=>({id:stage.id==='risk'?'r1':`fixture-${stage.id}`,stage_id:stage.id,title:stage.id==='risk'?'Проверить риск перед выходом':stage.title,roles:stage.id==='lane'?[1,2,3]:[],decision_question:'Чего я хотел добиться и что знал до решения?',signal:'Перед переходом на следующую задачу.',action:'Назови цель и условие отмены действия.',why:'Так можно заранее заметить опасность.',exception:'Срочная помощь может изменить план.',drill:'Выбери три похожих эпизода.',measurement:'Объясни выбор по информации до действия.',focus_window_matches:3,mini_lesson:'Это учебный пример, не факт о твоём матче.',source_refs:[],review_mode:stage.id==='risk'?'episode_review':'manual_context',evidence_types:stage.id==='risk'?['death']:[]}));
    const learningCatalog=position=>({schema_version:'narma.curriculum.v1',version:'narma.curriculum.v1',stages:learningStages,exercises:learningExercises.filter(exercise=>!exercise.roles.length||exercise.roles.includes(position)),position,position_required:!position,sources:[]});
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
      return {summary:summarize(selected),heroes:[...groups].map(([key,rows])=>({hero:rows[0].hero,label:rows[0].label,position:rows[0].position,favorite:favorites.has(key),...summarize(rows)})),available_heroes:[{hero:'npc_dota_hero_necrolyte',label:'Necrophos'},{hero:'npc_dota_hero_lion',label:'Lion'}],history:selected,trends:sameRole.length===6?[{hero:'npc_dota_hero_necrolyte',position:2,metric:'deaths_per_30',status:'ready',early_n:3,recent_n:3,early_mean:9,recent_mean:6,delta:-3,unit:'смертей'}]:[],patterns:sameRole.length>=3?[{id:'repeat-death',hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2,title:malicious,observation:'Повторная смерть в двух матчах.',action:'Перед возвращением на линию проверь доступные предметы.',occurrences:2,eligible_matches:sameRole.length,evidence:[{job_id:'pool-0',match_id:'8984000000'}]}]:[],coaching:coaching.patterns.length?coaching:null,goals,limitations:['Синтетическая тестовая выборка. Дата разбора не является датой игры.']};
    }
    const errors=[], requests=[];
    const integrationRequests=[];
    let chatgpt={provider:'openai-codex',scope:'personal',configured:true,can_connect:true,status:'disconnected',auth_generation:null,connected_at:null,pending:null,last_error_code:null},chatgptPollConnect=false,chatgptRejectSession=false,chatgptDeleteFailed=false,chatgptProviderRejected=false;
    const pendingChatgpt=()=>({...chatgpt,status:'pending',auth_generation:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',pending:{user_code:'ABCD-12345',verification_url:'https://auth.openai.com/codex/device',expires_at:new Date(Date.now()+600000).toISOString(),poll_interval_seconds:5,poll_after_seconds:5}});
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      const url=route.request().url();
      if(url===itemImageUrl||url===blinkImageUrl||url===heroImageUrl) { if(width===1440) await route.fulfill({contentType:'image/png',body:itemImage}); else await route.abort(); }
      else if(new URL(url).origin!==origin) {externalRequests.push(url);await route.abort();}
      else await route.fallback();
    });
    await page.route('**/api/**',async route=>{
      const request=route.request(), url=new URL(request.url()), endpoint=url.pathname, method=request.method(); requests.push(endpoint);
      let body, status=200, responseHeaders={};
      if(endpoint==='/api/auth/login') { authenticated=true; body={authenticated:true}; }
      else if(endpoint==='/api/auth/logout') {authenticated=false;body={authenticated:false};}
      else if(endpoint==='/api/session') body={authenticated,setup_required:false,user:authenticated?{email:'fixture@example.test'}:null};
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
      else if(endpoint==='/api/learning') {const hero=url.searchParams.get('hero'),position=Number(url.searchParams.get('position'))||null;body={schema_version:'narma.learning.v1',catalog:learningCatalog(position),profile,scope:{hero,position},plans:learningPlans.filter(plan=>(!hero||plan.hero===hero)&&(!position||plan.position===position)).map(projectPlan),history:[...poolMatches,...(job?[learningMatch(job.id)]:[])].filter(match=>(!hero||match.hero===hero)&&(!position||match.position===position))};}
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
      else if(endpoint==='/api/replays'&&method==='POST') {
        const command=request.postDataJSON(); assert.equal(command.filename,'synthetic.dem'); assert.equal(command.nickname,'SyntheticPlayer'); assert.equal('account_id' in command,false);
        job={...command,state:'uploading',progress:0,match_id:null,created_at:new Date().toISOString()}; status=201; body={replay:job,part_bytes:5*1024**2};
      }
      else if(endpoint==='/api/replays') body={replays:job?[job]:[],worker_ready:true,max_bytes:512*1024**2};
      else if(job&&endpoint===`/api/replays/${job.id}/parts/1`&&method==='PUT') { uploaded=true; assert.equal(request.postDataBuffer().subarray(0,8).toString('binary'),'PBDEMS2\x00'); body={uploaded:true,part_number:1}; }
      else if(job&&endpoint===`/api/replays/${job.id}/complete`) { assert.equal(uploaded,true); bound=true; job={...job,state:'ready',progress:100,match_id:'8984479726'}; body={replay:job}; }
      else if(job&&endpoint===`/api/replays/${job.id}/source`&&method==='DELETE') {job.source_retained=false;body={source_deleted:true,report_retained:true};}
      else if(job&&endpoint===`/api/replays/${job.id}`) body={replay:job,hero_context:legacy?{...heroContext,hero:'npc_dota_hero_lion',label:'Lion'}:heroContext,parts:uploaded?[1]:[],archived_report:job.state==='ready'?{id:1,created_at:new Date().toISOString(),hero_context:{...heroContext,summary:'Контекст сохранённого разбора.',abilities:[{...heroContext.abilities[0],casts:7}]},report:{...report,metrics:{...report.metrics,kills:9},evidence:[{id:'old-death',type:'death',time:500,title:'Старый эпизод'}],coaching:{status:'ready',summary:'Сохранённый комментарий',points:[{title:'Сохранённый эпизод',observation:'Предыдущий разбор.',evidence_ids:['old-death']}]}}}:null,report:job.state==='ready'?{...report,...(legacy?{insights:undefined,coaching:{status:'unavailable',points:[]}}:{}),...(width===1440?{coaching:{status:'unavailable',summary:'',points:[]}}:{})}:null};
      else throw Error(`Unexpected frontend API request: ${method} ${endpoint}`);
      await route.fulfill({status,json:body,headers:responseHeaders});
    });
    await page.goto(origin);
    await page.getByLabel('Email',{exact:true}).fill('fixture@example.test');
    await page.getByLabel('Пароль',{exact:true}).fill('Synthetic passphrase 2026');
    await page.getByRole('button',{name:'Войти',exact:true}).click();
    await page.getByRole('heading',{name:'Разбор твоего матча'}).waitFor();
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-entry.png`)});
    assert.equal(await page.getByRole('button',{name:'Загрузить и разобрать'}).isDisabled(),true);
    assert.equal(await page.locator('#replay-file').getAttribute('accept'),'.dem');
    assert.equal(await page.locator('body').innerText().then(text=>/OpenDota|Open Dota|MP4|3\s?600 кадров/.test(text)),false);
    await page.getByLabel('Твой ник в этом матче',{exact:true}).fill('SyntheticPlayer');
    await page.locator('#replay-file').setInputFiles({name:'synthetic.dem',mimeType:'application/octet-stream',buffer:Buffer.concat([Buffer.from('PBDEMS2\x00','binary'),Buffer.alloc(32)])});
    assert.equal(await page.getByRole('button',{name:'Загрузить и разобрать'}).isEnabled(),true);
    await page.getByRole('button',{name:'Загрузить и разобрать'}).click();
    await page.getByRole('heading',{name:'Матч 8984479726',exact:true}).waitFor();
    await page.getByText('17 / 16 / 20',{exact:true}).waitFor();
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-hero-header.png`)});
    assert.equal(await page.locator('#nickname-field').isHidden(),true);
    assert.equal(await page.locator('#timeline-value').textContent(),'78:41');
    await page.locator('#economy-heading').scrollIntoViewIfNeeded();
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-charts.png`)});
    await page.getByRole('button',{name:'10:00 · Смерть',exact:true}).first().click();
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
    assert.equal(await page.locator('#next-game-plan h4').textContent(),'План за Necrophos','The hero plan replaces generic training even without Gemini.');
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
    await page.getByRole('button',{name:'10:00 · Смерть',exact:true}).first().click();
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
    assert.equal(await page.locator('#item-cards .item-card:visible h4').textContent(),'Radiance','An archived report starts with its own first item.');
    assert.match(await page.locator('#hero-context').textContent(),/Контекст сохранённого разбора/);
    assert.match(await page.locator('#hero-context .hero-abilities').textContent(),/7 применений/);
    assert.match(await page.locator('#metrics').textContent(),/9 \/ 16 \/ 20/);
    await page.getByRole('button',{name:'8:20 · Смерть',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'8:20');
    assert.equal(await page.locator('#events [data-evidence-id=old-death]').count(),1);
    await page.locator('#item-rail .item-chip').nth(1).click();
    await page.getByRole('button',{name:'Вернуться к текущему разбору',exact:true}).click();
    assert.equal(await page.locator('#item-cards .item-card:visible h4').textContent(),'Radiance','Current-report selection never inherits the archived selection.');
    assert.equal(await page.locator('#events [data-evidence-id=old-death]').count(),0);
    legacy=true; await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.getByText('В этом отчёте нет разбивки золота по источникам. Изменение ценности предметов показано выше.',{exact:true}).waitFor();
    assert.equal(await page.locator('#gold-chart .chart-line').count(),1);
    assert.equal(await page.locator('#item-cards .item-card').count(),1);
    assert.equal(await page.locator('#income-chart .chart-bar').count(),0);
    assert.equal(await page.locator('#hero-context').isHidden(),true,'Context for another hero is never attached to this report.');
    await page.getByRole('button',{name:'Пул героев',exact:true}).click();
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
    await page.getByLabel('Герой',{exact:true}).selectOption('npc_dota_hero_necrolyte');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===1);
    assert.equal(await coachCards.getByRole('heading',{name:'Решения в разных позициях',exact:true}).count(),0,'Filtering a hero hides conclusions that cite another hero.');
    await page.getByLabel('Герой',{exact:true}).selectOption('npc_dota_hero_lion');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-roster .pool-hero-row').length===1&&document.querySelector('#pool-roster').textContent.includes('Lion'));
    assert.equal(await coachCards.count(),0,'One matching episode cannot retain a two-match recommendation.');
    await page.getByLabel('Герой',{exact:true}).selectOption('');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===2);
    await page.getByLabel('Позиция',{exact:true}).selectOption('2');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===1);
    assert.match(await coachCards.textContent(),/Necrophos · 2 · Мидер/);
    assert.doesNotMatch(await coachCards.textContent(),/Lion/);
    await page.getByLabel('Позиция',{exact:true}).selectOption('5');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-matches .pool-match-row').length===1&&document.querySelector('#pool-matches').textContent.includes('Lion'));
    assert.equal(await coachCards.count(),0,'Position filters cannot turn mixed-context conclusions into same-role advice.');
    await page.getByLabel('Позиция',{exact:true}).selectOption('');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-patterns .pool-coach-card').length===2);
    await coachCard.locator('summary').click();
    await coachCard.getByRole('button',{name:'Матч 8984000001 · 12:00',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984000001',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#timeline-value').textContent==='12:00');
    assert.equal(await page.locator('#events [data-evidence-id="death-1"].selected-event').count(),1);
    assert.ok(requests.includes('/api/replays/pool-1'),'A coaching episode opens its own saved report.');
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984479726',exact:true}).waitFor();
    await page.getByRole('button',{name:'Пул героев',exact:true}).click();
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
    await page.getByLabel('Позиция',{exact:true}).selectOption('3');
    await page.waitForFunction(()=>document.querySelectorAll('#pool-matches .pool-match-row').length===1);
    assert.equal(await page.locator('#pool-summary .metric dd').nth(1).textContent(),'—');
    await page.getByLabel('Позиция',{exact:true}).selectOption('');
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
    assert.equal(await page.locator('#hero-pool img').count(),0,'Reflection notes remain safe text.');
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
    await page.getByRole('button',{name:'Разбор матча',exact:true}).click();
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
    await learning.getByLabel('Моя позиция в этом матче',{exact:true}).selectOption('2');
    await learning.locator('.learning-plan').waitFor();
    await page.getByRole('button',{name:'Пул героев',exact:true}).click();
    await page.getByLabel('Герой',{exact:true}).selectOption('npc_dota_hero_necrolyte');
    await page.getByLabel('Позиция',{exact:true}).selectOption('2');
    const practice=page.locator('#pool-learning');
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
    await checkToggle.press('Enter');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    if(screenshotDir)await practice.screenshot({path:path.join(screenshotDir,`portal-${width}-learning.png`)});
    await page.addScriptTag({content:axe.source});
    const learningAccessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(learningAccessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    // A duplicate upload must navigate to the canonical report before exposing practice.
    learningAlias=true;
    await page.getByRole('button',{name:'Разбор матча',exact:true}).click();
    await page.locator('#history').getByRole('button',{name:'Открыть',exact:true}).click();
    await page.getByRole('heading',{name:'Матч 8984000001',exact:true}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#report-learning .learning-check-form select')?.value==='pool-1');
    assert.match(await learning.getByLabel('Эпизод из разбора',{exact:true}).textContent(),/12:00/);
    await learning.getByLabel('Эпизод из разбора',{exact:true}).selectOption('death-1');
    const canonicalEvent=page.locator('#events [data-evidence-id="death-1"]');
    assert.match(await canonicalEvent.textContent(),/12:00/,'Practice anchors and the visible replay share canonical timestamps.');
    assert.match(await page.locator('#notice').textContent(),/Открыт актуальный сохранённый разбор/);
    await page.getByRole('button',{name:'Мой игрок',exact:true}).click();
    await page.getByRole('heading',{name:'Мой игрок',exact:true}).waitFor();
    assert.match(await page.locator('#player-summary').textContent(),/Steam ID: 123/);
    await page.getByRole('button',{name:'Аккаунт',exact:true}).click();
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
    await page.getByRole('button',{name:'Мой игрок',exact:true}).click();
    const pausedCount=integrationRequests.length;await page.clock.fastForward(15000);assert.equal(integrationRequests.length,pausedCount,'Leaving account stops OAuth polling.');
    await page.getByRole('button',{name:'Аккаунт',exact:true}).click();await openai.waitFor();
    assert.equal(integrationRequests.filter(request=>request.endpoint.endsWith('/connect')).length,2,'Returning resumes the existing login without another connect request.');
    chatgptPollConnect=true;await page.clock.fastForward(5100);await integration.getByText('ChatGPT подключён',{exact:true}).waitFor();
    assert.match(await integration.innerText(),/Готовность тренерского разбора проверяется отдельно/);
    assert.equal(await integration.getByRole('link').count(),0);assert.equal(await integration.getByLabel('Код для входа в OpenAI').count(),0);
    const connectedCount=integrationRequests.length;await page.clock.fastForward(15000);assert.equal(integrationRequests.length,connectedCount,'Connected accounts no longer poll device auth.');
    const refreshIntegration=async()=>{await page.getByRole('button',{name:'Мой игрок',exact:true}).click();await page.getByRole('button',{name:'Аккаунт',exact:true}).click();await page.waitForFunction(()=>document.getElementById('chatgpt-integration').getAttribute('aria-busy')==='false');};
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
  console.log('Visual report income sources, item timings/delivery/realization, personal goals/reset and next-game plan; Portal .dem upload→report, selected-player binding, shared gold/XP timeline, customer coaching/filtered evidence links, safe text, account navigation, mobile layout and WCAG passed (mocked API; no paid calls).');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
