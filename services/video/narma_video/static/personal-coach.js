// Personal overview of owned, saved reports. Opening this page never generates a report.
import { mountCoachChat, renderModeLesson } from './coach-chat.js';
const el=(tag,text,className)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=String(text);if(className)item.className=className;return item;};
const text=value=>typeof value==='string'&&value.trim()?value.trim():'';
const list=value=>Array.isArray(value)?value:[];
const number=value=>typeof value==='number'&&Number.isFinite(value);
const count=value=>Number.isSafeInteger(value)&&value>=0?value:0;
const stamp=value=>{if(!number(value))return '—';const seconds=Math.floor(Math.abs(value));return `${value<0?'−':''}${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;};
const roles={1:'1 · Керри',2:'2 · Мидер',3:'3 · Офлейнер',4:'4 · Поддержка',5:'5 · Полная поддержка'};
const position=value=>roles[value]??'Позиция не указана';
const format=value=>number(value)?value.toLocaleString('ru-RU',{maximumFractionDigits:1}):'—';
const eventNames={death:'Смерть',kill:'Убийство',assist:'Помощь',purchase:'Покупка',item_used:'Применение предмета',item_observed:'Предмет в инвентаре',buyback:'Выкуп',respawn:'Возвращение',tower:'Башня'};
function button(label,action,className='quiet'){const item=el('button',label,className);item.type='button';item.addEventListener('click',()=>void action(item));return item;}
function dateLabel(match){const date=new Date(match.played_at??match.chronology_at??'');return `${match.date_source==='analysis'?'Разобран':'Игра'} ${Number.isFinite(date.valueOf())?date.toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'}):'· дата неизвестна'}${match.date_source==='user'?' · дата указана тобой':''}`;}
function paragraph(label,value,className=''){if(!text(value))return null;const row=el('div',undefined,`decision-field ${className}`);row.append(el('p',label,'decision-label'),el('p',value));return row;}

/** Versioned AI points are also used inside the complete replay report. */
export function renderDecisionPoints(target,points,{schemaVersion,evidence=new Map(),onEvidence=()=>{},headingLevel=4}={}){
  target.replaceChildren();
  for(const point of list(points).slice(0,12)){
    if(!point||typeof point!=='object')continue;
    const v2=['narma.replay-coaching.v2','narma.replay-coaching.v3'].includes(schemaVersion);
    const article=el('article',undefined,`report-point${v2?' decision-point':''}`);
    if(v2){
      article.dataset.pointKind=point.kind==='strength'?'strength':'review';
      const details=el('details',undefined,'decision-details'),summary=el('summary');
      summary.append(el('span',point.kind==='strength'?'Что стоит повторить':'Решение для разбора','decision-kind'),el('span',text(point.title)||'Эпизод','decision-title'));
      if(text(point.decision_question))summary.append(el('span',point.decision_question,'decision-question'));
      const body=el('div',undefined,'decision-body');
      for(const [label,value,style] of [['Факты эпизода',point.observation,'decision-observation'],['Почему это имеет значение',point.reasoning,''],['Другой вариант действия',point.alternative,'decision-alternative'],['Когда применять',point.when_to_apply,''],['Когда выбрать другое',point.when_not_to_apply,'decision-exception']]){const row=paragraph(label,value,style);if(row)body.append(row);}
      details.append(summary,body);article.append(details);
      appendEvidence(body,point);
    }else{
      article.append(el(`h${headingLevel}`,text(point.title)||'Эпизод'));
      if(text(point.observation))article.append(el('p',point.observation));
      if(text(point.advice))article.append(el('p',point.advice,'advice'));
      appendEvidence(article,point);
    }
    target.append(article);
  }
  function appendEvidence(host,point){
    const links=el('div',undefined,'evidence-links');
    for(const id of [...new Set(list(point.evidence_ids))].slice(0,12)){
      const item=evidence.get(id);if(!item||!number(item.time))continue;
      links.append(button(`${stamp(item.time)} · ${eventNames[item.type]??'Событие'}`,()=>onEvidence(id),'evidence-link'));
    }
    if(links.childElementCount)host.append(links);
  }
}

export function createPersonalCoach({api,onNavigate,onOpenReplay,heroName,heroIcon}){
  const host=document.getElementById('coach'),status=document.getElementById('coach-status'),content=document.getElementById('coach-content');
  const view={identity:null,profile:null,epoch:0,selection:0,generation:0,visible:false,dirty:true,loading:false,pool:null,learning:null,learningError:false,chosen:null};
  const valid=epoch=>epoch===view.epoch&&view.identity!==null;
  const context=match=>`${text(match.label)||heroName(match.hero)} · ${position(match.position)}`;
  function navigate(label,tab,className='quiet'){return button(label,()=>onNavigate(tab),className);}
  async function openMatch(match,evidenceId,control){
    if(!view.identity||!text(match?.job_id))return;
    const epoch=view.epoch;if(control)control.disabled=true;
    try{await onOpenReplay(match.job_id,evidenceId,{match_id:match.match_id,hero:match.hero,position:match.position,source_sha256:match.source_sha256,report_sha256:match.report_sha256});}catch(error){if(valid(epoch))status.textContent=`Не удалось открыть матч. ${error.message}`;}
    finally{if(control?.isConnected&&valid(epoch))control.disabled=false;}
  }
  function matchButton(match,label='Открыть разбор',evidenceId){return button(label,control=>openMatch(match,evidenceId,control));}
  function clear(){view.epoch++;view.selection++;view.pool=null;view.learning=null;view.chosen=null;view.dirty=true;view.loading=false;content.replaceChildren();content.hidden=true;status.textContent='';document.getElementById('coach-player').textContent='Личный разбор';host.setAttribute('aria-busy','false');document.getElementById('coach-refresh').disabled=false;}
  function setSession(user,profile){
    const identity=user?`${user.email??user.id??''}:${profile?.account_id??''}`:null;
    if(identity!==view.identity){clear();view.identity=identity;}
    view.profile=profile;
    if(view.visible&&view.identity&&view.dirty&&!view.loading)void load();
  }
  function setVisible(value){const entered=value&&!view.visible;view.visible=value;if(entered){view.dirty=true;view.generation++;view.selection++;}if(value&&view.identity&&view.dirty&&!view.loading)void load();}
  function invalidate(){view.dirty=true;view.generation++;view.selection++;if(view.visible&&view.identity&&!view.loading)void load();}
  async function load(){
    if(!view.identity||view.loading)return;
    const epoch=view.epoch,generation=view.generation;view.loading=true;view.dirty=false;view.selection++;
    status.textContent='Собираем твои сохранённые разборы и практику…';host.setAttribute('aria-busy','true');document.getElementById('coach-refresh').disabled=true;
    // Hide stale findings while refreshing; they must not outlive deleted or changed reports.
    content.replaceChildren();content.hidden=true;
    try{
      const [poolResult,learningResult]=await Promise.allSettled([api('/api/hero-pool?window=all'),api('/api/learning')]);
      if(!valid(epoch)||generation!==view.generation)return;
      if(poolResult.status!=='fulfilled')throw poolResult.reason;
      const pool=poolResult.value;
      if(view.profile&&pool.profile?.account_id!==view.profile.account_id)throw Error('Закреплённый игрок изменился. Обнови страницу.');
      view.pool=pool;view.learning=learningResult.status==='fulfilled'?learningResult.value:null;view.learningError=learningResult.status==='rejected';
      if(view.learning?.profile?.account_id!==pool.profile?.account_id){view.learning=null;view.learningError=true;}
      render();status.textContent='';
    }catch(error){if(valid(epoch)){view.pool=null;view.learning=null;view.dirty=true;status.textContent=`Не удалось собрать страницу тренера. ${error.message} Нажми «Обновить».`;}}
    finally{if(valid(epoch)){view.loading=false;host.setAttribute('aria-busy','false');document.getElementById('coach-refresh').disabled=false;if(generation!==view.generation&&view.visible)void load();}}
  }
  function section(title,id,eyebrow){const box=el('section',undefined,'coach-section');box.setAttribute('aria-labelledby',id);if(eyebrow)box.append(el('p',eyebrow,'eyebrow'));const heading=el('h2',title);heading.id=id;box.append(heading);return box;}
  function render(){
    const pool=view.pool,history=list(pool.history),profile=pool.profile,summary=pool.summary??{};content.replaceChildren();content.hidden=false;
    document.getElementById('coach-player').textContent=profile?.nickname?`Личный разбор · ${profile.nickname}`:'Личный разбор';
    const topline=el('div',undefined,'coach-overview');
    const total=count(summary.matches);topline.append(el('p',`${total} ${total===1?'матч в твоей истории':'матчей в твоей истории'}`,'coach-sample'));
    topline.append(el('p','Здесь собраны комментарии ИИ из твоих разборов, повторяющиеся события и текущая практика. Выбери одно решение, которое проверишь в следующей игре.','muted'));
    content.append(topline);
    if(!history.length){
      const empty=section('Начнём с твоего матча','coach-empty-heading','Первый шаг');empty.id='coach-empty';
      empty.append(el('p','Загрузи полный .dem и укажи свой ник. После разбора здесь появятся решения с таймкодами и фокус для следующей игры.','muted'),navigate('Загрузить первый реплей','review','secondary'));
      content.append(empty);renderPractice(content);return;
    }
    const focus=section('Что изменить в следующей игре','coach-focus-heading','Один матч · один фокус');focus.id='coach-focus';
    const picker=el('div',undefined,'coach-match-picker'),label=el('label','Матч для разбора решений'),select=el('select');label.htmlFor='coach-match-select';select.id='coach-match-select';
    for(const match of history){const option=new Option(`${context(match)} · #${match.match_id}${match.report_is_previous?' · обновляется':''}`,match.job_id);select.append(option);}
    const selected=history.find(match=>match.job_id===view.chosen)??history.find(match=>match.report_state==='ready'&&!match.report_is_previous)??history[0];view.chosen=selected.job_id;select.value=selected.job_id;
    const body=el('div');body.id='coach-match-detail';body.setAttribute('aria-live','polite');
    picker.append(label,select);focus.append(picker,body);content.append(focus);
    select.addEventListener('change',()=>{const match=history.find(item=>item.job_id===select.value);if(match){view.chosen=match.job_id;void loadChosen(match,body);}});
    renderSavedAI(content);
    const lower=el('div',undefined,'coach-columns');renderObservations(lower);renderPractice(lower);content.append(lower);
    renderTrends(content);renderHistory(content,history);renderLimits(content,pool);
    void loadChosen(selected,body);
  }
  async function loadChosen(match,body){
    const epoch=view.epoch,selection=++view.selection;body.replaceChildren(el('p','Открываем сохранённый разбор…','help'));body.setAttribute('aria-busy','true');
    try{
      const detail=await api(`/api/replays/${encodeURIComponent(match.job_id)}`);
      if(!valid(epoch)||selection!==view.selection||!body.isConnected)return;
      const report=detail.report,job=detail.replay;
      const current=job?.state==='ready'&&String(job.id)===String(match.job_id)&&!detail.report_is_previous&&report?.coverage?.complete===true&&String(report.match_id)===String(match.match_id)&&report.player?.account_id===view.pool.profile?.account_id&&report.player?.hero===match.hero&&text(match.source_sha256)&&report.coverage.source_sha256===match.source_sha256&&(!text(match.report_sha256)||detail.report_sha256===match.report_sha256);
      body.replaceChildren();
      const heading=el('div',undefined,'coach-match-context');heading.append(heroIcon(match.hero,{className:'coach-portrait',lazy:true}),el('div'));
      heading.lastChild.append(el('h3',context(match)),el('p',`Матч ${match.match_id} · ${dateLabel(match)}`,'help'));body.append(heading);
      if(!current){body.append(el('p','Этот отчёт обновляется или его контекст изменился. Для актуального фокуса выбери другой готовый матч либо обнови страницу тренера.','muted'),matchButton(match,'Открыть состояние разбора'));return;}
      const chat=el('section');
      const attachChat=()=>{body.append(chat);mountCoachChat(chat,{api,jobId:match.job_id,reportHash:detail.report_sha256,evidence:list(report.evidence),context:job.training_context??{},identity:view.identity,isCurrent:()=>valid(epoch)&&selection===view.selection,onEvidence:id=>openMatch(match,id)});};
      const coaching=report.coaching,status=detail.coaching_status;
      const usable=coaching?.status==='ready'&&text(coaching.summary)&&['ready','saved'].includes(status?.state)&&(status.provider!=='openai_api'||status.state==='saved'||status.verified_openai===true);
      if(!usable){
        const copy=status?.state==='context_changed'?'Позиция или контекст изменились. Прежний комментарий ИИ к ним не применяется.':status?.state==='unknown'?'Источник комментария не подтверждён. Открой отчёт, чтобы проверить его статус.':'Для этого матча нет готового комментария ИИ. Факты и события доступны в полном отчёте.';
        body.append(el('p',copy,'coach-unavailable'),matchButton(match,'Открыть факты и статус ИИ'));attachChat();return;
      }
      body.append(el('p',status.state==='saved'?'Сохранённый комментарий ИИ':'Комментарий ИИ из разбора','coach-source'),el('p',coaching.summary,'coach-summary'));
      const next=list(coaching.next_game).find(item=>text(item?.action));
      if(next){const plan=el('div',undefined,'coach-next-game');plan.id='coach-next-game';plan.append(el('p','Твой фокус на следующую игру','decision-label'),el('h3',text(next.title)||'Одно действие для проверки'),el('p',next.action));if(text(next.measure))plan.append(el('p',`Как проверить: ${next.measure}`,'help'));plan.append(navigate('Перейти к практике','learning'));body.append(plan);}
      const evidence=new Map(list(report.evidence).filter(item=>text(item?.id)).map(item=>[item.id,item]));
      const lesson=el('section');renderModeLesson(lesson,coaching,{evidence,onEvidence:id=>openMatch(match,id)});body.append(lesson);
      const points=el('div');points.id='coach-decisions';
      if(!['narma.replay-coaching.v2','narma.replay-coaching.v3'].includes(coaching.schema_version))body.append(el('p','Сохранённый разбор в прежнем формате. Подробное сравнение вариантов будет в новых комментариях ИИ.','help'));
      renderDecisionPoints(points,coaching.points,{schemaVersion:coaching.schema_version,evidence,onEvidence:id=>openMatch(match,id),headingLevel:3});body.append(points,matchButton(match,'Весь разбор: события, предметы и графики'));
      attachChat();
    }catch(error){if(valid(epoch)&&selection===view.selection&&body.isConnected){body.replaceChildren(el('p',`Не удалось открыть комментарий. ${error.message}`,'help'),button('Повторить загрузку',()=>loadChosen(match,body)));}}
    finally{if(valid(epoch)&&selection===view.selection&&body.isConnected)body.setAttribute('aria-busy','false');}
  }
  function renderObservations(target){
    const box=section('Что повторяется','coach-patterns-heading','Наблюдения по событиям реплеев');box.id='coach-patterns';
    const patterns=list(view.pool.patterns).slice(0,3);
    box.append(el('p','Счётчики помогают выбрать эпизоды для просмотра. Сами по себе они не объясняют причину и не оценивают качество игры.','help'));
    for(const pattern of patterns){const row=el('article',undefined,'coach-observation');row.append(el('p',`${text(pattern.label)||heroName(pattern.hero)} · ${position(pattern.position)}`,'coach-context'),el('h3',pattern.title),el('p',`${count(pattern.occurrences)} из ${count(pattern.eligible_matches)} подходящих матчей`,'coach-observation-count'));if(text(pattern.observation))row.append(el('p',pattern.observation,'help'));if(text(pattern.action))row.append(el('p',pattern.action));
      const links=el('div',undefined,'evidence-links');for(const ref of list(pattern.evidence).slice(0,2)){const match=list(view.pool.history).find(item=>item.job_id===ref.job_id&&String(item.match_id)===String(ref.match_id));if(match)links.append(matchButton(match,`Матч ${ref.match_id}`,list(ref.evidence_ids)[0]));}row.append(links);box.append(row);}
    if(!patterns.length)box.append(el('p','Пока мало сопоставимых игр: для повторения нужны минимум три матча на одном герое и позиции, с эпизодом хотя бы в двух. Позиция задаётся тобой.','muted'));
    box.append(navigate('Все наблюдения и герои','hero-pool'));target.append(box);
  }
  function renderSavedAI(target){
    const box=section('Что ИИ заметил в твоих матчах','coach-ai-observations-heading','Сохранённый разбор нескольких игр');box.id='coach-ai-observations';
    const history=list(view.pool.history),patterns=list(view.pool.coaching?.patterns).filter(pattern=>list(pattern.evidence).length&&list(pattern.evidence).every(ref=>history.some(match=>match.job_id===ref.job_id&&String(match.match_id)===String(ref.match_id)))).slice(0,3);
    if(!patterns.length){box.append(el('p','Общий комментарий ИИ по нескольким матчам пока не сохранён. Ниже — повторяющиеся события из реплеев, которые уже можно проверить.','muted'));target.append(box);return;}
    box.append(el('p','Эти выводы сохранены из отдельного разбора нескольких игр. Ссылки ведут к исходным эпизодам; открытие страницы не создаёт новый комментарий.','help'));
    for(const pattern of patterns){
      const row=el('article',undefined,'coach-ai-observation');
      row.append(el('h3',pattern.title),el('p',list(pattern.heroes).map(hero=>`${text(hero.label)||heroName(hero.hero)} · ${position(hero.position)}`).join(' / '),'coach-context'),el('p',pattern.observation));
      const cited=new Set(list(pattern.evidence).map(ref=>String(ref.match_id)));row.append(el('p',`В выводе использованы эпизоды из ${cited.size} матчей.`,'help'));
      for(const goal of list(pattern.goals).slice(0,2)){const practice=el('div',undefined,'coach-ai-practice');if(text(goal.action))practice.append(el('p',goal.action));if(text(goal.success_criterion))practice.append(el('p',`Как проверить: ${goal.success_criterion}`,'help'));if(count(goal.evaluate_after_matches))practice.append(el('p',`Вернись к проверке после ${count(goal.evaluate_after_matches)} новых подходящих матчей.`,'help'));row.append(practice);}
      const links=el('div',undefined,'evidence-links');for(const ref of list(pattern.evidence).slice(0,4)){const match=history.find(item=>item.job_id===ref.job_id&&String(item.match_id)===String(ref.match_id));links.append(matchButton(match,`Матч ${ref.match_id} · ${stamp(ref.time)}`,ref.evidence_id));}row.append(links);box.append(row);
    }
    box.append(navigate('Все выводы и исходные матчи','hero-pool'));target.append(box);
  }
  function renderPractice(target){
    const box=section('Текущая практика','coach-practice-heading','От решения к привычке');box.id='coach-practice';
    if(view.learningError){box.append(el('p','Практику сейчас не удалось загрузить. Сохранённые разборы доступны.','help'),navigate('Открыть мою практику','learning'));target.append(box);return;}
    const active=list(view.learning?.plans).filter(plan=>plan.status==='active'),plan=active.find(item=>item.validity==='current');
    if(plan){const exercise=plan.exercise??{};box.append(el('p',`${text(plan.hero_label)||heroName(plan.hero)} · ${position(plan.position)}`,'coach-context'),el('h3',text(exercise.title)||'Упражнение в работе'));if(text(exercise.action))box.append(el('p',exercise.action));if(text(exercise.measurement))box.append(el('p',`Как проверить: ${exercise.measurement}`,'help'));box.append(el('p',`Подходящих матчей с твоей проверкой: ${count(plan.training_matches)}.`,'coach-practice-count'),el('p',text(plan.progress_note)||'Это твоя самооценка после просмотра, а не автоматическая оценка освоения навыка.','help'));if(text(plan.comparison_note)){const details=el('details',undefined,'coach-method');details.append(el('summary','Какие проверки входят в счётчик'),el('p',plan.comparison_note,'help'));box.append(details);}if(active.length>1)box.append(el('p',`Всего активных упражнений: ${active.length}.`,'help'));}
    else box.append(el('p',active.length?'Контекст активной практики изменился. Проверь героя, позицию и исходный матч перед продолжением.':'Выбери одно упражнение под свой фокус. После следующей игры отметь, какое решение принял и что на него повлияло.','muted'));
    box.append(navigate(plan?'Продолжить практику':'Выбрать упражнение','learning','secondary'));target.append(box);
  }
  function renderTrends(target){
    const trends=list(view.pool.trends).filter(item=>item.status==='ready').slice(0,3);if(!trends.length)return;
    const box=section('Что меняется на дистанции','coach-trends-heading','Сравниваем одного героя и позицию');box.id='coach-trends';
    for(const trend of trends){const row=el('article',undefined,'coach-trend');row.append(el('div'),el('p',`${format(trend.early_mean)} → ${format(trend.recent_mean)} ${text(trend.unit)}`,'coach-trend-value'));row.firstChild.append(el('h3',trend.label),el('p',`${text(trend.hero_label)||heroName(trend.hero)} · ${position(trend.position)} · ${count(trend.early_n)} ранних / ${count(trend.recent_n)} последних`,'help'));const basis=trend.chronology_basis==='analysis'?'Порядок по дате разбора; дата игры неизвестна.':trend.chronology_basis==='user'?'Порядок по датам игр, указанным тобой.':trend.chronology_basis==='replay'?'Порядок по датам из реплеев.':'Источник порядка матчей не подтверждён.';row.append(el('p',`${basis} ${text(trend.build_note)} ${text(trend.interpretation)}`,'help coach-trend-note'));box.append(row);}
    box.append(navigate('Динамика и все показатели','hero-pool'));target.append(box);
  }
  function renderHistory(target,history){
    const box=section('Матчи для разбора','coach-matches-heading');box.id='coach-matches';
    for(const match of history.slice(0,6)){const row=el('article',undefined,'coach-match-row'),copy=el('div');copy.append(el('h3',`${text(match.label)||heroName(match.hero)} · #${match.match_id}`),el('p',`${position(match.position)} · ${dateLabel(match)}`,'help'));if(match.report_is_previous)copy.append(el('p','Показан предыдущий отчёт · обновление ещё не завершено','help'));row.append(heroIcon(match.hero,{className:'coach-match-portrait',lazy:true}),copy,matchButton(match));box.append(row);}
    if(history.length>6)box.append(navigate(`Все матчи · ${history.length}`,'hero-pool'));box.append(navigate('Загрузить новый реплей','review','secondary'));target.append(box);
  }
  function renderLimits(target,pool){const details=el('details',undefined,'coach-method');details.id='coach-limitations';details.append(el('summary','На чём основана эта страница'));const limits=el('ul');for(const limit of list(pool.limitations))if(text(limit))limits.append(el('li',limit));limits.append(el('li','Комментарии ИИ показаны из одного выбранного сохранённого отчёта. Повторяющиеся события и изменения счётчиков рассчитаны по реплеям; отдельный ИИ-анализ стиля игрока здесь не выполняется.'));details.append(limits);target.append(details);}
  document.getElementById('coach-refresh').addEventListener('click',()=>void load());
  return {setSession,setVisible,invalidate};
}
