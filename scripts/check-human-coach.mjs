// CI-only browser contract: synthetic accounts/reports, all remote traffic blocked.
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
const server=createServer(async(req,res)=>{try{const pathname=new URL(req.url,'http://local').pathname;const file=pathname.startsWith('/assets/')?pathname.slice(8):'index.html';if(file.includes('..'))return res.writeHead(404).end();res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(await readFile(path.join(root,file)));}catch{res.writeHead(404).end();}});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`,browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const link='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',job='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const injected='<img src=x onerror=window.__unsafe=1>';
const report={job_id:job,match_id:'1234567890',hero:'npc_dota_hero_axe',report_sha256:'a'.repeat(64),metrics:{kills:4,deaths:2,assists:5},evidence:[{id:'e10',type:'death',time:200}],ai_summary:'Проверь поддержку перед выходом за реку.',ai_points:[{title:'Проверка карты',observation:'На 3:20 герой погиб.',reasoning:'Нужен контекст решения.',alternative:'Назови видимых союзников перед выходом.',when_to_apply:'Перед выходом',when_not_to_apply:'Срочная защита'}],reviewed_at:null};
try{
 for(const width of [390,1280]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[],writes=[];
  let authenticated=true,role='coach',tasks=[],messages=[],shares=[structuredClone(report)],consent=false,meeting={url:null,starts_at:null,revision:0},failTask=true,holdDetail=false,release,revoked=false;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>new URL(route.request().url()).origin!==origin?route.abort():route.continue());
  await page.route('**/api/**',async route=>{
   const req=route.request(),pathname=new URL(req.url()).pathname,method=req.method();let data,status=200;
   if(method!=='GET')writes.push({path:pathname,body:req.postDataJSON()});
   if(pathname==='/api/session')data={authenticated,setup_required:false,registration_available:true,user:authenticated?{email:role+'@example.test',is_platform_owner:false}:null,coaching:{mode:'platform',available:false}};
   else if(pathname==='/api/profile')data={profile:null};
   else if(pathname==='/api/replays')data={replays:[],worker_ready:true};
   else if(pathname==='/api/auth/logout'){authenticated=false;data={authenticated:false};}
   else if(pathname==='/api/human-coach')data={coach_profile:role==='coach'?{display_name:'Тренер Алексей',experience:'Синтетический профиль для проверки интерфейса.',status:'approved'}:null,relationships:revoked?[]:[{id:link,student_name:'Ученик Никита',status:'active',role,coach_name:'Тренер Алексей',coach_status:'approved',awaiting_review:tasks.some(t=>t.state==='submitted')?1:0,new_reports:1,unread:messages.length}],reports:[{id:job,match_id:'1234567890',hero:'npc_dota_hero_axe'}]};
   else if(pathname==='/api/human-coach/invitations')data={url:origin+'/human-coach#coach_invite='+'T'.repeat(43),id:'new',expires_at:'2026-10-01T00:00:00Z'};
   else if(pathname==='/api/human-coach/invitation-preview')data={coach:{display_name:'Тренер Алексей',experience:'Синтетический тренер'}};
   else if(pathname==='/api/human-coach/accept')data={id:link};
   else if(pathname===`/api/human-coach/links/${link}`){
    if(method==='DELETE'){revoked=true;data={revoked:true};}
    else{if(holdDetail){holdDetail=false;await new Promise(r=>{release=r;});}data={id:link,role,student_name:'Ученик Никита',coach_name:'Тренер Алексей',coach_status:'approved',share_profile:consent,player_profile:consent?{profile:{answers:{goal:'decisions',practice_minutes:10}},guidance:{goal:'Лучше понимать решения',dose:'10 минут практики',explanation:'Коротко'}}:null,reports:shares,tasks,messages,older_before:null,meeting};}
   }else if(pathname===`/api/human-coach/links/${link}/tasks`){
    if(failTask){failTask=false;return route.fulfill({status:503,json:{detail:'Синтетическая ошибка. Повтори отправку.'}});}
    tasks=[{...req.postDataJSON(),state:'assigned',revision:1,student_note:'',coach_feedback:'',created_at:'2026-09-19T12:00:00Z'}];data={id:tasks[0].id};
   }else if(pathname.startsWith(`/api/human-coach/links/${link}/tasks/`)){
    const body=req.postDataJSON();tasks[0]={...tasks[0],revision:tasks[0].revision+1,state:body.action==='submit'?'submitted':body.action==='complete'?'completed':'archived',...(body.action==='submit'?{student_note:body.note,report_job_id:body.job_id,report_available:!!body.job_id}:{coach_feedback:body.note})};data={saved:true};
   }else if(pathname===`/api/human-coach/links/${link}/messages`){messages.push({...req.postDataJSON(),seq:messages.length+1,author:role,created_at:'2026-09-19T12:00:00Z'});data={saved:true};}
   else if(pathname===`/api/human-coach/links/${link}/seen`)data={saved:true};
   else if(pathname===`/api/human-coach/links/${link}/meeting`){const body=req.postDataJSON();meeting={url:body.url,starts_at:body.starts_at,revision:meeting.revision+1};data={saved:true};}
   else if(pathname===`/api/human-coach/links/${link}/consent`){consent=req.postDataJSON().share_profile;data={saved:true};}
   else if(pathname.startsWith(`/api/human-coach/links/${link}/reports/`)){
    if(pathname.endsWith('/reviewed'))shares[0].reviewed_at='2026-09-19T12:00:00Z';else shares=method==='DELETE'?[]:[structuredClone(report)];data={saved:true};
   }else if(await programFixture(route))return;
   else{errors.push(`Unexpected ${method} ${pathname}`);status=404;data={detail:'Not found'};}
   await route.fulfill({status,json:data});
  });
  await page.goto(origin+'/human-coach');await page.getByRole('button',{name:'Открыть кабинет',exact:true}).waitFor();
  await page.getByRole('button',{name:'Пригласить ученика',exact:true}).click();await page.getByLabel('Личная ссылка для ученика').waitFor();
  assert.match(await page.getByLabel('Личная ссылка для ученика').inputValue(),/#coach_invite=/);
  await page.getByRole('button',{name:'Открыть кабинет',exact:true}).click();await page.getByLabel('Одно действие на тренировку').waitFor();
  await page.getByLabel('Одно действие на тренировку').fill('Пауза перед выходом');await page.getByLabel('Что сделать и когда это подходит').fill('Перед выходом проверь союзников и путь отхода.');await page.getByLabel('По каким признакам проверим результат').fill('Найди один эпизод и объясни доступную информацию.');
  await page.getByRole('button',{name:'Назначить тренировку',exact:true}).click();await page.getByText('Синтетическая ошибка. Повтори отправку.').waitFor();assert.equal(await page.getByLabel('Одно действие на тренировку').inputValue(),'Пауза перед выходом');
  await page.getByRole('button',{name:'Назначить тренировку',exact:true}).click();await page.locator('.human-focus h3').waitFor();
  const creates=writes.filter(w=>w.path.endsWith('/tasks'));assert.equal(creates[0].body.id,creates[1].body.id,'Retries keep one task identity');
  await page.locator('summary').filter({hasText:/^Матч 1234567890 · axe$/}).click();await page.getByRole('button',{name:'Обсудить',exact:true}).click();
  assert.equal(await page.getByLabel('Эпизод',{exact:true}).inputValue(),'e10');await page.getByLabel('Сообщение',{exact:true}).fill(injected);await page.getByRole('button',{name:'Отправить сообщение',exact:true}).click();await page.locator('.human-message').waitFor();assert.equal(await page.locator('.human-message img').count(),0);assert.equal(await page.evaluate(()=>window.__unsafe),undefined);
  await page.getByText('Настроить встречу',{exact:true}).click();await page.getByLabel('Ссылка на созвон (https)').fill('https://call.example/room');await page.getByLabel('Дата и время на твоём устройстве').fill('2026-10-01T12:00');await page.getByRole('button',{name:'Сохранить встречу',exact:true}).click();await page.getByRole('link',{name:'Открыть встречу · call.example'}).waitFor();
  assert.equal(await page.getByRole('link',{name:'Открыть встречу · call.example'}).getAttribute('rel'),'noopener noreferrer');
  const audit=async()=>{await page.addScriptTag({content:axe.source});const violations=await page.evaluate(async()=>{const r=await window.axe.run(document.querySelector('#human-coach'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));});assert.deepEqual(violations,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No mobile overflow');};
  await audit();
  const directory=process.env.NARMA_PORTAL_SCREENSHOTS;if(directory){await mkdir(directory,{recursive:true});await page.screenshot({path:path.join(directory,`human-coach-${width}.png`),fullPage:true,animations:'disabled'});}
  role='student';await page.reload();await page.getByRole('button',{name:'Открыть кабинет',exact:true}).click();await page.getByLabel('Что получилось, а что помешало?').waitFor();
  await page.getByText('Доступ к данным',{exact:true}).click();await page.getByRole('checkbox',{name:/Делиться анкетой/}).check();const reloaded=page.waitForResponse(r=>r.url().endsWith('/links/'+link)&&r.request().method()==='GET');await page.getByRole('button',{name:'Сохранить доступ к анкете',exact:true}).click();await reloaded;await page.waitForFunction(()=>document.querySelector('#human-coach-content').getAttribute('aria-busy')==='false');await page.getByText('Доступ к данным',{exact:true}).click();await page.getByText('Лучше понимать решения',{exact:true}).first().waitFor();
  await page.getByLabel('Разбор для проверки (необязательно)').selectOption(job);await page.getByLabel('Что получилось, а что помешало?').fill('В одном эпизоде заметил отсутствие поддержки и отошёл.');await page.getByRole('button',{name:'Отправить результат тренеру',exact:true}).click();await page.locator('.human-focus').getByText('Ждёт проверки',{exact:true}).waitFor();
  await audit();if(directory)await page.screenshot({path:path.join(directory,`human-student-${width}.png`),fullPage:true,animations:'disabled'});
  role='coach';await page.reload();await page.getByRole('button',{name:'Открыть кабинет',exact:true}).click();await page.getByLabel('Следующий шаг').selectOption('complete');await page.getByLabel('Объясни решение и следующий шаг').fill('Решение объяснено. Проверим такой же сигнал в другой ситуации.');await page.getByRole('button',{name:'Сохранить обратную связь',exact:true}).click();await page.getByText('История тренировок',{exact:true}).waitFor();assert.equal(tasks[0].state,'completed');
  // Revoke requires a second deliberate click.
  role='student';await page.reload();await page.getByRole('button',{name:'Открыть кабинет',exact:true}).click();await page.getByText('Доступ к данным',{exact:true}).click();await page.getByRole('button',{name:'Завершить связь и отозвать доступ',exact:true}).click();assert.equal(revoked,false);await page.getByRole('button',{name:'Да, завершить связь',exact:true}).click();await page.getByText(/Пока здесь никого нет/).waitFor();assert.equal(revoked,true);
  // Invitation secret is removed from the URL and still usable in memory.
  revoked=false;await page.goto(origin+'/human-coach#coach_invite='+'T'.repeat(43));await page.getByLabel('Как тренеру к тебе обращаться?').waitFor();assert.equal(new URL(page.url()).hash,'');await page.getByLabel('Как тренеру к тебе обращаться?').fill('Никита');await page.getByRole('button',{name:'Принять приглашение',exact:true}).click();await page.locator('.human-intro h2').waitFor();
  await page.getByRole('button',{name:'← Все кабинеты',exact:true}).click();await page.getByRole('button',{name:'Открыть кабинет',exact:true}).waitFor();holdDetail=true;await page.getByRole('button',{name:'Открыть кабинет',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#human-coach-content').getAttribute('aria-busy')==='true');
  // Ensure the held request has reached the fixture before logging out.
  for(let n=0;n<100&&!release;n++)await new Promise(r=>setTimeout(r,10));assert.ok(release);
  await page.locator('#logout').click();await page.locator('#auth').waitFor({state:'visible'});release();await page.evaluate(()=>new Promise(r=>setTimeout(r,100)));assert.equal(await page.locator('#human-coach-content').innerText(),'');
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('Human coach: mobile/desktop, invitation, one task, retry, anchored conversation, XSS, meeting, consent, human review, revocation, logout race and WCAG passed. Synthetic data only.');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
