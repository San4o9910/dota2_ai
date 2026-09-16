const el=(tag,text,cls)=>Object.assign(document.createElement(tag),{...(text!=null?{textContent:String(text)}:{}),...(cls?{className:cls}:{})});
export function createPlayerProgram({host,api,current,onNavigate,onOpen,onCheck}){
  let serial=0;
  const action=(label,run,cls='secondary')=>{const b=el('button',label,cls);b.type='button';b.addEventListener('click',()=>run(b));return b;};
  async function load(){
    const token=++serial,identity=current();host.replaceChildren(el('p','Собираем твою программу…','help'));host.setAttribute('aria-busy','true');
    const valid=()=>token===serial&&current()===identity;
    try{
      const data=await api('/api/program');if(!valid())return;host.replaceChildren();
      const steps=el('ol',null,'program-steps');['Разбери свой матч','Отработай одно действие','Проверь следующий матч'].forEach((text,i)=>{const li=el('li',text);if(i===({upload:0,choose:0,practice:1,check:2}[data.stage]))li.setAttribute('aria-current','step');steps.append(li);});host.append(steps);
      const card=el('section',null,'surface program-focus');host.append(card);
      if(data.focus){
        const p=data.focus,e=p.exercise||{};card.append(el('p',`${p.hero_label} · позиция ${p.position}`,'eyebrow'),el('h2',e.title||'Текущее задание'),el('p',e.action,'program-action'));
        for(const [key,label] of [['why','Зачем'],['exception','Когда изменить решение'],['measurement','Как проверить']])if(e[key]){card.append(el('h3',label),el('p',e[key]));}
        const actions=el('div',null,'learning-actions');
        actions.append(data.check_candidates.length?action('Проверить следующий матч',()=>onCheck(p,data.check_candidates[0]),'primary'):action('Загрузить следующий матч',()=>onNavigate('review'),'primary'),action('Посмотреть исходный разбор',()=>onOpen(p.source_job_id)),action('Обсудить с тренером',()=>onNavigate('coach')));card.append(actions);
        card.append(el('p',`Сохранено личных проверок: ${p.reviewed_matches||0}. Матчей после начала практики: ${p.training_matches||0}.`,'help'));
        if(data.review?.status==='measured')card.append(el('p',`${data.review.label}: ${data.review.baseline} → ${data.review.recent_mean} ${data.review.unit||''}`,'program-action'));
        if(data.review?.note)card.append(el('p',data.review.note,'help'));
      }else{
        card.append(el('h2',data.stage==='upload'?'Начнём с твоего матча':'Выбери одно действие на следующую игру'),el('p',data.focus_needs_review?'Источник текущего задания изменился или практика завершена. Выбери актуальное задание.':'Разбор помогает найти эпизод, тренировка — проверить другое решение в следующей игре.'));
        card.append(data.latest_report?action('Выбрать тренировку из разбора',()=>onOpen(data.latest_report),'primary'):action('Разобрать свой матч',()=>onNavigate('review'),'primary'));
        const example=el('a','Посмотреть пример без загрузки','text-link');example.href='/example';card.append(example);
      }
      if(data.choices.length>1||(!data.focus&&data.choices.length)){
        const details=el('details',null,'surface');details.append(el('summary','Сменить текущее задание'));
        for(const p of data.choices){if(p.id===data.focus?.id)continue;details.append(action(`${p.exercise?.title} · ${p.hero_label} · ${p.position}`,async b=>{b.disabled=true;try{await api(`/api/program/focus/${encodeURIComponent(p.id)}`,'PUT',{});if(valid())await load();}catch(error){if(valid()){b.disabled=false;details.append(el('p',error.message,'help'));}}}));}host.append(details);
      }
      if(data.jobs.length){const jobs=el('section',null,'surface');jobs.append(el('h2','Последние загрузки'));for(const j of data.jobs){const status={uploading:'Загрузка не завершена',queued:'В очереди',processing:'Обрабатывается',failed:'Не удалось разобрать'}[j.state];jobs.append(action(`${status} · ${new Date(j.created_at).toLocaleDateString('ru-RU')}`,()=>onOpen(j.id)));}jobs.append(el('p','После передачи файла обработка продолжается на сервере. Готовый отчёт остаётся в истории разборов.','help'));host.append(jobs);}
      const more=el('div',null,'learning-actions');more.append(action('Все тренировки и проверки',()=>onNavigate('learning'),'quiet'),action('Обновить',load,'quiet'));host.append(more);
    }catch(error){if(valid()){host.replaceChildren(el('p',error.message,'help'),action('Попробовать ещё раз',load));}}
    finally{if(valid())host.setAttribute('aria-busy','false');}
  }
  return {load,clear(){serial++;host.replaceChildren();}};
}
