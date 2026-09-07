const $ = id => document.getElementById(id);
const state = {user:null, profile:null, setup:false, token:new URLSearchParams(location.hash.slice(1)).get('token'), selected:null, detail:null, busy:false, uploadId:null, time:0, evidence:new Map(), graphs:[]};
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
const eventLabels = {death:'Смерть',kill:'Убийство',assist:'Помощь',purchase:'Покупка',buyback:'Выкуп',respawn:'Возвращение',reincarnation:'Реинкарнация',tower:'Башня',ward_destroyed:'Сломанный вард',ward_item_used:'Применение предмета с вардами'};
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
function switchTab(tab) {
  if(!['review','player','account'].includes(tab)) return;
  for(const section of document.querySelectorAll('.tab-section')) section.hidden=section.id!==tab;
  for(const button of document.querySelectorAll('nav [data-tab]')) { if(button.dataset.tab===tab) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current'); }
}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>switchTab(button.dataset.tab)));
switchTab(location.pathname==='/account'?'account':'review');
function buttons() {
  $('replay-submit').disabled=state.busy || !$('replay-file').files[0] || (!state.profile && !$('nickname').value.trim());
  $('replay-file').disabled=state.busy; $('nickname').disabled=state.busy;
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
    $('auth-title').textContent=state.setup?'Создай свой аккаунт':'Вход в NARMA VISION';
    $('auth-copy').textContent=state.setup?'Первый вход владельца платформы. Придумай отдельный пароль для NARMA VISION.':'Войди, чтобы загрузить реплей и посмотреть разбор своего матча.';
    $('auth-submit').textContent=state.setup?'Создать аккаунт':'Войти'; $('auth-submit').disabled=state.setup&&!state.token;
    $('setup-help').hidden=!state.setup||!!state.token; $('password-help').hidden=!state.setup; $('password').autocomplete=state.setup?'new-password':'current-password'; return;
  }
  $('account-email').textContent=state.user.email; state.profile=(await api('/api/profile')).profile; profileView(); await refresh();
}
$('auth-form').addEventListener('submit',async event=>{
  event.preventDefault(); notice(); const button=$('auth-submit'); button.disabled=true;
  try { await api(state.setup?'/api/auth/setup':'/api/auth/login','POST',{email:$('email').value.trim(),password:$('password').value,...(state.setup?{token:state.token}:{})}); state.token=null; $('password').value=''; await session(); }
  catch(error) { notice(error.message); } finally { button.disabled=state.setup&&!state.token; }
});
$('logout').addEventListener('click',async()=>{ try { await api('/api/auth/logout','POST',{}); location.reload(); } catch(error) { notice(error.message); } });
$('password-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=event.target.querySelector('button'); button.disabled=true;
  try { await api('/api/auth/password','POST',{current_password:$('current-password').value,new_password:$('new-password').value}); $('current-password').value=''; $('new-password').value=''; state.user=null; await session(); notice('Пароль изменён. Войди с новым паролем.'); }
  catch(error) { notice(error.message); } finally { button.disabled=false; }
});
$('replay-file').addEventListener('change',()=>{ state.uploadId=null; buttons(); });
$('nickname').addEventListener('input',()=>{ state.uploadId=null; buttons(); });
$('replay-form').addEventListener('submit',async event=>{
  event.preventDefault(); const file=$('replay-file').files[0]; if(!file||state.busy) return;
  if(!/\.dem$/i.test(file.name)||file.size>512*1024**2||file.size<20) return notice('Выбери полный файл .dem размером до 512 МБ.');
  state.busy=true; buttons(); notice(); $('replay-progress').hidden=false; $('upload-status').textContent='Начинаем загрузку реплея…';
  try {
    state.uploadId??=crypto.randomUUID(); const id=state.uploadId;
    const init=await api('/api/replays','POST',{id,filename:file.name,size_bytes:file.size,...(!state.profile?{nickname:$('nickname').value.trim()}:{})});
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
  const history=$('history'); history.replaceChildren();
  if(!data.replays.length) history.append(node('p','Загрузи реплей — здесь появится твой первый матч.','empty'));
  for(const item of data.replays) {
    const row=node('article',undefined,'history-row'), info=node('div'), actions=node('div',undefined,'history-actions');
    info.append(node('p',item.match_id?`Матч ${item.match_id}`:item.filename,'history-name'),node('p',`${labels[item.state]??item.state} · ${item.nickname}`,'history-meta'));
    if(item.state==='processing') info.append(node('p',`${num(item.progress)}%`,'history-meta'));
    const open=node('button','Открыть'); open.addEventListener('click',()=>void openReplay(item.id,true).catch(error=>notice(error.message)));
    const remove=node('button','Удалить','delete'); remove.disabled=state.busy;
    remove.addEventListener('click',async()=>{ if(!confirm('Удалить этот реплей и его разбор?')) return; try { await api('/api/replays/'+item.id,'DELETE'); if(state.selected===item.id) { state.selected=null; state.detail=null; $('result').hidden=true; } await refresh(); } catch(error) { notice(error.message); } });
    actions.append(open,remove); row.append(info,actions); history.append(row);
  }
}
function svgNode(tag, attributes) { const element=document.createElementNS('http://www.w3.org/2000/svg',tag); for(const [key,value] of Object.entries(attributes)) element.setAttribute(key,String(value)); return element; }
function drawGraph(id, samples, key, duration) {
  const svg=$(id); svg.replaceChildren();
  const valid=samples.filter(sample=>Number.isFinite(sample[key])); const max=Math.max(1,...valid.map(sample=>sample[key]));
  const x=time=>20+Math.max(0,Math.min(duration,time))/Math.max(1,duration)*480;
  const y=value=>138-Math.max(0,value)/max*118;
  svg.append(svgNode('line',{x1:20,y1:138,x2:500,y2:138,class:'chart-axis'}));
  const top=svgNode('text',{x:20,y:14,class:'chart-axis-label'}); top.textContent=num(max); svg.append(top);
  const zero=svgNode('text',{x:20,y:155,class:'chart-axis-label'}); zero.textContent='0:00'; svg.append(zero);
  const end=svgNode('text',{x:500,y:155,'text-anchor':'end',class:'chart-axis-label'}); end.textContent=stamp(duration); svg.append(end);
  if(valid.length) svg.append(svgNode('polyline',{points:valid.map(sample=>`${x(sample.time).toFixed(2)},${y(sample[key]).toFixed(2)}`).join(' '),class:'chart-line',fill:'none','vector-effect':'non-scaling-stroke'}));
  const cursor=svgNode('line',{x1:20,x2:20,y1:20,y2:138,class:'chart-cursor'}); svg.append(cursor);
  state.graphs.push({cursor,x});
}
function seekTime(seconds, evidenceId=null) {
  const report=state.detail?.report; if(!report) return;
  const duration=Math.max(1,report.metrics?.duration_seconds??0); state.time=Math.max(0,Math.min(duration,seconds));
  $('timeline').value=String(Math.round(state.time)); $('timeline-value').textContent=stamp(state.time);
  const samples=(report.economy??[]).filter(sample=>Number.isFinite(sample.time)&&sample.time<=state.time);
  const snapshot=samples.at(-1);
  $('gold-value').textContent=num(snapshot?.net_worth); $('xp-value').textContent=num(snapshot?.xp);
  $('timeline-snapshot').textContent=snapshot?`${stamp(snapshot.time)} · Уровень ${num(snapshot.level)} · ${num(snapshot.kills)} / ${num(snapshot.deaths)} / ${num(snapshot.assists)} · Добивания ${num(snapshot.last_hits)} / ${num(snapshot.denies)}`:'До первого снимка статистики. Выбери более поздний момент.';
  for(const graph of state.graphs) { graph.cursor.setAttribute('x1',String(graph.x(state.time))); graph.cursor.setAttribute('x2',String(graph.x(state.time))); }
  for(const row of $('events').children) row.classList.toggle('selected-event',row.dataset.evidenceId===evidenceId);
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
  for(const evidence of state.detail?.report?.evidence??[]) {
    if(filter!=='all' && evidence.type!==filter) continue;
    const row=node('article',undefined,'event-row'); row.dataset.evidenceId=evidence.id;
    const time=node('button',stamp(evidence.time),'event-time'); time.setAttribute('aria-label',`Выбрать время ${stamp(evidence.time)}`); time.addEventListener('click',()=>seekTime(evidence.time,evidence.id));
    const copy=node('div'); copy.append(node('p',`${eventLabels[evidence.type]??'Событие'} · ${evidence.title??''}`,'event-title')); if(evidence.details) copy.append(node('p',evidence.details,'help'));
    row.append(time,copy); list.append(row);
  }
  if(!list.childElementCount) list.append(node('p','Таких событий в журнале нет.','empty'));
}
function renderDetail() {
  const detail=state.detail; if(!detail) return; const job=detail.replay, report=detail.report;
  $('result').hidden=false; $('result-title').textContent=job.match_id?`Матч ${job.match_id}`:job.filename; $('result-state').textContent=labels[job.state]??job.state;
  $('result-player').textContent=report?`${report.player.nickname} · ${heroName(report.player.hero)} · ${report.player.team==='radiant'?'Radiant':'Dire'}${report.outcome==='win'?' · Победа':report.outcome==='loss'?' · Поражение':''}`:job.nickname;
  $('analysis-progress').hidden=job.state!=='processing'; $('analysis-progress').value=job.progress??0;
  $('result-status').textContent=job.state==='failed'?(failures[job.failure_code]??'Не удалось завершить разбор этого реплея. Повтори загрузку полного файла .dem.'):job.state==='queued'?'Реплей загружен. Ожидаем начало разбора.':job.state==='processing'?`Читаем события матча и готовим разбор · ${num(job.progress)}%`:job.state==='uploading'?'Реплей ещё загружается.':report?`Полный матч · ${stamp(report.metrics?.duration_seconds)} · Разбор закреплённого игрока`:'Результат ещё не получен.';
  $('report-body').hidden=!report; if(!report) return;
  state.evidence=new Map((report.evidence??[]).map(event=>[event.id,event]));
  const metrics=$('metrics'); metrics.replaceChildren(); const m=report.metrics??{};
  for(const [label,value] of [['Убийства / смерти / помощи',`${num(m.kills)} / ${num(m.deaths)} / ${num(m.assists)}`],['Добивания / денаи',`${num(m.last_hits)} / ${num(m.denies)}`],['Ценность предметов и золота',num(m.net_worth)],['Всего заработано золота',num(m.total_earned_gold)],['Полученный опыт',num(m.xp)],['Время вне игры',stamp(m.confirmed_dead_seconds)]]) { const metric=node('div',undefined,'metric'); metric.append(node('dt',label),node('dd',value)); metrics.append(metric); }
  const duration=Math.max(1,m.duration_seconds??0), samples=(report.economy??[]).filter(sample=>Number.isFinite(sample.time)&&sample.time>=0&&sample.time<=duration);
  $('timeline').max=String(Math.ceil(duration)); state.graphs=[]; drawGraph('gold-chart',samples,'net_worth',duration); drawGraph('xp-chart',samples,'xp',duration);
  renderPoints($('findings'),report.findings); renderEvents();
  const coach=report.coaching; $('coaching-section').hidden=false;
  if(coach?.status==='ready') { $('coaching-summary').textContent=coach.summary??''; renderPoints($('coaching'),coach.points); }
  else { $('coaching-summary').textContent='Тренерский комментарий временно недоступен. Статистика и эпизоды из реплея доступны.'; $('coaching').replaceChildren(); }
  const coverage=report.coverage??{}; $('coverage-summary').textContent=coverage.complete?'Реплей прочитан полностью. Статистика и события относятся к закреплённому игроку.':'Полнота данных не подтверждена.';
  $('coverage-limits').replaceChildren(...(coverage.limits??[]).map(limit=>node('li',limit)));
  seekTime(state.time);
}
async function openReplay(id, scroll=false) {
  const changed=state.selected!==id; state.selected=id; const detail=await api('/api/replays/'+id); if(state.selected!==id) return;
  if(changed||(!state.detail?.report&&detail.report)) { state.time=detail.report?.metrics?.duration_seconds??0; $('event-filter').value='all'; }
  state.detail=detail; renderDetail(); if(scroll) $('result').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}
$('timeline').addEventListener('input',()=>seekTime(Number($('timeline').value)));
$('event-filter').addEventListener('change',renderEvents);
for(const id of ['gold-chart','xp-chart']) $(id).addEventListener('click',event=>{ const duration=state.detail?.report?.metrics?.duration_seconds; if(!duration) return; const box=$(id).getBoundingClientRect(), relative=(event.clientX-box.left)/box.width*520; seekTime((relative-20)/480*duration); });
$('refresh').addEventListener('click',()=>void refresh().then(()=>state.selected?openReplay(state.selected):undefined).catch(error=>notice(error.message)));
setInterval(()=>{ if(!state.user||document.hidden||state.busy) return; void refresh().then(()=>{ if(state.selected&&['queued','processing'].includes(state.detail?.replay.state)) return openReplay(state.selected); }).catch(error=>notice(error.message)); },10000);
void session().catch(error=>{ $('loading').textContent='Не удалось открыть кабинет.'; notice(error.message); });
