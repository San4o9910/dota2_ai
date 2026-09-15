// Text-only, owner-scoped conversation. Only submitting a question calls the AI.
const mounts=new WeakMap();
const el=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
const labels={foundations:'Основы · по шагам',application:'Применение · выбор вариантов',advanced:'Сложные решения · компромиссы'};
const time=value=>`${value<0?'−':''}${Math.floor(Math.abs(value)/60)}:${String(Math.floor(Math.abs(value)%60)).padStart(2,'0')}`;
const events={death:'Смерть',kill:'Убийство',assist:'Помощь',purchase:'Покупка',item_used:'Применение предмета',item_observed:'Предмет у героя',buyback:'Выкуп',respawn:'Возвращение',tower:'Башня'};

export function mountCoachChat(host,{api,jobId,reportHash,evidence=[],context={},identity,isCurrent=()=>true,onEvidence=()=>{},onRelatedEvidence=()=>{}}){
  const key=JSON.stringify([identity,jobId,reportHash,context]);
  if(mounts.get(host)?.key===key)return;
  mounts.get(host)?.dispose();host.replaceChildren();
  let live=true,busy=false,pending=null,timer=null,scope='replay',revision=0;
  const current=()=>live&&host.isConnected&&isCurrent();
  mounts.set(host,{key,dispose:()=>{live=false;clearTimeout(timer);}});
  host.className='coach-chat';host.setAttribute('aria-label','Чат с ИИ-тренером');
  const heading=el('div',undefined,'chat-heading');heading.append(el('p','Вопрос → объяснение → действие','eyebrow'),el('h3','Обсуди матч с тренером'));
  const description=el('p',`Матч и история разговора останутся контекстом ответа. ${labels[context.training_level]??'Обычный разбор'}.`,'help');
  const scopeLabel=el('label','Контекст разговора'),scopeInput=el('select');scopeInput.append(new Option('Этот матч','replay'),new Option('Мои матчи и текущая цель','series'));scopeLabel.append(scopeInput);
  const setScope=()=>{scope=scopeInput.value;revision++;pending=null;busy=false;input.value='';log.replaceChildren();description.textContent=scope==='series'?'Тренер использует этот матч, до двух других игр на том же герое и позиции и активное упражнение. История разговора сохраняется между матчами.':`Обсуждаем только этот матч. ${labels[context.training_level]??'Обычный разбор'}.`;void load();};
  scopeInput.addEventListener('change',setScope);
  const log=el('div',undefined,'chat-log');log.setAttribute('role','log');log.setAttribute('aria-label','История разговора');log.setAttribute('aria-live','polite');
  const status=el('p','Загружаем разговор…','help chat-status');status.setAttribute('role','status');
  const form=el('form',undefined,'chat-form'),field=el('label','Твой вопрос'),input=el('textarea');
  input.rows=3;input.maxLength=2000;input.required=true;input.placeholder='Что стоило проверить перед этим решением?';field.append(input);
  const episodeLabel=el('label','Эпизод для обсуждения'),episode=el('select');episode.append(new Option('Весь матч',''));
  const eventMap=new Map(evidence.filter(item=>typeof item?.id==='string'&&Number.isFinite(item.time)).map(item=>[item.id,item]));
  for(const item of [...eventMap.values()].sort((a,b)=>a.time-b.time))episode.append(new Option(`${time(item.time)} · ${String(item.title??item.label??events[item.type]??'Событие').slice(0,85)}`,item.id));
  episodeLabel.append(episode);
  const send=el('button','Спросить тренера','primary');send.type='submit';send.disabled=true;
  const refresh=el('button','Обновить разговор','quiet');refresh.type='button';
  const prompts=el('div',undefined,'chat-prompts');
  for(const text of ['Объясни главное решение проще','Какие были варианты?','Что проверить в следующей игре?']){const button=el('button',text,'quiet');button.type='button';button.addEventListener('click',()=>{input.value=text;input.focus();});prompts.append(button);}
  const actions=el('div',undefined,'chat-actions');actions.append(send,refresh);
  form.append(field,episodeLabel,actions,el('p','Ответ расходует доступный лимит ИИ. Открытие истории не создаёт запрос.','help'));
  host.append(heading,scopeLabel,description,log,prompts,form,status);
  host.addEventListener('narma-question',event=>{if(current()&&!busy&&typeof event.detail==='string'){input.value=event.detail.slice(0,2000);input.focus();}});
  function render(turns){
    log.replaceChildren();
    if(!turns.length)log.append(el('p','Спроси о конкретном решении, предмете или следующей тренировке.','chat-empty'));
    for(const turn of turns){
      const question=el('article',undefined,'chat-message chat-question');question.append(el('p','Ты','chat-author'),el('p',turn.question));log.append(question);
      const reply=el('article',undefined,'chat-message chat-answer');reply.append(el('p','ИИ-тренер','chat-author'));
      if(turn.state==='succeeded'&&turn.answer){
        reply.append(el('p',turn.answer.answer));const next=el('div',undefined,'chat-next');next.append(el('p','Следующий шаг','decision-label'),el('p',turn.answer.next_step));reply.append(next);
        const links=el('div',undefined,'evidence-links');for(const id of turn.answer.evidence_ids??[]){const ref=turn.references?.find(row=>row.id===id),item=ref??eventMap.get(id);if(!item||!Number.isFinite(item.time))continue;const button=el('button',`${ref?`Матч ${ref.match_id} · `:''}${time(item.time)} · К эпизоду`,'evidence-link');button.type='button';button.addEventListener('click',()=>ref&&ref.job_id!==jobId?onRelatedEvidence(ref):onEvidence(ref?.evidence_id??id));links.append(button);}reply.append(links);
      }else reply.append(el('p',turn.state==='running'?'Тренер готовит ответ…':'Ответ не удалось получить. Автоматической повторной отправки не было.','help'));
      log.append(reply);
    }
    log.scrollTop=log.scrollHeight;
  }
  async function load(){
    const generation=revision;
    clearTimeout(timer);refresh.disabled=true;
    try{const data=await api(`/api/replays/${encodeURIComponent(jobId)}/chat${scope==='series'?'?scope=series':''}`);if(!current()||generation!==revision)return;
      if(data.report_sha256!==reportHash)throw Error('Разбор обновился. Открой матч заново.');
      render(data.turns);busy=data.turns.some(turn=>turn.state==='running');
      const completed=pending&&data.turns.find(turn=>turn.id===pending.id&&turn.state!=='running');if(completed){pending=null;input.value='';}
      send.disabled=busy||!data.available;input.disabled=busy;episode.disabled=busy;
      status.textContent=busy?'Тренер отвечает. Можно оставить эту страницу открытой.':data.available?'': 'Отправка сейчас недоступна: проверь подключение или лимит ИИ. История сохранена.';
      if(busy)timer=setTimeout(()=>{if(current())void load();},3000);
    }catch(error){if(current()&&generation===revision){status.textContent=`Не удалось обновить разговор. ${error.message}`;send.disabled=busy;}}
    finally{if(current()&&generation===revision)refresh.disabled=false;}
  }
  refresh.addEventListener('click',()=>void load());
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!input.value.trim())return;
    const generation=revision;
    const question=input.value.trim(),evidenceId=episode.value||null;
    if(!pending||pending.question!==question||pending.evidence_id!==evidenceId)pending={id:crypto.randomUUID(),report_sha256:reportHash,question,evidence_id:evidenceId,scope};
    busy=true;send.disabled=true;input.disabled=true;episode.disabled=true;status.textContent='Тренер разбирает твой вопрос…';
    try{const data=await api(`/api/replays/${encodeURIComponent(jobId)}/chat`,'POST',pending);if(!current()||generation!==revision)return;
      if(data.turn?.state!=='running'){pending=null;input.value='';}busy=false;await load();
    }catch(error){if(current()&&generation===revision){busy=false;send.disabled=false;input.disabled=false;episode.disabled=false;status.textContent=`${error.message} Нажми «Обновить разговор», чтобы проверить ответ. Повторная отправка неизменённого вопроса использует тот же запрос.`;}}
  });
  void load();
}

export function renderModeLesson(host,coaching,{evidence=new Map(),onEvidence=()=>{}}={}){
  host.replaceChildren();host.hidden=!coaching?.lesson;
  if(!coaching?.lesson)return;
  const titles={foundations:['Понятие простыми словами','Действие по шагам','Сигнал для проверки'],application:['Сравнение вариантов','Условие выбора','Исключение'],advanced:['Цена альтернативы','Неизвестное и окно решения','Условие отмены плана']};
  const headings=titles[coaching.training_level];if(!headings){host.hidden=true;return;}
  host.className='mode-lesson';host.append(el('p',labels[coaching.training_level],'eyebrow'));
  ['first','second','third'].forEach((key,index)=>{const row=el('div',undefined,'mode-step');row.append(el('span',String(index+1).padStart(2,'0'),'mode-number'),el('div'));row.lastChild.append(el('h4',headings[index]),el('p',coaching.lesson[key]));host.append(row);});
  const links=el('div',undefined,'evidence-links');for(const id of coaching.lesson.evidence_ids??[]){const item=evidence.get(id);if(!item)continue;const button=el('button',`${time(item.time)} · Проверить эпизод`,'evidence-link');button.type='button';button.addEventListener('click',()=>onEvidence(id));links.append(button);}host.append(links);
}
