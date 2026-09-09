import { roleGuidance } from './role-guidance.js';
const $ = id => document.getElementById(id);
const state = {user:null, profile:null, setup:false, token:new URLSearchParams(location.hash.slice(1)).get('token'), selected:null, detail:null, busy:false, uploadId:null, time:0, evidence:new Map(), graphs:[], pool:null, poolRequest:0, showArchived:false, poolDrafts:new Map(), poolJournalOpen:new Set(), poolSignature:'', poolVisible:20, learning:null,reportLearning:null,learningRequest:0,reportLearningRequest:0,learningStage:null,learningExercise:null,reportExercise:null,learningDrafts:new Map(),learningMatches:new Map(),learningCanonicalTrail:new Set(),chatgpt:null,chatgptRequest:0,chatgptController:null,chatgptTimer:null,chatgptClock:null};
if (state.token) history.replaceState(null, '', location.pathname);
const labels = {uploading:'Загружается', queued:'В очереди', processing:'Разбираем матч', ready:'Разбор готов', failed:'Разбор остановлен'};
const failures = {
  REPLAY_NATIVE_UNAVAILABLE:'Не запустился серверный обработчик реплеев. Файл сохранён; повторно загружать его не нужно.',
  REPLAY_RESOURCE_LIMIT:'Обработчику не хватило ресурсов. Файл сохранён на сервере.',
  REPLAY_STORAGE_FULL:'На сервере не хватает места для обработки. Исходный реплей сохранён.',
  REPLAY_STORAGE_ACCESS:'Обработчик не смог открыть служебные файлы. Исходный реплей сохранён.',
  REPLAY_PARSE_FAILED:'Не удалось прочитать события матча. Попробуй повторно скачать реплей в Dota 2.',
  REPLAY_WORKER_INTERRUPTED:'Обработчик несколько раз прервался. Сохрани исходный файл и повтори разбор позже.',
  REPLAY_INCOMPLETE:'Файл реплея не прочитан до конца. Выбери полный .dem из Dota 2.',
  REPLAY_SOURCE_CHANGED:'Проверка целостности реплея не прошла. Загрузи файл заново.',
  REPLAY_IDENTITY_MISMATCH:'Данные игрока в матче не совпали с закреплённым Steam ID.',
  REPLAY_PARSE_TIMEOUT:'Разбор реплея занял слишком много времени. Повтори попытку позже.',
  REPLAY_UPLOAD_EXPIRED:'Загрузка не была завершена вовремя. Выбери файл и загрузи его заново.'
};
const eventLabels = {death:'Смерть',kill:'Убийство',assist:'Помощь',purchase:'Покупка',item_used:'Применение предмета',item_observed:'Предмет в инвентаре',buyback:'Выкуп',respawn:'Возвращение',reincarnation:'Реинкарнация',tower:'Башня',ward_destroyed:'Сломанный вард',ward_item_used:'Применение предмета с вардами'};
function notice(message='') { $('notice').textContent=message; $('notice').hidden=!message; }
function node(tag, text, className) { const element=document.createElement(tag); if(text!==undefined) element.textContent=String(text); if(className) element.className=className; return element; }
function num(value) { return typeof value==='number' && Number.isFinite(value) ? Math.round(value).toLocaleString('ru-RU') : '—'; }
function stamp(seconds) { if(!Number.isFinite(seconds)) return '—'; const value=Math.floor(Math.abs(seconds)); return `${seconds<0?'−':''}${Math.floor(value/60)}:${String(value%60).padStart(2,'0')}`; }
function heroName(value) { const names={npc_dota_hero_necrolyte:'Necrophos',npc_dota_hero_nevermore:'Shadow Fiend',npc_dota_hero_skeleton_king:'Wraith King',npc_dota_hero_windrunner:'Windranger',npc_dota_hero_zuus:'Zeus',npc_dota_hero_obsidian_destroyer:'Outworld Destroyer',npc_dota_hero_furion:'Nature’s Prophet'}; return names[value] ?? String(value??'').replace(/^npc_dota_hero_/,'').split('_').map(word=>word.charAt(0).toUpperCase()+word.slice(1)).join(' '); }
async function api(path, method='GET', body) {
  const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',headers:body!==undefined?{'Content-Type':'application/json'}:{},body:body!==undefined?JSON.stringify(body):undefined});
  let data; try { data=await response.json(); } catch { throw Error('Сервер вернул неполный ответ. Попробуй ещё раз.'); }
  if(!response.ok) { if(response.status===401 && state.user) { state.user=null; await session(); } throw Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос.'); }
  return data;
}
const tabPaths={review:'/replays','hero-pool':'/hero-pool',learning:'/my-learning',player:'/player',account:'/account'};
function pathTab() {return Object.keys(tabPaths).find(tab=>tabPaths[tab]===location.pathname)??'review';}
function switchTab(tab,{historyMode='push'}={}) {
  if(!Object.hasOwn(tabPaths,tab)||!$(tab)) return;
  if(historyMode==='push'&&location.pathname!==tabPaths[tab])history.pushState({tab},'',tabPaths[tab]);
  for(const section of document.querySelectorAll('.tab-section')) section.hidden=section.id!==tab;
  for(const button of document.querySelectorAll('nav [data-tab]')) { if(button.dataset.tab===tab) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current'); }
  // Keep the current report and unsaved forms in the DOM when changing sections.
  if(tab==='hero-pool'&&state.user&&(!state.pool||state.poolDirty)) void loadPool();
  if(tab==='learning'&&state.user) void loadLearning({preserveView:true});
  stopChatgptPolling();
  if(tab==='account'&&state.user) void loadChatgpt();
}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',event=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();switchTab(button.dataset.tab);}));
window.addEventListener('popstate',()=>switchTab(pathTab(),{historyMode:'none'}));
switchTab(pathTab(),{historyMode:'none'});
function buttons() {
  $('replay-submit').disabled=state.busy || !$('replay-file').files[0] || (!state.profile && !$('nickname').value.trim());
  $('replay-file').disabled=state.busy; $('nickname').disabled=state.busy;
  for(const id of ['replay-position','replay-mmr','replay-training-level']) $(id).disabled=state.busy;
}
function profileView() {
  const profile=state.profile;
  $('bound-nickname').textContent=profile?profile.nickname:'Первый матч';
  $('nickname-field').hidden=!!profile; $('nickname').required=!profile;
  const summary=$('player-summary'); summary.replaceChildren();
  if(profile) { const box=node('div',undefined,'player-card'); box.append(node('strong',profile.nickname),node('p',`Steam ID: ${profile.account_id} · Матч: ${profile.match_id}`,'help')); summary.append(box); }
  else summary.append(node('p','Загрузи первый матч и укажи свой ник. Игрок закрепится автоматически после чтения реплея.','muted'));
  buttons();
}
async function session() {
  const data=await api('/api/session'); state.setup=data.setup_required===true; state.user=data.authenticated?data.user:null;
  $('loading').hidden=true; $('workspace').hidden=!state.user; $('auth').hidden=!!state.user; $('logout').hidden=!state.user;
  if(!state.user) {
    stopChatgptPolling();state.chatgpt=null;$('chatgpt-content').replaceChildren();$('chatgpt-status').textContent='';
    state.pool=null; state.poolRequest++; state.poolDrafts.clear(); state.poolJournalOpen.clear(); state.poolSignature=''; state.poolVisible=20;
    state.profile=null; state.selected=null; state.detail=null; state.showArchived=false; $('result').hidden=true; $('pool-content').hidden=true;
    state.learning=null;state.reportLearning=null;state.learningRequest++;state.reportLearningRequest++;state.learningDrafts.clear();state.learningMatches.clear();state.learningStage=null;state.learningExercise=null;state.reportExercise=null;$('report-learning').replaceChildren();$('pool-learning').replaceChildren();
    $('pool-hero').replaceChildren(new Option('Все герои','')); $('pool-position').value=''; $('pool-period').value='all'; $('pool-favorites-only').checked=false; $('pool-refresh').disabled=false;
    if($('learning-hero'))$('learning-hero').replaceChildren(new Option('Все герои',''));if($('learning-position'))$('learning-position').value='';
    state.learningScope=null;state.learningSignature=null;state.poolDirty=false;
    $('pool-status').textContent=''; $('pool-content').setAttribute('aria-busy','false');
    $('auth-title').textContent=state.setup?'Создай свой аккаунт':'Вход в NARMA VISION';
    $('auth-copy').textContent=state.setup?'Первый вход владельца платформы. Придумай отдельный пароль для NARMA VISION.':'Войди, чтобы загрузить реплей и посмотреть разбор своего матча.';
    $('auth-submit').textContent=state.setup?'Создать аккаунт':'Войти'; $('auth-submit').disabled=state.setup&&!state.token;
    $('setup-help').hidden=!state.setup||!!state.token; $('password-help').hidden=!state.setup; $('password').autocomplete=state.setup?'new-password':'current-password'; return;
  }
  $('account-email').textContent=state.user.email;
  if($('learning')&&!$('learning').hidden)void loadLearning();
  if(!$('account').hidden)void loadChatgpt();
  state.profile=(await api('/api/profile')).profile; profileView(); await refresh(); if(!$('hero-pool').hidden&&!state.pool) await loadPool();
}
$('auth-form').addEventListener('submit',async event=>{
  event.preventDefault(); notice(); const button=$('auth-submit'); button.disabled=true;
  try { await api(state.setup?'/api/auth/setup':'/api/auth/login','POST',{email:$('email').value.trim(),password:$('password').value,...(state.setup?{token:state.token}:{})}); state.token=null; $('password').value=''; await session(); }
  catch(error) { notice(error.message); } finally { button.disabled=state.setup&&!state.token; }
});
$('logout').addEventListener('click',async()=>{stopChatgptPolling();try { await api('/api/auth/logout','POST',{}); location.reload(); } catch(error) { notice(error.message);if(!$('account').hidden)void loadChatgpt(); } });
$('password-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=event.target.querySelector('button'); button.disabled=true;
  try { await api('/api/auth/password','POST',{current_password:$('current-password').value,new_password:$('new-password').value}); $('current-password').value=''; $('new-password').value=''; state.user=null; await session(); notice('Пароль изменён. Войди с новым паролем.'); }
  catch(error) { notice(error.message); } finally { button.disabled=false; }
});

// OAuth credentials remain on the server. The browser receives only the short-lived login code.
function stopChatgptPolling() {
  state.chatgptRequest++;clearTimeout(state.chatgptTimer);clearInterval(state.chatgptClock);
  state.chatgptTimer=null;state.chatgptClock=null;state.chatgptController?.abort();state.chatgptController=null;
  $('chatgpt-integration').setAttribute('aria-busy','false');
}
function chatgptVisible() {return !!state.user&&!$('account').hidden&&!document.hidden;}
function chatgptDevice(data) {
  const pending=data?.pending;
  if(data?.status!=='pending'||!pending||pending.verification_url!=='https://auth.openai.com/codex/device'||typeof pending.user_code!=='string'||!/^[A-Za-z0-9 -]{4,32}$/.test(pending.user_code)||typeof data.auth_generation!=='string')return null;
  const expires=Date.parse(pending.expires_at);if(!Number.isFinite(expires))return null;
  return {...pending,expires};
}
function chatgptAction(label,run,className='secondary') {const button=node('button',label,className);button.type='button';button.addEventListener('click',()=>void run());return button;}
function renderChatgpt(message='') {
  const host=$('chatgpt-content'),data=state.chatgpt??{},status=$('chatgpt-status');host.replaceChildren();
  const device=chatgptDevice(data),expired=data.status==='expired'||(device&&device.expires<=Date.now());
  const labels={disconnected:'ChatGPT ещё не подключён',pending:'Ожидаем вход на странице OpenAI',connected:'ChatGPT подключён',expired:'Время для входа истекло',reconnect_required:'Нужно войти в ChatGPT заново',unavailable:'Подключение сейчас недоступно'};
  status.textContent=message||(expired?labels.expired:data.status==='pending'&&!device?labels.unavailable:labels[data.status]??labels.unavailable);
  const errorHints={CHATGPT_AUTH_EXPIRED:'Время для входа закончилось. Получи новый код.',CHATGPT_AUTH_DECRYPT:'Подключение нужно обновить. Войди в ChatGPT заново.',CHATGPT_AUTH_RATE_LIMIT:'Слишком много попыток входа. Подожди немного и проверь подключение снова.',CHATGPT_AUTH_REJECTED:'Вход не подтверждён. Проверь разрешение на вход по коду в аккаунте ChatGPT и попробуй ещё раз.',CHATGPT_AUTH_RESPONSE:'OpenAI не подтвердил подключение. Попробуй снова позже.',CHATGPT_AUTH_UNAVAILABLE:'Сейчас не удаётся связаться с OpenAI. Попробуй снова позже.'};
  if(errorHints[data.last_error_code])host.append(node('p',errorHints[data.last_error_code],'help'));
  if(data.status==='connected') {
    host.append(node('p','Вход подтверждён. Готовность тренерского разбора проверяется отдельно.','help'));
    if(data.last_error_code==='CHATGPT_DAILY_LIMIT')host.append(node('p','Дневной лимит тренерских запросов достигнут. Подключение сохранено.','help'));
    if(data.quota_paused===true||data.last_error_code==='CHATGPT_QUOTA'){
      const until=Date.parse(data.paused_until),known=Number.isFinite(until)&&until>Date.now();
      host.append(node('p',known?`Лимит ChatGPT исчерпан. Пауза до ${new Date(until).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}.`:'Лимит ChatGPT исчерпан. Время восстановления пока неизвестно. После восстановления доступа войди заново.','help'));
      if(!known&&data.can_connect===true)host.append(chatgptAction('Войти в ChatGPT заново',reconnectChatgpt));
    }
    host.append(chatgptAction('Отключить ChatGPT',()=>loadChatgpt('DELETE',{}),'quiet'));
  } else if(device&&!expired) {
    const steps=node('ol',undefined,'chatgpt-steps');steps.append(node('li','Скопируй код и открой OpenAI.'),node('li','Войди в свой аккаунт ChatGPT и подтверди подключение.'),node('li','Вернись сюда — статус обновится автоматически.'));host.append(steps);
    const label=node('label','Код для входа в OpenAI'),code=node('input');code.id='chatgpt-user-code';code.value=device.user_code;code.readOnly=true;code.autocomplete='off';code.spellcheck=false;label.htmlFor=code.id;code.addEventListener('click',()=>code.select());host.append(label,code);
    const actions=node('div',undefined,'chatgpt-actions'),link=node('a','Открыть OpenAI','secondary chatgpt-openai');link.href=device.verification_url;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';actions.append(link);
    if(navigator.clipboard?.writeText)actions.append(chatgptAction('Скопировать код',async()=>{try{await navigator.clipboard.writeText(device.user_code);status.textContent='Код скопирован. Открой OpenAI и введи его для входа.';}catch{code.focus();code.select();status.textContent='Выделенный код можно скопировать вручную.';}},'quiet'));
    host.append(actions,node('p','', 'help chatgpt-expiry'),chatgptAction('Отменить подключение',()=>loadChatgpt('DELETE',{}),'quiet'));
    const tick=()=>{const remaining=Math.max(0,Math.ceil((device.expires-Date.now())/1000)),element=host.querySelector('.chatgpt-expiry');if(element)element.textContent=`Код действует ещё ${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}.`;if(!remaining){stopChatgptPolling();state.chatgpt={...data,status:'expired',pending:null};renderChatgpt();}};
    tick();if(device.expires>Date.now())state.chatgptClock=setInterval(tick,1000);
  } else {
    if(data.can_connect===true)host.append(chatgptAction(expired||data.status==='reconnect_required'?'Войти в ChatGPT заново':'Подключить ChatGPT',()=>loadChatgpt('POST',{},'/connect')));
    else host.append(node('p',data.configured===true?'Подключение пока недоступно для этого аккаунта. Разборы и твоя практика сохранены.':'Настройка подключения на сервере ещё не завершена. Разборы и твоя практика сохранены.','help'));
    if(data.status==='unavailable'||(data.status==='pending'&&!device))host.append(chatgptAction('Проверить снова',()=>loadChatgpt(),'quiet'));
  }
}
async function loadChatgpt(method='GET',body,suffix='') {
  if(!chatgptVisible())return;stopChatgptPolling();const request=state.chatgptRequest,controller=new AbortController();state.chatgptController=controller;
  $('chatgpt-integration').setAttribute('aria-busy','true');for(const button of $('chatgpt-content').querySelectorAll('button'))button.disabled=true;
  if(method==='POST'&&suffix==='/connect')$('chatgpt-status').textContent='Готовим вход через OpenAI…';
  try {
    const response=await fetch(`/api/integrations/chatgpt${suffix}`,{method,credentials:'same-origin',cache:'no-store',signal:controller.signal,headers:body!==undefined?{'Content-Type':'application/json'}:{},body:body!==undefined?JSON.stringify(body):undefined});
    const errorCode=response.headers.get('X-Narma-Error');
    if(response.status===401&&errorCode==='PORTAL_SIGN_IN'){state.user=null;await session();return;}
    if(!response.ok)throw Object.assign(Error('unavailable'),{code:errorCode});
    const data=await response.json();if(request!==state.chatgptRequest||!chatgptVisible())return;
    state.chatgpt=data;renderChatgpt();
    const device=chatgptDevice(data);if(device&&device.expires>Date.now()){
      const delay=Math.max(5,Math.min(60,Number(device.poll_after_seconds)||Number(device.poll_interval_seconds)||5));
      state.chatgptTimer=setTimeout(()=>void loadChatgpt('POST',{auth_generation:data.auth_generation},'/poll'),delay*1000);
    }
    return data;
  }catch(error){if(error.name==='AbortError'||request!==state.chatgptRequest)return;state.chatgpt={...state.chatgpt,status:'unavailable',pending:null,last_error_code:error.code??null};renderChatgpt('Не удалось проверить подключение. Попробуй ещё раз.');}
  finally {if(request===state.chatgptRequest){state.chatgptController=null;$('chatgpt-integration').setAttribute('aria-busy','false');}}
}
async function reconnectChatgpt() {
  const disconnected=await loadChatgpt('DELETE',{});
  if(disconnected?.status==='disconnected'&&chatgptVisible())await loadChatgpt('POST',{},'/connect');
}
window.addEventListener('pagehide',stopChatgptPolling);
window.addEventListener('pageshow',event=>{if(event.persisted&&chatgptVisible())void loadChatgpt();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopChatgptPolling();else if(chatgptVisible())void loadChatgpt();});

$('replay-file').addEventListener('change',()=>{ state.uploadId=null; buttons(); });
$('nickname').addEventListener('input',()=>{ state.uploadId=null; buttons(); });
for(const id of ['replay-position','replay-mmr','replay-training-level']) $(id).addEventListener('input',()=>{ state.uploadId=null; buttons(); });
$('replay-form').addEventListener('submit',async event=>{
  event.preventDefault(); const file=$('replay-file').files[0]; if(!file||state.busy) return;
  if(!/\.dem$/i.test(file.name)||file.size>512*1024**2||file.size<20) return notice('Выбери полный файл .dem размером до 512 МБ.');
  const position=$('replay-position').value?Number($('replay-position').value):null;
  const mmr=$('replay-mmr').value.trim()===''?null:Number($('replay-mmr').value);
  const training_level=$('replay-training-level').value||null;
  if(mmr!==null&&(!Number.isInteger(mmr)||mmr<0||mmr>20000)) return notice('Укажи целый MMR от 0 до 20 000 или оставь поле пустым.');
  state.busy=true; buttons(); notice(); $('replay-progress').hidden=false; $('upload-status').textContent='Начинаем загрузку реплея…';
  try {
    state.uploadId??=crypto.randomUUID(); const id=state.uploadId;
    const init=await api('/api/replays','POST',{id,filename:file.name,size_bytes:file.size,position,mmr,training_level,...(!state.profile?{nickname:$('nickname').value.trim()}:{})});
    if(init.replay.state==='uploading') {
      const status=await api('/api/replays/'+id), completed=new Set(status.parts);
      for(let offset=0;offset<file.size;offset+=init.part_bytes) {
        const part=Math.floor(offset/init.part_bytes)+1;
        if(!completed.has(part)) {
          const response=await fetch(`/api/replays/${id}/parts/${part}`,{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/octet-stream'},body:file.slice(offset,offset+init.part_bytes)});
          if(!response.ok) { const error=await response.json(); throw Error(typeof error.detail==='string'?error.detail:'Не удалось загрузить часть реплея. Нажми загрузку ещё раз, чтобы продолжить.'); }
        }
        const progress=Math.round(Math.min(file.size,offset+init.part_bytes)/file.size*100);
        $('replay-progress').value=progress; $('upload-status').textContent=`Загружаем реплей · ${progress}%`;
      }
      $('upload-status').textContent='Проверяем файл и определяем игрока…'; await api('/api/replays/'+id+'/complete','POST',{});
    }
    state.uploadId=null; $('replay-file').value=''; $('upload-status').textContent='Матч в очереди. Разбор продолжится, даже если закрыть страницу.';
    state.profile=(await api('/api/profile')).profile; profileView(); await refresh(); await openReplay(id,true);
  } catch(error) { $('upload-status').textContent=error.message; notice(error.message); }
  finally { state.busy=false; buttons(); }
});
async function refresh() {
  if(!state.user) return;
  const data=await api('/api/replays'); $('worker-status').textContent=data.worker_ready?'Обработчик реплеев работает':'Ожидаем обработчик реплеев';
  const signature=data.replays.map(item=>`${item.id}:${item.state}:${item.updated_at??''}`).sort().join('|');
  if(signature!==state.poolSignature) { state.poolSignature=signature; state.poolDirty=true; if(!$('hero-pool').hidden) void loadPool(); }
  const history=$('history'); history.replaceChildren();
  if(!data.replays.length) history.append(node('p','Загрузи реплей — здесь появится твой первый матч.','empty'));
  for(const item of data.replays) {
    const row=node('article',undefined,'history-row'), info=node('div'), actions=node('div',undefined,'history-actions');
    info.append(node('p',item.match_id?`Матч ${item.match_id}`:item.filename,'history-name'),node('p',`${labels[item.state]??item.state} · ${item.nickname}`,'history-meta'));
    if(item.state==='processing') info.append(node('p',`${num(item.progress)}%`,'history-meta'));
    const open=node('button','Открыть'); open.addEventListener('click',()=>void openReplay(item.id,true).catch(error=>notice(error.message)));
    const remove=node('button','Удалить','delete'); remove.disabled=state.busy;
    remove.addEventListener('click',async()=>{ if(!confirm('Удалить этот реплей и его разбор?')) return; try { await api('/api/replays/'+item.id,'DELETE'); state.poolDrafts.delete(String(item.match_id)); state.poolJournalOpen.delete(String(item.match_id)); if(state.selected===item.id) { state.selected=null; state.detail=null; $('result').hidden=true; } await refresh(); } catch(error) { notice(error.message); } });
    actions.append(open);
    if(item.state==='ready'&&item.source_retained!==false) {
      const free=node('button','Освободить место'); free.addEventListener('click',async()=>{ if(!confirm('Удалить исходный .dem? Разбор и статистика в пуле героев сохранятся. Повторный разбор потребует загрузки файла.')) return; free.disabled=true; try { await api('/api/replays/'+item.id+'/source','DELETE'); await refresh(); notice('Исходный реплей удалён. Разбор и статистика сохранены.'); } catch(error) { notice(error.message); free.disabled=false; } }); actions.append(free);
    }
    actions.append(remove); row.append(info,actions); history.append(row);
  }
}
function svgNode(tag, attributes) { const element=document.createElementNS('http://www.w3.org/2000/svg',tag); for(const [key,value] of Object.entries(attributes)) element.setAttribute(key,String(value)); return element; }
const sourceColors=['#dcc071','#9fc5a8','#91b8d8','#c1a2d5','#d49b8a','#b7bdad','#d5bba3'];
function finite(value) { return typeof value==='number' && Number.isFinite(value); }
function itemName(value) { return String(value??'Предмет').replace(/^item_/,'').split('_').map(word=>word.charAt(0).toUpperCase()+word.slice(1)).join(' '); }
function displayedReport() { return state.showArchived&&state.detail?.archived_report?.report?state.detail.archived_report.report:state.detail?.report; }
function insight() { return displayedReport()?.insights??{}; }
function jumpTime(time) { seekTime(time); $('economy-heading').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}); }
function timeButton(time, label, className='evidence-link') { const button=node('button',`${stamp(time)}${label?` · ${label}`:''}`,className); button.type='button'; button.addEventListener('click',()=>jumpTime(time)); return button; }
function graphFrame(id,duration,maximum) {
  const svg=$(id); svg.replaceChildren(); const max=Math.max(1,maximum);
  // Small adjacent charts need CSS-sized labels: SVG text otherwise shrinks
  // with the 520-unit viewBox to less than nine pixels on a phone.
  if(id==='gold-chart'||id==='xp-chart') {
    for(const previous of svg.parentElement.querySelectorAll('.chart-readable-max,.chart-readable-times')) previous.remove();
    const maximumLabel=node('p',`Макс. ${num(maximum)}`,'chart-readable-max');
    const times=node('div',undefined,'chart-readable-times');
    for(const time of [0,duration/2,duration]) times.append(node('span',stamp(time)));
    svg.before(maximumLabel); svg.after(times);
  }
  const x=time=>20+Math.max(0,Math.min(duration,time))/Math.max(1,duration)*480, y=value=>138-Math.max(0,value)/max*118;
  for(const fraction of [0,.5,1]) { const line=svgNode('line',{x1:20,x2:500,y1:y(max*fraction),y2:y(max*fraction),class:'chart-grid'}); svg.append(line); }
  for(const [time,label,anchor] of [[0,'0:00','start'],[duration/2,stamp(duration/2),'middle'],[duration,stamp(duration),'end']]) { const text=svgNode('text',{x:x(time),y:157,'text-anchor':anchor,class:'chart-axis-label'}); text.textContent=label; svg.append(text); }
  const top=svgNode('text',{x:20,y:14,class:'chart-axis-label'}); top.textContent=num(maximum); svg.append(top);
  const cursor=svgNode('line',{x1:20,x2:20,y1:20,y2:138,class:'chart-cursor'}); svg.append(cursor); state.graphs.push({cursor,x}); return {svg,x,y,cursor};
}
function drawBars(id,bins,key,duration) {
  const valid=bins.filter(bin=>finite(bin.start)&&finite(bin.end)&&bin.end>bin.start&&finite(bin[key]));
  const {svg,x,y,cursor}=graphFrame(id,duration,Math.max(0,...valid.map(bin=>bin[key])));
  for(const bin of valid) { const bar=svgNode('rect',{x:x(bin.start)+.5,y:y(bin[key]),width:Math.max(.7,x(bin.end)-x(bin.start)-1),height:Math.max(0,138-y(bin[key])),rx:1,class:'chart-bar'}); const title=svgNode('title',{}); title.textContent=`${stamp(bin.start)}–${stamp(bin.end)}: ${num(bin[key])}`; bar.append(title); svg.insertBefore(bar,cursor); }
  if(!valid.length) { const empty=svgNode('text',{x:260,y:80,'text-anchor':'middle',class:'chart-empty'}); empty.textContent='Нет поминутных данных'; svg.append(empty); }
}
function drawCombat(duration) {
  const target=$('combat-strip'); target.replaceChildren(); const svg=svgNode('svg',{viewBox:'0 0 520 44',role:'img','aria-label':'Моменты убийств, смертей и получения предметов. Точные времена доступны в хронологии.'}), x=t=>20+Math.max(0,Math.min(duration,t))/duration*480;
  svg.append(svgNode('line',{x1:20,x2:500,y1:22,y2:22,class:'chart-axis'}));
  for(const interval of insight().death_intervals??[]) if(finite(interval.start)&&finite(interval.end)) svg.append(svgNode('rect',{x:x(interval.start),y:9,width:Math.max(1,x(interval.end)-x(interval.start)),height:26,class:'death-period'}));
  for(const event of displayedReport().evidence??[]) {
    if(!['kill','death'].includes(event.type)||!finite(event.time)) continue;
    const marker=event.type==='kill'?svgNode('circle',{cx:x(event.time),cy:22,r:3,class:'combat-kill'}):svgNode('path',{d:`M ${x(event.time)} 14 l 5 8 l -5 8 l -5 -8 Z`,class:'combat-death'});
    const title=svgNode('title',{}); title.textContent=`${stamp(event.time)} · ${eventLabels[event.type]}`; marker.append(title); svg.append(marker);
  }
  for(const item of insight().items??[]) if(finite(item.time)) svg.append(svgNode('rect',{x:x(item.time)-2,y:35,width:4,height:7,class:'combat-purchase'}));
  const cursor=svgNode('line',{x1:20,x2:20,y1:0,y2:44,class:'chart-cursor'}); svg.append(cursor); state.graphs.push({cursor,x}); target.append(svg);
  svg.addEventListener('click',event=>{const box=svg.getBoundingClientRect(); seekTime(((event.clientX-box.left)/box.width*520-20)/480*duration);});
}
function renderSources() {
  const gold=insight().gold??{}, target=$('gold-sources'); target.replaceChildren();
  const sources=(gold.sources??[]).filter(source=>finite(source.gold)&&source.gold>0), total=sources.reduce((sum,source)=>sum+source.gold,0), max=Math.max(1,...sources.map(source=>source.gold));
  $('income-total').textContent=finite(gold.recorded_income)?`${num(gold.recorded_income)} золота`:'';
  for(const [index,source] of sources.entries()) {
    const row=node('div',undefined,'source-row'), heading=node('div',undefined,'source-heading'); heading.append(node('span',source.label??source.key),node('strong',`${num(source.gold)} · ${Math.round(source.gold/Math.max(1,total)*100)}%`));
    const track=node('div',undefined,'source-track'), bar=node('span'); bar.style.width=`${source.gold/max*100}%`; bar.style.background=sourceColors[index%sourceColors.length]; track.setAttribute('aria-hidden','true'); track.append(bar); row.append(heading,track); target.append(row);
  }
  if(!sources.length) target.append(node('p','В этом отчёте нет разбивки золота по источникам. Изменение ценности предметов показано выше.','muted'));
  $('income-coverage').textContent=`Доли от подтверждённых поступлений. ${gold.coverage_note??'Источники дохода показываются только по событиям реплея.'}`;
  if(finite(gold.recorded_loss)&&gold.recorded_loss>0) target.append(node('p',`Потери золота: ${num(gold.recorded_loss)}. Они учитываются отдельно от заработка.`,'help'));
  for(const flow of gold.other_flows??[]) if(finite(flow.gold)&&flow.gold!==0) target.append(node('p',`${flow.label??flow.key}: ${num(flow.gold)} · отдельно от заработка`,'help'));
}
function updateMoment() {
  const report=displayedReport(); if(!report) return;
  const data=insight(), select=bins=>(bins??[]).find(bin=>state.time>=bin.start&&(state.time<bin.end||(state.time===report.metrics?.duration_seconds&&state.time===bin.end))), bin=select(data.gold?.bins), pace=select(data.pace);
  $('income-value').textContent=bin?num(bin.income):'—'; $('farm-value').textContent=pace?num(pace.last_hits):'—';
  $('income-window').textContent=bin?`${stamp(bin.start)}–${stamp(bin.end)} · Потери: ${num(bin.loss)} золота`:'Выбери интервал на общей шкале.';
  const target=$('moment-summary'); target.replaceChildren(); target.append(node('p',`На отметке ${stamp(state.time)}`,'eyebrow'));
  if(pace) { target.append(node('h4',`${num(pace.last_hits)} добиваний · ${num(pace.kills)} убийств · ${num(pace.assists)} помощи`)); target.append(node('p',`${stamp(pace.start)}–${stamp(pace.end)} · ${num(pace.deaths)} смертей · ${num(pace.xp)} опыта`,'help')); }
  const sources=new Map((data.gold?.sources??[]).map(source=>[source.key,source.label]));
  if(bin) { const parts=Object.entries(bin.by_source??{}).filter(([,amount])=>finite(amount)&&amount>0).map(([key,amount])=>`${sources.get(key)??key}: ${num(amount)}`); target.append(node('p',parts.length?parts.join(' · '):'Дохода в журнале за эту минуту нет.','help')); }
  if(!pace&&!bin) target.append(node('p','Для этой минуты подробных счётчиков нет. Снимок общей статистики указан под шкалой времени.','help'));
}
function itemGoalKey(item) { const player=displayedReport()?.player??{}; return `narma.item-goal.v1:${player.account_id??'unknown'}:${player.hero??'unknown'}:${item.item}`; }
function readGoal(item) { try { const value=localStorage.getItem(itemGoalKey(item)); return value&&/^\d{1,3}:[0-5]\d$/.test(value)?value:''; } catch { return ''; } }
function goalSeconds(text) { if(!/^\d{1,3}:[0-5]\d$/.test(text)) return null; const [minutes,seconds]=text.split(':').map(Number); return minutes*60+seconds; }
// Inventory art comes directly from Valve's fixed CDN path. Replay text never
// supplies a host, extension or arbitrary URL; missing art keeps a neutral tile.
function itemIconUrl(value) {
  const match=typeof value==='string'&&/^item_([a-z0-9_]{1,80})$/.exec(value);
  return match?`https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/${match[1]}.png`:null;
}
function itemIcon(value) {
  const tile=node('span',undefined,'item-icon'), fallback=node('span','◇','item-icon-fallback'); tile.setAttribute('aria-hidden','true'); tile.append(fallback);
  const url=itemIconUrl(value); if(!url) return tile;
  const picture=node('img',undefined,'item-image'); picture.alt=''; picture.width=88; picture.height=64; picture.loading='lazy'; picture.decoding='async'; picture.referrerPolicy='no-referrer';
  picture.addEventListener('load',()=>{picture.hidden=false;picture.classList.add('item-image-loaded');fallback.hidden=true;});
  picture.addEventListener('error',()=>{picture.hidden=true;fallback.hidden=false;});
  picture.src=url; tile.append(picture); return tile;
}
function renderItems() {
  const report=displayedReport(), data=insight(), provided=Array.isArray(data.items), items=provided?data.items:(report.inventory??[]).filter(entry=>finite(entry.time)).map((entry,index)=>({id:`legacy-${index}`,item:entry.item,label:itemName(entry.item),time:entry.time,event_id:entry.event_id,acquisition:'purchase',timing:{label:'Без эталона',basis:'Нет сопоставимого ориентира по герою, роли и рейтингу.'},realization:{note:'В этом отчёте нет данных о доставке и применении предмета.'}}));
  const rail=$('item-rail'), cards=$('item-cards'); rail.replaceChildren(); cards.replaceChildren(); rail.setAttribute('role','group'); rail.setAttribute('aria-label','Выбрать предмет'); $('item-count').textContent=`${items.length} предметов`;
  if(!items.length) { cards.append(node('p','В этом отчёте нет подтверждённых покупок ключевых предметов.','muted')); return; }
  // Keep each card's draft and expanded details while switching items. Selection
  // belongs to this render only, so another replay or archive starts at its first item.
  const selectItem=index=>{
    for(const [position,card] of Array.from(cards.children).entries()) card.hidden=position!==index;
    for(const [position,chip] of Array.from(rail.children).entries()) chip.setAttribute('aria-pressed',String(position===index));
  };
  for(const [index,item] of items.entries()) {
    const label=item.label??itemName(item.item), card=node('article',undefined,'item-card'); card.dataset.time=String(item.time); card.id=`item-card-${index}`; card.hidden=index!==0;
    const chip=node('button',`${stamp(item.time)} · ${label}`,'item-chip'); chip.type='button'; chip.setAttribute('aria-pressed',String(index===0)); chip.setAttribute('aria-controls',card.id);
    chip.addEventListener('click',()=>{selectItem(index);if(finite(item.time)) seekTime(item.time);}); chip.prepend(itemIcon(item.item)); rail.append(chip);
    const heading=node('div',undefined,'item-heading'), identity=node('div',undefined,'item-identity'), title=node('h4',label); title.id=`item-title-${index}`; card.setAttribute('aria-labelledby',title.id); identity.append(itemIcon(item.item),title); heading.append(identity); card.append(heading);
    const milestones=node('dl',undefined,'item-milestones');
    for(const [title,value] of [[item.acquisition==='inventory'?'Первое появление':'Покупка',item.time],['Первое применение',item.realization?.first_use_time]]) {
      const row=node('div'), amount=node('dd');
      if(finite(value)) {const button=timeButton(value,'','item-milestone-time');button.setAttribute('aria-label',`${title}: ${stamp(value)}`);amount.append(button);}
      else amount.append(node('span','Нет записи','item-missing'));
      row.append(node('dt',title),amount); milestones.append(row);
    }
    card.append(milestones);
    const timing=node('div',undefined,'item-timing'), badge=node('span',item.timing?.label??'Без эталона','timing-badge'), basis=node('p',item.timing?.basis??'Нет сопоставимого ориентира по герою, роли и рейтингу.','help'); timing.append(badge,basis); card.append(timing);
    const steps=node('dl',undefined,'item-steps');
    for(const [title,value] of [['Первый снимок у героя',item.first_hero_inventory_time],['В активном слоте',item.first_active_inventory_time]]) { const row=node('div'), amount=node('dd'); if(finite(value)) {const button=timeButton(value,'','item-step-time');button.setAttribute('aria-label',`${title}: ${stamp(value)}`);amount.append(button);} else amount.textContent='—'; row.append(node('dt',title),amount); steps.append(row); }
    card.append(steps);
    const realization=item.realization??{}, summary=node('div',undefined,'item-realization'); summary.append(node('p','Реализация · что видно в реплее','eyebrow'));
    const statusLabels={used_soon:'Применён в первые 2 минуты',used_later:'Первое применение позже 2 минут',no_recorded_use:'Применение не записано',passive_item:'Пассивный эффект',no_window:'Недостаточно времени после покупки'};
    if(statusLabels[realization.status]) summary.append(node('p',statusLabels[realization.status],'realization-status'));
    summary.append(node('p',finite(realization.observed_seconds)?`После ${item.acquisition==='inventory'?'появления в инвентаре':'покупки'} · ${stamp(realization.observed_seconds)}`:'События после приобретения','eyebrow'));
    if(finite(realization.casts)) summary.append(node('p',`${num(realization.casts)} применений · ${num(realization.kills)} убийств · ${num(realization.assists)} помощи · ${num(realization.deaths)} смертей`,'outcome-counts'));
    if(realization.note) {const details=node('details',undefined,'item-observation');details.append(node('summary','Что подтверждено в эпизоде'),node('p',realization.note,'help'));summary.append(details);}
    if(finite(realization.delay_seconds)) summary.append(node('p',`От ${item.acquisition==='inventory'?'наблюдения в инвентаре':'покупки'} до применения: ${stamp(realization.delay_seconds)}.`,'help'));
    if(finite(realization.delay_from_active_seconds)) summary.append(node('p',`От активного слота до применения: ${stamp(realization.delay_from_active_seconds)}.`,'help'));
    if(finite(realization.objectives)&&realization.objectives>0) summary.append(node('p',`Событий у объектов: ${num(realization.objectives)}.`,'help'));
    const evidenceLinks=node('div',undefined,'evidence-links');
    for(const id of (realization.evidence_ids??[]).slice(0,3)) { const event=state.evidence.get(id); if(!event) continue; const button=node('button',`${stamp(event.time)} · ${eventLabels[event.type]??'Событие'}`,'evidence-link'); button.addEventListener('click',()=>focusEvidence(id)); evidenceLinks.append(button); }
    if(evidenceLinks.childElementCount) summary.append(evidenceLinks); card.append(summary);
    const funding=item.funding;
    if(funding) { const box=node('details',undefined,'item-funding'); box.append(node('summary',`Доход перед приобретением · ${stamp(funding.start)}–${stamp(funding.end)}`));
      const labels=new Map((data.gold?.sources??[]).map(source=>[source.key,source.label])); const parts=Object.entries(funding.by_source??{}).filter(([,amount])=>finite(amount)&&amount>0).map(([key,amount])=>`${labels.get(key)??key}: ${num(amount)}`);
      box.append(node('p',parts.length?parts.join(' · '):'Нет разбивки по источникам за это окно.','help')); if(funding.note) box.append(node('p',funding.note,'help')); card.append(box);
    }
    const goal=node('details',undefined,'item-goal'); goal.append(node('summary','Сравнить со своей целью'));
    const inputId=`item-goal-${index}`, input=node('input'); input.id=inputId; input.inputMode='text'; input.placeholder='20:00'; input.maxLength=6; input.value=readGoal(item); input.setAttribute('aria-describedby',`${inputId}-help`);
    const inputLabel=node('label','Личная цель, мин:сек'); inputLabel.htmlFor=inputId; const help=node('p','Нормальный: в пределах ±1 минуты от твоей цели. Это не норма по рейтингу. Цель хранится только в этом браузере.','help'); help.id=`${inputId}-help`;
    const controls=node('div',undefined,'goal-controls'), save=node('button','Применить','quiet'), clear=node('button','Убрать цель','quiet'), feedback=node('p','','help'); feedback.setAttribute('role','status');
    const applyGoal=value=>{ const seconds=goalSeconds(value); if(seconds===null) { badge.textContent=item.timing?.label??'Без эталона'; badge.className='timing-badge'; basis.textContent=item.timing?.basis??'Нет сопоставимого ориентира по герою, роли и рейтингу.'; return; } const delta=item.time-seconds; badge.textContent=delta < -60?'Ранний · личная цель':delta > 60?'Поздний · личная цель':'Нормальный · личная цель'; badge.className=`timing-badge ${delta < -60?'timing-early':delta>60?'timing-late':'timing-normal'}`; basis.textContent=`Цель ${stamp(seconds)} ± 1 минута · ${delta===0?'точно в цель':`${stamp(Math.abs(delta))} ${delta<0?'раньше':'позже'}`}. Это сравнение с твоей целью, не с другими игроками.`; };
    save.type='button'; clear.type='button'; save.addEventListener('click',()=>{const value=input.value.trim(); if(goalSeconds(value)===null) {feedback.textContent='Укажи время в формате 20:00.'; return;} applyGoal(value); try{localStorage.setItem(itemGoalKey(item),value);feedback.textContent='Цель сохранена в этом браузере.';}catch{feedback.textContent='Цель применена. Сохранить в браузере не удалось.';}});
    clear.addEventListener('click',()=>{input.value='';applyGoal('');try{localStorage.removeItem(itemGoalKey(item));feedback.textContent='Цель убрана.';}catch{feedback.textContent='Цель убрана на этой странице. Хранилище браузера недоступно.';}});
    applyGoal(input.value); controls.append(input,save,clear); goal.append(inputLabel,controls,help,feedback); card.append(goal); cards.append(card);
  }
}
function selectedHeroContext() {
  const context=state.showArchived?state.detail?.archived_report?.hero_context:state.detail?.hero_context;
  return context?.hero===displayedReport()?.player?.hero?context:null;
}
function renderHeroContext() {
  const target=$('hero-context'), context=selectedHeroContext(); target.replaceChildren(); target.hidden=!context;
  if(!context) return;
  const heading=node('h4',`Разбор за ${context.label??heroName(context.hero)}`); heading.id='hero-context-heading';
  target.append(heading,node('p',context.position_label??positionName(context.position),'hero-context-role'));
  if(context.summary) target.append(node('p',context.summary,'hero-context-summary'));
  const guidance=roleGuidance(context.role_context);if(guidance)target.append(guidance);
  if(context.abilities?.length) {
    target.append(node('p','Применения способностей из реплея','eyebrow'));
    const abilities=node('ul',undefined,'hero-abilities');
    for(const ability of context.abilities.slice(0,8)) {
      const row=node('li'); row.append(node('strong',ability.label??ability.name??'Способность'),node('span',`${num(ability.casts)} применений`));
      if(finite(ability.first_time)) row.append(node('span',`${stamp(ability.first_time)}${finite(ability.last_time)&&ability.last_time!==ability.first_time?` — ${stamp(ability.last_time)}`:''}`,'help'));
      abilities.append(row);
    }
    target.append(abilities,node('p','Счётчик может включать применения до начала матча. Число применений само по себе не показывает их качество.','help'));
  }
  if(context.focus?.length) {
    const focus=node('div',undefined,'hero-focus'); renderPoints(focus,context.focus.slice(0,3)); target.append(focus);
  }
  if(context.limits?.length) { const limits=node('ul',undefined,'hero-context-limits help'); limits.append(...context.limits.slice(0,5).map(value=>node('li',value))); target.append(limits); }
  const sources=node('div',undefined,'hero-context-sources');
  for(const source of (context.sources??[]).slice(0,3)) {
    let url; try {url=new URL(source.url);} catch {continue;} if(url.protocol!=='https:') continue;
    const link=node('a',source.title??url.hostname); link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer'; sources.append(link);
  }
  if(sources.childElementCount) target.append(sources);
}
function renderTraining() {
  const target=$('next-game-plan'), coach=displayedReport().coaching, context=selectedHeroContext(), plans=coach?.status==='ready'&&coach.next_game?.length?coach.next_game:context?.training_plan?.length?context.training_plan:insight().training_plan??[]; target.replaceChildren();
  for(const [index,plan] of plans.slice(0,3).entries()) { const card=node('article',undefined,'training-card'); card.append(node('p',`0${index+1}`,'training-number'),node('h4',plan.title??'Приоритет на матч'),node('p',plan.action??'','training-action'));
    if(plan.measure) {const measure=node('div',undefined,'training-measure');measure.append(node('span','Как проверить'),node('p',plan.measure));card.append(measure);}
    const links=node('div',undefined,'evidence-links'); for(const id of (plan.evidence_ids??[]).slice(0,2)) {const evidence=state.evidence.get(id);if(!evidence)continue;const button=node('button',`${stamp(evidence.time)} · ${eventLabels[evidence.type]??'Эпизод'}`,'evidence-link');button.addEventListener('click',()=>focusEvidence(id));links.append(button);} if(links.childElementCount)card.append(links);target.append(card);
  }
  if(!target.childElementCount) target.append(node('p','Для этого отчёта отдельный план ещё не сформирован. Ниже доступны комментарии к подтверждённым эпизодам.','muted'));
}

function drawGraph(id,samples,key,duration) {
  const valid=samples.filter(sample=>finite(sample[key])), maximum=Math.max(0,...valid.map(sample=>sample[key])), {svg,x,y,cursor}=graphFrame(id,duration,maximum);
  if(valid.length) { const points=valid.map(sample=>`${x(sample.time).toFixed(2)},${y(sample[key]).toFixed(2)}`).join(' '); svg.insertBefore(svgNode('polygon',{points:`${x(valid[0].time)},138 ${points} ${x(valid.at(-1).time)},138`,class:'chart-area'}),cursor); svg.insertBefore(svgNode('polyline',{points,class:'chart-line',fill:'none','vector-effect':'non-scaling-stroke'}),cursor); }
  else {const empty=svgNode('text',{x:260,y:80,'text-anchor':'middle',class:'chart-empty'});empty.textContent='Нет данных';svg.append(empty);}
}
function seekTime(seconds, evidenceId=null) {
  const report=displayedReport(); if(!report) return;
  const duration=Math.max(1,report.metrics?.duration_seconds??0); state.time=Math.max(0,Math.min(duration,seconds));
  $('timeline').value=String(Math.round(state.time)); $('timeline-value').textContent=stamp(state.time);
  const samples=(report.economy??[]).filter(sample=>Number.isFinite(sample.time)&&sample.time<=state.time);
  const snapshot=samples.at(-1);
  $('gold-value').textContent=num(snapshot?.net_worth); $('xp-value').textContent=num(snapshot?.xp);
  $('timeline-snapshot').textContent=snapshot?`${stamp(snapshot.time)} · Уровень ${num(snapshot.level)} · ${num(snapshot.kills)} / ${num(snapshot.deaths)} / ${num(snapshot.assists)} · Добивания ${num(snapshot.last_hits)} / ${num(snapshot.denies)}`:'До первого снимка статистики. Выбери более поздний момент.';
  for(const graph of state.graphs) { graph.cursor.setAttribute('x1',String(graph.x(state.time))); graph.cursor.setAttribute('x2',String(graph.x(state.time))); }
  for(const row of $('events').children) row.classList.toggle('selected-event',row.dataset.evidenceId===evidenceId);
  updateMoment();
}
function focusEvidence(id) {
  const evidence=state.evidence.get(id); if(!evidence) return;
  $('event-filter').value='all'; renderEvents(); seekTime(evidence.time,id);
  const row=Array.from($('events').children).find(element=>element.dataset.evidenceId===id);
  row?.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
function renderPoints(target, points) {
  target.replaceChildren();
  for(const point of points??[]) {
    const article=node('article',undefined,'report-point'); article.append(node('h4',point.title??'Эпизод'));
    if(point.observation) article.append(node('p',point.observation));
    if(point.advice) article.append(node('p',point.advice,'advice'));
    const links=node('div',undefined,'evidence-links');
    for(const id of point.evidence_ids??[]) { const evidence=state.evidence.get(id); if(!evidence) continue; const link=node('button',`${stamp(evidence.time)} · ${eventLabels[evidence.type]??'Событие'}`,'evidence-link'); link.addEventListener('click',()=>focusEvidence(id)); links.append(link); }
    if(links.childElementCount) article.append(links); target.append(article);
  }
  if(!target.childElementCount) target.append(node('p','В этом матче нет подтверждённых эпизодов для отдельной рекомендации. Статистика и хронология доступны ниже.','muted'));
}
function renderEvents() {
  const filter=$('event-filter').value, list=$('events'); list.replaceChildren();
  for(const evidence of displayedReport()?.evidence??[]) {
    if(filter!=='all' && evidence.type!==filter) continue;
    const row=node('article',undefined,'event-row'); row.dataset.evidenceId=evidence.id;
    const time=node('button',stamp(evidence.time),'event-time'); time.setAttribute('aria-label',`Выбрать время ${stamp(evidence.time)}`); time.addEventListener('click',()=>seekTime(evidence.time,evidence.id));
    const copy=node('div'); copy.append(node('p',`${eventLabels[evidence.type]??'Событие'} · ${evidence.title??''}`,'event-title')); if(evidence.details) copy.append(node('p',evidence.details,'help'));
    row.append(time,copy); list.append(row);
  }
  if(!list.childElementCount) list.append(node('p','Таких событий в журнале нет.','empty'));
}
function heroIcon(hero,{label=heroName(hero),className='report-portrait',lazy=false}={}) {
  const match=typeof hero==='string'&&/^npc_dota_hero_([a-z0-9_]{1,80})$/.exec(hero);
  const portrait=node('span',undefined,className),fallback=node('span',match?label.slice(0,2).toUpperCase():'—','report-portrait-fallback');
  portrait.setAttribute('aria-hidden','true'); portrait.append(fallback);
  if(match) {
    const picture=node('img'); picture.alt=''; picture.width=256; picture.height=144; picture.decoding='async'; picture.referrerPolicy='no-referrer'; picture.hidden=!lazy;
    if(lazy)picture.loading='lazy';
    picture.addEventListener('load',()=>{picture.hidden=false;fallback.hidden=true;});
    picture.addEventListener('error',()=>{picture.hidden=true;fallback.hidden=false;});
    picture.src=`https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/${match[1]}.png`; portrait.append(picture);
  }
  return portrait;
}
function renderHeroHeader(report) {
  const target=$('report-hero'); target.replaceChildren(); target.hidden=!report;
  if(!report) return;
  const hero=report.player?.hero,label=typeof hero==='string'&&/^npc_dota_hero_([a-z0-9_]{1,80})$/.test(hero)?heroName(hero):'Герой не определён';
  target.append(heroIcon(hero,{label}),node('h3',label,'report-hero-name'));
}
function renderDetail() {
  const detail=state.detail; if(!detail) return; const job=detail.replay, report=state.showArchived&&detail.archived_report?.report?detail.archived_report.report:detail.report;
  $('result').hidden=false; $('result-title').textContent=job.match_id?`Матч ${job.match_id}`:job.filename; $('result-state').textContent=labels[job.state]??job.state;
  $('result-player').textContent=report?`${report.player.nickname} · ${report.player.team==='radiant'?'Radiant':'Dire'}${report.outcome==='win'?' · Победа':report.outcome==='loss'?' · Поражение':''}`:job.nickname;
  $('analysis-progress').hidden=job.state!=='processing'; $('analysis-progress').value=job.progress??0;
  $('result-status').textContent=job.state==='failed'?(failures[job.failure_code]??'Не удалось завершить разбор этого реплея. Повтори загрузку полного файла .dem.'):job.state==='queued'?'Реплей загружен. Ожидаем начало разбора.':job.state==='processing'?`Читаем события матча и готовим разбор · ${num(job.progress)}%`:job.state==='uploading'?'Реплей ещё загружается.':report?`Полный матч · ${stamp(report.metrics?.duration_seconds)} · Разбор закреплённого игрока`:'Результат ещё не получен.';
  $('report-body').hidden=!report;
  renderHeroHeader(report);
  const trainingContext=report?.coaching?.context??(!state.showArchived&&!detail.report_is_previous?job.training_context:null);
  const contextParts=[];
  if(trainingContext?.position>=1&&trainingContext.position<=5) contextParts.push(`Позиция ${trainingContext.position}`);
  if(Number.isInteger(trainingContext?.mmr)&&trainingContext.mmr>=0) contextParts.push(`MMR ${num(trainingContext.mmr)} · указан тобой`);
  const depthLabels={foundations:'Основы',application:'Применение',advanced:'Сложные решения'};
  if(depthLabels[trainingContext?.training_level]) contextParts.push(depthLabels[trainingContext.training_level]);
  $('report-training-context').hidden=!report||!contextParts.length; $('report-training-context').textContent=contextParts.join(' · ');
  const archive=$('previous-report-toggle'); archive.hidden=!detail.archived_report?.report||detail.report_is_previous===true; archive.textContent=state.showArchived?'Вернуться к текущему разбору':'Предыдущий тренерский разбор'; archive.setAttribute('aria-pressed',String(state.showArchived));
  $('previous-report-note').hidden=!(state.showArchived||detail.report_is_previous||report?.coaching?.origin==='previous_report');
  $('previous-report-note').textContent=state.showArchived||detail.report_is_previous?'Показан сохранённый предыдущий разбор целиком, с его исходными событиями и таймкодами.':report?.coaching?.origin==='previous_report'?'Сохранён предыдущий тренерский комментарий: обновить его в этом запуске не удалось.':'';
  if(!report) return;
  state.evidence=new Map((report.evidence??[]).map(event=>[event.id,event]));
  const metrics=$('metrics'); metrics.replaceChildren(); const m=report.metrics??{};
  for(const [label,value] of [['Убийства / смерти / помощи',`${num(m.kills)} / ${num(m.deaths)} / ${num(m.assists)}`],['Добивания / денаи',`${num(m.last_hits)} / ${num(m.denies)}`],['Ценность предметов и золота',num(m.net_worth)],['Всего заработано золота',num(m.total_earned_gold)],['Полученный опыт',num(m.xp)],['Время вне игры',stamp(m.confirmed_dead_seconds)]]) { const metric=node('div',undefined,'metric'); metric.append(node('dt',label),node('dd',value)); metrics.append(metric); }
  const duration=Math.max(1,m.duration_seconds??0), samples=(report.economy??[]).filter(sample=>Number.isFinite(sample.time)&&sample.time>=0&&sample.time<=duration);
  $('timeline').max=String(Math.ceil(duration)); state.graphs=[]; drawGraph('gold-chart',samples,'net_worth',duration); drawGraph('xp-chart',samples,'xp',duration);
  drawBars('income-chart',insight().gold?.bins??[],'income',duration); drawBars('farm-chart',insight().pace??[],'last_hits',duration); drawCombat(duration); renderSources(); renderItems(); renderHeroContext(); renderTraining(); renderReportLearning();
  renderPoints($('findings'),report.findings); renderEvents();
  const coach=report.coaching; $('coaching-section').hidden=false;
  if(coach?.status==='ready') { $('coaching-summary').textContent=coach.summary??''; renderPoints($('coaching'),coach.points); }
  else {
    const needsConnection=coach?.failure_code==='CHATGPT_NOT_CONNECTED';
    $('coaching-summary').textContent=coach?.status==='context_changed'?'Контекст разбора обновлён. Упражнение выше учитывает текущую позицию; прежний тренерский комментарий больше не применяется.':needsConnection?'Статистика матча готова. Подключи ChatGPT в аккаунте, чтобы использовать тренера Narma.':'Тренерский комментарий временно недоступен. Статистика и эпизоды из реплея доступны.';
    $('coaching').replaceChildren();
    if(needsConnection){
      const connect=node('a','Подключить ChatGPT','secondary coaching-connect');connect.href=tabPaths.account;
      connect.addEventListener('click',event=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();switchTab('account');$('chatgpt-heading').scrollIntoView({block:'start'});});$('coaching').append(connect);
    }
  }
  const coverage=report.coverage??{}; $('coverage-summary').textContent=coverage.complete?'Реплей прочитан полностью. Статистика и события относятся к закреплённому игроку.':'Полнота данных не подтверждена.';
  $('coverage-limits').replaceChildren(...(coverage.limits??[]).map(limit=>node('li',limit)));
  seekTime(state.time);
}
async function openReplay(id, scroll=false, canonicalRedirect=false) {
  if(!canonicalRedirect)state.learningCanonicalTrail.clear();
  const changed=state.selected!==id; if(changed) state.showArchived=false; state.selected=id; const detail=await api('/api/replays/'+id); if(state.selected!==id) return;
  if(changed||(!state.detail?.report&&detail.report)) { state.time=detail.report?.metrics?.duration_seconds??0; $('event-filter').value='all'; }
  state.detail=detail; if(changed) {state.reportLearning=null;state.reportExercise=null;} renderDetail(); if(detail.report&&!state.showArchived&&!detail.report_is_previous) void loadReportLearning(); if(scroll) $('result').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
$('previous-report-toggle').addEventListener('click',()=>{ state.showArchived=!state.showArchived; state.time=displayedReport()?.metrics?.duration_seconds??0; renderDetail(); if(!state.showArchived) void loadReportLearning(); });
$('timeline').addEventListener('input',()=>seekTime(Number($('timeline').value)));
$('event-filter').addEventListener('change',renderEvents);
for(const id of ['gold-chart','xp-chart','income-chart','farm-chart']) $(id).addEventListener('click',event=>{ const duration=displayedReport()?.metrics?.duration_seconds; if(!duration) return; const box=$(id).getBoundingClientRect(), relative=(event.clientX-box.left)/box.width*520; seekTime((relative-20)/480*duration); });
$('refresh').addEventListener('click',()=>void refresh().then(()=>state.selected?openReplay(state.selected):undefined).catch(error=>notice(error.message)));
setInterval(()=>{ if(!state.user||document.hidden||state.busy) return; void refresh().then(()=>{ if(state.selected&&['queued','processing'].includes(state.detail?.replay.state)) return openReplay(state.selected); }).catch(error=>notice(error.message)); },10000);
void session().catch(error=>{ $('loading').textContent='Не удалось открыть кабинет.'; notice(error.message); });

// Long-term observations use only saved reports for the authenticated player.
const poolFocusLabels={item_plan:'План на ключевой предмет',farm_checkpoint:'Фарм на 10-й минуте',safe_return:'Возвращение после смерти',lane_support:'Помощь союзнику на линии',rotation_window:'Окно для перемещения'};
function poolFocusOptions(position,current) {
  const options={
    1:{farm_checkpoint:'Доступ к добиваниям и безопасному фарму',item_plan:'Предмет для фарма, защиты или урона',safe_return:'Безопасная задача после возвращения'},
    2:{farm_checkpoint:'Ресурсы линии и цена ухода с мида',rotation_window:'Волна, руна и выход на другую линию',item_plan:'Предмет для реализации темпа',safe_return:'Новый маршрут после возвращения'},
    3:{farm_checkpoint:'Рабочий предмет и давление на керри',item_plan:'Вход, контроль или командная защита',rotation_window:'Давление с поддержкой команды',safe_return:'Возвращение к доступной команде задаче'},
    4:{lane_support:'Условия для игры офлейнера',rotation_window:'Безопасный уход к руне или на ганг',item_plan:'Контроль, мобильность или спасение',safe_return:'Полезная помощь после возвращения'},
    5:{lane_support:'Безопасный фарм керри и отвод по волне',rotation_window:'Помощь миду без потери линии керри',item_plan:'Спасение союзника и нужные расходники',safe_return:'Защита и обзор после возвращения'},
  }[position]??{item_plan:poolFocusLabels.item_plan,safe_return:poolFocusLabels.safe_return};
  if(current&&!Object.hasOwn(options,current))options[current]=`${poolFocusLabels[current]??'Сохранённый фокус'} · выбран ранее`;
  return options;
}
const poolReflectionLabels={done:'Выполнил',partial:'Частично',not_done:'Не выполнил'};
const positionLabels={1:'1 · Керри',2:'2 · Мидер',3:'3 · Офлейнер',4:'4 · Поддержка',5:'5 · Полная поддержка'};
const poolMetricLabels={deaths_per_30:'Смерти на 30 минут',gpm:'Золото в минуту',xpm:'Опыт в минуту',last_hits_10:'Добивания к 10-й минуте',net_worth_10:'Ценность героя на 10-й минуте',item_delay_seconds:'До первого применения предмета, сек.'};
function positionName(value) { return positionLabels[value]??'Позиция не указана'; }
function decimal(value) { return finite(value)?value.toLocaleString('ru-RU',{maximumFractionDigits:1}):'—'; }
function poolDate(value) { const date=new Date(value??''); return Number.isFinite(date.valueOf())?date.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit',year:'2-digit'}):'Дата неизвестна'; }
function matchDateLabel(match) { return `${match.date_source==='analysis'?'Разобран':'Игра'} ${poolDate(match.played_at??match.chronology_at)}${match.date_source==='user'?' · дата указана вручную':''}`; }
function poolQuery() {
  const query=new URLSearchParams({window:$('pool-period').value});
  if($('pool-hero').value) query.set('hero',$('pool-hero').value);
  if($('pool-position').value) query.set('position',$('pool-position').value);
  if($('pool-favorites-only').checked) query.set('favorites_only','true');
  return query;
}
async function loadPool() {
  if(!state.user) return;
  const request=++state.poolRequest,sourceSignature=state.poolSignature;
  $('pool-status').textContent='Собираем результаты твоих матчей…'; $('pool-content').setAttribute('aria-busy','true'); $('pool-refresh').disabled=true;
  try {
    const data=await api('/api/hero-pool?'+poolQuery());
    if(request!==state.poolRequest||!state.user) return;
    state.pool=data; state.poolDirty=sourceSignature!==state.poolSignature; renderPool(); $('pool-status').textContent='';
  } catch(error) {
    if(request!==state.poolRequest) return;
    state.pool=null; $('pool-content').hidden=true; $('pool-status').textContent=`Не удалось открыть пул героев. ${error.message} Нажми «Обновить пул», чтобы повторить.`;
  } finally { if(request===state.poolRequest) { $('pool-content').setAttribute('aria-busy','false'); $('pool-refresh').disabled=false; } }
}
async function poolMutation(button,path,method,body,success) {
  const focusId=button.id, focusLabel=button.getAttribute('aria-label'); button.disabled=true;
  try { await api(path,method,body); await loadPool();
    if(body&&Object.hasOwn(body,'position')) {
      state.reportLearning=null;state.reportExercise=null;
      await loadLearning({preserveView:true});
      if(state.selected&&path.endsWith(`/${encodeURIComponent(state.selected)}`))await openReplay(state.selected);
    }
    $('pool-status').textContent=success;
    const replacement=focusId?$(focusId):focusLabel?Array.from($('hero-pool').querySelectorAll('button[aria-label]')).find(item=>item.getAttribute('aria-label')===focusLabel):null;
    (replacement??$('pool-refresh')).focus({preventScroll:true});
  }
  catch(error) { if(state.pool&&state.user) renderPool(); $('pool-status').textContent=error.message; const replacement=focusId?$(focusId):null; (replacement??$('pool-refresh')).focus({preventScroll:true}); }
  finally { if(button.isConnected) button.disabled=false; }
}
function poolMatchButton(match,label='Открыть разбор') {
  const button=node('button',label,'quiet'); button.type='button';
  button.addEventListener('click',async()=>{ button.disabled=true; switchTab('review'); try { await openReplay(match.job_id,true); if(finite(match.time)) seekTime(match.time,match.evidence_id); } catch(error) { notice(error.message); } finally { button.disabled=false; } });
  return button;
}
function renderPool() {
  const data=state.pool, summary=data.summary??{};
  const selected=$('pool-hero').value; $('pool-hero').replaceChildren(new Option('Все герои',''));
  for(const hero of data.available_heroes??[]) $('pool-hero').append(new Option(hero.label||heroName(hero.hero),hero.hero));
  if(selected&&!Array.from($('pool-hero').options).some(option=>option.value===selected)) $('pool-hero').append(new Option(heroName(selected),selected));
  $('pool-hero').value=selected;
  const metrics=$('pool-summary'); metrics.replaceChildren();
  for(const [label,value] of [['Матчей в выборке',num(summary.matches)],['Винрейт',finite(summary.winrate_pct)?`${decimal(summary.winrate_pct)}%`:'—'],['Победы / поражения',`${num(summary.wins)} / ${num(summary.losses)}`],['Исход неизвестен',num(summary.unknown_outcomes)]]) { const metric=node('div',undefined,'metric'); metric.append(node('dt',label),node('dd',value)); metrics.append(metric); }
  const caveats=[`Винрейт: ${num(summary.known_outcomes)} матчей с известным исходом.`];
  if(summary.known_outcomes>0&&summary.known_outcomes<10) caveats.push('Малая выборка: процент может заметно меняться после каждого матча.');
  if(summary.unknown_positions) caveats.push(`Без позиции: ${num(summary.unknown_positions)}.`);
  if(summary.analysis_dated_matches) caveats.push(`У ${num(summary.analysis_dated_matches)} матчей нет даты игры: они показаны по дате разбора.`);
  $('pool-limitations').replaceChildren(...(data.limitations??[]).filter(limit=>typeof limit==='string').map(limit=>node('li',limit)));
  $('pool-coverage').textContent=caveats.join(' ');
  $('pool-role-guidance')?.remove();
  const guidance=roleGuidance(data.role_context);if(guidance){guidance.id='pool-role-guidance';$('pool-coverage').after(guidance);}
  $('pool-content').hidden=false;
  const empty=!summary.matches; $('pool-empty').hidden=!empty; $('pool-data').hidden=empty;
  const filtered=!!($('pool-hero').value||$('pool-position').value||$('pool-favorites-only').checked||$('pool-period').value!=='all');
  $('pool-empty').querySelector('h2').textContent=filtered?'Нет матчей с такими фильтрами':'Пул начинается с первого матча';
  $('pool-empty-copy').textContent=filtered?'Измени период, героя или позицию. В избранное можно добавить сочетание героя и позиции в таблице пула.':'Загрузи реплей своего игрока. Готовые разборы соберутся здесь по героям и позициям.';
  if(empty) return;
  const reflections=(data.history??[]).filter(match=>match.reflection), reflectionCounts=Object.keys(poolReflectionLabels).map(key=>`${reflections.filter(match=>match.reflection===key).length} · ${poolReflectionLabels[key].toLowerCase()}`);
  $('pool-practice-summary').textContent=reflections.length?`Личные проверки: ${reflectionCounts.join(' · ')}. Это твоя самооценка по выбранному фокусу, отдельно от показателей реплея.`:'Выбери фокус и отметь после игры, получилось ли его выполнить. Личная проверка помогает связать решения с практикой.';
  renderPoolRoster(); renderPoolTrend(); renderPoolPatterns(); renderPoolGoals(); renderPoolMatches();
}
function renderPoolRoster() {
  const target=$('pool-roster'); target.replaceChildren(); const heroes=state.pool.heroes??[];
  $('pool-roster-count').textContent=`${heroes.length} сочетаний`;
  for(const hero of heroes) {
    const row=node('article',undefined,'pool-hero-row');
    const identity=node('div',undefined,'pool-hero-identity'), avatar=heroIcon(hero.hero,{label:hero.label||heroName(hero.hero),className:'report-portrait pool-hero-portrait',lazy:true});
    const copy=node('div'); copy.append(node('h3',hero.label||heroName(hero.hero)),node('p',positionName(hero.position),'help')); identity.append(avatar,copy);
    const stats=node('div',undefined,'pool-hero-stats'), winrate=node('strong',finite(hero.winrate_pct)?`${decimal(hero.winrate_pct)}%`:'—');
    stats.append(winrate,node('span',`${num(hero.wins)} побед · ${num(hero.losses)} поражений`),node('small',`${num(hero.matches)} матчей${hero.unknown_outcomes?` · ${num(hero.unknown_outcomes)} без исхода`:''}`));
    const actions=node('div',undefined,'pool-hero-actions');
    const focus=node('button','Динамика','quiet'); focus.type='button'; focus.setAttribute('aria-label',`Динамика: ${hero.label||heroName(hero.hero)}, ${positionName(hero.position)}`); focus.addEventListener('click',async()=>{ $('pool-hero').value=hero.hero; $('pool-position').value=hero.position??'unknown'; state.poolVisible=20; await loadPool(); $('pool-trend-heading').scrollIntoView({block:'start'}); }); actions.append(focus);
    if(hero.position) {
      const favorite=node('button',hero.favorite?'★':'☆','pool-favorite'); favorite.type='button'; favorite.setAttribute('aria-pressed',String(!!hero.favorite)); favorite.setAttribute('aria-label',`Избранное: ${hero.label||heroName(hero.hero)}, ${positionName(hero.position)}`);
      favorite.addEventListener('click',()=>void poolMutation(favorite,hero.favorite?`/api/hero-pool/favorites/${encodeURIComponent(hero.hero)}/${hero.position}`:'/api/hero-pool/favorites',hero.favorite?'DELETE':'PUT',hero.favorite?undefined:{hero:hero.hero,position:hero.position},hero.favorite?'Сочетание убрано из избранного.':'Герой и позиция добавлены в избранное.')); actions.append(favorite);
    }
    row.append(identity,stats,actions); target.append(row);
  }
}
function renderPoolTrend() {
  const metric=$('pool-metric').value, label=poolMetricLabels[metric], history=[...(state.pool?.history??[])].sort((a,b)=>String(a.chronology_at).localeCompare(String(b.chronology_at))||String(a.match_id).localeCompare(String(b.match_id)));
  const points=history.map((match,index)=>({match,index,value:match.metrics?.[metric]})).filter(point=>finite(point.value));
  const svg=$('pool-trend-chart'), chartWidth=matchMedia('(max-width:680px)').matches?360:760; svg.setAttribute('viewBox',`0 0 ${chartWidth} 240`); svg.replaceChildren();
  const title=svgNode('title',{id:'pool-trend-title'}); title.textContent=label;
  const desc=svgNode('desc',{id:'pool-trend-description'}); desc.textContent=`${points.length} матчей с показателем. Точные значения и даты — под графиком. Отсутствующие значения не заменяются нулём.`; svg.append(title,desc);
  const groups=new Set(points.map(point=>`${point.match.hero}:${point.match.position??'unknown'}`)), chronology=new Set(points.map(point=>point.match.date_source)), builds=new Set(points.map(point=>point.match.engine_build??null));
  const comparable=groups.size===1&&points.every(point=>point.match.position)&&chronology.size===1&&builds.size===1;
  $('pool-trend-context').textContent=comparable?`${heroName(points[0]?.match.hero)} · ${positionName(points[0]?.match.position)}. ${label}.`:`${label}. Для сравнения выбери одного героя и позицию. Точки разных ролей, источников даты и версий игры не соединяются.`;
  const values=points.map(point=>point.value), maximum=Math.max(1,...values), x=index=>56+(history.length>1?index/(history.length-1):.5)*(chartWidth-88), y=value=>202-(value/maximum)*178;
  for(const fraction of [0,.5,1]) { const yy=y(maximum*fraction); svg.append(svgNode('line',{x1:56,x2:chartWidth-32,y1:yy,y2:yy,class:'chart-grid'})); const text=svgNode('text',{x:45,y:yy+4,'text-anchor':'end',class:'pool-chart-axis'}); text.textContent=decimal(maximum*fraction); svg.append(text); }
  if(comparable&&points.length>1) {
    // Break at missing observations rather than drawing an invented interpolation.
    for(let i=1;i<points.length;i++) if(points[i].index===points[i-1].index+1) svg.append(svgNode('line',{x1:x(points[i-1].index),y1:y(points[i-1].value),x2:x(points[i].index),y2:y(points[i].value),class:'pool-chart-line'}));
  }
  for(const point of points) { const circle=svgNode('circle',{cx:x(point.index),cy:y(point.value),r:5,class:'pool-chart-point'}), hint=svgNode('title',{}); hint.textContent=`${matchDateLabel(point.match)} · ${point.match.label||heroName(point.match.hero)} · ${positionName(point.match.position)} · ${label}: ${decimal(point.value)}`; circle.append(hint); svg.append(circle); }
  if(!points.length) { const text=svgNode('text',{x:chartWidth/2,y:118,'text-anchor':'middle',class:'pool-chart-empty'}); text.textContent='Нет данных по этому показателю'; svg.append(text); }
  const dates=$('pool-chart-dates'); dates.replaceChildren();
  if(history.length) dates.append(node('span',poolDate(history[0].played_at??history[0].chronology_at)),node('span','Матчи по порядку'),node('span',poolDate(history.at(-1).played_at??history.at(-1).chronology_at)));
  const matching=(state.pool?.trends??[]).filter(trend=>trend.metric===metric), ready=matching.filter(trend=>trend.status==='ready');
  const notes=[];
  if(ready.length===1&&comparable) {
    const trend=ready[0]; notes.push(`Первые ${num(trend.early_n)}: ${decimal(trend.early_mean)} → последние ${num(trend.recent_n)}: ${decimal(trend.recent_mean)}. Изменение: ${trend.delta>0?'+':''}${decimal(trend.delta)}${trend.unit?` ${trend.unit}`:''}.`);
  } else if(matching.some(trend=>trend.status==='mixed_builds')) notes.push('Матчи относятся к разным версиям игры: общий вывод о динамике не рассчитывается.');
  else if(matching.some(trend=>trend.status==='ambiguous_chronology')) notes.push('У ранних и последних матчей совпадают даты: направление изменений определить нельзя.');
  else notes.push('Для вывода о динамике нужны хотя бы 3 ранних и 3 последних сопоставимых матча на одном герое и позиции.');
  if(points.length&&builds.has(null)) notes.push('Версия игры известна не для всех матчей; сравнение не учитывает возможные изменения патча.');
  if(chronology.has('analysis')) notes.push('Для матчей без даты игры используется дата разбора; порядок может отличаться от порядка игр.');
  if(chronology.size>1) notes.push('Источники дат различаются — сравнение периодов не рассчитывается.');
  if(metric==='gpm'||metric==='xpm'||metric==='last_hits_10'||metric==='net_worth_10') notes.push('Больше фарма не всегда означает более полезную игру: учитывай задачу своей позиции.');
  if(metric==='item_delay_seconds') notes.push('Показывает задержку применения записанных активных предметов; состав покупок между матчами может различаться.');
  $('pool-trend-note').textContent=notes.join(' ');
  const table=node('table',undefined,'pool-values-table'), caption=node('caption',`${label} по матчам`); table.append(caption);
  const head=node('thead'), heading=node('tr'); for(const value of ['Матч / дата','Герой / позиция',label]) { const th=node('th',value); th.scope='col'; heading.append(th); } head.append(heading); table.append(head);
  const body=node('tbody');
  for(const match of history) { const row=node('tr'), matchCell=node('td'); matchCell.append(node('span',`#${match.match_id}`),node('small',matchDateLabel(match))); const heroCell=node('td'); heroCell.append(node('span',match.label||heroName(match.hero)),node('small',positionName(match.position))); row.append(matchCell,heroCell,node('td',decimal(match.metrics?.[metric]))); body.append(row); }
  table.append(body); $('pool-trend-values').replaceChildren(table);
}
function renderPoolPatterns() {
  const target=$('pool-patterns'); target.replaceChildren(); const patterns=state.pool.patterns??[];
  const coaching=state.pool.coaching;
  for(const pattern of coaching?.patterns??[]) {
    const card=node('article',undefined,'pool-pattern-card pool-coach-card');
    const identities=(pattern.heroes??[]).map(hero=>`${hero.label||heroName(hero.hero)} · ${positionName(hero.position)}`);
    card.append(node('p','Наблюдение тренера','eyebrow'),node('h3',pattern.title),node('p',identities.join(' / '),'help'),node('p',pattern.observation,'muted'));
    for(const goal of pattern.goals??[]) {
      const practice=node('div',undefined,'pool-practice');
      practice.append(node('h4','На следующие игры'),node('p',goal.action),node('p',`Как проверить: ${goal.success_criterion}`,'help'),node('p',`Вернись к проверке после ${num(goal.evaluate_after_matches)} новых матчей.`,'help'));
      card.append(practice);
    }
    const details=node('details',undefined,'pool-coach-evidence');
    details.append(node('summary',`Эпизоды для проверки · ${new Set((pattern.evidence??[]).map(ref=>ref.match_id)).size} матчей`));
    const evidence=node('div',undefined,'evidence-links');
    for(const ref of pattern.evidence??[]) evidence.append(poolMatchButton(ref,`Матч ${ref.match_id} · ${stamp(ref.time)}`));
    details.append(evidence); card.append(details);
    card.append(node('p','Это рекомендация для проверки в игре. Новые разборы помогут уточнить её.','help'));
    target.append(card);
  }
  for(const pattern of patterns) {
    const card=node('article',undefined,'pool-pattern-card'); card.append(node('p',`${pattern.label||heroName(pattern.hero)} · ${positionName(pattern.position)}`,'eyebrow'),node('h3',pattern.title),node('p',pattern.observation,'muted'));
    if(finite(pattern.occurrences)&&finite(pattern.eligible_matches)) card.append(node('p',`Наблюдается в ${num(pattern.occurrences)} из ${num(pattern.eligible_matches)} подходящих матчей.`,'help'));
    if(pattern.action) card.append(node('p',pattern.action,'pool-practice'));
    const evidence=node('div',undefined,'evidence-links'); for(const item of (pattern.evidence??[]).slice(0,3)) evidence.append(poolMatchButton(item,`Матч ${item.match_id}`)); card.append(evidence);
    if(pattern.position) {
      const active=(state.pool.goals??[]).some(goal=>goal.pattern_id===pattern.id&&goal.hero===pattern.hero&&goal.position===pattern.position&&goal.status==='active');
      const practice=node('button',active?'Уже в плане':'Взять в практику','secondary'); practice.type='button'; practice.disabled=active;
      practice.addEventListener('click',()=>void poolMutation(practice,'/api/hero-pool/goals','POST',{pattern_id:pattern.id,hero:pattern.hero,position:pattern.position},'Практика сохранена. Следующие подходящие матчи покажут результат.')); card.append(practice);
    }
    target.append(card);
  }
  if(!patterns.length&&!coaching?.patterns?.length) target.append(node('p','Пока недостаточно сопоставимых матчей для повторяющегося паттерна. Укажи позиции и добавляй новые разборы.','empty'));
}
function renderPoolGoals() {
  const target=$('pool-goals'); target.replaceChildren(); const goals=state.pool.goals??[]; if(!goals.length) return;
  target.append(node('h3','Моя практика'));
  for(const goal of goals) {
    const card=node('article',undefined,'pool-goal-card'); card.append(node('p',`${heroName(goal.hero)} · ${positionName(goal.position)} · ${goal.status==='active'?'В работе':goal.status==='paused'?'На паузе':'Завершена'}`,'eyebrow'),node('h4',goal.title??'Практика на следующие матчи'),node('p',goal.action,'muted'));
    const checks=goal.checks??[]; card.append(node('p',checks.length?`Матчей с проверкой: ${num(checks.length)}.`:'Результат появится после следующего подходящего матча.','help'));
    if(goal.metric&&finite(goal.threshold)) card.append(node('p',`Критерий: ${poolMetricLabels[goal.metric]??(goal.metric==='repeated_deaths'?'Повторные смерти':goal.metric)} ≤ ${decimal(goal.threshold)}.`,'help'));
    for(const check of checks.slice(0,5)) { const line=node('div',undefined,'pool-goal-check'), status={reached:'Критерий выполнен',review:'Нужен разбор эпизода',unknown:'Нет данных',predates_goal:'Матч сыгран до начала практики'}[check.status]??'Наблюдение'; line.append(poolMatchButton(check,`Матч ${check.match_id}`),node('span',`${status}${finite(check.value)?` · ${decimal(check.value)}`:''}${check.chronology_basis==='analysis'?' · дата игры неизвестна':''}`,'help')); card.append(line); }
    const actions=node('div',undefined,'evidence-links');
    for(const [status,label] of goal.status==='completed'?[['active','Вернуть в практику']]:goal.status==='paused'?[['active','Продолжить'],['completed','Завершить']]:[['paused','Пауза'],['completed','Завершить']]) { const button=node('button',label,'quiet'); button.type='button'; button.addEventListener('click',()=>void poolMutation(button,`/api/hero-pool/goals/${encodeURIComponent(goal.id)}`,'PATCH',{status},'Статус практики сохранён.')); actions.append(button); }
    card.append(actions); target.append(card);
  }
}
function renderPoolMatches() {
  const target=$('pool-matches'); target.replaceChildren(); const matches=state.pool.history??[]; $('pool-match-count').textContent=`${matches.length} матчей`;
  for(const match of matches.slice(0,state.poolVisible)) {
    const row=node('article',undefined,'pool-match-row'); row.dataset.matchId=String(match.match_id); const copy=node('div',undefined,'pool-match-copy'); copy.append(node('h3',`${match.label||heroName(match.hero)} · #${match.match_id}`),node('p',matchDateLabel(match),'help'));
    const outcome=node('span',match.outcome==='win'?'Победа':match.outcome==='loss'?'Поражение':'Исход неизвестен',`pool-outcome ${match.outcome==='win'?'pool-win':match.outcome==='loss'?'pool-loss':''}`); copy.append(outcome);
    if(match.report_is_previous) copy.append(node('p',match.report_state==='failed'?'Сохранённый разбор · обновление остановилось':'Сохранённый разбор · обновляется','help'));
    const control=node('div',undefined,'pool-position-control'), label=node('label',`Позиция в матче ${match.match_id}`), select=node('select'); select.id=`pool-position-${match.job_id}`; label.htmlFor=select.id; select.append(new Option('Не указана',''));
    for(const [value,text] of Object.entries(positionLabels)) select.append(new Option(text,value)); select.value=match.position??''; select.disabled=!!match.report_state&&match.report_state!=='ready';
    select.addEventListener('change',()=>void poolMutation(select,`/api/hero-pool/matches/${encodeURIComponent(match.job_id)}`,'PUT',{position:select.value?Number(select.value):null},`Позиция в матче ${match.match_id} сохранена.`)); control.append(label,select);
    row.append(copy,control,poolMatchButton(match));
    if(match.date_source!=='replay') {
      const details=node('details',undefined,'pool-match-date'), summary=node('summary',match.played_at?'Изменить дату игры':'Указать дату игры'), form=node('form'), dateLabel=node('label','Дата и время игры'), input=node('input'), help=node('p','Твой часовой пояс. Дата игры уточнит период и порядок матчей. Пустое поле вернёт дату разбора.','help'), save=node('button','Сохранить дату','quiet');
      input.type='datetime-local'; input.id=`pool-date-${match.job_id}`; input.min='2010-01-01T00:00'; input.setAttribute('aria-describedby',`pool-date-help-${match.job_id}`); help.id=`pool-date-help-${match.job_id}`; dateLabel.htmlFor=input.id; dateLabel.textContent=`Дата и время игры ${match.match_id}`;
      const localValue=date=>new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
      input.max=localValue(new Date(Date.now()+86400000)); input.value=match.played_at?localValue(new Date(match.played_at)):'';
      save.type='submit'; save.disabled=!!match.report_state&&match.report_state!=='ready'; save.setAttribute('aria-label',`Сохранить дату матча ${match.match_id}`);
      form.addEventListener('submit',event=>{ event.preventDefault(); const value=input.value?new Date(input.value).toISOString():null; void poolMutation(save,`/api/hero-pool/matches/${encodeURIComponent(match.job_id)}`,'PUT',{played_at:value},`Дата матча ${match.match_id} сохранена.`); });
      form.append(dateLabel,input,help,save); details.append(summary,form); row.append(details);
    }
    renderPoolJournal(row,match); target.append(row);
  }
  if(matches.length>state.poolVisible) { const more=node('button',`Показать ещё · осталось ${num(matches.length-state.poolVisible)}`,'pool-more quiet'); more.type='button'; more.addEventListener('click',()=>{state.poolVisible+=20;renderPoolMatches();}); target.append(more); }
}
function renderPoolJournal(row,match) {
  const key=String(match.match_id), draft=state.poolDrafts.get(key)??match;
  const details=node('details',undefined,'pool-journal'), summary=node('summary','Личная проверка'+(draft.reflection?` · ${poolReflectionLabels[draft.reflection]??'Результат отмечен'}`:''));
  details.open=state.poolJournalOpen.has(key)||state.poolDrafts.has(key);
  details.addEventListener('toggle',()=>{if(details.open)state.poolJournalOpen.add(key);else state.poolJournalOpen.delete(key);});
  const form=node('form',undefined,'pool-journal-form'), fields=node('div',undefined,'pool-journal-fields');
  const focus=node('select',undefined,'pool-focus'), reflection=node('select',undefined,'pool-reflection');
  focus.id=`pool-focus-${match.job_id}`; reflection.id=`pool-reflection-${match.job_id}`;
  focus.append(new Option('Фокус не выбран','')); reflection.append(new Option('Ещё не проверил',''));
  for(const [value,label] of Object.entries(poolFocusOptions(match.position,draft.focus))) focus.append(new Option(label,value));
  for(const [value,label] of Object.entries(poolReflectionLabels)) reflection.append(new Option(label,value));
  focus.value=draft.focus??''; reflection.value=draft.reflection??'';
  for(const [text,control] of [[`Мой фокус в матче ${match.match_id}`,focus],[`После игры ${match.match_id}: получилось?`,reflection]]) {const field=node('div'),label=node('label',text);label.htmlFor=control.id;field.append(label,control);fields.append(field);}
  const noteLabel=node('label',`Что заметил после игры ${match.match_id}`), note=node('textarea',undefined,'pool-note'); note.id=`pool-note-${match.job_id}`; noteLabel.htmlFor=note.id; note.maxLength=500; note.rows=3; note.value=draft.note??''; note.placeholder='Какое решение хочу повторить или изменить в следующем матче';
  const help=node('p','Фокус, отметка выполнения и заметка — твоя оценка игры. Они сохраняются в аккаунте отдельно от статистики реплея.','help');
  const save=node('button','Сохранить проверку','secondary pool-save'), status=node('p',state.poolDrafts.has(key)?'Есть несохранённые изменения.':'','help pool-save-status');
  save.type='submit'; save.id=`pool-save-${match.job_id}`; save.setAttribute('aria-label',`Сохранить проверку матча ${match.match_id}`); status.id=`pool-journal-status-${match.job_id}`; status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
  const readOnly=!!match.report_state&&match.report_state!=='ready'; for(const control of [focus,reflection,note,save])control.disabled=readOnly;
  const values=()=>({focus:focus.value||null,reflection:reflection.value||null,note:note.value.trim()});
  form.addEventListener('input',()=>{state.poolDrafts.set(key,values());state.poolJournalOpen.add(key);status.textContent='Есть несохранённые изменения.';});
  form.addEventListener('submit',async event=>{
    event.preventDefault(); if(save.disabled)return; const submitted=values();
    if(submitted.reflection&&!submitted.focus) {status.textContent='Выбери фокус, для которого отмечаешь результат.';focus.focus();return;}
    state.poolDrafts.set(key,submitted); for(const control of [focus,reflection,note,save])control.disabled=true;status.textContent='Сохраняем…';
    try {
      await api(`/api/hero-pool/matches/${encodeURIComponent(match.job_id)}`,'PUT',submitted);
      if(JSON.stringify(state.poolDrafts.get(key))===JSON.stringify(submitted))state.poolDrafts.delete(key);
      Object.assign(match,submitted); await loadPool();
      const message=state.poolDrafts.has(key)?'Проверка сохранена. Есть новые несохранённые изменения.':'Проверка сохранена в аккаунте.';
      const currentStatus=$(`pool-journal-status-${match.job_id}`);if(currentStatus)currentStatus.textContent=message;$('pool-status').textContent=message;
      ($(`pool-save-${match.job_id}`)??$('pool-refresh')).focus({preventScroll:true});
    } catch(error) {status.textContent=`Не удалось сохранить. ${error.message}`;}
    finally {for(const control of [focus,reflection,note,save])if(control.isConnected)control.disabled=readOnly;}
  });
  form.append(fields,noteLabel,note,help,save,status);details.append(summary,form);row.append(details);
}
for(const id of ['pool-period','pool-hero','pool-position','pool-favorites-only']) $(id).addEventListener('change',()=>{state.poolVisible=20;void loadPool();});
$('pool-refresh').addEventListener('click',()=>void loadPool());
$('pool-metric').addEventListener('change',()=>{ if(state.pool) renderPoolTrend(); });
for(const id of ['learning-hero','learning-position']) $(id)?.addEventListener('change',()=>void loadLearning());
$('learning-refresh')?.addEventListener('click',()=>void loadLearning());

matchMedia('(max-width:680px)').addEventListener('change',()=>{ if(state.pool) renderPoolTrend(); });

// Curriculum is a saved-report projection; player reflections remain self-reports.
const learningAssessmentLabels={applied:'Выполнил',partial:'Частично',not_applied:'Не выполнил',no_opportunity:'Подходящей ситуации не было',uncertain:'Нужно посмотреть'};
function learningError(target,error,retry) {
  target.replaceChildren(node('p',`Не удалось открыть практику. ${error.message}`,'help'));
  const button=node('button','Повторить загрузку практики','quiet');button.type='button';button.addEventListener('click',retry);target.append(button);
}
async function loadReportLearning() {
  if(!state.user||!state.selected||state.showArchived||state.detail?.report_is_previous)return;
  const jobId=state.selected,request=++state.reportLearningRequest;
  if(!state.reportLearning)$('report-learning').replaceChildren(node('p','Подбираем упражнение по сохранённому разбору…','help'));
  try {
    const data=await api(`/api/learning/reports/${encodeURIComponent(jobId)}`);
    if(request!==state.reportLearningRequest||state.selected!==jobId||!state.user||state.showArchived)return;
    if(data.job_id!==jobId){
      if(!data.job_id||state.learningCanonicalTrail.has(data.job_id))throw Error('Не удалось определить актуальный разбор этого матча. Обнови страницу.');
      state.learningCanonicalTrail.add(jobId);state.reportLearning=null;
      $('report-learning').replaceChildren(node('p','Открываем актуальный разбор и его эпизоды…','help'));
      try{await openReplay(data.job_id,false,true);if(state.selected===data.job_id)notice('Открыт актуальный сохранённый разбор этого матча. Практика и таймкоды относятся к нему.');}catch(error){if(state.selected===data.job_id){state.selected=jobId;learningError($('report-learning'),error,()=>void loadReportLearning());}}return;
    }
    state.reportLearning=data;renderReportLearning();
  } catch(error) {if(request===state.reportLearningRequest&&state.selected===jobId&&!state.showArchived)learningError($('report-learning'),error,()=>void loadReportLearning());}
}
async function loadLearning({preserveView=false}={}) {
  if(!state.user)return;
  const request=++state.learningRequest,query=new URLSearchParams();
  if($('learning-hero')?.value)query.set('hero',$('learning-hero').value);
  if($('learning-position')?.value)query.set('position',$('learning-position').value);
  const scope=query.toString();
  if(state.learningScope!==scope){state.learning=null;state.learningStage=null;state.learningExercise=null;state.learningScope=scope;}
  $('learning-refresh-notice')?.remove();
  if(!state.learning)$('pool-learning').replaceChildren(node('p','Открываем упражнения и сохранённую практику…','help'));
  if($('learning-refresh'))$('learning-refresh').disabled=true;
  try {
    const data=await api(`/api/learning?${query}`);
    if(request!==state.learningRequest||!state.user)return;
    const selector=$('learning-hero');
    if(selector){
      const selected=selector.value,known=new Map(Array.from(selector.options).filter(option=>option.value).map(option=>[option.value,option.text]));
      for(const match of data.history??[])if(typeof match.hero==='string'&&/^npc_dota_hero_[a-z0-9_]{1,80}$/.test(match.hero))known.set(match.hero,match.label||heroName(match.hero));
      selector.replaceChildren(new Option('Все герои',''));
      for(const [hero,label]of Array.from(known).sort((a,b)=>a[1].localeCompare(b[1],'ru')))selector.append(new Option(label,hero));
      selector.value=selected;
    }
    const signature=JSON.stringify(data),unchanged=state.learning&&state.learningSignature===signature;
    state.learning=data;state.learningSignature=signature;if(!preserveView||!unchanged)renderLearning();
  } catch(error) {
    if(request!==state.learningRequest)return;
    if(preserveView&&state.learning){
      const message=node('p','Не удалось обновить практику. Сохранённый вид и твой ввод остались на странице. Нажми «Обновить практику», чтобы повторить.','help');message.id='learning-refresh-notice';message.setAttribute('role','status');$('pool-learning').prepend(message);
    }else {state.learningSignature=null;learningError($('pool-learning'),error,()=>void loadLearning());}
  }
  finally {if(request===state.learningRequest&&$('learning-refresh'))$('learning-refresh').disabled=false;}
}
function learningStatus(text) {const status=node('p',text,'help learning-status');status.setAttribute('role','status');return status;}
function learningDetails(title,text) {const details=node('details',undefined,'learning-details');details.append(node('summary',title),node('p',text,'help'));return details;}
function learningContext(hero,position) {return `${heroName(hero)||'Герой не выбран'} · ${positionName(position)}`;}
function validLearningPlan(plan) {return plan.status==='active'&&plan.validity==='current';}
function learningPlanText(plan) {
  if(plan.validity==='source_unavailable')return 'Исходный разбор недоступен. Выбери упражнение в доступном матче.';
  if(plan.validity==='source_changed')return 'Исходный разбор обновился. Выбери фокус по его новым данным.';
  if(plan.validity==='scope_changed')return 'Позиция исходного матча изменена. Выбери фокус для подтверждённой позиции.';
  return plan.status==='completed'?'Практика завершена тобой':plan.status==='paused'?'Практика на паузе':'Текущий фокус';
}
async function learningMutation(button,path,method,body,scope) {
  button.disabled=true;const status=scope.querySelector('.learning-status')??scope.appendChild(learningStatus(''));status.textContent='Сохраняем…';
  try {
    await api(path,method,body);
    if(scope.isConnected)status.textContent='Сохранено в аккаунте.';
    await Promise.all([loadReportLearning(),loadLearning()]);
  }catch(error){if(scope.isConnected)status.textContent=error.message;}
  finally{if(button.isConnected)button.disabled=false;}
}
function learningStartButton(card,exercise,jobId,currentPlan) {
  if(currentPlan?.exercise_id===exercise.id&&validLearningPlan(currentPlan))return;
  if(currentPlan&&validLearningPlan(currentPlan)){card.append(node('p','Сейчас в работе другой фокус. Приостанови или заверши его ниже, чтобы начать это упражнение.','help'));return;}
  const button=node('button','Начать практику · 3–5 игр','secondary learning-start');button.type='button';button.disabled=!jobId;
  button.addEventListener('click',()=>void learningMutation(button,'/api/learning/plans','POST',{job_id:jobId,exercise_id:exercise.id},card));card.append(button,learningStatus(''));
}
function learningExerciseCard(exercise,{hero,position,jobId,suggestion,currentPlan}={}) {
  const card=node('article',undefined,'learning-exercise');card.dataset.exerciseId=exercise.id;
  card.append(node('p',hero?learningContext(hero,position):'Упражнение по методике Narma','eyebrow'),node('h4',exercise.title));
  if(suggestion?.observation){const observed=node('div',undefined,'learning-observation');observed.append(node('p',suggestion.kind==='episode_review'?'Эпизод для проверки':'Выбрано для самостоятельной проверки','eyebrow'),node('p',suggestion.observation,'help'));if(suggestion.limitation)observed.append(node('p',suggestion.limitation,'help'));card.append(observed);}
  card.append(node('p',exercise.decision_question,'learning-question'),node('p',exercise.action,'learning-action'));
  const rationale=node('div',undefined,'learning-rationale');rationale.append(node('strong','Почему это помогает'),node('p',exercise.why,'help'));card.append(rationale);
  if(exercise.exception){const exception=node('div',undefined,'learning-instruction');exception.append(node('strong','Когда выбрать другое действие'),node('p',exercise.exception,'help'));card.append(exception);}
  const details=node('details',undefined,'learning-details');details.append(node('summary','Когда применять и как тренировать'));
  for(const [label,value] of [['Сигнал',exercise.signal],['Упражнение',exercise.drill],['Как проверить',exercise.measurement],['Пример',exercise.mini_lesson]])if(value){const part=node('div',undefined,'learning-instruction');part.append(node('strong',label),node('p',value,'help'));details.append(part);}
  card.append(details);
  if(suggestion?.evidence_ids?.length&&jobId===state.selected){const links=node('div',undefined,'evidence-links');for(const id of suggestion.evidence_ids.slice(0,2)){const ref=state.evidence.get(id);if(!ref)continue;const button=node('button',`${stamp(ref.time)} · ${eventLabels[ref.type]??'Эпизод'}`,'quiet');button.type='button';button.addEventListener('click',()=>focusEvidence(id));links.append(button);}card.append(links);}
  if(hero&&position&&jobId)learningStartButton(card,exercise,jobId,currentPlan);
  else card.append(node('p',hero?position?'Для сохранения практики нужен разбор этого героя на выбранной позиции.':'Укажи позицию в матче, чтобы сохранить практику.':'Для сохранения практики выбери героя и позицию. Упражнения можно изучать без реплея.','help'));
  return card;
}
function renderReportLearning() {
  const target=$('report-learning');target.replaceChildren();
  if(state.showArchived||state.detail?.report_is_previous){target.append(node('p','Для практики открой текущий разбор: упражнение привязывается к его событиям.','help'));return;}
  const data=state.reportLearning;if(!data){target.append(node('p','Подбираем упражнение по сохранённому разбору…','help'));return;}
  const role=node('div',undefined,'learning-role'),label=node('label','Моя позиция в этом матче'),select=node('select');select.id='learning-report-position';label.htmlFor=select.id;select.append(new Option('Подтверди позицию',''));for(const [value,text]of Object.entries(positionLabels))select.append(new Option(text,value));select.value=data.position??'';
  select.addEventListener('change',async()=>{select.disabled=true;state.reportLearningRequest++;const status=learningStatus('Сохраняем позицию…');role.append(status);try{await api(`/api/hero-pool/matches/${encodeURIComponent(data.job_id)}`,'PUT',{position:select.value?Number(select.value):null});state.reportLearning=null;state.reportExercise=null;await openReplay(state.selected);await loadLearning({preserveView:true});if(state.pool)await loadPool();}catch(error){status.textContent=error.message;select.disabled=false;}});
  role.append(label,select,node('p',data.position_required?'Позиция не определяется по имени героя. Подтверди, какую работу ты выполнял.':'Позиция указана тобой. Упражнения учитывают героя и эту позицию.','help'));target.append(role);
  const guidance=roleGuidance(data.role_context??data.catalog?.role_context);if(guidance)target.append(guidance);
  const exercises=data.catalog?.exercises??[],active=(data.plans??[]).find(validLearningPlan);
  let exercise=exercises.find(item=>item.id===state.reportExercise)??exercises.find(item=>item.id===active?.exercise_id)??exercises.find(item=>item.id===data.suggestions?.[0]?.exercise_id)??exercises[0];
  if(!exercise){target.append(node('p','Выбери позицию, чтобы открыть подходящее упражнение.','help'));return;}
  state.reportExercise=exercise.id;
  const choice=node('select'),choiceLabel=node('label','Фокус следующей игры');choice.id='learning-report-exercise';choiceLabel.htmlFor=choice.id;for(const item of exercises)choice.append(new Option(item.title,item.id));choice.value=exercise.id;choice.addEventListener('change',()=>{state.reportExercise=choice.value;renderReportLearning();$('learning-report-exercise')?.focus({preventScroll:true});});target.append(choiceLabel,choice);
  target.append(learningExerciseCard(exercise,{hero:data.hero,position:data.position,jobId:data.position?data.job_id:null,suggestion:data.suggestions?.find(item=>item.exercise_id===exercise.id),currentPlan:active}));
  if(active)target.append(learningPlanCard(active,[{job_id:data.job_id,match_id:data.match_id,hero:data.hero,position:data.position}],data));
  else if(data.plans?.length)target.append(learningPlanCard(data.plans[0],[],data));
}
function renderLearning() {
  const target=$('pool-learning'),data=state.learning;target.replaceChildren();if(!data)return;
  const stages=data.catalog?.stages??[],exercises=data.catalog?.exercises??[],plans=data.plans??[];
  const hero=$('learning-hero')?.value??'',position=Number($('learning-position')?.value)||null,scopeReady=!!hero&&!!position;
  const guidance=roleGuidance(data.role_context??data.catalog?.role_context);if(guidance)target.append(guidance);
  const current=scopeReady?plans.find(plan=>validLearningPlan(plan)&&plan.hero===hero&&plan.position===position):null;
  const preferred=exercises.find(item=>item.id===current?.exercise_id),firstAvailable=stages.find(stage=>exercises.some(exercise=>exercise.stage_id===stage.id));if(!stages.some(stage=>stage.id===state.learningStage))state.learningStage=preferred?.stage_id??firstAvailable?.id??stages[0]?.id;
  const rail=node('div',undefined,'learning-stages');rail.setAttribute('role','group');rail.setAttribute('aria-label','Ступени обучения');
  for(const stage of stages){const button=node('button',`${stage.order} · ${stage.title}`,'quiet');button.type='button';button.setAttribute('aria-pressed',String(stage.id===state.learningStage));button.addEventListener('click',()=>{state.learningStage=stage.id;state.learningExercise=null;renderLearning();Array.from($('pool-learning').querySelectorAll('.learning-stages button')).find(item=>item.getAttribute('aria-pressed')==='true')?.focus({preventScroll:true});});rail.append(button);}target.append(rail);
  const stage=stages.find(item=>item.id===state.learningStage);if(stage?.description)target.append(node('p',stage.description,'help'));
  const available=exercises.filter(item=>item.stage_id===state.learningStage),exercise=available.find(item=>item.id===state.learningExercise)??available.find(item=>item.id===current?.exercise_id)??available[0];
  if(exercise){state.learningExercise=exercise.id;if(available.length>1){const label=node('label','Упражнение ступени'),select=node('select');select.id='learning-pool-exercise';label.htmlFor=select.id;for(const item of available)select.append(new Option(item.title,item.id));select.value=exercise.id;select.addEventListener('change',()=>{state.learningExercise=select.value;renderLearning();$('learning-pool-exercise')?.focus({preventScroll:true});});target.append(label,select);}
    const match=(data.history??[]).find(item=>item.hero===hero&&item.position===position&&(!item.report_state||item.report_state==='ready'));
    target.append(learningExerciseCard(exercise,{hero:scopeReady?hero:null,position,jobId:scopeReady?match?.job_id:null,currentPlan:current}));
  }else target.append(node('p','Для упражнений линии выбери позицию: задачи коров и поддержки различаются.','help'));
  if(current)target.append(learningPlanCard(current,data.history??[]));
  const other=plans.filter(plan=>plan.id!==current?.id);if(other.length){const details=node('details',undefined,'learning-details learning-plan-history');details.append(node('summary',scopeReady?'Другие сохранённые фокусы':'Сохранённые фокусы по героям и позициям'));let loaded=false;details.addEventListener('toggle',()=>{if(details.open&&!loaded){loaded=true;for(const plan of other)details.append(learningPlanCard(plan,data.history??[]));}});target.append(details);}
  target.append(node('p','Личные отметки помогают разбирать решения. Они не подтверждают освоение ступени автоматически; винрейт оценивай вместе с числом матчей.','help'));
}
function learningPlanCard(plan,history,reportData=null) {
  const card=node('article',undefined,'learning-plan');card.dataset.planId=plan.id;
  card.append(node('p',learningPlanText(plan),'eyebrow'),node('h4',`${plan.exercise?.title??'Практика'} · ${learningContext(plan.hero,plan.position)}`));
  const counts=node('p',`Матчей практики: ${num(plan.training_matches??0)} · личных проверок: ${num(plan.reviewed_matches??0)}`,'help');card.append(counts);
  if(plan.comparison_note)card.append(node('p',plan.comparison_note,'help'));
  if(plan.training_matches>0){const results=Object.entries(learningAssessmentLabels).map(([key,label])=>`${label.toLowerCase()}: ${num(plan.self_report_counts?.[key]??0)}`);card.append(node('p',`Твои отметки в новых матчах: ${results.join(' · ')}. Это не автоматическая оценка навыка.`,'help'));}
  if(plan.stale_checks>0)card.append(node('p',`Проверок с изменёнными или недоступными данными: ${num(plan.stale_checks)}. Они не входят в прогресс практики.`,'help'));
  if(!(plan.training_matches>0))card.append(node('p','Новых отмеченных матчей практики пока нет. Исходный матч и матчи без подтверждённой даты не показывают прогресс после начала задания.','help learning-no-matches'));
  const actions=node('div',undefined,'learning-actions');
  const transitions=plan.status==='active'?[['paused','Пауза'],['completed','Завершить практику']]:plan.status==='paused'?[...(plan.validity==='current'?[['active','Продолжить практику']]:[]),['completed','Завершить практику']]:plan.validity==='current'?[['active','Вернуть в практику']]:[];
  for(const [status,label]of transitions){const button=node('button',label,'quiet');button.type='button';button.addEventListener('click',()=>void learningMutation(button,`/api/learning/plans/${encodeURIComponent(plan.id)}`,'PATCH',{status},card));actions.append(button);}card.append(actions);
  if(plan.can_check&&plan.validity==='current') {
    const comparable=history.filter(match=>match.hero===plan.hero&&match.position===plan.position&&(!match.report_state||match.report_state==='ready'));
    if(comparable.length){const form=learningCheckForm(plan,comparable,reportData);if(reportData)card.append(form);else{const check=node('details',undefined,'learning-details learning-check-toggle');check.append(node('summary','Проверить матч по этому фокусу'),form);card.append(check);}}
    else card.append(node('p','Открой или загрузи матч этого героя на этой позиции для личной проверки.','help'));
  }
  const checks=plan.checks??[];if(checks.length){const details=node('details',undefined,'learning-details learning-check-history');details.append(node('summary',`История личных проверок · ${checks.length}`));for(const check of checks){const row=node('div',undefined,'learning-check-row');row.append(poolMatchButton(check,`Матч ${check.match_id}`),node('p',`Твоя оценка: ${learningAssessmentLabels[check.self_assessment]??'Нужно посмотреть'}`,'help'),node('p',check.answer,'learning-answer'));if(check.validity!=='current')row.append(node('p','Данные матча изменились или недоступны. Эта отметка требует повторной проверки.','help'));else if(!check.is_training)row.append(node('p',check.chronology_status==='baseline'?'Исходный матч · точка отсчёта':check.chronology_status==='date_unknown'?'Дата игры не подтверждена · вне счётчика практики':check.build_status==='different_build'?'Другая версия игры · вне серии практики':'Матч до начала практики · вне счётчика практики','help'));details.append(row);}card.append(details);}
  card.append(learningStatus(''));return card;
}
function learningCheckForm(plan,matches,reportData) {
  const instance=reportData?'report':'pool',prefix=`learning-${instance}-${plan.id}`,form=node('form',undefined,'learning-check-form');form.append(node('h5','Личная проверка'),node('p','Это твоя оценка решения, а не подтверждённый вывод по реплею. Ответ и отметка сохранятся в аккаунте.','help'));
  const matchLabel=node('label','Матч для проверки'),matchSelect=node('select');matchSelect.id=`${prefix}-match`;matchLabel.htmlFor=matchSelect.id;for(const match of matches)matchSelect.append(new Option(`#${match.match_id}`,match.job_id));const selected=state.learningMatches.get(prefix);if(matches.some(match=>match.job_id===selected))matchSelect.value=selected;
  const episodeLabel=node('label','Эпизод из разбора'),episodeSelect=node('select');episodeSelect.id=`${prefix}-episode`;episodeLabel.htmlFor=episodeSelect.id;episodeSelect.append(new Option('Весь контекст матча / подходящей ситуации нет',''));
  const question=node('label',plan.exercise?.decision_question??'Чего ты хотел добиться и что получилось?'),answer=node('textarea',undefined,'pool-note');answer.id=`${prefix}-answer`;question.htmlFor=answer.id;answer.maxLength=1500;answer.required=true;answer.rows=3;answer.placeholder='Что я знал до решения, чего хотел и что попробую иначе';
  const assessmentLabel=node('label','Твоя оценка выполнения'),assessment=node('select');assessment.id=`${prefix}-assessment`;assessmentLabel.htmlFor=assessment.id;assessment.append(new Option('Выбери свою оценку',''));assessment.required=true;for(const [value,label]of Object.entries(learningAssessmentLabels))assessment.append(new Option(label,value));
  const help=node('p','Для оценки конкретного эпизода выбери событие. Если ситуации не было или данных недостаточно, отметь это явно.','help'),save=node('button','Сохранить личную проверку','secondary');save.type='submit';const status=learningStatus('');
  form.append(matchLabel,matchSelect,episodeLabel,episodeSelect,question,answer,assessmentLabel,assessment,help,save,status);
  let request=0,currentJob=matchSelect.value;
  const key=()=>`${plan.id}:${currentJob}`;
  const values=()=>({evidence_id:episodeSelect.value||null,answer:answer.value,self_assessment:assessment.value});
  const remember=()=>{state.learningDrafts.set(key(),values());status.textContent='Есть несохранённые изменения.';};
  const populate=async()=>{
    currentJob=matchSelect.value;state.learningMatches.set(prefix,currentJob);const requestId=++request;
    const stored=state.learningDrafts.get(key())??(plan.checks??[]).find(check=>check.job_id===currentJob)??{};answer.value=stored.answer??'';assessment.value=stored.self_assessment??'';
    episodeSelect.replaceChildren(new Option('Весь контекст матча / подходящей ситуации нет',''));episodeSelect.disabled=true;save.disabled=true;status.textContent='Загружаем эпизоды…';
    try{const data=reportData?.job_id===currentJob?reportData:await api(`/api/learning/reports/${encodeURIComponent(currentJob)}`);if(requestId!==request||!form.isConnected)return;
      const types=plan.exercise?.evidence_types??[],candidates=data.exercise_candidates?.[plan.exercise_id]??data.review_candidates??[];for(const ref of candidates)if(!types.length||types.includes(ref.type))episodeSelect.append(new Option(`${stamp(ref.time)} · ${ref.title??eventLabels[ref.type]??'Эпизод'}`,ref.evidence_id));
      if(Array.from(episodeSelect.options).some(option=>option.value===stored.evidence_id))episodeSelect.value=stored.evidence_id;
      episodeSelect.disabled=false;save.disabled=false;status.textContent=state.learningDrafts.has(key())?'Есть несохранённые изменения.':'';
    }catch(error){if(requestId===request)status.textContent=`Не удалось загрузить эпизоды. ${error.message}`;}
  };
  for(const control of [episodeSelect,answer,assessment])control.addEventListener('input',remember);
  matchSelect.addEventListener('change',()=>void populate());
  form.addEventListener('submit',async event=>{event.preventDefault();const submitted={job_id:currentJob,...values()};if(!submitted.answer.trim()){answer.focus();return;}if(!submitted.evidence_id&&plan.exercise?.review_mode==='episode_review'&&!['no_opportunity','uncertain'].includes(submitted.self_assessment)){status.textContent='Выбери эпизод, к которому относится оценка, или отметь, что подходящей ситуации не было.';episodeSelect.focus();return;}
    const draftKey=key();state.learningDrafts.set(draftKey,values());const controls=[matchSelect,episodeSelect,answer,assessment,save];for(const control of controls)control.disabled=true;status.textContent='Сохраняем личную проверку…';
    try{await api(`/api/learning/plans/${encodeURIComponent(plan.id)}/checks`,'PUT',submitted);state.learningDrafts.delete(draftKey);await Promise.all([loadReportLearning(),loadLearning()]);const replacement=$(`${prefix}-answer`);replacement?.closest('form')?.querySelector('.learning-status')?.replaceChildren(document.createTextNode('Личная проверка сохранена в аккаунте.'));replacement?.focus({preventScroll:true});}
    catch(error){status.textContent=error.message;for(const control of controls)control.disabled=false;}
  });
  // The form must be connected before an immediately available report is applied.
  queueMicrotask(()=>void populate());return form;
}
