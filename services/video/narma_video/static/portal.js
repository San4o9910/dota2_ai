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
const sourceColors=['#dcc071','#9fc5a8','#91b8d8','#c1a2d5','#d49b8a','#b7bdad','#d5bba3'];
function finite(value) { return typeof value==='number' && Number.isFinite(value); }
function itemName(value) { return String(value??'Предмет').replace(/^item_/,'').split('_').map(word=>word.charAt(0).toUpperCase()+word.slice(1)).join(' '); }
function insight() { return state.detail?.report?.insights??{}; }
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
  for(const event of state.detail.report.evidence??[]) {
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
  const report=state.detail?.report; if(!report) return;
  const data=insight(), select=bins=>(bins??[]).find(bin=>state.time>=bin.start&&(state.time<bin.end||(state.time===report.metrics?.duration_seconds&&state.time===bin.end))), bin=select(data.gold?.bins), pace=select(data.pace);
  $('income-value').textContent=bin?num(bin.income):'—'; $('farm-value').textContent=pace?num(pace.last_hits):'—';
  $('income-window').textContent=bin?`${stamp(bin.start)}–${stamp(bin.end)} · Потери: ${num(bin.loss)} золота`:'Выбери интервал на общей шкале.';
  const target=$('moment-summary'); target.replaceChildren(); target.append(node('p',`На отметке ${stamp(state.time)}`,'eyebrow'));
  if(pace) { target.append(node('h4',`${num(pace.last_hits)} добиваний · ${num(pace.kills)} убийств · ${num(pace.assists)} помощи`)); target.append(node('p',`${stamp(pace.start)}–${stamp(pace.end)} · ${num(pace.deaths)} смертей · ${num(pace.xp)} опыта`,'help')); }
  const sources=new Map((data.gold?.sources??[]).map(source=>[source.key,source.label]));
  if(bin) { const parts=Object.entries(bin.by_source??{}).filter(([,amount])=>finite(amount)&&amount>0).map(([key,amount])=>`${sources.get(key)??key}: ${num(amount)}`); target.append(node('p',parts.length?parts.join(' · '):'Дохода в журнале за эту минуту нет.','help')); }
  if(!pace&&!bin) target.append(node('p','Для этой минуты подробных счётчиков нет. Снимок общей статистики указан под шкалой времени.','help'));
  for(const card of $('item-cards').children) card.classList.toggle('item-selected',finite(Number(card.dataset.time))&&Math.abs(Number(card.dataset.time)-state.time)<1);
}
function itemGoalKey(item) { const player=state.detail?.report?.player??{}; return `narma.item-goal.v1:${player.account_id??'unknown'}:${player.hero??'unknown'}:${item.item}`; }
function readGoal(item) { try { const value=localStorage.getItem(itemGoalKey(item)); return value&&/^\d{1,3}:[0-5]\d$/.test(value)?value:''; } catch { return ''; } }
function goalSeconds(text) { if(!/^\d{1,3}:[0-5]\d$/.test(text)) return null; const [minutes,seconds]=text.split(':').map(Number); return minutes*60+seconds; }
function renderItems() {
  const report=state.detail.report, data=insight(), provided=Array.isArray(data.items), items=provided?data.items:(report.inventory??[]).filter(entry=>finite(entry.time)).map((entry,index)=>({id:`legacy-${index}`,item:entry.item,label:itemName(entry.item),time:entry.time,event_id:entry.event_id,acquisition:'purchase',timing:{label:'Без эталона',basis:'Нет сопоставимого ориентира по герою, роли и рейтингу.'},realization:{note:'В этом отчёте нет данных о доставке и применении предмета.'}}));
  const rail=$('item-rail'), cards=$('item-cards'); rail.replaceChildren(); cards.replaceChildren(); $('item-count').textContent=`${items.length} предметов`;
  if(!items.length) { cards.append(node('p','В этом отчёте нет подтверждённых покупок ключевых предметов.','muted')); return; }
  for(const [index,item] of items.entries()) {
    const label=item.label??itemName(item.item), card=node('article',undefined,'item-card'); card.dataset.time=String(item.time);
    rail.append(timeButton(item.time,label,'item-chip'));
    const heading=node('div',undefined,'item-heading'), identity=node('div',undefined,'item-identity'), icon=node('span',String(index+1).padStart(2,'0'),'item-number'); icon.setAttribute('aria-hidden','true'); identity.append(icon,node('h4',label)); heading.append(identity,timeButton(item.time,item.acquisition==='inventory'?'В инвентаре':'Покупка'));
    card.append(heading);
    const timing=node('div',undefined,'item-timing'), badge=node('span',item.timing?.label??'Без эталона','timing-badge'), basis=node('p',item.timing?.basis??'Нет сопоставимого ориентира по герою, роли и рейтингу.','help'); timing.append(badge,basis); card.append(timing);
    const steps=node('dl',undefined,'item-steps');
    for(const [title,value] of [['Первый снимок у героя',item.first_hero_inventory_time],['В активном слоте',item.first_active_inventory_time],['Первое применение',item.realization?.first_use_time]]) { const row=node('div'), amount=node('dd'); if(finite(value)) {const button=timeButton(value,'','item-step-time');button.setAttribute('aria-label',`${title}: ${stamp(value)}`);amount.append(button);} else amount.textContent='—'; row.append(node('dt',title),amount); steps.append(row); }
    card.append(steps);
    const realization=item.realization??{}, summary=node('div',undefined,'item-realization');
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
function renderTraining() {
  const target=$('next-game-plan'), coach=state.detail.report.coaching, plans=coach?.status==='ready'&&coach.next_game?.length?coach.next_game:insight().training_plan??[]; target.replaceChildren();
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
  const report=state.detail?.report; if(!report) return;
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
  drawBars('income-chart',insight().gold?.bins??[],'income',duration); drawBars('farm-chart',insight().pace??[],'last_hits',duration); drawCombat(duration); renderSources(); renderItems(); renderTraining();
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
for(const id of ['gold-chart','xp-chart','income-chart','farm-chart']) $(id).addEventListener('click',event=>{ const duration=state.detail?.report?.metrics?.duration_seconds; if(!duration) return; const box=$(id).getBoundingClientRect(), relative=(event.clientX-box.left)/box.width*520; seekTime((relative-20)/480*duration); });
$('refresh').addEventListener('click',()=>void refresh().then(()=>state.selected?openReplay(state.selected):undefined).catch(error=>notice(error.message)));
setInterval(()=>{ if(!state.user||document.hidden||state.busy) return; void refresh().then(()=>{ if(state.selected&&['queued','processing'].includes(state.detail?.replay.state)) return openReplay(state.selected); }).catch(error=>notice(error.message)); },10000);
void session().catch(error=>{ $('loading').textContent='Не удалось открыть кабинет.'; notice(error.message); });
