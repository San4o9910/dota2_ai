import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';

// Browser regression fixtures only. Production never imports or serves this file.
const require=createRequire(import.meta.url);
function dependency(name) {
  try { return require(name); }
  catch { const runtime=process.env.PLAYWRIGHT_NODE_MODULES||process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES; if(!runtime)throw Error(`Install ${name} to run the public experience check.`);return require(path.join(runtime,name)); }
}
const {chromium}=dependency('playwright'),axe=dependency('axe-core');
const root=path.resolve(process.env.NARMA_PORTAL_TEST_ROOT||'services/video/narma_video/static');
const publicRoutes=['/','/heroes','/learn','/practice','/updates'];
const files=new Map(publicRoutes.map(route=>[route,['explore.html','text/html']]));
for(const filename of ['explore.js','practice.js','explore.css','practice.css','practice-scenarios.json'])files.set('/assets/'+filename,[filename,filename.endsWith('.css')?'text/css':filename.endsWith('.json')?'application/json':'text/javascript']);
const server=createServer(async(request,response)=>{
  const file=files.get(new URL(request.url,'http://localhost').pathname);
  if(!file){response.writeHead(404).end();return;}
  try{response.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: https://cdn.cloudflare.steamstatic.com https://clan.fastly.steamstatic.com; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");response.setHeader('Content-Type',file[1]);response.end(await readFile(path.join(root,file[0])));}
  catch{response.writeHead(500).end('Missing test asset');}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const screenshotDir=process.env.NARMA_EXPLORE_SCREENSHOTS;
if(screenshotDir)await mkdir(screenshotDir,{recursive:true});
const scenarios=JSON.parse(await readFile(path.join(root,'practice-scenarios.json'),'utf8')).scenarios;
assert.ok(scenarios.length>=5,'The actual authored trainer must contain enough distinct questions.');
assert.equal(scenarios.find(row=>row.id==='lane-last-hit')?.correctChoiceId,'b','The known last-hit scenario must reward timing damage after the allied projectile.');
const malicious='<img src=x onerror=alert(1)>',stamp='2026-01-02T12:00:00Z';
const heroRows=[
  [2,'axe','Axe','strength',1], [8,'juggernaut','Juggernaut','agility',1],
  [36,'necrolyte','Necrophos','intelligence',2], [21,'windrunner','Windranger','universal',2],
].map(([id,slug,display_name,attribute,complexity])=>({id,slug,display_name,attribute,complexity,name:'npc_dota_hero_'+slug,image_url:`https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/${slug}.png`,official_url:'https://www.dota2.com/hero/'+display_name.toLowerCase()}));
const heroes={schema_version:'narma.explore.v1',heroes:heroRows,source_url:'https://www.dota2.com/heroes',checked_at:stamp,stale:false,refreshing:false,errors:[]};
const newsImage='https://clan.fastly.steamstatic.com/images/3703047/'+'a'.repeat(40)+'.png';
const updates={schema_version:'narma.explore.v1',source_url:'https://www.dota2.com/news',checked_at:stamp,stale:true,refreshing:false,errors:['source_unavailable'],latest_patch:{version:'7.40b',url:'https://www.dota2.com/patches/7.40b',published_at:stamp},news:[
  {id:'qa-patch',title:'Проверочная публикация об обновлении',category:'patch',url:'https://store.steampowered.com/news/app/570/view/10001',published_at:stamp,image_url:newsImage},
  {id:'qa-event',title:'Проверочная публикация о событии',category:'event',url:'https://store.steampowered.com/news/app/570/view/10002',published_at:stamp,image_url:null},
  {id:'qa-text',title:malicious,category:'news',url:'https://store.steampowered.com/news/app/570/view/10003',published_at:stamp,image_url:'https://evil.example.test/news.png'},
  {id:'qa-script',title:'Небезопасная ссылка',category:'news',url:'javascript:alert(1)',published_at:stamp},
  {id:'qa-lookalike',title:'Поддельный адрес Valve',category:'news',url:'https://store.steampowered.com.evil.example.test/news',published_at:stamp},
]};
// Exercise content comes from the actual dependency-free production catalog.
const catalogByPosition=JSON.parse(execFileSync(process.env.NARMA_TEST_PYTHON||'python3',['-c',"import importlib.util,json,sys; spec=importlib.util.spec_from_file_location('curriculum',sys.argv[1]); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); print(json.dumps([module.get_catalog(position or None) for position in range(6)],ensure_ascii=False))",path.resolve(root,'..','curriculum.py')],{encoding:'utf8'}));
const realExercises=new Map(catalogByPosition.flatMap(catalog=>catalog.exercises).map(exercise=>[exercise.id,exercise]));
assert.equal(realExercises.size,13,'The full authored curriculum is available to the public learning test.');
const catalog=position=>{const value=structuredClone(catalogByPosition[position||0]);value.sources.push({id:'qa-unsafe',title:'Небезопасный тестовый источник',url:'javascript:alert(1)'});for(const exercise of value.exercises)exercise.source_refs.push('qa-unsafe');return value;};
const pixel=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try {
  for(const width of [390,1440]) {
    const page=await browser.newPage({viewport:{width,height:1000}});
    const errors=[],unexpected=[],apiRequests=[];
    let newsFailed=false;
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(/Content Security Policy|Refused to (?:execute|apply|load)/i.test(message.text()))errors.push(message.text());});
    page.on('dialog',async dialog=>{errors.push('Unexpected dialog: '+dialog.message());await dialog.dismiss();});
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin===origin){await route.fallback();return;}
      if(/^https:\/\/cdn\.cloudflare\.steamstatic\.com\/apps\/dota2\/images\/dota_react\/(?:heroes|items)\/[a-z0-9_]+\.png$/.test(url.href)||url.href===newsImage){await route.fulfill({contentType:'image/png',body:pixel});return;}
      unexpected.push(url.href);await route.abort();
    });
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url());apiRequests.push({method:request.method(),path:url.pathname,position:url.searchParams.get('position')});
      let body,status=200;
      if(request.method()!=='GET'){unexpected.push(`${request.method()} ${url.pathname}`);status=405;body={};}
      else if(url.pathname==='/api/explore/heroes')body=heroes;
      else if(url.pathname==='/api/explore/updates'){status=newsFailed?503:200;body=newsFailed?{detail:'Synthetic unavailable news feed'}:updates;}
      else if(url.pathname==='/api/explore/learning')body=catalog(Number(url.searchParams.get('position'))||null);
      else{unexpected.push(url.pathname);status=404;body={};}
      await route.fulfill({status,json:body});
    });
    async function open(route){await page.goto(origin+route);await page.locator('#page-content[aria-busy="false"]').waitFor();assert.equal(await page.locator('h1').count(),1);assert.equal(await page.locator('input[type=password]').count(),0,'Public content must be usable before Narma login.');}
    async function accessibility(label){
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${label} must fit a ${width}px viewport.`);
      await page.evaluate(axe.source);
      const result=await page.evaluate(async()=>window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
      assert.deepEqual(result.violations.map(violation=>({id:violation.id,nodes:violation.nodes.map(node=>node.target)})),[],label);
      if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`explore-fixture-${width}-${label}.png`),fullPage:true});
    }
    await open('/');
    assert.equal(await page.locator('#home-heroes .hero-tile').count(),4);
    assert.equal(await page.locator('#home-stages .stage-preview').count(),6);
    assert.equal(await page.locator('#home-news .update-compact').count(),3);
    assert.match(await page.locator('#home-news .source-note.is-stale').textContent(),/сохранённ.*верси/i);
    assert.equal(await page.locator('a[href="/replays"]').count()>0,true,'The public home leads to existing replay analysis.');
    for(const route of publicRoutes)assert.equal(await page.locator(`.main-nav a[href="${route}"]`).count(),1);
    await accessibility('home');
    const heroNav=page.locator('.main-nav a[href="/heroes"]');await heroNav.focus();await heroNav.press('Enter');
    await page.waitForURL(url=>url.pathname==='/heroes');await page.locator('#hero-grid [data-hero]').first().waitFor();
    assert.equal(await page.locator('.main-nav [aria-current="page"]').getAttribute('href'),'/heroes');
    assert.equal(await page.locator('#hero-grid [data-hero]').count(),4);
    await page.locator('#hero-search').fill('necro');
    assert.equal(await page.locator('#hero-grid [data-hero]').count(),1);
    const necrophos=page.locator('#hero-grid [data-hero="36"]');await necrophos.focus();await necrophos.press('Enter');
    assert.equal(await page.locator('#hero-inspector h2').textContent(),'Necrophos');
    assert.equal(await page.locator('#hero-inspector a[target="_blank"]').getAttribute('href'),'https://www.dota2.com/hero/necrophos');
    assert.equal(await necrophos.getAttribute('aria-pressed'),'true');
    await page.locator('#hero-search').fill('');await page.locator('[data-attribute="strength"]').click();
    assert.equal(await page.locator('#hero-grid [data-hero]').count(),1);
    assert.equal(await page.locator('#hero-grid [data-hero]').getAttribute('data-hero'),'2');
    await page.locator('#hero-search').fill('not-a-dota-hero');
    await page.getByRole('button',{name:'Сбросить фильтры',exact:true}).click();
    assert.equal(await page.locator('#hero-grid [data-hero]').count(),4);
    assert.equal(await page.locator('[data-attribute=""]').getAttribute('aria-pressed'),'true');
    await accessibility('heroes');
    await page.reload();await page.locator('#hero-grid [data-hero]').first().waitFor();
    assert.equal(await page.locator('#hero-inspector h2').textContent(),'Necrophos','A direct URL preserves the selected hero.');

    await open('/learn');
    assert.equal(await page.locator('[data-stage]').count(),6);
    await page.locator('#learn-position').selectOption('5');
    await page.waitForFunction(()=>document.querySelector('#learning-library').getAttribute('aria-busy')==='false');
    await page.locator('[data-stage="lane"]').click();
    await page.locator('[data-exercise="l2"]').waitFor();
    assert.equal(await page.locator('[data-exercise="l1"]').count(),0,'Support lessons must not show the core-only exercise.');
    const lesson=page.locator('[data-exercise="l2"]');
    const reason=lesson.getByText('Почему это работает и когда менять решение',{exact:true});await reason.focus();await reason.press('Enter');
    assert.equal(await lesson.getByText(realExercises.get('l2').why,{exact:true}).isVisible(),true);
    assert.equal((await lesson.textContent()).includes(realExercises.get('l2').exception),true);
    await lesson.getByText('Источники методики',{exact:true}).click();
    assert.equal(await lesson.locator('.lesson-sources a').count(),realExercises.get('l2').source_refs.length,'Real curriculum sources remain available; the unsafe injected source is not clickable.');
    const mapStage=page.locator('[data-stage="map"]');await mapStage.focus();await mapStage.press('Enter');
    assert.equal(await page.locator('[data-exercise="m1"]').count(),1);
    assert.equal(await page.locator('[data-exercise="l2"]').count(),0);
    assert.equal(await page.locator('#lesson-content a[href="/practice?position=5"]').count(),1,'Practice receives the selected position.');
    await accessibility('learn');
    await page.reload();await page.locator('[data-exercise="m1"]').waitFor();
    assert.equal(await page.locator('#learn-position').inputValue(),'5');
    const renderedLessons=new Set();
    for(const position of ['2','5']){
      await page.locator('#learn-position').selectOption(position);
      await page.waitForFunction(()=>document.querySelector('#learning-library').getAttribute('aria-busy')==='false');
      for(const stage of catalogByPosition[Number(position)].stages){
        await page.locator(`[data-stage="${stage.id}"]`).click();
        for(const card of await page.locator('#lesson-content [data-exercise]').all()){
          const id=await card.getAttribute('data-exercise'),exercise=realExercises.get(id);assert.ok(exercise);
          assert.equal(await card.locator('h3').textContent(),exercise.title);
          assert.equal(await card.locator('.lesson-question').textContent(),exercise.decision_question);
          assert.equal((await card.textContent()).includes(exercise.measurement),true,'Every authored lesson includes how to check the result.');renderedLessons.add(id);
        }
      }
    }
    assert.deepEqual([...renderedLessons].sort(),[...realExercises.keys()].sort(),'Every real lesson can be reached from the public catalog.');

    await open('/updates');
    assert.equal(await page.locator('#news-grid .news-card').count(),3,'Script and lookalike-host links must be excluded.');
    assert.equal(await page.locator('#news-grid img').count(),1,'Only the approved official news image is rendered.');
    assert.equal(await page.locator('#news-grid img').getAttribute('src'),newsImage);
    assert.equal(await page.locator('#news-grid h2').filter({hasText:malicious}).count(),1,'News titles are displayed as literal text.');
    assert.equal(await page.locator('#news-grid script,#news-grid iframe,#news-grid [onerror]').count(),0);
    assert.match(await page.locator('.source-note.is-stale').textContent(),/сохранённ.*верси/i);
    assert.match(await page.locator('.source-note.is-stale').textContent(),/Проверено/);
    for(const link of await page.locator('#updates-content a').evaluateAll(links=>links.map(link=>({href:link.href,rel:link.rel,target:link.target})))){assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');assert.match(link.href,/^https:\/\/(?:www\.dota2\.com|store\.steampowered\.com)\//);}
    await page.locator('[data-category="event"]').click();
    assert.equal(await page.locator('#news-grid .news-card').count(),1);
    assert.match(await page.locator('#news-grid').textContent(),/Проверочная публикация о событии/);
    await page.locator('[data-category=""]').click();
    await accessibility('updates');
    newsFailed=true;await open('/');
    await page.locator('#home-news .error-box').waitFor();
    assert.equal(await page.locator('#home-heroes .hero-tile').count(),4,'News failure cannot disable the hero library.');
    assert.equal(await page.locator('#home-stages .stage-preview').count(),6,'News failure cannot disable learning.');
    newsFailed=false;await page.locator('#home-news').getByRole('button',{name:'Попробовать снова',exact:true}).click();await page.locator('#home-news .update-compact').first().waitFor();

    await open('/practice?position=5');
    const practice=page.locator('#practice-root');
    await practice.locator('[data-practice-start]').waitFor();
    assert.equal(await practice.locator('[data-practice-filter="position"]').inputValue(),'5','The trainer receives the role selected in learning.');
    await practice.locator('[data-practice-filter="topic"]').selectOption('lane');
    const shortCount=scenarios.filter(scenario=>scenario.topic==='lane'&&scenario.positions.includes(5)).length;
    assert.ok(shortCount>0&&shortCount<5);
    assert.match(await practice.locator('[data-practice-availability]').textContent(),new RegExp(`В серии будет ${shortCount}`),'A short selection advertises its actual length.');
    await practice.locator('[data-practice-reset-filters]').click();
    await practice.locator('[data-practice-start]').focus();await practice.locator('[data-practice-start]').press('Enter');
    const seen=new Set();
    for(let index=0;index<5;index++){
      const card=practice.locator('[data-scenario-id]');await card.waitFor();
      const id=await card.getAttribute('data-scenario-id'),scenario=scenarios.find(row=>row.id===id);
      assert.ok(scenario,'The trainer uses a real authored scenario.');assert.equal(seen.has(id),false,'A practice round cannot repeat a question.');seen.add(id);
      assert.match(await card.textContent(),new RegExp(scenario.question.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
      const selected=index===0?scenario.choices.find(choice=>choice.id!==scenario.correctChoiceId):scenario.choices.find(choice=>choice.id===scenario.correctChoiceId);
      const answer=practice.locator(`[data-choice-id="${selected.id}"]`);await answer.focus();await answer.press('Enter');
      await practice.locator('[data-practice-next]').waitFor();
      assert.equal(await practice.locator('[data-choice-id]:enabled').count(),0,'Answered choices are locked to prevent double scoring.');
      for(const choice of scenario.choices)assert.equal(await practice.getByText(choice.explanation,{exact:true}).isVisible(),true,'Each choice receives its own explanation.');
      assert.equal(await practice.locator('.practice-exception').textContent(),'Когда решение изменится: '+scenario.exception,'The answer includes the condition that would change the decision.');
      if(index===0)await accessibility('practice-answer');
      await practice.locator('[data-practice-next]').click();
    }
    await practice.locator('[data-practice-retry]').waitFor();
    assert.match(await practice.textContent(),/4\s*(?:из|\/)\s*5/,'A round with one wrong answer reports four out of five.');
    assert.equal(seen.size,5);
    await accessibility('practice-result');
    await practice.locator('[data-practice-retry]').focus();await practice.locator('[data-practice-retry]').press('Enter');
    await practice.locator('[data-scenario-id]').waitFor();
    assert.equal(await practice.locator('[data-choice-id]:enabled').count(),3,'Retry starts a fresh, unanswered question.');
    assert.equal(await practice.locator('[data-practice-retry]').count(),0);
    assert.ok(apiRequests.every(request=>request.path.startsWith('/api/explore/')&&request.method==='GET'),'Public visitors never invoke auth, replay, Hermes, or model APIs.');
    assert.deepEqual(unexpected,[],'The synthetic public UI run never contacts live sources or providers.');
    assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Public home/heroes/learning/updates/trainer routes, keyboard navigation, safe/stale content, isolated feed failure, authored five-question round/results/retry, mobile/desktop layout and WCAG passed (mocked public feeds; no paid calls).');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
