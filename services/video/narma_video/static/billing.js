const el=(tag,text,cls)=>Object.assign(document.createElement(tag),{...(text!=null?{textContent:String(text)}:{}),...(cls?{className:cls}:{})});
const rub=amount=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB'}).format(amount/100);
const labels={pending:'Ожидает подтверждения',succeeded:'Завершён',canceled:'Отменён',requested:'Заявка принята'};
const safeLink=(url,label)=>{const a=el('a',label);try{const u=new URL(url);if(u.protocol==='https:'&&!u.username&&!u.password){a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}}catch{}return a;};
export function createBilling({host,api,current}){
  let serial=0;
  async function load(){
    const token=++serial,identity=current(),valid=()=>serial===token&&current()===identity;host.replaceChildren(el('p','Загружаем покупки…','help'));
    const button=(label,run,cls='secondary')=>{const b=el('button',label,cls);b.type='button';b.addEventListener('click',async()=>{b.disabled=true;try{await run();}catch(error){if(valid()){status.textContent=error.message;b.disabled=false;}}});return b;};
    const status=el('p','','help');status.setAttribute('role','status');
    try{
      const data=await api('/api/billing');if(!valid())return;host.replaceChildren(el('h2','Разборы и покупки'),status);
      host.append(el('p',`Доступно разборов: ${data.balance}. В обработке: ${data.held}.`,'program-action'));
      host.append(el('p','Покупка разовая, без автоматического продления. Просмотр готовых отчётов не расходует баланс. При техническом сбое попытка возвращается.','help'));
      if(data.mode==='test')host.append(el('p','Тестовый магазин: настоящие деньги не принимаются, тестовый баланс не оплачивает реальные разборы.','help'));
      if(!data.checkout_enabled)host.append(el('p','Продажа разборов пока не открыта. Пилот работает в пределах доступных лимитов.','help'));
      else{
        const consent=el('label'),accepted=el('input');accepted.type='checkbox';consent.append(accepted,document.createTextNode(' Принимаю '),safeLink(data.terms_url,'условия покупки'),document.createTextNode(' и ознакомился с '),safeLink(data.privacy_url,'обработкой данных'));host.append(consent);
        for(const product of data.products){const key=crypto.randomUUID();host.append(button(`${product.units===1?'Один разбор':'Пять разборов'} · ${rub(product.amount)}`,async()=>{if(!accepted.checked)throw Error('Сначала прочитай и прими условия покупки.');const result=await api('/api/billing/orders','POST',{id:key,product:product.id,terms_version:data.terms_version,accepted:true});if(!valid())return;await load();if(current()!==identity)return;if(result.order?.checkout_url){const a=safeLink(result.order.checkout_url,'Перейти к оплате');a.className='button primary';host.prepend(a);}},'primary'));}
      }
      host.append(button('Проверить баланс и историю',load,'quiet'));
      if(data.seller)host.append(el('p',`Продавец: ${data.seller}`,'help'));
      if(data.support_email){const a=el('a','Помощь с покупкой или разбором');a.href='mailto:'+encodeURIComponent(data.support_email);host.append(a);}
      const list=el('div',null,'billing-orders');host.append(list);
      if(!data.orders.length)list.append(el('p','Покупок пока нет.','help'));
      for(const order of data.orders){const card=el('article',null,'surface');card.append(el('h3',`${order.units} разбор(ов) · ${rub(order.amount)}`),el('p',`${labels[order.status]}${order.mode==='test'?' · тестовый заказ':''}. Остаток: ${order.remaining}.`),el('p',`Заказ ${order.id}`,'help'));list.append(card);
        if(order.status==='pending'){card.append(button('Проверить оплату',async()=>{await api(`/api/billing/orders/${order.id}/refresh`,'POST',{});if(valid())await load();}));if(order.checkout_url)card.append(safeLink(order.checkout_url,'Продолжить оплату'));
          card.append(el('p','Если оплата зависла, проверь этот заказ. Создавать новый для повторной оплаты не нужно.','help'));}
        const refund=data.refunds.find(r=>r.order_id===order.id);
        if(refund)card.append(el('p',`Возврат ${rub(refund.amount)}: ${labels[refund.status]}.`,'help'));
        else if(order.status==='succeeded'&&order.remaining>0){const form=el('form'),label=el('label','Причина возврата неиспользованного остатка'),reason=el('textarea');reason.required=true;reason.minLength=5;reason.maxLength=1500;label.append(reason);form.append(label);const submit=el('button','Запросить возврат','secondary');submit.type='submit';form.append(submit);form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await api(`/api/billing/orders/${order.id}/refund`,'POST',{reason:reason.value.trim()});if(valid())await load();}catch(error){if(valid()){status.textContent=error.message;submit.disabled=false;}}});const details=el('details');details.append(el('summary','Вернуть неиспользованные разборы'),el('p','Остаток будет недоступен для новых разборов до решения по возврату. Сохранённые отчёты останутся доступны.','help'),form);card.append(details);}
      }
      if(identity?.is_platform_owner){const queue=await api('/api/billing/refunds');if(!valid())return;const section=el('section',null,'surface');section.append(el('h3','Заявки на возврат'));host.append(section);
        for(const refund of queue.refunds){const item=el('div');item.append(el('p',`${refund.id} · ${rub(refund.amount)} · ${labels[refund.status]}`),el('p',refund.reason));section.append(item);if(!['requested','pending'].includes(refund.status))continue;const label=el('label','Текущий пароль владельца'),password=el('input');password.type='password';password.autocomplete='current-password';label.append(password);item.append(label,button('Подтвердить или проверить возврат',async()=>{const value=password.value;password.value='';if(!value)throw Error('Введи текущий пароль владельца.');await api(`/api/billing/refunds/${refund.id}/approve`,'POST',{current_password:value});if(valid())await load();}));}
      }
    }catch(error){if(valid()){host.replaceChildren(el('h2','Разборы и покупки'),status);status.textContent=error.message;host.append(button('Повторить',load));}}
  }
  return {load,clear(){serial++;host.replaceChildren();}};
}
