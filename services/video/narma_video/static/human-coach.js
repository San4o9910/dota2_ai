import {profileAnswerRows} from './player-profile.js';
// Human training workspace: every read/write is authorized again on the server.
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
const button=(text,action,cls='secondary')=>{const b=el('button',text,cls);b.type='button';b.addEventListener('click',action);return b;};
const stamp=s=>Number.isFinite(s)?`${s<0?'−':''}${Math.floor(Math.abs(s)/60)}:${String(Math.floor(Math.abs(s)%60)).padStart(2,'0')}`:'—';
const hero=s=>String(s||'Герой').replace(/^npc_dota_hero_/,'').replaceAll('_',' ');
const taskStates={assigned:'В работе',submitted:'Ждёт проверки',changes_requested:'Нужно уточнение',completed:'Проверено тренером',archived:'В архиве'};
const profileStates={pending:'Заявка на рассмотрении',approved:'Доступ тренера подтверждён',suspended:'Доступ тренера приостановлен'};
let serial=0;
function field(form,label,{type='text',value='',maxLength=2000,required=true,rows=4}={}){
 const id=`human-field-${++serial}`,wrap=el('label',label),input=el(type==='textarea'?'textarea':'input');input.id=id;wrap.htmlFor=id;
 if(type!=='textarea')input.type=type;else input.rows=rows;
 input.value=value;input.maxLength=maxLength;input.required=required;wrap.append(input);form.append(wrap);return input;
}
function select(form,label,options){const id=`human-field-${++serial}`,wrap=el('label',label),input=el('select');input.id=id;wrap.htmlFor=id;for(const [value,text] of options)input.append(new Option(text,value));wrap.append(input);form.append(wrap);return input;}
function block(title,copy){const n=el('section',undefined,'human-card');n.append(el('h2',title));if(copy)n.append(el('p',copy,'muted'));return n;}
function disclosure(title){const d=el('details',undefined,'human-details');d.append(el('summary',title));return d;}
function displayDate(s){return s?new Date(s).toLocaleString('ru-RU',{dateStyle:'medium',timeStyle:'short'}):'Время уточняется';}

export function createHumanCoach({host,api,current}){
 let generation=0,selected=null,data=null,active=false;
 const params=new URLSearchParams(location.hash.slice(1));
 let invite=/^[A-Za-z0-9_-]{43}$/.test(params.get('coach_invite')??'')?params.get('coach_invite'):null;
 if(params.has('coach_invite'))history.replaceState(null,'',location.pathname);
 const endpoint=(id=selected)=>`/api/human-coach/links/${encodeURIComponent(id)}`;
 function clear(){generation++;selected=null;data=null;host.replaceChildren();}
 function visible(value){active=value;if(!value){generation++;host.replaceChildren();}}
 function valid(ticket,identity){return generation===ticket&&current()===identity&&active;}
 function form(parent,label,action,guard){
  const f=el('form',undefined,'human-form'),status=el('p','','help');status.setAttribute('role','status');
  const submit=el('button',label,'primary');submit.type='submit';f.append(submit,status);parent.append(f);
  f.addEventListener('submit',async event=>{event.preventDefault();if(submit.disabled||!guard())return;submit.disabled=true;status.textContent='Сохраняем…';
   try{await action(f);if(guard())status.textContent='Сохранено.';}catch(error){if(guard())status.textContent=error.message;}finally{if(guard())submit.disabled=false;}
  });return {f,status,submit,finish:()=>f.append(submit,status)};
 }
 async function action(b,fn,guard,status){if(b.disabled||!guard())return;b.disabled=true;
  try{await fn();}catch(error){if(guard())status.textContent=error.message;}finally{if(guard())b.disabled=false;}
 }
 async function load(id=selected){
  if(!current()||!active)return;selected=id;const ticket=++generation,identity=current(),guard=()=>valid(ticket,identity);
  host.replaceChildren();const status=el('p','Загружаем кабинет…','help');status.setAttribute('role','status');host.append(status);host.setAttribute('aria-busy','true');
  try{
   const loaded=await api('/api/human-coach');if(!guard())return;data=loaded;
   if(invite){const p=await api('/api/human-coach/invitation-preview','POST',{token:invite});if(!guard())return;host.replaceChildren();renderInvite(p,guard);return;}
   if(id){const detail=await api(endpoint(id));if(!guard())return;host.replaceChildren();renderWorkspace(detail,guard);return;}
   host.replaceChildren();renderHome(guard);
  }catch(error){if(guard()){status.textContent=error.message;host.append(button('Обновить',()=>void load(id)),button('К списку',()=>{invite=null;void load(null);},'quiet'));}}
  finally{if(guard())host.setAttribute('aria-busy','false');}
 }
 function renderInvite(preview,guard){
  const card=block(`Тренер ${preview.coach.display_name} приглашает тебя`,preview.coach.experience);
  card.append(el('p','После принятия тренер увидит только выбранное здесь имя. Матчи и анкету ты откроешь отдельно. Личный диалог с ИИ остаётся закрытым.','human-note'));
  let name;const f=form(card,'Принять приглашение',async()=>{const saved=await api('/api/human-coach/accept','POST',{token:invite,student_name:name.value});if(guard()){invite=null;await load(saved.id);}},guard);
  name=field(f.f,'Как тренеру к тебе обращаться?',{maxLength:60});f.finish();
  card.append(button('Не принимать',()=>{invite=null;void load(null);},'quiet'));host.append(card);
 }
 function renderHome(guard){
  const intro=block('Вместе — от решения к привычке','Тренер смотрит выбранные эпизоды, даёт одно задание и проверяет, что получилось. Ты управляешь доступом к своим данным.');
  intro.classList.add('human-intro');const toolbar=el('div',undefined,'human-actions');toolbar.append(button('Обновить кабинет',()=>void load(null),'quiet'));intro.append(toolbar);host.append(intro);
  const list=block(data.coach_profile?.status==='approved'?'Ученики и мои тренеры':'Мои тренеры');
  if(!data.relationships.length)list.append(el('p','Пока здесь никого нет. Получи личную ссылку от своего тренера и открой её после входа в NARMA.','muted'));
  for(const item of data.relationships){const card=el('article',undefined,'human-person'),title=item.role==='coach'?(item.student_name||'Новое приглашение'):item.coach_name;
   card.append(el('p',item.role==='coach'?'УЧЕНИК':'МОЙ ТРЕНЕР','eyebrow'),el('h3',title));
   if(item.status==='invited')card.append(el('p',`Приглашение действует до ${displayDate(item.expires_at)}. Ссылка показывается только при создании.`,'help'));
   else{const labels=[];if(item.awaiting_review)labels.push('Задание ждёт проверки');if(item.new_reports)labels.push(`Новых разборов: ${item.new_reports}`);if(item.unread)labels.push(`Сообщений: ${item.unread}`);card.append(el('p',labels.join(' · ')||'Можно продолжить тренировку','human-signal'));if(item.coach_status!=='approved')card.append(el('p','Доступ тренера приостановлен. Можно отозвать связь.','help'));
    card.append(button('Открыть кабинет',()=>void load(item.id)));}
   const status=el('p','','help');status.setAttribute('role','status');let confirmed=false;const remove=button(item.status==='invited'?'Отменить приглашение':'Завершить связь',()=>{
    if(!confirmed){confirmed=true;remove.textContent='Да, отозвать доступ';return;}void action(remove,async()=>{await api(endpoint(item.id),'DELETE');if(guard())await load(null);},guard,status);
   },'quiet');card.append(remove,status);list.append(card);
  }host.append(list);
  const profile=data.coach_profile;
  if(profile){const box=block(profile.display_name,profileStates[profile.status]);box.append(el('p',profile.experience));
   if(profile.status==='approved'){const status=el('p','','help');status.setAttribute('role','status');const make=button('Пригласить ученика',()=>void action(make,async()=>{
    const saved=await api('/api/human-coach/invitations','POST',{});if(!guard())return;
    const label=el('label','Личная ссылка для ученика'),input=el('input');input.value=saved.url;input.readOnly=true;input.setAttribute('aria-label','Личная ссылка для ученика');label.append(input);
    status.replaceChildren(label,el('span',' Скопируй ссылку и передай ученику. Она одноразовая и действует 7 дней.','help'));input.focus();input.select();
   },guard,status),'primary');box.append(make,status);}host.append(box);
  }else{
   const box=disclosure('Я тренер — подключить свой кабинет');box.append(el('p','Опиши опыт и способ работы. Владелец NARMA проверит заявку перед выдачей доступа. Это не автоматическое подтверждение квалификации.','help'));
   let name,experience;const f=form(box,'Отправить заявку',async()=>{await api('/api/human-coach/application','POST',{display_name:name.value,experience:experience.value});if(guard())await load(null);},guard);
   name=field(f.f,'Имя тренера',{maxLength:60});experience=field(f.f,'Опыт, специализация и как проверить квалификацию',{type:'textarea',maxLength:1500});experience.minLength=20;f.finish();host.append(box);
  }
  if(current()?.is_platform_owner){const box=disclosure('Заявки тренеров · управление платформой');const b=button('Показать заявки',()=>void action(b,async()=>{
    const result=await api('/api/human-coach/applications');if(!guard())return;b.hidden=true;
    if(!result.applications.length)box.append(el('p','Заявок пока нет.','help'));
    for(const p of result.applications){const row=block(p.display_name,profileStates[p.status]);row.append(el('p',p.experience));let password,decision;
     const f=form(row,'Сохранить решение',async()=>{const secret=password.value;password.value='';await api(`/api/human-coach/applications/${encodeURIComponent(p.owner_id)}`,'PUT',{status:decision.value,expected_revision:p.revision,current_password:secret});if(guard())await load(null);},guard);
     decision=select(f.f,'Решение',[['approved','Подтвердить доступ'],['suspended','Приостановить доступ']]);password=field(f.f,'Твой пароль',{type:'password',maxLength:256});password.autocomplete='current-password';f.finish();box.append(row);}
   },guard,status));const status=el('p','','help');status.setAttribute('role','status');box.append(b,status);host.append(box);}
 }
 function renderWorkspace(w,guard){
  const isCoach=w.role==='coach',base=endpoint(w.id),intro=block(isCoach?w.student_name:w.coach_name,isCoach?'Кабинет ученика':'Твой живой тренер');
  intro.classList.add('human-intro');intro.prepend(button('← Все кабинеты',()=>void load(null),'quiet'));
  const counts=el('dl',undefined,'human-stats');for(const [label,value] of [['Открытых разборов',w.reports.filter(r=>!r.unavailable).length],['Проверенных тренировок',w.tasks.filter(t=>t.state==='completed').length]]){const cell=el('div');cell.append(el('dt',label),el('dd',value));counts.append(cell);}intro.append(counts,el('p','Прогресс здесь — история заданий и обратной связи. Выполнение само по себе не доказывает рост рейтинга.','help'),button('Обновить',()=>void load(w.id),'quiet'));host.append(intro);
  const activeTask=w.tasks.find(t=>['assigned','submitted','changes_requested'].includes(t.state));
  const focus=block('Одна текущая тренировка',activeTask?null:'Тренер выберет одно действие и объяснит, по каким признакам его проверить.');focus.classList.add('human-focus');
  if(activeTask)renderTask(focus,activeTask,w,guard);
  else if(isCoach)taskForm(focus,w,guard);
  host.append(focus);
  if(w.tasks.some(t=>['completed','archived'].includes(t.state))){const history=disclosure('История тренировок');for(const t of w.tasks.filter(t=>['completed','archived'].includes(t.state))){const card=el('article',undefined,'human-history');renderTask(card,t,w,guard);history.append(card);}host.append(history);}
  renderReports(w,guard);renderMessages(w,guard);renderMeeting(w,guard);
  const privacy=disclosure('Доступ к данным');
  privacy.append(el('p','Тренер видит выбранные разборы, сообщения этого кабинета и задания. Сырые реплеи, почта, Steam ID и личный чат с ИИ здесь недоступны.','help'));
  if(!isCoach){const f=el('form',undefined,'human-form'),label=el('label',undefined,'human-check'),check=el('input');check.type='checkbox';check.checked=w.share_profile;label.append(check,el('span','Делиться анкетой: цели, опыт, привычки и учебные ответы, включая дальнейшие изменения.'));const status=el('p','','help');status.setAttribute('role','status');const save=button('Сохранить доступ к анкете',()=>void action(save,async()=>{await api(base+'/consent','PUT',{share_profile:check.checked});if(guard())await load(w.id);},guard,status));f.append(label,save,status);privacy.append(f);}
  if(w.player_profile){privacy.append(el('p','Ученик разрешил доступ к анкете. Это самоописание, а не оценка навыка или психологический диагноз.','help'));const g=w.player_profile.guidance;if(g)privacy.append(el('h3',g.goal),el('p',g.dose),el('p',g.explanation));const answers=el('dl',undefined,'human-answers');for(const [label,value] of profileAnswerRows(w.player_profile.profile.answers)){answers.append(el('dt',label),el('dd',value));}privacy.append(answers);}
  const status=el('p','','help');status.setAttribute('role','status');let confirmed=false;const remove=button('Завершить связь и отозвать доступ',()=>{if(!confirmed){confirmed=true;remove.textContent='Да, завершить связь';return;}void action(remove,async()=>{await api(base,'DELETE');if(guard())await load(null);},guard,status);},'quiet');privacy.append(el('p','Отзыв закрывает дальнейший доступ в NARMA. Ранее просмотренное или сохранённое другим человеком невозможно забрать обратно.','help'),remove,status);host.append(privacy);
 }
 function taskForm(parent,w,guard,preset){
  let title,instruction,criterion;const id=crypto.randomUUID();const f=form(parent,'Назначить тренировку',async()=>{await api(endpoint(w.id)+'/tasks','POST',{id,title:title.value,instruction:instruction.value,criterion:criterion.value});if(guard())await load(w.id);},guard);
  title=field(f.f,'Одно действие на тренировку',{maxLength:100,value:preset?.title||''});title.minLength=3;
  instruction=field(f.f,'Что сделать и когда это подходит',{type:'textarea',value:preset?.alternative||''});instruction.minLength=10;
  criterion=field(f.f,'По каким признакам проверим результат',{type:'textarea',maxLength:600});criterion.minLength=5;
  f.f.prepend(el('p','Задание отправляется от твоего имени. Проверь рекомендацию, уточни условия и критерий результата.','help'));f.finish();
 }
 function renderTask(parent,t,w,guard){
  parent.append(el('p',taskStates[t.state],'eyebrow'),el('h3',t.title),el('p',t.instruction),el('h4','Как проверим'),el('p',t.criterion));
  if(t.student_note)parent.append(el('h4','Ответ ученика'),el('p',t.student_note));
  if(t.report_job_id)parent.append(el('p',t.report_available?'Ученик приложил доступный разбор для проверки.':'Приложенный разбор сейчас недоступен: доступ отозван или версия изменилась.','help'));
  if(t.coach_feedback)parent.append(el('h4','Обратная связь тренера'),el('p',t.coach_feedback));
  if(['completed','archived'].includes(t.state))return;
  const coach=w.role==='coach';if(!coach&&!['assigned','changes_requested'].includes(t.state))return;
  let note,choice,report;const f=form(parent,coach?'Сохранить обратную связь':'Отправить результат тренеру',async()=>{await api(endpoint(w.id)+`/tasks/${t.id}`,'PUT',{expected_revision:t.revision,action:coach?choice.value:'submit',note:note.value,job_id:coach?null:report.value||null});if(guard())await load(w.id);},guard);
  if(coach)choice=select(f.f,'Следующий шаг',t.state==='submitted'?[['complete','Подтвердить выполнение'],['revise','Попросить уточнение'],['archive','Архивировать']]:[['archive','Архивировать задание']]);
  else report=select(f.f,'Разбор для проверки (необязательно)',[['','Без разбора'],...w.reports.filter(r=>!r.unavailable).map(r=>[r.job_id,`Матч ${r.match_id} · ${hero(r.hero)}`])]);
  note=field(f.f,coach?'Объясни решение и следующий шаг':'Что получилось, а что помешало?',{type:'textarea'});note.minLength=3;f.finish();
 }
 function renderReports(w,guard){
  const card=block('Эпизоды для совместного разбора','Здесь только те версии матчей, которыми ученик поделился с этим тренером.');
  if(w.role==='student'){let choice;const f=form(card,'Открыть доступ к разбору',async()=>{if(!choice.value)throw Error('Выбери готовый разбор.');await api(endpoint(w.id)+`/reports/${choice.value}`,'PUT',{});if(guard())await load(w.id);},guard);
   choice=select(f.f,'Выбери свой матч',[['','Выбери матч'],...data.reports.map(r=>[r.id,`Матч ${r.match_id} · ${hero(r.hero)}`])]);f.finish();if(!data.reports.length)card.append(el('p','Сначала загрузи свой реплей в разделе «Разобрать матч».','help'));}
  if(!w.reports.length)card.append(el('p','Разборы пока не открыты.','muted'));
  for(const r of w.reports){const d=disclosure(r.unavailable?'Версия разбора недоступна':`Матч ${r.match_id} · ${hero(r.hero)}`),status=el('p','','help');status.setAttribute('role','status');
   if(r.unavailable)d.append(el('p','Матч удалён или пересчитан. Ученик может заново поделиться готовой версией.','help'));
   else{d.append(el('p',r.reviewed_at?'Тренер отметил разбор как просмотренный.':'Ожидает просмотра тренером.','help'));
    if(r.ai_summary)d.append(el('h3','Черновик ИИ'),el('p',r.ai_summary),el('p','Рекомендации ИИ нужно проверить по контексту матча. Итоговое задание подписывает тренер.','help'));
    for(const p of r.ai_points){const point=el('article',undefined,'human-history');point.append(el('h4',p.title),el('p',p.observation),el('p',p.reasoning),el('p',p.alternative));if(p.when_to_apply)point.append(el('p',`Когда подходит: ${p.when_to_apply}`));if(p.when_not_to_apply)point.append(el('p',`Когда не подходит: ${p.when_not_to_apply}`));
     if(w.role==='coach'&&!w.tasks.some(t=>['assigned','submitted','changes_requested'].includes(t.state))){const adopt=button('Взять за основу задания',()=>{const focus=host.querySelector('.human-focus');focus.querySelector('form')?.remove();taskForm(focus,w,guard,p);focus.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});});point.append(adopt);}d.append(point);}
    const facts=el('p',`Убийства ${r.metrics.kills??'—'} · смерти ${r.metrics.deaths??'—'} · помощи ${r.metrics.assists??'—'}`,'help');d.append(facts);
    const episodes=el('ul',undefined,'human-episodes');for(const e of r.evidence){const item=el('li');item.append(el('span',`${stamp(e.time)} · ${{death:'Смерть',kill:'Убийство',purchase:'Покупка',assist:'Помощь'}[e.type]||e.type}`));const b=button('Обсудить',()=>{const form=host.querySelector('.human-message-form');form.querySelector('[data-message-report]').value=r.job_id;form.dispatchEvent(new Event('reportchange'));form.querySelector('[data-message-evidence]').value=e.id;form.querySelector('textarea').focus();});item.append(b);episodes.append(item);}d.append(episodes);
    if(w.role==='coach'){const reviewed=button('Отметить просмотренным',()=>void action(reviewed,async()=>{await api(endpoint(w.id)+`/reports/${r.job_id}/reviewed`,'POST',{});if(guard())await load(w.id);},guard,status));d.append(reviewed);}
   }
   if(w.role==='student'){const remove=button('Закрыть доступ к этому матчу',()=>void action(remove,async()=>{await api(endpoint(w.id)+`/reports/${r.job_id}`,'DELETE');if(guard())await load(w.id);},guard,status),'quiet');d.append(remove);}d.append(status);card.append(d);
  }host.append(card);
 }
 function renderMessages(w,guard){
  const card=block('Разговор с живым тренером','Вопросы, пояснения и ссылки на созвон. Этот разговор отделён от твоего личного чата с ИИ.');
  const log=el('div',undefined,'human-messages');log.setAttribute('role','log');log.setAttribute('aria-label','Разговор тренера и ученика');
  const render=(messages,prepend=false)=>{const fragment=document.createDocumentFragment();for(const m of messages){const item=el('article',undefined,'human-message');item.append(el('p',`${m.author==='coach'?w.coach_name:w.student_name} · ${displayDate(m.created_at)}`,'eyebrow'));if(m.job_id){const r=w.reports.find(r=>r.job_id===m.job_id),e=r?.evidence?.find(e=>e.id===m.evidence_id);item.append(el('p',`Матч ${r?.match_id||'недоступен'}${e?' · '+stamp(e.time):''}`,'help'));}item.append(el('p',m.body));fragment.append(item);}if(prepend)log.prepend(fragment);else log.append(fragment);};
  render(w.messages);let before=w.older_before;const status=el('p','','help');status.setAttribute('role','status');if(before){const older=button('Более ранние сообщения',()=>void action(older,async()=>{const previous=await api(endpoint(w.id)+`?before=${before}`);if(!guard())return;render(previous.messages,true);before=previous.older_before;older.hidden=!before;},guard,status),'quiet');card.append(older,status);}
  if(!w.messages.length)log.append(el('p','Начни с вопроса о текущей тренировке.','muted'));card.append(log);
  let message,report,evidence;let id=crypto.randomUUID();const f=form(card,'Отправить сообщение',async()=>{await api(endpoint(w.id)+'/messages','POST',{id,body:message.value,job_id:report.value||null,evidence_id:evidence.value||null});if(guard()){id=crypto.randomUUID();await load(w.id);}},guard);f.f.classList.add('human-message-form');
  report=select(f.f,'Привязать к матчу (необязательно)',[['','Общий вопрос'],...w.reports.filter(r=>!r.unavailable).map(r=>[r.job_id,`Матч ${r.match_id} · ${hero(r.hero)}`])]);report.dataset.messageReport='';
  evidence=select(f.f,'Эпизод',[['','Без таймкода']]);evidence.dataset.messageEvidence='';
  const update=()=>{evidence.replaceChildren(new Option('Без таймкода',''));const r=w.reports.find(r=>r.job_id===report.value);for(const e of r?.evidence||[])evidence.append(new Option(`${stamp(e.time)} · ${e.type}`,e.id));};report.addEventListener('change',update);f.f.addEventListener('reportchange',update);
  message=field(f.f,'Сообщение',{type:'textarea'});f.finish();host.append(card);
  const last=w.messages.at(-1)?.seq;if(last)void api(endpoint(w.id)+'/seen','POST',{seq:last}).catch(()=>{});
 }
 function renderMeeting(w,guard){
  const card=block('Следующая встреча',displayDate(w.meeting.starts_at));
  if(w.meeting.starts_at)card.append(el('p','Время показано в часовом поясе твоего устройства.','help'));
  if(w.meeting.url){try{const url=new URL(w.meeting.url);if(url.protocol==='https:'&&!url.username&&!url.password){const a=el('a',`Открыть встречу · ${url.hostname}`,'button secondary');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';card.append(a);}}catch{}}
  else card.append(el('p','Можно созвониться в привычном сервисе. Ссылку добавляет тренер.','help'));
  if(w.role==='coach'){const edit=disclosure('Настроить встречу');let url,date;const f=form(edit,'Сохранить встречу',async()=>{await api(endpoint(w.id)+'/meeting','PUT',{expected_revision:w.meeting.revision,url:url.value||null,starts_at:date.value?new Date(date.value).toISOString():null});if(guard())await load(w.id);},guard);
   url=field(f.f,'Ссылка на созвон (https)',{type:'url',value:w.meeting.url||'',maxLength:500,required:false});date=field(f.f,'Дата и время на твоём устройстве',{type:'datetime-local',required:false});if(w.meeting.starts_at){const d=new Date(w.meeting.starts_at);date.value=new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}f.finish();edit.append(el('p','Запись сохраняется в кабинете. Автоматические приглашения и напоминания не отправляются.','help'));card.append(edit);}
  host.append(card);
 }
 return {load,clear,visible,get pendingInvitation(){return !!invite;}};
}
