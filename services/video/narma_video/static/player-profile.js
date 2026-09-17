const node=(tag,text,cls)=>Object.assign(document.createElement(tag),{...(text!=null?{textContent:String(text)}:{}),...(cls?{className:cls}:{})});
const field=(key,title,choices,help='')=>({key,title,choices,help});
const fields=[
 field('goal','Что хочешь изменить в своей игре?', [['consistency','Играть стабильнее'],['new_role','Освоить роль'],['returning','Вернуться после перерыва'],['ranked','Подготовиться к рейтингу'],['decisions','Лучше понимать решения'],['custom','Своя цель']], 'Выберем одно направление. Рост рейтинга не обещаем.'),
 field('position','На какой позиции играешь чаще?',[[1,'1 · Керри'],[2,'2 · Мидер'],[3,'3 · Офлейнер'],[4,'4 · Поддержка'],[5,'5 · Полная поддержка'],[null,'Пробую разные / пока не знаю']], 'В каждом матче роль можно указать отдельно.'),
 field('rank_band','Какой сейчас примерный рейтинг?',[['unranked','Без рейтинга'],['unknown','Не знаю / не хочу указывать'],['under1000','До 1 000 MMR'],['1000_2000','1 000–2 000 MMR'],['2000_3000','2 000–3 000 MMR'],['3000_5000','3 000–5 000 MMR'],['5000_8000','5 000–8 000 MMR'],['over8000','Больше 8 000 MMR']], 'Это стартовый ориентир, а не оценка навыков.'),
 field('experience','Какой у тебя сейчас опыт?',[['beginner','Начинаю разбираться'],['regular','Играю регулярно'],['returning','Возвращаюсь после перерыва']], 'Новое понятие можно будет объяснить подробнее в любой момент.'),
 field('matches_per_week','Сколько матчей обычно играешь за неделю?',[['rare','0–2 матча'],['steady','3–7 матчей'],['frequent','8–15 матчей'],['intensive','Больше 15'],['variable','По-разному']], 'Подстроим проверку под твой ритм. Играть чаще не обязательно.'),
 field('practice_minutes','Сколько времени есть на отдельную практику?',[[0,'Только во время матча'],[5,'До 5 минут'],[10,'До 10 минут'],[20,'До 20 минут']], 'Дадим выполнимое задание вместо длинного списка.'),
 field('explanation','Как удобнее получать совет?',[['short','Короткий вывод и действие'],['detailed','С пояснением и примером'],['question','Сначала вопрос о моём решении']], 'Подачу можно менять. Факты разбора останутся теми же.'),
 field('learning_obstacle','Что чаще мешает применить совет?',[['understanding','Не до конца понимаю совет'],['noticing','Понимаю, но не замечаю момент'],['execution','Замечаю, но сложно выполнить'],['unsure','Пока не знаю']], 'Выберем объяснение, тренировку распознавания или повторение действия.'),
 field('after_losses','После двух поражений что чаще происходило в последних играх?',[['steady','Продолжал в обычном темпе'],['rush','Начинал спешить'],['switch','Менял героя или роль'],['pause','Делал паузу'],['varies','По-разному'],['skip','Не хочу отвечать']], 'Необязательно. Это привычка в игре, а не характеристика личности.'),
 field('communication','Как обычно играешь?',[['solo','Чаще соло'],['friends','Чаще с друзьями'],['mixed','По-разному']], 'Упражнение должно учитывать, можешь ли ты заранее договориться с командой.'),
 field('focus_skill','Что сейчас хочется проверить в первую очередь?',[['laning','Решения на линии'],['resources','Ресурсы и перемещения'],['vision','Обзор и выходы по карте'],['fights','Выбор и участие в боях'],['items','Предметы под задачу'],['after_fight','Действия после боя'],['unknown','Пока не знаю']], 'Это твоя гипотеза. Проверим её по собственным матчам.'),
 field('feedback_format','С чего удобнее начать тренировку?',[['episode','С эпизода моего матча'],['checklist','С короткой памятки'],['practice','С повторения действия']], 'Подстроим первый шаг под удобный способ практики.')
];
const tone=field('tone','Какой тон тебе ближе?',[['calm','Спокойный'],['direct','Прямой и уважительный']]);
const scenarios=[
 {id:'lane',title:'Волна или помощь?',text:'К вашей башне идёт волна. Союзник зовёт в бой, но ты не знаешь, сможет ли команда дождаться тебя. Что проверишь или сделаешь первым?'},
 {id:'map',title:'Выход за реку',text:'Несколько соперников не видны. За рекой есть ресурс, но поддержки рядом нет. Как будешь принимать решение о выходе?'},
 {id:'fight',title:'Что после боя?',text:'Команда выиграла небольшой бой. Часть союзников потеряла много здоровья, линии отодвинуты не все. На чём сосредоточишь следующий шаг?'}
];
const scenarioChoices=[['act','Попробую сразу действовать'],['wait','Сначала соберу недостающую информацию'],['alternative','Выберу другое доступное действие'],['unknown','Пока не знаю — хочу разобрать с тренером']];
const TOTAL=fields.length+scenarios.length;
const labelFor=(f,value)=>f.choices.find(([key])=>key===value)?.[1]??'Не указано';
export function renderProfileGuidance(guide,{preliminary=false}={}){
 const card=node('section',null,'profile-guidance');card.dataset.profileRevision=String(guide.revision);
 card.append(node('p',preliminary?'Твоя первая практика · по ответам':'Твой ритм практики','eyebrow'),node('h3',preliminary?guide.title:guide.goal));
 if(preliminary)card.append(node('p',guide.action,'program-action'));
 card.append(node('p',guide.dose),node('p',guide.preparation));
 if(preliminary)card.append(node('p',guide.exception,'help'),node('p',guide.measurement,'help'));
 const why=node('details');why.append(node('summary','Почему эта тренировка подходит тебе'));
 for(const text of guide.basis||[])why.append(node('p',text));
 why.append(node('p',`${guide.explanation} ${guide.tone}.`),node('p',guide.limitation,'help'));card.append(why);return card;
}

export function createPlayerProfile({host,api,current,onNavigate,onChanged}){
 let profile=null,guide=null,step=0,serial=0,busy=false,mode='summary',identity=null;
 const button=(text,run,cls='secondary')=>{const b=node('button',text,cls);b.type='button';b.addEventListener('click',()=>void run());return b;};
 const valid=(token,user)=>token===serial&&current()===user&&user===identity;
 function focusHeading(){const h=host.querySelector('h2');if(h){h.tabIndex=-1;h.focus({preventScroll:true});}}
 function clear(){serial++;identity=null;profile=null;guide=null;busy=false;host.replaceChildren();}
 async function load({autoStart=false}={}){
  identity=current();const user=identity,token=++serial;busy=false;
  host.replaceChildren(node('p','Открываем твой профиль…','help'));host.setAttribute('aria-busy','true');
  try{
   const data=await api('/api/player-profile');if(!valid(token,user))return;
   profile=data.profile;guide=data.guidance;onChanged?.(data);
   if(autoStart&&profile.state==='not_started'){step=0;mode='form';onNavigate('player-profile');}
   else if(profile.state==='partial'||(profile.state==='ready'&&profile.last_step>7&&profile.last_step<TOTAL)){step=Math.min(profile.last_step,TOTAL-1);mode='form';}
   else mode='summary';
   render();return data;
  }catch(error){if(valid(token,user)){host.replaceChildren(node('p',error.message,'help'),button('Попробовать ещё раз',()=>load({autoStart})));}}
  finally{if(valid(token,user))host.setAttribute('aria-busy','false');}
 }
 function start(index=0){if(!profile)return;step=index;mode='form';render();focusHeading();}
 function options(form,f,value,{optional=false}={}){
  const group=node('fieldset',null,'profile-question');const legend=node('legend',f.title);group.append(legend);
  if(f.help)group.append(node('p',f.help,'help'));
  const list=node('div',null,'profile-options');
  for(const [key,text] of f.choices){const label=node('label',null,'profile-choice'),input=document.createElement('input');input.type='radio';input.name=f.key;input.value=key===null?'unknown':String(key);input.checked=value===key;input.required=!optional;label.append(input,node('span',text));list.append(label);}
  group.append(list);form.append(group);return group;
 }
 function textField(form,key,label,value,max,textarea=false){const wrap=node('div',null,'profile-text-field'),l=node('label',label),input=document.createElement(textarea?'textarea':'input');input.id=`profile-${key}`;input.name=key;input.maxLength=max;input.value=value||'';l.htmlFor=input.id;if(textarea)input.rows=3;wrap.append(l,input);form.append(wrap);return input;}
 function selected(form,key){return form.querySelector(`input[name="${key}"]:checked`)?.value;}
 function collect(form){
  const answers={},f=fields[step];
  if(f){const value=selected(form,f.key);if(value!==undefined)answers[f.key]=f.key==='position'?(value==='unknown'?null:Number(value)):f.key==='practice_minutes'?Number(value):value;
   if(step===0)answers.goal_note=form.elements.goal_note.value.trim();
   if(step===1)answers.heroes=form.elements.heroes.value.split(',').map(x=>x.trim()).filter(Boolean);
   if(step===6){const toneValue=selected(form,'tone');if(toneValue)answers.tone=toneValue;}
  }else{const scenario=scenarios[step-fields.length],choice=selected(form,'scenario');if(choice)answers.scenarios={...profile.answers.scenarios,[scenario.id]:{choice,reason:form.elements.reason.value.trim()}};}
  return answers;
 }
 async function persist(action,answers,lastStep,form,done){
  if(busy)return;busy=true;const token=serial,user=identity,status=form.querySelector('[role="status"]');
  const controls=[...form.querySelectorAll('input,textarea,button')];controls.forEach(x=>x.disabled=true);status.textContent='Сохраняем…';
  try{
   const data=await api('/api/player-profile','PUT',{expected_revision:profile.revision,action,last_step:lastStep,answers});if(!valid(token,user))return;
   profile=data.profile;guide=data.guidance;onChanged?.(data);busy=false;done();
  }catch(error){if(valid(token,user)){status.textContent=`${error.message} Ответы на экране сохранены. Можно повторить отправку.`;controls.forEach(x=>x.disabled=false);const refresh=button('Перечитать сохранённый профиль',()=>load());status.append(document.createTextNode(' '),refresh);}}
  finally{if(valid(token,user))busy=false;}
 }
 function render(){
  host.replaceChildren();host.removeAttribute('aria-busy');
  if(!profile)return;
  if(mode==='summary'){summary();return;}
  const card=node('section',null,'surface profile-wizard');const deep=step>=7;
  card.append(node('p',deep?`Глубже о твоей игре · ${step-6} из ${TOTAL-7}`:`Настройка тренера · ${step+1} из 7`,'eyebrow'));
  const progress=document.createElement('progress');progress.max=deep?TOTAL-7:7;progress.value=deep?step-7:step;progress.setAttribute('aria-label',deep?'Пройдено дополнительных вопросов':'Пройдено основных вопросов');card.append(progress);
  card.append(node('h2',deep?'Разберём твои привычки':'Тренер под твою игру'));
  if(step===0)card.append(node('p','Около 2–3 минут. Ответы сохраняются после каждого шага. Можно настроить позже.','muted'));
  const form=document.createElement('form');form.noValidate=true;form.className='profile-form';card.append(form);host.append(card);
  const a=profile.answers;
  if(step<fields.length){options(form,fields[step],Object.hasOwn(a,fields[step].key)?a[fields[step].key]:undefined);
   if(step===0){const input=textField(form,'goal_note','Своя цель · если выбрал этот вариант',a.goal_note,160);input.autocomplete='off';}
   if(step===1)textField(form,'heroes','До трёх привычных героев через запятую · необязательно',(a.heroes||[]).join(', '),122);
   if(step===6)options(form,tone,a.tone,{optional:true});
  }else{
   const scenario=scenarios[step-fields.length],saved=a.scenarios?.[scenario.id];
   form.append(node('p',scenario.text,'profile-scenario'),node('p',`Рассмотри ситуацию со своей позиции${a.position?` ${a.position}`:''}. Это вопрос для знакомства с твоими решениями: баллов и оценки личности не будет.`,'help'));
   options(form,field('scenario',scenario.title,scenarioChoices),saved?.choice);textField(form,'reason','Почему этот вариант? Что ещё нужно знать? · необязательно',saved?.reason,300,true);
  }
  const error=node('p','','profile-error');error.setAttribute('role','alert');form.append(error);
  const actions=node('div',null,'profile-actions');if(step>0)actions.append(button('Назад',()=>{step--;render();focusHeading();},'quiet'));
  const next=node('button',step===6?'Получить первую тренировку':step===TOTAL-1?'Сохранить профиль':'Сохранить и продолжить','primary');next.type='submit';actions.append(next);form.append(actions);
  const later=button(deep?'Закончить на этом':'Настроить позже',()=>persist(deep&&profile.state==='ready'?'finish':'skip',collect(form),step,form,()=>{mode='summary';render();onNavigate('training');}), 'quiet');form.append(later);
  const status=node('p','','help');status.setAttribute('role','status');status.setAttribute('aria-live','polite');form.append(status);
  form.append(node('p','Ответы доступны в твоём аккаунте. Нужные для ответа настройки и пояснения передаются ИИ-тренеру. Не указывай личные контакты или другие сведения, не нужные тренировке.','profile-privacy help'));
  form.addEventListener('submit',event=>{event.preventDefault();const answers=collect(form);const f=fields[step];if((f&&!Object.hasOwn(answers,f.key))||(!f&&!answers.scenarios)){error.textContent='Выбери вариант. Если не уверен, можно вернуться к настройке позже.';form.querySelector('input')?.focus();return;}
   if(step===0&&answers.goal==='custom'&&!answers.goal_note){error.textContent='Коротко опиши свою цель.';form.elements.goal_note.focus();return;}
   const finish=step===6||step===TOTAL-1;
   void persist(finish?'finish':'save',answers,step+1,form,()=>{if(finish)mode='summary';else step++;render();focusHeading();});
  });
 }
 function summary(){
  const card=node('section',null,'surface profile-summary');host.append(card);
  card.append(node('p',profile.state==='ready'?'Твой профиль сохранён':'Можно начать с малого','eyebrow'),node('h2',profile.state==='ready'?'Тренер знает твои ориентиры':'Настрой тренировку под себя'));
  if(guide)card.append(renderProfileGuidance(guide,{preliminary:true}));else card.append(node('p','Выбери цель, опыт и удобный ритм. Без анкеты доступны твои отчёты и обычный разбор.'));
  const actions=node('div',null,'profile-actions');actions.append(button(guide?'К моей тренировке':'Начать настройку',()=>guide?onNavigate('training'):start(),'primary'));
  if(guide)actions.append(button('Изменить основные ответы',()=>start()),button('Уточнить привычки и решения',()=>start(7)));else actions.append(button('Перейти к матчам',()=>onNavigate('review')));card.append(actions);
  if(Object.keys(profile.answers).length){const details=node('details',null,'profile-answers');details.append(node('summary','Все сохранённые ответы'));
   for(const f of [...fields,tone])if(Object.hasOwn(profile.answers,f.key)){const p=node('p');p.append(node('strong',`${f.title} `),document.createTextNode(labelFor(f,profile.answers[f.key])));details.append(p);}
   if(profile.answers.heroes?.length)details.append(node('p',`Герои: ${profile.answers.heroes.join(', ')}`));
   if(profile.answers.goal_note)details.append(node('p',`Своя цель: ${profile.answers.goal_note}`));
   for(const scenario of scenarios){const answer=profile.answers.scenarios?.[scenario.id];if(answer)details.append(node('p',`${scenario.title}: ${scenarioChoices.find(([k])=>k===answer.choice)?.[1]}. ${answer.reason||''}`));}
   card.append(details);
  }
  const resetBox=node('div',null,'profile-reset');resetBox.append(button('Сбросить ответы анкеты',()=>{
   resetBox.replaceChildren(node('p','Удалить ответы и сохранённые настройки тренировок? Отчёты и тексты прежних диалогов останутся.'),button('Да, сбросить ответы',async()=>{
    if(busy)return;busy=true;const token=serial,user=identity;resetBox.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{const data=await api('/api/player-profile','DELETE');if(!valid(token,user))return;profile=data.profile;guide=data.guidance;onChanged?.(data);render();focusHeading();}
    catch(error){if(valid(token,user)){resetBox.append(node('p',error.message,'help'));resetBox.querySelectorAll('button').forEach(b=>b.disabled=false);}}
    finally{if(valid(token,user))busy=false;}
   }),button('Оставить ответы',()=>render(),'quiet'));
  },'quiet'));if(Object.keys(profile.answers).length)card.append(resetBox);
  card.append(node('p','Опыт и привычки можно пересматривать. Анкета не определяет психотип и не доказывает уровень навыков.','help'));
 }
 return {load,clear,start,get value(){return profile;}};
}
