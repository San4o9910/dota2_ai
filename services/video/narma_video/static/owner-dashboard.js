const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const usd=value=>`$${(Number(value??0)/1e6).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4})}`;
const kinds={replay:'Разборы демо',video:'Разборы видео',hermes:'Фоновый тренер',chat:'Чат'};
const reasons={context:'Не учтена ситуация',role:'Не учтена роль',generic:'Общий совет',facts:'Ошибка в фактах',helpful:'Совет помог'};
export function createOwnerDashboard({api,host}){
  let identity=null,generation=0;
  function setSession(user){generation++;identity=user?.is_platform_owner?user:null;host.replaceChildren();}
  function clearPassword(){host.querySelectorAll('input[type=password]').forEach(input=>{input.value='';});}
  async function load(){const own=identity,id=++generation;host.replaceChildren();if(!own){host.append(el('p','Раздел доступен владельцу платформы.','help'));return;}
    const status=el('p','Загружаем состояние платформы…','help');status.setAttribute('role','status');host.append(status);
    const current=()=>identity===own&&generation===id&&host.isConnected;
    try{const data=await api('/api/owner/dashboard');if(!current())return;status.textContent='';
      host.append(el('p',data.window_note,'help'));
      const jobs=el('div',undefined,'owner-metrics');for(const row of data.jobs){const box=el('section',undefined,'growth-block');box.append(el('h3',kinds[row.kind]??row.kind),el('p',`Готово: ${row.ready} · Ошибки: ${row.failed}`),el('p',`В очереди: ${row.queued} · В работе: ${row.processing}`),el('p',row.mean_completion_seconds===null?'Нет готовых заданий за период.':`Среднее время до готовности: ${Math.round(row.mean_completion_seconds/60)} мин.`,'help'));jobs.append(box);}host.append(jobs);
      const costs=el('section',undefined,'growth-block');costs.append(el('h3','Расходы на ИИ'));
      for(const row of data.costs)costs.append(el('p',`${kinds[row.kind]??row.kind}: ${usd(row.spent_microusd)} · ${row.calls} запросов · в резерве ${usd(row.held_microusd)}`));
      costs.append(el('p',data.cost_note,'help'));if(data.openai_budget){const b=data.openai_budget;costs.append(el('p',`Общий остаток OpenAI: ${usd(Math.max(0,b.limit_microusd-b.spent_microusd-b.reserved_microusd))}. Срок: ${new Date(b.expires_at).toLocaleString('ru-RU')}.`));}host.append(costs);
      const users=el('section',undefined,'growth-block');users.append(el('h3','Расходы и ограничения по игрокам'),el('p','Лимит — общая сумма расходов на ИИ за всё время, включая резерв. Пустое поле оставляет только общие ограничения платформы. Ноль запрещает новые запросы. Снижение лимита не отменяет уже отправленный запрос.','help'));
      const password=el('input');password.type='password';password.autocomplete='current-password';password.maxLength=256;const label=el('label','Твой пароль для изменения лимита');label.append(password);users.append(label);
      for(const user of data.users){const row=el('form',undefined,'owner-user');row.append(el('h4',user.email),el('p',`Учтено ${usd(user.spent_microusd)} · в резерве ${usd(user.held_microusd)}${user.unknown_calls?` · требуют сверки: ${user.unknown_calls}`:''}`));
        const input=el('input');input.type='text';input.inputMode='decimal';input.placeholder='Только общий лимит';input.value=user.limit_microusd===null?'':String(Number(user.limit_microusd)/1e6);const field=el('label','Общий лимит игрока, $');field.append(input);
        const save=el('button','Сохранить лимит','secondary');save.type='submit';const state=el('p','','help');state.setAttribute('role','status');row.append(field,save,state);
        row.addEventListener('submit',async event=>{event.preventDefault();if(!current()||save.disabled)return;const value=input.value.trim().replace(',','.');
          if(value&&!/^\d{1,4}(?:\.\d{1,2})?$/.test(value)){state.textContent='Введи сумму с точностью до центов, например 2,50.';return;}
          const limit=value?Math.round(Number(value)*1e6):null;if(limit!==null&&limit>1e9){state.textContent='Максимальное значение — $1000.';return;}
          if(!password.value){state.textContent='Подтверди изменение своим паролем.';password.focus();return;}
          save.disabled=true;try{const credential=password.value;password.value='';await api(`/api/owner/users/${encodeURIComponent(user.owner_id)}/ai-limit`,'PUT',{limit_microusd:limit,current_password:credential});if(current())state.textContent='Лимит сохранён. Общий бюджет платформы не изменился.';}catch(error){if(current())state.textContent=error.message;}finally{if(current())save.disabled=false;}
        });users.append(row);
      }host.append(users);
      const feedback=el('section',undefined,'growth-block');feedback.append(el('h3','Отзывы о советах'));if(!data.feedback.length)feedback.append(el('p','Отзывов пока нет.','help'));
      for(const item of data.feedback){const row=el('article',undefined,'owner-feedback');row.append(el('h4',reasons[item.reason]??'Отзыв'),el('p',`${item.email} · ${new Date(item.created_at).toLocaleDateString('ru-RU')}`,'help'),el('p',item.comment||'Без пояснения'));feedback.append(row);}host.append(feedback);
    }catch(error){if(current()){status.textContent=error.message;const retry=el('button','Повторить','quiet');retry.type='button';retry.addEventListener('click',()=>void load());host.append(retry);}}
  }
  return {setSession,load,clearPassword};
}
