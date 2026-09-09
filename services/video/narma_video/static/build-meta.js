const ranks={HERALD_GUARDIAN:'Herald / Guardian',CRUSADER_ARCHON:'Crusader / Archon',LEGEND_ANCIENT:'Legend / Ancient',DIVINE_IMMORTAL:'Divine / Immortal'};
const modes={guide:'Учебный план',popular:'Чаще покупают',winrate:'Выше винрейт предметов'};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function createBuildMeta(signal,onPreferences){
  const params=new URLSearchParams(location.search);
  let rank=ranks[params.get('rank')]?params.get('rank'):'HERALD_GUARDIAN';
  let mode=modes[params.get('basis')]?params.get('basis'):'guide';
  let host=null,guide=null,callback=null,data=null,timer=null,request=null,sequence=0,disposed=false;
  const preferences=()=>({rank,basis:mode});
  const cancel=()=>{clearTimeout(timer);request?.abort();sequence++;};
  const dispose=()=>{disposed=true;cancel();};
  signal.addEventListener('abort',dispose,{once:true});
  function render(){
    if(!host?.isConnected||disposed)return;
    const status=host.querySelector('[data-meta-status]');
    const source=host.querySelector('[data-meta-source]');
    let message='Загружаем статистику покупок…';
    if(data?.status==='unavailable')message='Статистика покупок сейчас недоступна. Учебный план остаётся доступен.';
    else if(data?.stale&&data?.checked_at)message='Показана сохранённая статистика. Свежесть выборки пока не подтверждена.';
    else if(data?.status==='ready')message='Текущая неделя STRATZ · покупки на 0–75-й минутах. Проценты относятся к отдельным предметам.';
    if(data?.patch_status==='transition')message+=' Вышел новый патч: ждём выборку, которая не смешивает версии игры.';
    else if(data?.patch_status==='pool_review')message+=' План предметов требует проверки после нового патча.';
    else if(data?.patch_status==='unknown'&&data?.status==='ready')message+=' Актуальный патч пока не подтверждён.';
    status.textContent=message;
    source.replaceChildren();
    if(data?.checked_at){
      const stamp=new Date(data.checked_at);
      const link=document.createElement('a');link.href='https://stratz.com';
      // Use only the validated fixed-origin link supplied by this endpoint.
      if(/^https:\/\/stratz\.com\/heroes\/[1-9][0-9]{0,3}$/.test(data.source_url||''))link.href=data.source_url;
      else link.href='https://stratz.com';
      link.textContent='Статистика STRATZ ↗';link.target='_blank';link.rel='noopener noreferrer';source.append(link);
      if(Number.isFinite(stamp.getTime()))source.append(document.createTextNode(` · Обновлено ${stamp.toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}`));
    }
    const plan=data?.status==='ready'&&!data.stale&&Array.isArray(data.plans?.[mode])&&data.plans[mode].length===6?data.plans[mode]:null;
    let note=null;
    if(mode!=='guide')note=plan
      ?`${mode==='popular'?'Подбор по частоте покупки':'Подбор по винрейту с учётом размера выборки'} отдельных предметов для ${ranks[rank]}. Выбор ограничен подходящими герою предметами из руководства. Это не рейтинг готовых комплектов и не обязательный порядок покупок.`
      :'По выбранным условиям пока нет подтверждённого подбора на шесть слотов. Ниже показан учебный план.';
    callback(plan,note,data);
  }
  async function refresh(){
    if(disposed||!host?.isConnected)return;
    if(document.hidden){timer=setTimeout(refresh,60000);return;}
    request?.abort();request=new AbortController();const mine=++sequence;
    try{
      const response=await fetch(`/api/explore/builds?guide=${encodeURIComponent(guide.id)}&rank=${rank}`,{credentials:'omit',signal:AbortSignal.any([signal,request.signal,AbortSignal.timeout(20000)])});
      if(!response.ok)throw Error('unavailable');
      const value=await response.json();
      if(value.schema_version!=='narma.build-meta.v1'||value.guide!==guide.id||value.rank!==rank)throw Error('invalid');
      if(mine!==sequence||disposed)return;
      data=value;render();
    }catch{
      if(mine!==sequence||disposed)return;
      data=data?.checked_at?{...data,status:'stale',stale:true,plans:{}}:{status:'unavailable'};render();
    }finally{if(mine===sequence&&!disposed)timer=setTimeout(refresh,data?.status==='loading'?10000:60000);}
  }
  function mount(target,currentGuide,onPlan){
    cancel();host=target;guide=currentGuide;callback=onPlan;data=null;
    host.innerHTML=`<div class="build-evidence-controls"><div class="field"><label for="build-rank">Ранг матчей</label><select id="build-rank">${Object.entries(ranks).map(([id,label])=>`<option value="${id}"${rank===id?' selected':''}>${label}</option>`).join('')}</select></div><div class="field"><label for="build-basis">Основа подбора</label><select id="build-basis">${Object.entries(modes).map(([id,label])=>`<option value="${id}"${mode===id?' selected':''}>${label}</option>`).join('')}</select></div></div><p data-meta-status role="status" aria-live="polite"></p><p class="build-evidence-source" data-meta-source></p>`;
    host.querySelector('#build-rank').addEventListener('change',event=>{rank=event.target.value;cancel();data=null;render();onPreferences();void refresh();});
    host.querySelector('#build-basis').addEventListener('change',event=>{mode=event.target.value;render();onPreferences();});
    render();void refresh();
  }
  return {mount,dispose,preferences};
}

export function itemEvidence(item){
  const e=item.evidence;
  if(!e||!Number.isInteger(e.matches)||e.matches<=0||!Number.isFinite(e.winrate)||e.winrate<0||e.winrate>100)return '';
  const format=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1});
  const minute=Number.isFinite(e.average_minute)&&e.average_minute>=0&&e.average_minute<=75?`<div><span>Средняя минута покупки</span><strong>${format.format(e.average_minute)} мин</strong></div>`:'';
  return `<div class="build-evidence-numbers"><div><span>Победы в матчах с предметом</span><strong>${format.format(e.winrate)}%</strong></div><div><span>Матчей в выборке</span><strong>${format.format(e.matches)}</strong></div>${minute}</div><p class="build-evidence-caution">${e.matches<100?'Малая выборка: меньше 100 матчей. ':''}Это статистика предмета, а не всего комплекта. Дорогие покупки чаще успевают сделать в успешных играх.</p>`;
}
