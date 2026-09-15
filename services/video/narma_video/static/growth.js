// Personal learning views. No automatic model request and no public report URL.
const mounts=new WeakMap();
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const button=(text,fn,cls='quiet')=>{const n=el('button',text,cls);n.type='button';n.addEventListener('click',fn);return n;};
const number=n=>Number.isFinite(n)?n.toLocaleString('ru-RU',{maximumFractionDigits:2}):'—';
const stamp=n=>Number.isFinite(n)?`${n<0?'−':''}${Math.floor(Math.abs(n)/60)}:${String(Math.floor(Math.abs(n)%60)).padStart(2,'0')}`:'—';
const block=(title)=>{const n=el('section',undefined,'growth-block');n.append(el('h3',title));return n;};
const field=(text,input)=>{const n=el('label',text);n.append(input);return n;};
const details=(text)=>{const n=el('details',undefined,'growth-details');n.append(el('summary',text));return n;};
export function clearGrowth(host){mounts.get(host)?.dispose();mounts.delete(host);host.replaceChildren();}

export function mountProgress(host,{api,isCurrent=()=>true,onOpen=()=>{}}){
  clearGrowth(host);let live=true;mounts.set(host,{dispose:()=>{live=false;}});
  const current=()=>live&&host.isConnected&&isCurrent();
  host.className='growth-progress';host.append(el('h3','Проверка твоего фокуса'));
  const status=el('p','Сравниваем сохранённые матчи…','help');status.setAttribute('role','status');host.append(status);
  async function load(){try{const data=await api('/api/learning/progress');if(!current())return;status.textContent='';
    if(!data.plans.length){status.textContent='Выбери упражнение в «Моей практике». После новых игр здесь появится проверка.';return;}
    for(const plan of data.plans){const row=block(`${plan.hero_label} · ${plan.exercise?.title??'Текущий фокус'}`),r=plan.review;
      if(r.status==='measured'){row.append(el('p',`${r.label}: ${number(r.baseline)} → ${number(r.recent_mean)} ${r.unit}`,'growth-comparison'),el('p',`Исходный матч → среднее по ${r.matches.length} новым играм.`,'help'));
        for(const match of r.matches){const event=match.evidence?.[0];row.append(button(`Матч ${match.match_id} · ${number(match.value)} ${r.unit}`,()=>onOpen(match.job_id,event?.id,match)));}}
      row.append(el('p',r.note,'help'));host.append(row);
    }
  }catch(error){if(current()){status.textContent=`Не удалось проверить практику. ${error.message}`;host.append(button('Повторить проверку',()=>{clearGrowth(host);mountProgress(host,{api,isCurrent,onOpen});}));}}}
  void load();
}

export function mountReportTools(host,{api,jobId,reportHash,report,identity,isCurrent=()=>true,onEvidence=()=>{},onQuestion=()=>{},heroName=()=>''}){
  const key=JSON.stringify([jobId,reportHash,identity]);if(mounts.get(host)?.key===key)return;
  clearGrowth(host);let live=true;const urls=[];mounts.set(host,{key,dispose:()=>{live=false;for(const url of urls)URL.revokeObjectURL(url);}});
  const current=()=>live&&host.isConnected&&isCurrent();host.className='growth-tools';
  const coach=report.coaching?.status==='ready'?report.coaching:null,points=coach?.points??[];
  const strength=points.find(p=>p.kind==='strength'),review=points.find(p=>p.kind!=='strength'),next=coach?.next_game?.find(p=>p.action);
  const brief=block('Разбор за минуту');brief.classList.add('growth-brief');
  const summaries=[['Что получилось',strength?.observation??'Подтверждённый сильный эпизод пока не выделен.'],['Что пересмотреть',review?.observation??coach?.summary??'Комментарий тренера недоступен. Посмотри записанные события матча.'],['В следующей игре',next?.action??'Выбери один эпизод и сформулируй вопрос к своему решению.']];
  for(const [label,value] of summaries){const part=el('div');part.append(el('p',label,'decision-label'),el('p',value));brief.append(part);}
  const evidence=(review?.evidence_ids??[]).find(id=>report.evidence?.some(e=>e.id===id));
  if(evidence){const item=report.evidence.find(e=>e.id===evidence);brief.append(button(`${stamp(item.time)} · Посмотреть момент`,()=>onEvidence(evidence),'secondary'));}
  host.append(brief);

  if(coach){
    const feedback=details('Оценить совет тренера'),form=el('form'),which=el('select');which.append(new Option('Общий разбор',''));
    points.forEach((p,i)=>which.append(new Option(String(p.title??p.observation??`Совет ${i+1}`).slice(0,100),String(i))));
    const reason=el('select');for(const [v,t] of [['context','Не учтена ситуация'],['role','Не учтена моя роль'],['generic','Слишком общий совет'],['facts','Ошибка в фактах'],['helpful','Совет помог']])reason.append(new Option(t,v));
    const comment=el('textarea');comment.rows=3;comment.maxLength=1500;comment.placeholder='Какую цель ты преследовал? Чего не хватает в объяснении?';
    const status=el('p','','help');status.setAttribute('role','status');const send=el('button','Сохранить отзыв','secondary');send.type='submit';
    let pending=null;
    form.append(field('Какой совет',which),field('Твоя оценка',reason),field('Пояснение',comment),el('p','Отзыв получит владелец NARMA для проверки качества.','help'),send,status);
    form.addEventListener('submit',async event=>{event.preventDefault();if(send.disabled||!current())return;
      const body={report_sha256:reportHash,reason:reason.value,comment:comment.value.trim(),point_index:which.value===''?null:Number(which.value)};
      if(!pending||JSON.stringify(pending.body)!==JSON.stringify(body))pending={id:crypto.randomUUID(),body};send.disabled=true;
      try{await api(`/api/replays/${jobId}/feedback`,'POST',{id:pending.id,...body});if(!current())return;status.textContent='Отзыв сохранён. Спасибо!';
        if(reason.value!=='helpful')status.append(button('Уточнить это в чате',()=>onQuestion(`Я не согласен с ${which.value===''?'общим разбором':`советом «${which.selectedOptions[0].textContent}»`}. ${comment.value.trim()} Сначала уточни недостающие обстоятельства.`)));
      }catch(error){if(current()){status.textContent=error.message;send.disabled=false;}}
    });feedback.append(form);host.append(feedback);
  }

  const practice=details('Потренироваться на эпизоде из этого матча'),practiceBody=el('div');practice.append(practiceBody);host.append(practice);
  let practiceLoaded=false;
  practice.addEventListener('toggle',()=>{if(!practice.open||practiceLoaded||!current())return;practiceLoaded=true;void loadPractice();});
  async function loadPractice(){practiceBody.replaceChildren(el('p','Подбираем эпизоды…','help'));
    try{const data=await api(`/api/replays/${jobId}/practice`);if(!current())return;if(data.report_sha256!==reportHash)throw Error('Разбор обновился. Открой его заново.');practiceBody.replaceChildren();
      if(!data.scenarios.length){practiceBody.append(el('p',data.position_required?'Сначала укажи позицию в этом матче.':'В этом реплее нет подходящих подтверждённых эпизодов. Упражнения доступны в «Моей практике».','help'));return;}
      const pick=el('select'),content=el('div');data.scenarios.forEach((s,i)=>pick.append(new Option(s.title,String(i))));practiceBody.append(field('Выбери ситуацию',pick),content);
      const render=()=>{const s=data.scenarios[Number(pick.value)];content.replaceChildren();const form=el('form'),answer=el('textarea');answer.minLength=10;answer.maxLength=1500;answer.rows=3;answer.required=true;
        const saved=data.attempts.find(a=>a.exercise_id===s.exercise_id&&a.evidence_id===s.episode.evidence_id);if(saved)answer.value=saved.answer;
        const send=el('button','Сохранить ответ и разобрать варианты','secondary');send.type='submit';const result=el('div');result.setAttribute('aria-live','polite');let pending=null;
        content.append(button(`${stamp(s.episode.time)} · Открыть эпизод`,()=>onEvidence(s.episode.evidence_id)),el('p',s.question));
        form.append(field('Как бы ты поступил и почему?',answer),send);content.append(form,result);
        form.addEventListener('submit',async event=>{event.preventDefault();if(send.disabled||!current())return;const value=answer.value.trim();if(value.length<10)return;
          if(!pending||pending.answer!==value)pending={id:crypto.randomUUID(),answer:value,report_sha256:reportHash,exercise_id:s.exercise_id,evidence_id:s.episode.evidence_id};send.disabled=true;
          try{const r=await api(`/api/replays/${jobId}/practice`,'POST',pending);if(!current())return;result.replaceChildren();for(const [k,t] of [['action','Вариант действия'],['why','Почему'],['exception','Когда выбрать иначе'],['measurement','Как проверить']]){result.append(el('p',t,'decision-label'),el('p',r.reflection[k]));}result.append(el('p',r.note,'help'),button('Обсудить мой ответ с ИИ',()=>onQuestion(`Эпизод ${stamp(s.episode.time)}. ${s.question} Мой ответ: ${value}. Какие условия я мог не учесть?`)));}
          catch(error){if(current()){result.textContent=error.message;send.disabled=false;}}
        });};pick.addEventListener('change',render);render();
    }catch(error){if(current()){practiceBody.replaceChildren(el('p',error.message,'help'),button('Повторить',loadPractice));}}
  }

  const share=details('Карточка для Telegram'),options=el('div',undefined,'share-options'),choice=el('select');
  const choices=[{label:'Факты моего матча',title:'Мой матч',copy:`Убийства / смерти / помощи: ${number(report.metrics?.kills)} / ${number(report.metrics?.deaths)} / ${number(report.metrics?.assists)}`}];
  if(next?.action)choices.unshift({label:'Мой фокус на следующую игру',title:'Мой следующий шаг',copy:next.action});
  if(strength?.observation)choices.push({label:'Полезный вывод тренера',title:'Стоит повторить',copy:strength.observation});
  choices.forEach((row,i)=>choice.append(new Option(row.label,String(i))));
  const showName=el('input'),showMatch=el('input');showName.type=showMatch.type='checkbox';
  const preview=el('img');preview.alt='Предпросмотр карточки NARMA VISION';preview.className='share-preview';preview.hidden=true;
  const status=el('p','','help');status.setAttribute('role','status');const actions=el('div',undefined,'chat-actions');let card=null,version=0;
  const download=button('Скачать PNG',()=>{if(!card||!current())return;const a=el('a');a.href=card.url;a.download='narma-vision-result.png';a.click();});download.disabled=true;
  const send=button('Поделиться…',async()=>{if(!card||!current())return;try{const file=new File([card.blob],'narma-vision-result.png',{type:'image/png'});if(navigator.canShare?.({files:[file]}))await navigator.share({files:[file],title:'NARMA VISION'});else status.textContent='Скачай PNG и прикрепи его в Telegram.';}catch(error){if(current()&&error.name!=='AbortError')status.textContent='Не удалось открыть отправку. Можно скачать карточку.';}});send.disabled=true;
  const prepare=button('Посмотреть карточку',async()=>{const v=++version;const c=document.createElement('canvas');c.width=1080;c.height=1080;const ctx=c.getContext('2d');ctx.fillStyle='#001621';ctx.fillRect(0,0,1080,1080);ctx.fillStyle='#FF4103';ctx.fillRect(70,70,8,110);ctx.fillStyle='#FFFDF1';ctx.font='500 38px sans-serif';ctx.fillText('NARMA VISION',110,115);ctx.fillStyle='#B5C2C6';ctx.font='26px sans-serif';ctx.fillText('ТВОЯ ИГРА. ТВОИ РЕШЕНИЯ.',110,160);
    const selected=choices[Number(choice.value)];ctx.fillStyle='#FF9A78';ctx.font='32px sans-serif';ctx.fillText(selected.title,70,280);ctx.fillStyle='#FFFDF1';ctx.font='38px sans-serif';
    const words=selected.copy.split(/\s+/);let line='',y=370,lines=0;for(let i=0;i<words.length;i++){const nextLine=(line+' '+words[i]).trim();if(ctx.measureText(nextLine).width>930&&line){ctx.fillText(line,70,y);y+=56;lines++;line=words[i];if(lines===8){line+='…';break;}}else line=nextLine;}ctx.fillText(line,70,y);
    ctx.fillStyle='#B5C2C6';ctx.font='28px sans-serif';ctx.fillText(heroName(report.player?.hero).slice(0,40),70,940);if(showName.checked)ctx.fillText(String(report.player?.nickname??'').slice(0,36),70,990);if(showMatch.checked){ctx.textAlign='right';ctx.fillText(`#${report.match_id}`,1010,990);}
    const blob=await new Promise(resolve=>c.toBlob(resolve,'image/png'));if(!current()||v!==version||!blob)return;if(card)URL.revokeObjectURL(card.url);const url=URL.createObjectURL(blob);urls.push(url);card={blob,url};preview.src=url;preview.hidden=false;download.disabled=send.disabled=false;status.textContent='Проверь карточку перед отправкой.';
  },'secondary');
  const invalidate=()=>{version++;card=null;preview.removeAttribute('src');preview.hidden=true;download.disabled=send.disabled=true;status.textContent='Обнови предпросмотр после изменений.';};for(const input of [choice,showName,showMatch])input.addEventListener('change',invalidate);
  options.append(field('Что показать',choice),field('Показать мой ник',showName),field('Показать номер матча',showMatch));actions.append(prepare,download,send);share.append(options,actions,preview,status);host.append(share);
}
