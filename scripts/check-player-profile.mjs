// Synthetic UI-only coverage. Never contacts providers or production accounts.
import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';
import {programFixture} from './program-fixtures.mjs';
const require=createRequire(import.meta.url);
const dependency=name=>{try{return require(name);}catch{return require(path.join(process.env.PLAYWRIGHT_NODE_MODULES,name));}};
const {chromium}=dependency('playwright'),axe=dependency('axe-core');
const root=path.resolve('services/video/narma_video/static');
const server=createServer(async(req,res)=>{
 try{const pathname=new URL(req.url,'http://local').pathname;const file=pathname.startsWith('/assets/')?pathname.slice(8):'index.html';if(file.includes('..'))return res.writeHead(404).end();
  const body=await readFile(path.join(root,file));res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(body);
 }catch{res.writeHead(404).end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`,browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const empty=()=>({revision:0,state:'not_started',last_step:0,answers:{},questionnaire_version:'narma.player-profile.v1'});
function guidance(profile){if(!Object.keys(profile.answers).length)return null;return {revision:profile.revision,goal:'Синтетическая цель',title:'Проверка решения',action:'Назови цель и запасной вариант.',dose:profile.answers.practice_minutes===0?'Практика только внутри матча.':`До ${profile.answers.practice_minutes||5} минут практики.`,preparation:'Начни с одного эпизода.',explanation:'Короткое объяснение.',tone:'Спокойно',basis:['Основано на твоих ответах.'],limitation:'Это самооценка.',exception:'Учитывай новую информацию.',measurement:'Проверь один эпизод.'};}
try{
 for(const width of [390,1280]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],writes=[];
  let authenticated=false,profile=empty(),failNext=false,hold=false,release;
  await page.addInitScript(()=>{window.__profileMotion=[];const animate=Element.prototype.animate;Element.prototype.animate=function(frames,options){window.__profileMotion.push({duration:options?.duration,tag:this.tagName,frames});return animate.call(this,frames,options);};});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{if(new URL(route.request().url()).origin!==origin)return route.abort();return route.continue();});
  await page.route('**/api/**',async route=>{
   const endpoint=new URL(route.request().url()).pathname,method=route.request().method();let data,status=200;
   if(endpoint==='/api/session')data={authenticated,setup_required:false,registration_available:true,user:authenticated?{email:'synthetic@example.test',is_platform_owner:false}:null,coaching:{mode:'platform',available:false}};
   else if(endpoint==='/api/auth/register'){authenticated=true;data={authenticated:true};}
   else if(endpoint==='/api/auth/logout'){authenticated=false;data={authenticated:false};}
   else if(endpoint==='/api/player-profile'){
    if(method==='PUT'){
     const body=route.request().postDataJSON();writes.push(body);
     if(hold){hold=false;await new Promise(resolve=>{release=resolve;});}
     if(failNext){failNext=false;return route.fulfill({status:503,json:{detail:'Синтетическая временная ошибка'}});}
     if(body.expected_revision!==profile.revision)return route.fulfill({status:409,json:{detail:'Профиль изменён в другой вкладке.'}});
     profile={...profile,revision:profile.revision+1,answers:{...profile.answers,...body.answers},last_step:body.last_step,state:body.action==='skip'?'skipped':body.action==='finish'||profile.state==='ready'?'ready':'partial'};
    }else if(method==='DELETE')profile={...empty(),revision:profile.revision+1,state:'skipped'};
    data={profile,guidance:guidance(profile)};
   }else if(endpoint==='/api/program')data={player_profile:{state:profile.state,revision:profile.revision},guidance:guidance(profile),focus:null,choices:[],review:null,check_candidates:[],stage:'upload',jobs:[],latest_report:null};
   else if(endpoint==='/api/profile')data={profile:null};
   else if(endpoint==='/api/replays')data={replays:[],worker_ready:true};
   else if(await programFixture(route))return;
   else {errors.push(`Unexpected endpoint ${method} ${endpoint}`);status=404;data={detail:'Not found'};}
   await route.fulfill({status,json:data});
  });
  await page.goto(origin+'/register');await page.locator('#auth').waitFor({state:'visible'});
  await page.locator('#email').fill('synthetic@example.test');await page.locator('#password').fill('Synthetic passphrase 2026');await page.locator('#password-confirmation').fill('Synthetic passphrase 2026');await page.locator('#auth-submit').click();
  await page.waitForURL('**/player-profile');await page.locator('.profile-form input[name="goal"]').first().waitFor();
  const choose=async(key,value)=>{await page.locator(`.profile-form input[name="${key}"][value="${value}"]`).check();};
  const next=async()=>{const response=page.waitForResponse(r=>r.url().endsWith('/api/player-profile')&&r.request().method()==='PUT');await page.locator('.profile-form button[type="submit"]').click();await response;};
  await choose('goal','custom');await page.locator('#profile-goal_note').fill('<img src=x onerror=window.__unsafe=1>');await next();
  await choose('position','4');await page.locator('#profile-heroes').fill('Lion, Rubick');await next();
  await choose('rank_band','unknown');await next();
  await page.reload();await page.locator('.profile-form input[name="experience"]').first().waitFor();assert.equal(profile.last_step,3);
  await choose('experience','returning');failNext=true;await next();await page.getByText(/Ответы на экране сохранены/).waitFor();assert.equal(await page.locator('input[value="returning"]').isChecked(),true);await next();
  await choose('matches_per_week','rare');await next();await choose('practice_minutes','10');await next();
  await choose('explanation','short');await choose('tone','direct');await next();await page.locator('.profile-summary').waitFor();
  assert.equal(profile.state,'ready');assert.equal(profile.answers.heroes.length,2);
  assert.match(await page.locator('.profile-guidance').innerText(),/10 минут/);
  await page.getByText('Все сохранённые ответы',{exact:true}).click();assert.equal(await page.locator('.profile-answers img,.profile-answers script').count(),0);assert.equal(await page.evaluate(()=>window.__unsafe),undefined);
  await page.getByRole('button',{name:'К моей тренировке',exact:true}).click();await page.waitForURL('**/training');await page.locator('#program-content .profile-guidance').waitFor();
  assert.match(await page.locator('#program-content').innerText(),/10 минут/);
  await page.locator('nav [data-tab="player-profile"]').click();await page.getByRole('button',{name:'Уточнить привычки и решения',exact:true}).click();
  for(const [key,value] of [['learning_obstacle','noticing'],['after_losses','skip'],['communication','solo'],['focus_skill','vision'],['feedback_format','checklist']]){await choose(key,value);await next();}
  for(let i=0;i<3;i++){await choose('scenario','unknown');await page.locator('#profile-reason').fill('Нужно проверить доступную информацию.');await next();}
  await page.locator('.profile-summary').waitFor();assert.equal(Object.keys(profile.answers.scenarios).length,3);
  await page.getByRole('button',{name:'Изменить основные ответы',exact:true}).click();
  await page.addScriptTag({content:axe.source});
  const accessibility=await page.evaluate(async()=>{const result=await window.axe.run(document.querySelector('#player-profile'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));});assert.deepEqual(accessibility,[]);
  assert.ok(await page.evaluate(()=>window.__profileMotion.some(x=>x.duration===1050&&x.frames.some(f=>f.clipPath))),'Text has a visible sweep, not an imperceptible opacity change.');
  assert.ok(await page.evaluate(()=>window.__profileMotion.some(x=>x.duration===480&&x.frames.some(f=>f.transform==='scale(.955)'))),'Buttons provide press feedback.');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No mobile horizontal overflow.');
  const screenshots=process.env.NARMA_PORTAL_SCREENSHOTS;if(screenshots){await mkdir(screenshots,{recursive:true});await page.locator('#profile-goal_note').fill('Лучше понимать решения в матче.');await page.screenshot({path:path.join(screenshots,`player-profile-${width}.png`),fullPage:true,animations:'disabled'});}
  await page.emulateMedia({reducedMotion:'reduce'});const count=await page.evaluate(()=>window.__profileMotion.length);await choose('goal','decisions');assert.equal(await page.evaluate(()=>window.__profileMotion.length),count);
  // The browser keeps the draft on a conflict; only an explicit reload replaces it.
  profile={...profile,revision:profile.revision+1};await next();await page.getByText(/Профиль изменён в другой вкладке/).waitFor();assert.equal(await page.locator('input[value="decisions"]').isChecked(),true);
  await page.getByRole('button',{name:'Перечитать сохранённый профиль',exact:true}).click();await page.locator('.profile-summary').waitFor();
  await page.getByRole('button',{name:'Сбросить ответы анкеты',exact:true}).click();await page.getByRole('button',{name:'Да, сбросить ответы',exact:true}).click();await page.getByRole('button',{name:'Начать настройку',exact:true}).waitFor();assert.deepEqual(profile.answers,{});
  await page.getByRole('button',{name:'Начать настройку',exact:true}).click();await choose('goal','consistency');hold=true;
  const delayed=page.waitForResponse(r=>r.url().endsWith('/api/player-profile')&&r.request().method()==='PUT');
  await page.locator('.profile-form button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('.profile-form button[type="submit"]').disabled);
  await page.locator('#logout').click();await page.locator('#auth').waitFor({state:'visible'});release();await (await delayed).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('#player-profile-content').innerText(),'','A delayed answer cannot repopulate a signed-out profile.');
  assert.deepEqual(errors,[]);assert.ok(writes.every(w=>!Object.hasOwn(w,'owner_id')));await page.close();
 }
 console.log('Player onboarding: signup, seven steps, resume, retry/conflict, deeper questions, practice context, reset/logout race, mobile/desktop, visible motion/reduced motion and WCAG passed. Synthetic APIs; no paid calls.');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
