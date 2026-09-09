import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

// Browser regression fixtures only. Production never imports or serves this file.
const require=createRequire(import.meta.url);
function dependency(name) {
  try { return require(name); }
  catch { const runtime=process.env.PLAYWRIGHT_NODE_MODULES||process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES; if(!runtime)throw Error(`Install ${name} to run the public experience check.`);return require(path.join(runtime,name)); }
}
const {chromium}=dependency('playwright'),axe=dependency('axe-core');
const root=path.resolve(process.env.NARMA_PORTAL_TEST_ROOT||'services/video/narma_video/static');
const publicRoutes=['/','/heroes','/builds','/learn','/practice','/updates'];
const files=new Map(publicRoutes.map(route=>[route,['explore.html','text/html']]));
for(const filename of ['explore.js','practice.js','builds.js','build-meta.js','explore.css','practice.css','builds.css','practice-scenarios.json','build-guides.json'])files.set('/assets/'+filename,[filename,filename.endsWith('.css')?'text/css':filename.endsWith('.json')?'application/json':'text/javascript']);
files.set('/assets/dota/items/hurricane_pike.png',['dota/items/hurricane_pike.png','image/png']);
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
const buildCatalog=JSON.parse(await readFile(path.join(root,'build-guides.json'),'utf8'));
const itemIcon=id=>id==='hurricane_pike'?'/assets/dota/items/hurricane_pike.png':`https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/${id}.png`;
assert.equal(buildCatalog.schema_version,'narma.build-guides.v1');
assert.ok(buildCatalog.guides.length>=2,'Build selection uses the actual authored library.');
for(const guide of buildCatalog.guides){
  assert.equal(guide.final_items?.length,6,`${guide.id}: a complete inventory has six items.`);
  assert.equal(new Set(guide.final_items.map(item=>item.id)).size,6,`${guide.id}: no accidental duplicate slots.`);
  assert.ok(guide.final_items.every(item=>/^[a-z0-9_]{1,80}$/.test(item.id)&&item.name&&item.why));
}
const {buildFreshness}=await import(pathToFileURL(path.join(root,'builds.js')));
const freshnessNow=Date.parse('2026-09-09T12:00:00Z');
const checkedGuide={verified_patch:'7.41e',checked_at:'2026-09-09'};
const currentFeed={latest_patch:{version:'7.41e'},checked_at:'2026-09-09T11:59:00Z',stale:false,errors:[]};
assert.equal(buildFreshness(checkedGuide,currentFeed,freshnessNow).state,'reviewed');
assert.equal(buildFreshness(checkedGuide,{...currentFeed,stale:true},freshnessNow).state,'unknown','A cached matching patch is not proof of currentness.');
assert.equal(buildFreshness(checkedGuide,{...currentFeed,checked_at:'2026-09-08'},freshnessNow).state,'unknown');
assert.equal(buildFreshness(checkedGuide,{...currentFeed,latest_patch:{version:'7.42'}},freshnessNow).state,'patch_changed');
assert.equal(buildFreshness({...checkedGuide,checked_at:'2026-08-01'},currentFeed,freshnessNow).state,'review_due','A long-lived patch does not keep an old guide current forever.');
assert.equal(buildFreshness(checkedGuide,undefined,freshnessNow).state,'unknown');
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
    let newsFailed=false,buildPatchOverride=null,metaStale=false;
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{if(/Content Security Policy|Refused to (?:execute|apply|load)/i.test(message.text()))errors.push(message.text());});
    page.on('dialog',async dialog=>{errors.push('Unexpected dialog: '+dialog.message());await dialog.dismiss();});
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin===origin){await route.fallback();return;}
      if(/^https:\/\/cdn\.cloudflare\.steamstatic\.com\/apps\/dota2\/(?:images\/dota_react\/(?:heroes|items)|videos\/dota_react\/heroes\/renders)\/[a-z0-9_]+\.png$/.test(url.href)||url.href===newsImage){await route.fulfill({contentType:'image/png',body:pixel});return;}
      unexpected.push(url.href);await route.abort();
    });
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url());apiRequests.push({method:request.method(),path:url.pathname,position:url.searchParams.get('position')});
      let body,status=200;
      if(request.method()!=='GET'){unexpected.push(`${request.method()} ${url.pathname}`);status=405;body={};}
      else if(url.pathname==='/api/explore/heroes')body=heroes;
      else if(url.pathname==='/api/explore/updates'){status=newsFailed?503:200;body=newsFailed?{detail:'Synthetic unavailable news feed'}:buildPatchOverride||updates;}
      else if(url.pathname==='/api/explore/builds'){
        const g=buildCatalog.guides.find(g=>g.id===url.searchParams.get('guide'));
        const evidence=Object.fromEntries((g?.final_items||[]).map(item=>[item.id,{id:item.id,matches:200,wins:120,winrate:60,average_minute:22.5}]));
        const plan=(g?.final_items||[]).map(item=>({...item,evidence:evidence[item.id]}));
        body={schema_version:'narma.build-meta.v1',guide:g?.id,rank:url.searchParams.get('rank'),status:metaStale?'stale':'ready',stale:metaStale,checked_at:new Date().toISOString(),source_url:'https://stratz.com/heroes/47',patch_status:'after_patch_release',items:evidence,plans:metaStale?{}:{popular:plan,winrate:plan}};
      }
      else if(url.pathname==='/api/explore/learning')body=catalog(Number(url.searchParams.get('position'))||null);
      else{unexpected.push(url.pathname);status=404;body={};}
      await route.fulfill({status,json:body});
    });
    await page.route('**/assets/build-guides.json',async route=>{
      const fixture=structuredClone(buildCatalog);
      for(const guide of fixture.guides)guide.source_refs.push({title:'Небезопасный источник',url:'javascript:alert(1)'},{title:'Поддельный домен',url:'https://www.dota2.com.evil.example.test/hero/axe'});
      await route.fulfill({json:fixture});
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
    const normalMotion=await page.evaluate(()=>({animation:getComputedStyle(document.body,'::before').animationName,events:getComputedStyle(document.body,'::before').pointerEvents}));
    assert.equal(normalMotion.animation,'battlefield-mist','The Dota-themed background has gentle motion.');
    assert.equal(normalMotion.events,'none','Decorative mist cannot intercept user actions.');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.deepEqual(await page.evaluate(()=>['::before','::after'].map(pseudo=>({animation:getComputedStyle(document.body,pseudo).animationName,transform:getComputedStyle(document.body,pseudo).transform}))),[{animation:'none',transform:'none'},{animation:'none',transform:'none'}],'Reduced-motion users receive a static background.');
    await page.emulateMedia({reducedMotion:'no-preference'});
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

    await open('/builds');
    await page.locator('#build-list [data-guide]').first().waitFor();
    assert.equal(await page.locator('#build-list [data-guide]').count(),buildCatalog.guides.length);
    assert.equal(await page.locator('#build-detail .build-guide').count(),1,'Only one selected build is expanded at a time.');
    const initialGuide=buildCatalog.guides[0];
    await page.locator('#build-search').fill(initialGuide.hero_name);
    await page.locator('#build-position').selectOption(String(initialGuide.position));
    const matchingGuides=buildCatalog.guides.filter(guide=>guide.position===initialGuide.position&&`${guide.hero_name} ${guide.title} ${guide.hero_slug}`.toLocaleLowerCase('ru-RU').includes(initialGuide.hero_name.toLocaleLowerCase('ru-RU')));
    assert.equal(await page.locator('#build-list [data-guide]').count(),matchingGuides.length,'Builds filter by both hero and position.');
    await page.locator(`#build-list [data-guide="${initialGuide.id}"]`).focus();await page.locator(`#build-list [data-guide="${initialGuide.id}"]`).press('Enter');
    const selectedGuide=page.locator('#build-detail .build-guide');
    assert.equal(await selectedGuide.getAttribute('data-guide-id'),initialGuide.id);
    assert.equal(await selectedGuide.locator('h2').textContent(),initialGuide.hero_name);
    const slots=selectedGuide.locator('[data-build-slot]');
    assert.equal(await slots.count(),6);
    assert.deepEqual(await slots.locator('img').evaluateAll(images=>images.map(img=>img.getAttribute('src'))),initialGuide.final_items.map(item=>itemIcon(item.id)));
    assert.equal(await selectedGuide.locator('#build-slot-detail h4').textContent(),initialGuide.final_items[0].name);
    await slots.nth(5).focus();await slots.nth(5).press('Enter');
    assert.equal(await selectedGuide.locator('[data-build-slot][aria-pressed="true"]').count(),1);
    assert.equal(await slots.nth(5).getAttribute('aria-pressed'),'true');
    assert.equal(await selectedGuide.locator('#build-slot-detail h4').count(),1);
    assert.equal(await selectedGuide.locator('#build-slot-detail h4').textContent(),initialGuide.final_items[5].name);
    const slotBoxes=await slots.evaluateAll(elements=>elements.map(e=>{const b=e.getBoundingClientRect();return {x:Math.round(b.x),y:Math.round(b.y)};}));
    assert.equal(new Set(slotBoxes.map(b=>b.x)).size,3,'Inventory keeps three columns.');
    assert.equal(new Set(slotBoxes.map(b=>b.y)).size,2,'Inventory keeps two rows.');
    buildPatchOverride={...updates,stale:false,errors:[],checked_at:new Date().toISOString(),latest_patch:{version:'7.999'}};
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForFunction(()=>document.querySelector('.build-patch')?.textContent.includes('7.999'));
    assert.equal(await selectedGuide.locator('.build-patch').getAttribute('data-freshness'),'patch_changed');
    assert.equal(await selectedGuide.locator('#build-slot-detail h4').textContent(),initialGuide.final_items[5].name,'A patch refresh preserves the selected item.');
    newsFailed=true;
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForFunction(()=>document.querySelector('.build-patch')?.dataset.freshness==='unknown');
    assert.equal(await selectedGuide.locator('#build-slot-detail h4').textContent(),initialGuide.final_items[5].name,'A feed outage preserves useful guide content.');
    newsFailed=false;buildPatchOverride=null;
    const expectedItems=[...initialGuide.starting_items,...initialGuide.core_items,...initialGuide.situational_items];
    assert.ok(expectedItems.length>0);
    assert.deepEqual(await selectedGuide.locator('.build-item h4').allTextContents(),expectedItems.map(item=>item.name));
    assert.deepEqual(await selectedGuide.locator('.build-item img').evaluateAll(images=>images.map(image=>image.getAttribute('src'))),expectedItems.map(item=>itemIcon(item.id)),'Item cards use their actual Dota inventory icon identifiers.');
    assert.equal((await selectedGuide.textContent()).includes(initialGuide.next_game_check),true,'A build ends with an action the player can check in their next match.');
    await selectedGuide.locator('.build-sources summary').click();
    const sourceLinks=await selectedGuide.locator('.build-sources a').evaluateAll(links=>links.map(link=>({href:link.href,rel:link.rel,target:link.target})));
    assert.equal(sourceLinks.length,initialGuide.source_refs.length,'Unsafe injected references are not rendered as clickable sources.');
    for(const link of sourceLinks){assert.ok(initialGuide.source_refs.some(source=>source.url===link.href));assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');}
    assert.equal(await selectedGuide.locator('script,iframe,[onerror],a[href^="javascript:"]').count(),0);
    await accessibility('builds');
    await page.reload();await page.locator('#build-detail .build-guide').waitFor();
    assert.equal(await page.locator('#build-detail .build-guide').getAttribute('data-guide-id'),initialGuide.id,'A direct build URL preserves the selected guide.');
    assert.equal(await page.locator('#build-position').inputValue(),String(initialGuide.position));
    await page.locator('#build-search').fill('not-a-real-dota-build');
    assert.equal(await page.locator('#build-list [data-guide]').count(),0);
    assert.equal(await page.locator('#build-detail .build-guide').count(),0,'An empty filter does not retain a misleading previous build.');
    await page.locator('#build-search').fill('');await page.locator('#build-position').selectOption('');
    const otherGuide=buildCatalog.guides.find(guide=>guide.id!==initialGuide.id);
    await page.locator(`#build-list [data-guide="${otherGuide.id}"]`).click();
    assert.equal(await page.locator('#build-detail .build-guide').count(),1);
    assert.equal(await page.locator('#build-detail .build-guide').getAttribute('data-guide-id'),otherGuide.id,'Choosing another build replaces the details instead of stacking all guides.');
    const pikeGuide=buildCatalog.guides.find(guide=>guide.final_items.some(item=>item.id==='hurricane_pike'));
    await page.locator(`#build-list [data-guide="${pikeGuide.id}"]`).click();
    await page.getByRole('button',{name:/^Слот [1-6]: Hurricane Pike$/}).click();
    const pikeImage=page.locator('.build-inventory img[src="/assets/dota/items/hurricane_pike.png"]');
    await pikeImage.waitFor({state:'visible'});
    await page.waitForFunction(()=>{const img=document.querySelector('.build-inventory img[src="/assets/dota/items/hurricane_pike.png"]');return img?.complete&&img.naturalWidth>0;});
    assert.equal(await page.locator('#build-slot-detail h4').textContent(),'Hurricane Pike','The bundled original loads without an external CDN request.');

    await page.locator('#build-basis').selectOption('popular');
    await page.waitForFunction(()=>document.querySelector('.build-inventory-heading p')?.textContent.includes('Подбор по частоте покупки'));
    assert.equal(await page.locator('[data-build-slot]').count(),6);
    assert.equal(await page.locator('#build-slot-detail').count(),1);
    assert.match(await page.locator('#build-slot-detail').textContent(),/60%/);
    assert.match(await page.locator('#build-slot-detail').textContent(),/200/);
    await page.locator('#build-rank').selectOption('DIVINE_IMMORTAL');
    await page.waitForFunction(()=>document.querySelector('.build-inventory-heading p')?.textContent.includes('Divine / Immortal'));
    assert.equal(new URL(page.url()).searchParams.get('rank'),'DIVINE_IMMORTAL');
    await page.locator('#build-basis').selectOption('winrate');
    assert.match(await page.locator('.build-inventory-heading p').textContent(),/размера выборки/);
    await accessibility('builds-statistics');
    metaStale=true;
    await page.locator('#build-rank').selectOption('CRUSADER_ARCHON');
    await page.waitForFunction(()=>document.querySelector('[data-meta-status]')?.textContent.includes('сохранённая статистика'));
    assert.match(await page.locator('.build-inventory-heading p').textContent(),/показан учебный план/);
    assert.equal(await page.locator('[data-build-slot]').count(),6,'A source failure keeps the authored inventory available.');
    assert.equal(await page.locator('#build-slot-detail').count(),1);
    metaStale=false;

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
    async function checkPracticeExplanations(kind,choices,choiceId){
      const chosen=choices.find(choice=>choice.id===choiceId);
      const selectedExplanation=practice.locator(`[data-practice-selected-explanation="${kind}"]`);
      const alternatives=practice.locator(`[data-practice-alternatives="${kind}"]`);
      assert.equal(await selectedExplanation.textContent(),chosen.explanation,'The explanation of the selected action stays visible.');
      assert.equal(await selectedExplanation.isVisible(),true);
      assert.equal(await alternatives.getAttribute('open'),null,'Other explanations start collapsed to keep the decision review compact.');
      for(const choice of choices.filter(choice=>choice.id!==choiceId))assert.equal(await alternatives.getByText(choice.explanation,{exact:true}).isVisible(),false);
      const summary=alternatives.locator('summary');await summary.focus();await summary.press('Enter');
      for(const choice of choices)assert.equal(await practice.getByText(choice.explanation,{exact:true}).isVisible(),true,'Every alternative remains available with its own explanation.');
      await summary.focus();await summary.press('Enter');
      assert.equal(await alternatives.getAttribute('open'),null,'Screenshots and continued practice use the compact default review.');
    }
    await practice.locator('[data-practice-start]').waitFor();
    assert.equal(await practice.locator('[data-practice-filter="position"]').inputValue(),'5','The trainer receives the role selected in learning.');
    await practice.locator('[data-practice-filter="topic"]').selectOption('lane');
    assert.equal(await practice.locator('[data-practice-filter="difficulty"]').inputValue(),'foundations');
    const shortCount=scenarios.filter(scenario=>scenario.difficulty==='foundations'&&scenario.topic==='lane'&&scenario.positions.includes(5)).length;
    assert.ok(shortCount>0&&shortCount<5);
    assert.match(await practice.locator('[data-practice-availability]').textContent(),new RegExp(`В серии будет ${shortCount}`),'A short selection advertises its actual length.');
    await practice.locator('[data-practice-reset-filters]').click();
    await practice.locator('[data-practice-start]').focus();await practice.locator('[data-practice-start]').press('Enter');
    const seen=new Set();
    for(let index=0;index<5;index++){
      const card=practice.locator('[data-scenario-id]');await card.waitFor();
      const id=await card.getAttribute('data-scenario-id'),scenario=scenarios.find(row=>row.id===id);
      assert.ok(scenario,'The trainer uses a real authored scenario.');assert.equal(seen.has(id),false,'A practice round cannot repeat a question.');seen.add(id);
      assert.equal(scenario.difficulty,'foundations','An introductory series does not mix in advanced questions.');
      assert.match(await card.textContent(),new RegExp(scenario.question.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
      const selected=index===0?scenario.choices.find(choice=>choice.id!==scenario.correctChoiceId):scenario.choices.find(choice=>choice.id===scenario.correctChoiceId);
      const answer=practice.locator(`[data-choice-id="${selected.id}"]`);await answer.focus();await answer.press('Enter');
      await practice.locator('[data-practice-next]').waitFor();
      assert.equal(await practice.locator('[data-choice-id]:enabled').count(),0,'Answered choices are locked to prevent double scoring.');
      await checkPracticeExplanations('main',scenario.choices,selected.id);
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
    for(const difficulty of ['application','advanced']){
      await open('/practice?difficulty='+difficulty);
      await practice.locator('[data-practice-start]').waitFor();
      assert.equal(await practice.locator('[data-practice-filter="difficulty"]').inputValue(),difficulty,'A direct training link preserves its selected depth.');
      await practice.locator('[data-practice-start]').click();
      const levelSeen=new Set();let missedId;
      for(let index=0;index<5;index++){
        const card=practice.locator('[data-scenario-id]');await card.waitFor();
        const id=await card.getAttribute('data-scenario-id'),scenario=scenarios.find(row=>row.id===id);
        assert.equal(scenario?.difficulty,difficulty,'Every question belongs to the chosen level.');
        assert.equal(levelSeen.has(id),false,'The selected level produces five distinct scenarios.');levelSeen.add(id);
        const chosen=index===0?scenario.choices.find(choice=>choice.id!==scenario.correctChoiceId):scenario.choices.find(choice=>choice.id===scenario.correctChoiceId);
        if(index===0)missedId=id;
        await practice.locator(`[data-choice-id="${chosen.id}"]`).click();
        await practice.locator('[data-practice-next]').waitFor();
        assert.equal(await practice.locator('[data-choice-id]:enabled').count(),0);
        await checkPracticeExplanations('main',scenario.choices,chosen.id);
        if(difficulty==='advanced'){
          assert.ok(scenario.variation,'Advanced decisions include a changed condition to evaluate.');
          await practice.locator('[data-practice-variation-reveal]').focus();await practice.locator('[data-practice-variation-reveal]').press('Enter');
          assert.equal(await practice.locator('.practice-variation-question').textContent(),scenario.variation.question);
          const variationChoice=scenario.variation.choices.find(choice=>choice.id!==scenario.variation.correctChoiceId);
          await practice.locator(`[data-variation-choice="${variationChoice.id}"]`).focus();await practice.locator(`[data-variation-choice="${variationChoice.id}"]`).press('Enter');
          await practice.locator('[data-practice-variation-feedback]').waitFor();
          assert.equal(await practice.locator('[data-variation-choice]:enabled').count(),0,'The extra decision also locks after the first answer.');
          assert.equal(await practice.locator('[data-choice-id]:enabled').count(),0,'Changing conditions cannot reopen the original answer.');
          assert.equal(await practice.locator('[data-choice-id].practice-choice--selected').getAttribute('data-choice-id'),chosen.id,'The extra decision preserves the original selection.');
          await checkPracticeExplanations('variation',scenario.variation.choices,variationChoice.id);
          if(index===0)await accessibility('practice-advanced-variation');
        }
        await practice.locator('[data-practice-next]').click();
      }
      await practice.locator('[data-practice-retry]').waitFor();
      assert.equal(levelSeen.size,5);
      assert.equal(await practice.locator('.practice-score').textContent(),'4 из 5','Extra decisions do not change the original five-question score.');
      const stored=await page.evaluate(()=>JSON.parse(localStorage.getItem('narma.practice.v1.history')));
      assert.equal(stored.version,'narma.practice.v1');
      assert.deepEqual({difficulty:stored.sessions.at(-1).difficulty,correct:stored.sessions.at(-1).correct,total:stored.sessions.at(-1).total},{difficulty,correct:4,total:5},'Completion history records the selected difficulty and primary score.');
      assert.deepEqual(stored.sessions.map(entry=>entry.difficulty),difficulty==='advanced'?['foundations','application','advanced']:['foundations','application'],'Changing level preserves earlier completed practice.');
      if(difficulty==='advanced'){
        await practice.locator('[data-practice-repeat-missed]').click();
        await practice.locator('[data-scenario-id]').waitFor();
        assert.equal(await practice.locator('[data-scenario-id]').getAttribute('data-scenario-id'),missedId,'Focused retry contains the missed decision only.');
        assert.equal(await practice.locator('[data-practice-progress]').textContent(),'Вопрос 1 из 1');
        const scenario=scenarios.find(row=>row.id===missedId);
        await practice.locator(`[data-choice-id="${scenario.correctChoiceId}"]`).click();
        await practice.locator('[data-practice-next]').click();
        await practice.locator('[data-practice-retry]').waitFor();
        assert.equal(await practice.locator('.practice-score').textContent(),'1 из 1');
        assert.equal(await practice.locator('[data-practice-repeat-missed]').count(),0,'Correct focused retry does not invent remaining mistakes.');
      }
    }
    assert.ok(apiRequests.every(request=>request.path.startsWith('/api/explore/')&&request.method==='GET'),'Public visitors never invoke auth, replay, Hermes, or model APIs.');
    assert.deepEqual(unexpected,[],'The synthetic public UI run never contacts live sources or providers.');
    assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Public home/heroes/builds/learning/updates/trainer routes; selected item guides and safe sources; three practice levels with locked follow-up answers, history and focused retry; reduced motion, keyboard navigation, safe/stale feeds, mobile/desktop layout and WCAG passed (mocked public feeds; no paid calls).');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
