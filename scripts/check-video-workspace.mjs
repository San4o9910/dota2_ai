import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
function dependency(name){try{return require(name);}catch{return require(path.join(process.env.PLAYWRIGHT_NODE_MODULES||process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES,name));}}
const playwright=dependency('playwright');
const root=path.resolve(process.env.NARMA_PORTAL_TEST_ROOT||'services/video/narma_video/static');
const server=createServer(async(request,response)=>{try{const name=request.url.startsWith('/assets/')?request.url.slice(8):'index.html';if(name.includes('..'))return response.writeHead(404).end();response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');response.end(await readFile(path.join(root,name)));}catch{response.writeHead(404).end();}});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await playwright.chromium.launch({headless:true,args:['--no-sandbox']});
const screenshotDir=process.env.NARMA_VIDEO_SCREENSHOTS;
if(screenshotDir)await mkdir(screenshotDir,{recursive:true});
const readyId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const injected='<img src=x onerror=alert(1)>';
function analysis(){return {mode:'selective_v1',overview:{focus_nickname:'SyntheticPlayer',focus_player_confirmed:true,identity_evidence:'Ник виден в интерфейсе.',hud_readable:true,candidates:[],uncertainty:[]},episodes:[
  {episode_id:'lane-1',start_seconds:90,end_seconds:135,categories:['lane','support'],selection:'coverage',question:'Как обеспечить пространство своему керри?',result:{observations:[{observation_id:'obs-1',video_seconds:100,observation:'Саппорт переместился ближе к своему керри.',confidence:'medium'}],uncertainty:['Намерение игрока по записи не подтверждается.']}},
  {episode_id:'rotation-2',start_seconds:360,end_seconds:390,categories:['rotation'],selection:'overview',question:injected,result:{observations:[{observation_id:'obs-2',video_seconds:372,observation:'Герой начал перемещение к реке.',confidence:'low'}],uncertainty:[]}}
],coaching:{status:'ready',summary:'Выбери один повторяемый момент для проверки.',points:[{title:'Перед уходом с линии',observation:injected,advice:'Проверь безопасность керри перед перемещением.',evidence_ids:['obs-1']}],next_game:[{title:'Один фокус',action:'Объясни цель своего следующего перемещения.',measure:'После матча найди момент и проверь решение.',evidence_ids:['obs-2']}]},coverage:{kind:'selected_episodes',overview_fps:0.2,detail_fps:2,reviewed_seconds:75,complete:false}};}
try{
  for(const width of [390,1440]){
    const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    let authenticated=true,bound=true,coach=true,failPart=true;
    const records=new Map([[readyId,{id:readyId,filename:'support-match.mp4',size_bytes:64,state:'ready',nickname:'SyntheticPlayer',hero:'Crystal Maiden',position:5,analysis_mode:'selective_v1',analysis_phase:'complete',duration_seconds:2400}]]);
    const parts=new Map(),writes=[],integrationRequests=[];
    await page.route('**/api/**',async route=>{const request=route.request(),url=new URL(request.url()),endpoint=url.pathname,method=request.method();let status=200,body;
      if(endpoint==='/api/session')body={authenticated,setup_required:false,user:authenticated?{email:'fixture@example.test'}:null,coaching:{mode:'platform',available:coach,personal_connect:false}};
      else if(endpoint==='/api/profile')body={profile:bound?{account_id:123,nickname:'SyntheticPlayer',match_id:'8984479726'}:null};
      else if(endpoint==='/api/replays')body={replays:[],worker_ready:true};
      else if(endpoint.startsWith('/api/integrations/')){integrationRequests.push(endpoint);status=403;body={detail:'Personal OAuth must not be called in platform mode.'};}
      else if(endpoint==='/api/auth/logout'){authenticated=false;body={authenticated:false};}
      else if(endpoint==='/api/auth/login'){authenticated=true;body={authenticated:true};}
      else if(endpoint==='/api/videos'&&method==='GET')body={videos:[...records.values()],worker_ready:true,budget_available:true,coach_available:coach,analysis_mode:'selective_v1',max_bytes:2*1024**3};
      else if(endpoint==='/api/videos'&&method==='POST'){const value=request.postDataJSON();writes.push({kind:'create',value});assert.equal(value.account_id,undefined);assert.equal(value.nickname,undefined);let job=records.get(value.id);if(!job){job={...value,state:'uploading',nickname:'SyntheticPlayer',analysis_mode:'selective_v1'};records.set(value.id,job);parts.set(value.id,[]);}body={video:job,part_bytes:16};}
      else if(endpoint.startsWith('/api/videos/')){const [,id,suffix,number]=endpoint.match(/^\/api\/videos\/([^/]+)(?:\/([^/]+))?(?:\/(\d+))?$/)||[];const job=records.get(id);if(!job){status=404;body={detail:'Видео не найдено.'};}
        else if(suffix==='parts'){writes.push({kind:'part',id,number:Number(number)});if(number==='2'&&failPart){failPart=false;status=503;body={detail:'Synthetic interrupted upload'};}else{parts.get(id).push(Number(number));body={uploaded:true,part_number:Number(number)};}}
        else if(suffix==='complete'){assert.deepEqual(parts.get(id),[1,2,3,4]);job.state='queued';body={video:job};writes.push({kind:'complete',id});}
        else if(suffix==='source')return route.fulfill({status:200,contentType:'video/mp4',body:Buffer.from('synthetic media placeholder')});
        else if(method==='DELETE'){records.delete(id);body={deleted:true};writes.push({kind:'delete',id});}
        else body={video:job,parts:parts.get(id)||[],batches:[],analysis:job.state==='ready'?analysis():null};
      }else{status=404;body={detail:`Unexpected fixture route ${endpoint}`};}
      await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto(`${origin}/videos`);await page.locator('#video-history').getByText('support-match.mp4').waitFor();
    assert.equal(await page.locator('#videos').isVisible(),true);
    await page.locator('#video-history').getByRole('button',{name:'Открыть',exact:true}).click();await page.locator('#video-report').getByRole('heading',{name:'Что изменить в следующих играх'}).waitFor();
    assert.equal(await page.locator('#video-player').getAttribute('autoplay'),null);
    assert.equal(await page.locator('#video-player').getAttribute('src'),`/api/videos/${readyId}/source`);
    assert.match(await page.locator('#video-coverage').innerText(),/выбранные эпизоды/);
    assert.equal(await page.locator('.video-episode').count(),1);
    const second=page.locator('.video-episode-rail button').nth(1);await second.focus();await page.keyboard.press('Enter');
    assert.equal(await second.getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#video-selected-episode h4').innerText(),injected);
    assert.equal(await page.locator('#video-selected-episode img,#video-report script').count(),0);
    assert.match(await page.locator('#video-selected-episode').innerText(),/Низкая уверенность/);
    await page.evaluate(()=>{const player=document.getElementById('video-player');Object.defineProperty(player,'duration',{get:()=>2400});Object.defineProperty(player,'readyState',{get:()=>1});Object.defineProperty(player,'currentTime',{get:()=>window.__videoTime??0,set:value=>{window.__videoTime=value;}});});
    await page.locator('#video-selected-episode').getByRole('button',{name:'6:12',exact:true}).click();
    assert.equal(await page.evaluate(()=>window.__videoTime),372);
    assert.equal(await page.locator('#video-player').evaluate(video=>video.paused),true);
    await page.locator('#video-hero').fill('Crystal Maiden');await page.locator('#video-position').selectOption('5');await page.locator('#video-mmr').fill('1500');await page.locator('#video-training-level').selectOption('foundations');
    const videoFile={name:'new-support.mp4',mimeType:'video/mp4',buffer:Buffer.alloc(64,7)};
    await page.locator('#video-file').setInputFiles(videoFile);await page.locator('#video-submit').click();await page.locator('#video-upload-status').getByText(/Загрузка прервалась/).waitFor();
    const created=writes.find(write=>write.kind==='create').value;assert.equal(created.hero,'Crystal Maiden');assert.equal(created.position,5);assert.equal(created.mmr,1500);assert.equal(created.training_level,'foundations');
    // Reload and reselect exactly the same File metadata: completed chunks are not resent.
    const lastModified=await page.locator('#video-file').evaluate(input=>input.files[0].lastModified);
    await page.reload();await page.locator('#video-history').getByRole('button',{name:'Продолжить',exact:true}).click();
    await page.locator('#video-file').setInputFiles({name:'different.mp4',mimeType:'video/mp4',buffer:Buffer.alloc(64,9)});await page.locator('#video-submit').click();await page.locator('#video-upload-status').getByText(/Это другой файл/).waitFor();
    assert.equal(writes.filter(write=>write.kind==='create').length,1,'A mismatched file must not resume the existing upload.');
    await page.locator('#video-file').evaluate((input,modified)=>{const transfer=new DataTransfer();transfer.items.add(new File([new Uint8Array(64).fill(7)],'new-support.mp4',{type:'video/mp4',lastModified:modified}));input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));},lastModified);
    await page.locator('#video-submit').click();await page.locator('#video-upload-status').getByText(/Запись загружена/).waitFor();
    assert.deepEqual(writes.filter(write=>write.kind==='part').map(write=>write.number),[1,2,2,3,4]);
    assert.equal(new Set(writes.filter(write=>write.kind==='create').map(write=>write.value.id)).size,1);
    await page.locator('nav [data-tab="account"]').click();await page.locator('#platform-coach').waitFor();
    assert.equal(await page.locator('#chatgpt-integration').isVisible(),false);assert.equal(integrationRequests.length,0);
    assert.match(await page.locator('#platform-coach-status').innerText(),/Личная подписка ChatGPT.*не нужна/);
    await page.goBack();await page.locator('#videos').waitFor();
    await page.locator('#video-history .history-row').filter({hasText:'support-match.mp4'}).getByRole('button',{name:'Открыть',exact:true}).click();await page.locator('#video-selected-episode').waitFor();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),`No horizontal page overflow at ${width}px`);
    await page.addScriptTag({content:dependency('axe-core').source});
    const accessibility=await page.evaluate(async()=>await window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
    assert.deepEqual(accessibility.violations.map(value=>({id:value.id,nodes:value.nodes.map(node=>node.target)})),[],`Video accessibility at ${width}px`);
    await page.evaluate(()=>document.activeElement?.blur());
    if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`video-${width}.png`),fullPage:true});
    page.once('dialog',dialog=>dialog.accept());await page.locator('#video-history .history-row').filter({hasText:'support-match.mp4'}).getByRole('button',{name:'Удалить',exact:true}).click();await page.locator('#video-result').waitFor({state:'hidden'});
    assert.equal(await page.locator('#video-player').getAttribute('src'),null);
    coach=false;await page.reload();await page.locator('#video-availability').getByText(/приостановлены/).waitFor();
    await page.locator('#video-file').setInputFiles(videoFile);assert.equal(await page.locator('#video-submit').isDisabled(),true);
    bound=false;await page.reload();await page.getByRole('button',{name:'Закрепить игрока по реплею',exact:true}).waitFor();assert.equal(await page.locator('#video-file').isDisabled(),true);
    await page.locator('#logout').click();await page.locator('#auth').waitFor();assert.equal(await page.locator('#video-player').getAttribute('src'),null);
    assert.deepEqual(errors,[]);await page.close();console.log(`Video workspace ${width}px: upload resume, scope, episode selection, timestamps, partial coverage, auth gate, deletion and unavailable states passed.`);
  }
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
