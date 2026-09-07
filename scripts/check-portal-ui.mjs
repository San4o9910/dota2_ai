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
    function poolResponse(url) {
      const query=url.searchParams, hero=query.get('hero'), pos=query.get('position'), period=query.get('window'), favoriteOnly=query.get('favorites_only')==='true';
      const selected=poolMatches.filter(match=>(!hero||match.hero===hero)&&(!pos||String(match.position??'unknown')===pos)&&(!favoriteOnly||favorites.has(match.hero+':'+match.position))&&(period==='all'||Date.parse(match.chronology_at)>=Date.now()-Number(period)*86400000));
      const summarize=rows=>{const wins=rows.filter(r=>r.outcome==='win').length,losses=rows.filter(r=>r.outcome==='loss').length;return {matches:rows.length,wins,losses,known_outcomes:wins+losses,unknown_outcomes:rows.length-wins-losses,winrate_pct:wins+losses?Math.round(wins/(wins+losses)*1000)/10:null,unknown_positions:rows.filter(r=>r.position===null).length,analysis_dated_matches:rows.filter(r=>r.date_source==='analysis').length};};
      const groups=new Map(); for(const match of selected) {const key=match.hero+':'+match.position;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(match);}
      const sameRole=selected.filter(match=>match.hero==='npc_dota_hero_necrolyte'&&match.position===2);
      return {summary:summarize(selected),heroes:[...groups].map(([key,rows])=>({hero:rows[0].hero,label:rows[0].label,position:rows[0].position,favorite:favorites.has(key),...summarize(rows)})),available_heroes:[{hero:'npc_dota_hero_necrolyte',label:'Necrophos'},{hero:'npc_dota_hero_lion',label:'Lion'}],history:selected,trends:sameRole.length===6?[{hero:'npc_dota_hero_necrolyte',position:2,metric:'deaths_per_30',status:'ready',early_n:3,recent_n:3,early_mean:9,recent_mean:6,delta:-3,unit:'смертей'}]:[],patterns:sameRole.length>=3?[{id:'repeat-death',hero:'npc_dota_hero_necrolyte',label:'Necrophos',position:2,title:malicious,observation:'Повторная смерть в двух матчах.',action:'Перед возвращением на линию проверь доступные предметы.',occurrences:2,eligible_matches:sameRole.length,evidence:[{job_id:'pool-0',match_id:'8984000000'}]}]:[],goals,limitations:['Синтетическая тестовая выборка. Дата разбора не является датой игры.']};
    }
    const errors=[], requests=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{
      const url=route.request().url();
      if(url===itemImageUrl) { if(width===1440) await route.fulfill({contentType:'image/png',body:itemImage}); else await route.abort(); }
      else if(new URL(url).origin!==origin) {externalRequests.push(url);await route.abort();}
      else await route.fallback();
    });
    await page.route('**/api/**',async route=>{
      const request=route.request(), url=new URL(request.url()), endpoint=url.pathname, method=request.method(); requests.push(endpoint);
      let body, status=200;
      if(endpoint==='/api/auth/login') { authenticated=true; body={authenticated:true}; }
      else if(endpoint==='/api/session') body={authenticated,setup_required:false,user:authenticated?{email:'fixture@example.test'}:null};
      else if(endpoint==='/api/hero-pool') {status=poolFailed?503:200;body=poolFailed?{detail:'Проверка восстановления после ошибки.'}:poolResponse(url);}
      else if(endpoint==='/api/hermes') body={stage:'offline_bridge',runtime_connected:false,automatic_tracking:false,last_review:null};
      else if(endpoint==='/api/hero-pool/favorites'&&method==='PUT') {const value=request.postDataJSON();favorites.add(value.hero+':'+value.position);body={saved:true};}
      else if(endpoint.startsWith('/api/hero-pool/favorites/')&&method==='DELETE') {const parts=endpoint.split('/');favorites.delete(parts[4]+':'+parts[5]);body={deleted:true};}
      else if(endpoint.startsWith('/api/hero-pool/matches/')&&method==='PUT') {const match=poolMatches.find(item=>item.job_id===endpoint.split('/').at(-1));assert.ok(match);const value=request.postDataJSON();poolWrites.push(value);if(poolSaveFailed&&'note' in value){status=503;body={detail:'Не удалось сохранить дневник (проверка).'};}else{if('position' in value)match.position=value.position;if('played_at' in value){match.played_at=value.played_at;match.date_source=value.played_at?'user':'analysis';match.chronology_at=value.played_at??match.analyzed_at??match.chronology_at;}for(const key of ['focus','reflection','note'])if(key in value)match[key]=value[key];body={saved:true};}}
      else if(endpoint==='/api/hero-pool/goals'&&method==='POST') {const value=request.postDataJSON();goals.push({id:'goal-1',...value,title:'Практика после смерти',action:'Проверь готовность перед возвращением.',status:'active',metric:'repeated_deaths',threshold:0,checks:[{job_id:'pool-0',match_id:'8984000000',value:1,status:'predates_goal',chronology_basis:'user'},{job_id:'pool-1',match_id:'8984000001',value:0,status:'unknown',chronology_basis:'analysis'}]});body={goal:goals[0]};}
      else if(endpoint.startsWith('/api/hero-pool/goals/')&&method==='PATCH') {goals[0].status=request.postDataJSON().status;body={saved:true};}
      else if(endpoint==='/api/profile') body={profile:bound?profile:null};
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
      await route.fulfill({status,json:body});
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
    assert.equal(await page.locator('#next-game-plan .training-card').count(),1);
    assert.equal(await page.locator('#item-cards .item-card').count(),1);
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
    await page.getByText('Сравнить со своей целью',{exact:true}).click();
    await page.getByLabel('Личная цель, мин:сек',{exact:true}).fill('10:00');
    await page.getByRole('button',{name:'Применить',exact:true}).click();
    await page.getByText('Поздний · личная цель',{exact:true}).waitFor();
    assert.match(await page.locator('.item-timing').textContent(),/не с другими игроками/);
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-items.png`)});
    await page.getByRole('button',{name:'Убрать цель',exact:true}).click();
    await page.getByText('Без эталона',{exact:true}).waitFor();
    assert.equal(await page.locator('#income-chart .chart-cursor').getAttribute('x1'),await page.locator('#xp-chart .chart-cursor').getAttribute('x1'));
    const axe=dependency('axe-core'); await page.addScriptTag({content:axe.source});
    const accessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(accessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    const originalItemId=report.insights.items[0].item;
    report.insights.items[0].item='item_../../foreign';
    await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#item-cards .item-image').length===0);
    assert.equal(await page.locator('#item-rail .item-image').count(),0,'Malformed item identifiers cannot create external image URLs.');
    report.insights.items[0].item=originalItemId;
    await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#item-cards .item-image').length===1);
    await page.getByRole('button',{name:'Предыдущий тренерский разбор',exact:true}).click();
    await page.getByRole('heading',{name:'Сохранённый эпизод',exact:true}).waitFor();
    assert.match(await page.locator('#hero-context').textContent(),/Контекст сохранённого разбора/);
    assert.match(await page.locator('#hero-context .hero-abilities').textContent(),/7 применений/);
    assert.match(await page.locator('#metrics').textContent(),/9 \/ 16 \/ 20/);
    await page.getByRole('button',{name:'8:20 · Смерть',exact:true}).click();
    assert.equal(await page.locator('#timeline-value').textContent(),'8:20');
    assert.equal(await page.locator('#events [data-evidence-id=old-death]').count(),1);
    await page.getByRole('button',{name:'Вернуться к текущему разбору',exact:true}).click();
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
    await page.getByRole('heading',{name:'Hermes не подключён',exact:true}).waitFor();
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
    await page.getByRole('button',{name:'Мой игрок',exact:true}).click();
    await page.getByRole('heading',{name:'Мой игрок',exact:true}).waitFor();
    assert.match(await page.locator('#player-summary').textContent(),/Steam ID: 123/);
    await page.getByRole('button',{name:'Аккаунт',exact:true}).click();
    await page.getByRole('heading',{name:'Изменить пароль',exact:true}).waitFor();
    assert.equal(requests.some(url=>url.startsWith('/api/videos')),false);
    assert.deepEqual(externalRequests,[],'Synthetic UI fixtures must never contact external providers.');
    assert.deepEqual(errors,[]); await page.close();
  }
  console.log('Visual report income sources, item timings/delivery/realization, personal goals/reset and next-game plan; Portal .dem upload→report, selected-player binding, shared gold/XP timeline, evidence links, safe text, account navigation, mobile layout and WCAG passed (mocked API; no paid calls).');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
