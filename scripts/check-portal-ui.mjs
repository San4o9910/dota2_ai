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
try {
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}});
    let authenticated=false, bound=false, job=null, uploaded=false, legacy=false;
    const errors=[], requests=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',async route=>{
      const request=route.request(), endpoint=new URL(request.url()).pathname, method=request.method(); requests.push(endpoint);
      let body, status=200;
      if(endpoint==='/api/auth/login') { authenticated=true; body={authenticated:true}; }
      else if(endpoint==='/api/session') body={authenticated,setup_required:false,user:authenticated?{email:'fixture@example.test'}:null};
      else if(endpoint==='/api/profile') body={profile:bound?profile:null};
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
    await page.getByRole('button',{name:'Мой игрок',exact:true}).click();
    await page.getByRole('heading',{name:'Мой игрок',exact:true}).waitFor();
    assert.match(await page.locator('#player-summary').textContent(),/Steam ID: 123/);
    await page.getByRole('button',{name:'Аккаунт',exact:true}).click();
    await page.getByRole('heading',{name:'Изменить пароль',exact:true}).waitFor();
    assert.equal(requests.some(url=>url.startsWith('/api/videos')),false);
    assert.deepEqual(errors,[]); await page.close();
  }
  console.log('Visual report income sources, item timings/delivery/realization, personal goals/reset and next-game plan; Portal .dem upload→report, selected-player binding, shared gold/XP timeline, evidence links, safe text, account navigation, mobile layout and WCAG passed (mocked API; no paid calls).');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
