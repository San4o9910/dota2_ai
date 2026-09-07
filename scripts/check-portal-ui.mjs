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
// Entirely synthetic history: role changes and an unknown result must stay visible.
const heroPoolMatches=Array.from({length:10},(_,index)=>({
  match_id:String(9000000101+index),job_id:`fixture-pool-${index+1}`,
  hero:index===9?'npc_dota_hero_zuus':'npc_dota_hero_necrolyte',hero_label:index===9?'Zeus':'Necrophos',
  position:index<6?3:index===8?null:2,outcome:['win','loss','win','win','loss','win','loss','win',null,'win'][index],
  uploaded_at:new Date(Date.UTC(2026,7,index+1)).toISOString(),
  metrics:{lh10:32+index*3,nw10:3300+index*100,deaths10:index<3?2:1,dead_pct:18-index/2,gpm:360+index*8},
  focus:index<6?'item_plan':null,reflection:index<3?'done':index===3?'partial':index===4?'not_done':null,note:''
}));
function poolCounts(matches) {
  const wins=matches.filter(match=>match.outcome==='win').length,losses=matches.filter(match=>match.outcome==='loss').length;
  return {matches:matches.length,wins,losses,unknown:matches.length-wins-losses,winrate:wins+losses?wins/(wins+losses)*100:null};
}
function heroPoolFixture(matches,url) {
  const hero=url.searchParams.get('hero')||null,position=url.searchParams.get('position')||null;
  const selected=matches.filter(match=>(!hero||match.hero===hero)&&(!position||(position==='unknown'?match.position===null:match.position===Number(position))));
  const heroes=[...new Set(matches.map(match=>match.hero))].map(value=>{
    const group=matches.filter(match=>match.hero===value);
    return {hero:value,hero_label:group[0].hero_label,...poolCounts(group),positions:[...new Set(group.map(match=>match.position))].map(value=>({position:value,...poolCounts(group.filter(match=>match.position===value))}))};
  });
  const ready=!!hero&&!!position&&selected.length>=6,ascending=[...selected].sort((a,b)=>a.match_id.localeCompare(b.match_id)),older=ascending.slice(0,3),recent=ascending.slice(-3);
  const average=(group,key)=>group.reduce((total,match)=>total+match.metrics[key],0)/group.length;
  return {schema_version:'narma.hero-pool.v1',scope:{account_id:profile.account_id,nickname:profile.nickname,hero,position,chronology:'match_id',source:'uploaded_replays',total_available:matches.length,limit:1000,truncated:false,context:'Только загруженные реплеи закреплённого игрока.'},summary:poolCounts(selected),heroes,matches:[...selected].reverse(),
    trends:{status:!hero||!position?'choose_hero_position':ready?'ready':'insufficient',eligible_matches:selected.length,note:ready?'Сравниваем три ранних и три последних матча на одном герое и позиции.':'Для сравнения нужны матчи на одном герое и позиции; одна игра не показывает динамику.',older_match_ids:ready?older.map(match=>match.match_id):[],recent_match_ids:ready?recent.map(match=>match.match_id):[],metrics:ready?[['lh10','Добивания к 10:00',''],['nw10','Ценность к 10:00','золота'],['deaths10','Смерти до 10:00','']].map(([key,label,unit])=>({key,label,unit,older:average(older,key),recent:average(recent,key),delta:average(recent,key)-average(older,key),older_count:3,recent_count:3})):[]},
    patterns:hero&&position&&position!=='unknown'&&selected.length>=3?[{id:'item-plan',title:'Предмет появился, следующий выход задержался',observation:'В трёх реплеях между покупкой и первым применением прошло больше двух минут.',action:'До покупки выбери следующий безопасный эпизод.',measure:'После матча сравни покупку, доставку и первое применение.',matches:3,eligible_matches:selected.length,evidence:selected.slice(0,3).map(match=>({match_id:match.match_id,job_id:match.job_id,time:700,event_id:'purchase-1',item:'item_radiance'}))}]:[],
    practice:{tracked:selected.filter(match=>match.focus).length,done:selected.filter(match=>match.reflection==='done').length,partial:selected.filter(match=>match.reflection==='partial').length,not_done:selected.filter(match=>match.reflection==='not_done').length,unreviewed:selected.filter(match=>match.focus&&!match.reflection).length}};
}
try {
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}});
    let authenticated=false, bound=false, job=null, uploaded=false, legacy=false,poolFailure=false,poolSaveFailure=false,poolMatches=structuredClone(heroPoolMatches);
    const errors=[], requests=[],poolWrites=[],externalRequests=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',async route=>{ if(new URL(route.request().url()).origin!==origin) { externalRequests.push(route.request().url()); await route.abort(); } else await route.fallback(); });
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url()), endpoint=url.pathname, method=request.method(); requests.push(endpoint);
      let body, status=200;
      if(endpoint==='/api/auth/login') { authenticated=true; body={authenticated:true}; }
      else if(endpoint==='/api/session') body={authenticated,setup_required:false,user:authenticated?{email:'fixture@example.test'}:null};
      else if(endpoint==='/api/profile') body={profile:bound?profile:null};
      else if(endpoint==='/api/hero-pool'&&method==='GET') { status=poolFailure?503:200; body=poolFailure?{detail:'Пул временно недоступен (проверка).'}:heroPoolFixture(poolMatches,url); }
      else if(endpoint.startsWith('/api/hero-pool/matches/')&&method==='PUT') {
        const match=poolMatches.find(match=>match.match_id===endpoint.split('/').at(-1)); assert.ok(match,'Only a listed synthetic match can be saved.');
        const command=request.postDataJSON(); poolWrites.push(command);
        assert.deepEqual(Object.keys(command).sort(),['focus','note','position','reflection']);
        if(poolSaveFailure) { status=503; body={detail:'Не удалось сохранить дневник (проверка).'}; }
        else { Object.assign(match,command); body={saved:true,match_id:match.match_id,...command}; }
      }
      else if(endpoint.startsWith('/api/replays/fixture-pool-')&&method==='GET') {
        const match=poolMatches.find(match=>`/api/replays/${match.job_id}`===endpoint); assert.ok(match);
        body={replay:{id:match.job_id,state:'ready',progress:100,match_id:match.match_id,nickname:profile.nickname},parts:[],report:{...report,match_id:match.match_id,outcome:match.outcome,player:{...report.player,hero:match.hero}}};
      }
      else if(endpoint==='/api/replays'&&method==='POST') {
        const command=request.postDataJSON(); assert.equal(command.filename,'synthetic.dem'); assert.equal(command.nickname,'SyntheticPlayer'); assert.equal('account_id' in command,false);
        job={...command,state:'uploading',progress:0,match_id:null,created_at:new Date().toISOString()}; status=201; body={replay:job,part_bytes:5*1024**2};
      }
      else if(endpoint==='/api/replays') body={replays:job?[job]:[],worker_ready:true,max_bytes:512*1024**2};
      else if(job&&endpoint===`/api/replays/${job.id}/parts/1`&&method==='PUT') { uploaded=true; assert.equal(request.postDataBuffer().subarray(0,8).toString('binary'),'PBDEMS2\x00'); body={uploaded:true,part_number:1}; }
      else if(job&&endpoint===`/api/replays/${job.id}/complete`) { assert.equal(uploaded,true); bound=true; job={...job,state:'ready',progress:100,match_id:'8984479726'}; body={replay:job}; }
      else if(job&&endpoint===`/api/replays/${job.id}`) body={replay:job,parts:uploaded?[1]:[],report:job.state==='ready'?{...report,...(legacy?{insights:undefined,coaching:{status:'unavailable',points:[]}}:{}),...(width===1440?{coaching:{status:'unavailable',summary:'',points:[]}}:{})}:null};
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
    assert.equal(await page.locator('#next-game-plan .training-card').count(),1);
    assert.equal(await page.locator('#item-cards .item-card').count(),1);
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
    legacy=true; await page.getByRole('button',{name:'Обновить',exact:true}).click();
    await page.getByText('В этом отчёте нет разбивки золота по источникам. Изменение ценности предметов показано выше.',{exact:true}).waitFor();
    assert.equal(await page.locator('#gold-chart .chart-line').count(),1);
    assert.equal(await page.locator('#item-cards .item-card').count(),1);
    assert.equal(await page.locator('#income-chart .chart-bar').count(),0);
    const waitPoolCount=count=>page.waitForFunction(expected=>!document.getElementById('hero-pool').hasAttribute('aria-busy')&&!document.getElementById('pool-summary').hidden&&document.querySelectorAll('#pool-history .pool-match').length===expected,count);
    await page.locator('button[data-tab="hero-pool"]').click();
    await waitPoolCount(10);
    assert.match(await page.locator('#pool-heroes').innerText(),/Necrophos/);
    assert.match(await page.locator('#pool-heroes').innerText(),/Zeus/);
    assert.match(await page.locator('#pool-summary').innerText(),/66[,.]7/);
    assert.match(await page.locator('.pool-hero-card').filter({has:page.getByRole('heading',{name:'Necrophos',exact:true})}).locator('.pool-hero-rate').innerText(),/62[,.]5/);
    await page.locator('.pool-hero-card').filter({has:page.getByRole('heading',{name:'Zeus',exact:true})}).locator('.pool-hero-select').click();
    await waitPoolCount(1);
    assert.equal(await page.locator('#pool-hero').inputValue(),'npc_dota_hero_zuus');
    assert.match(await page.locator('#pool-summary').innerText(),/100%/);
    await page.locator('#pool-hero').selectOption('npc_dota_hero_necrolyte');
    await waitPoolCount(9);
    await page.locator('#pool-position').selectOption('3');
    await waitPoolCount(6);
    assert.match(await page.locator('#pool-summary').innerText(),/66[,.]7/);
    assert.match(await page.locator('#pool-trends').innerText(),/Добивания к 10:00/);
    assert.equal(await page.locator('#pool-trends .pool-trend-dot').count(),6);
    assert.equal(await page.locator('#pool-trends .pool-comparison').count(),3);
    await page.locator('#pool-trend-metric').selectOption('nw10');
    assert.match(await page.locator('#pool-trends svg').getAttribute('aria-label'),/Ценность предметов и золота к 10:00/);
    await page.locator('.pool-chart-table summary').click();
    assert.equal(await page.locator('.pool-chart-table tbody tr').count(),6);
    assert.match(await page.locator('#pool-patterns').innerText(),/следующий выход задержался/);
    if(screenshotDir) await page.screenshot({path:path.join(screenshotDir,`portal-${width}-hero-pool.png`),fullPage:true});
    const poolAccessibility=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(poolAccessibility.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(item=>item.target)})),[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.locator('#pool-position').selectOption('2');
    await waitPoolCount(2);
    assert.match(await page.locator('#pool-summary').innerText(),/50/);
    assert.match(await page.locator('#pool-trends').innerText(),/не показывает динамику/);
    await page.locator('#pool-position').selectOption('unknown');
    await waitPoolCount(1);
    assert.equal((await page.locator('#pool-summary').innerText()).includes('%'),false,'Unknown results cannot become 0% winrate.');
    assert.match(await page.locator('#pool-trends').innerText(),/не показывает динамику/);
    assert.equal(await page.locator('#pool-trends .pool-trend-line, #pool-trends .pool-comparison').count(),0,'One observed match cannot become a growth line or an earlier/later comparison.');
    await page.locator('#pool-position').selectOption('3');
    await waitPoolCount(6);
    const editedMatchId='9000000106',editedMatch=page.locator(`.pool-match[data-match-id="${editedMatchId}"]`);
    await editedMatch.locator('.pool-match-position').selectOption('2');
    await editedMatch.locator('.pool-focus').selectOption('safe_return');
    await editedMatch.locator('.pool-reflection').selectOption('partial');
    await editedMatch.locator('.pool-note').fill(malicious);
    poolSaveFailure=true;
    await editedMatch.locator('.pool-save').click();
    await editedMatch.locator('.pool-save-status').filter({hasText:'Не удалось сохранить дневник (проверка).'}).waitFor();
    assert.equal(await editedMatch.locator('.pool-note').inputValue(),malicious,'A failed save must preserve the user draft.');
    assert.equal(await editedMatch.locator('.pool-match-position').inputValue(),'2');
    poolSaveFailure=false;
    await editedMatch.locator('.pool-save').click();
    await waitPoolCount(5);
    assert.deepEqual(poolWrites.at(-1),{position:2,focus:'safe_return',reflection:'partial',note:malicious});
    await page.locator('#pool-position').selectOption('2');
    await waitPoolCount(3);
    assert.equal(await editedMatch.locator('.pool-note').inputValue(),malicious);
    assert.equal(await editedMatch.locator('.pool-focus').inputValue(),'safe_return');
    assert.equal(await editedMatch.locator('.pool-reflection').inputValue(),'partial');
    assert.equal(await page.locator('#hero-pool img').count(),0,'Diary notes are rendered as text, not markup.');
    await editedMatch.locator('.pool-open-report').click();
    await page.getByRole('heading',{name:`Матч ${editedMatchId}`,exact:true}).waitFor();
    assert.equal(await page.locator('#review').isVisible(),true);
    assert.equal(await page.locator('#hero-pool').isHidden(),true);
    await page.locator('button[data-tab="hero-pool"]').click();
    poolFailure=true;
    await page.locator('#pool-refresh').click();
    await page.locator('#pool-status').filter({hasText:'Пул временно недоступен (проверка).'}).waitFor();
    poolFailure=false;
    await page.locator('#pool-refresh').click();
    await waitPoolCount(3);
    poolMatches=[structuredClone(heroPoolMatches[6])];
    await page.locator('#pool-refresh').click();
    await waitPoolCount(1);
    assert.match(await page.locator('#pool-trends').innerText(),/не показывает динамику/);
    assert.equal(await page.locator('#pool-trends .pool-trend-line, #pool-trends .pool-comparison').count(),0);
    poolMatches=[];
    await page.locator('#pool-refresh').click();
    await waitPoolCount(0);
    assert.equal(await page.locator('#pool-trends svg').count(),0);
    assert.equal((await page.locator('#pool-summary').innerText()).includes('%'),false,'Empty history cannot claim a winrate.');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.getByRole('button',{name:'Мой игрок',exact:true}).click();
    await page.getByRole('heading',{name:'Мой игрок',exact:true}).waitFor();
    assert.match(await page.locator('#player-summary').textContent(),/Steam ID: 123/);
    await page.getByRole('button',{name:'Аккаунт',exact:true}).click();
    await page.getByRole('heading',{name:'Изменить пароль',exact:true}).waitFor();
    assert.equal(requests.some(url=>url.startsWith('/api/videos')),false);
    assert.deepEqual(externalRequests,[],'Fixtures must never contact a provider or other external host.');
    assert.deepEqual(errors,[]); await page.close();
  }
  console.log('Hero pool role/hero filters, known-result winrates, sparse-history honesty, journal save/recovery, report navigation and WCAG; visual report sources, item delivery/realization, personal goals and next-game plan; .dem upload, binding, timeline and mobile layout passed (synthetic API fixtures; no provider/network calls).');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
