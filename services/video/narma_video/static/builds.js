import {createBuildMeta,itemEvidence} from './build-meta.js';
import {adaptationOptions,applyAdaptation} from './build-adaptations.js';
import {roleGuidance} from './role-guidance.js';
import {WORKSHOP_PHASES,validateWorkshopFeed,workshopMatchesPosition,workshopRoleLabel,workshopFreshness,sortWorkshopGuides} from './workshop-builds.js';
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const positions = {1:'Керри',2:'Мидер',3:'Офлейнер',4:'Поддержка',5:'Полная поддержка'};
const isWorkshop = guide => guide?.source === 'workshop';
const matchesPosition = (guide,position) => isWorkshop(guide)?workshopMatchesPosition(guide,position):(!position||String(guide.position)===position);
const guideRole = guide => isWorkshop(guide)?(guide.position_exact?`${guide.position} · ${positions[guide.position]}`:workshopRoleLabel(guide)):`${guide.position} · ${positions[guide.position]}`;
const mountedBuilds = new WeakMap();
const REVIEW_MAX_AGE = 7 * 24 * 60 * 60 * 1000;
export function buildFreshness(guide, feed, now = Date.now()) {
  const patch = feed?.latest_patch?.version;
  const checked = Date.parse(guide.checked_at || '');
  const feedChecked = Date.parse(feed?.checked_at || '');
  const reviewed = Number.isFinite(checked) && checked <= now && now - checked < REVIEW_MAX_AGE;
  const freshFeed = feed?.stale === false && Array.isArray(feed.errors) && feed.errors.length === 0
    && Number.isFinite(feedChecked) && feedChecked <= now + 300000 && now - feedChecked < 30 * 60 * 1000;
  if (patch && guide.verified_patch && patch !== guide.verified_patch) return {state:'patch_changed', stale:true,
    text:`Нужна повторная проверка: сборка для ${guide.verified_patch}, последняя известная версия — ${patch}.`};
  if (!freshFeed || !patch) return {state:'unknown', stale:true,
    text:`Последняя сверка механики: ${guide.verified_patch || 'патч не указан'}. Актуальную версию патча сейчас подтвердить не удалось.`};
  if (!reviewed || !guide.verified_patch) return {state:'review_due', stale:true,
    text:`Текущий патч ${patch}. План покупки требует новой проверки: мета меняется и внутри патча.`};
  return {state:'reviewed', stale:false, text:`Механика сверена с патчем ${guide.verified_patch}. Это учебный план, а не рейтинг по винрейту.`};
}
const sourceHosts = new Set(['www.dota2.com','dota2.com','store.steampowered.com','steamcommunity.com','dotacoach.gg','www.dotacoach.gg','bsjdota.com','www.youtube.com','youtube.com']);
function sourceURL(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.port && sourceHosts.has(url.hostname) ? url.href : ''; } catch { return ''; }
}
function asset(kind,id) {
  if(!/^[a-z0-9_]{1,80}$/.test(id||''))return '';
  // Keep this verified original on our origin after repeated CDN image failures.
  if(kind==='items'&&id==='hurricane_pike')return '/assets/dota/items/hurricane_pike.png';
  return `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/${kind}/${id}.png`;
}
function picture(kind,id,name,cls='') { const src=asset(kind,id);return src?`<img src="${src}" alt="" class="${cls}" width="88" height="64" loading="lazy" decoding="async">`:''; }
function sources(rows) {return (rows||[]).filter(row=>sourceURL(row.url)).map(row=>`<a href="${esc(sourceURL(row.url))}" target="_blank" rel="noopener noreferrer">${esc(row.title)} ↗</a>`).join('');}
function list(rows) {return `<ul>${(Array.isArray(rows)?rows:rows?[rows]:[]).map(row=>`<li>${esc(row)}</li>`).join('')}</ul>`;}
function items(rows) {
  return `<div class="build-items">${(rows||[]).map(item=>`<article class="build-item">${picture('items',item.id,item.name)}<div><h4>${esc(item.name)}</h4><p>${esc(item.why)}</p>${item.condition?`<p class="build-condition"><strong>Когда:</strong> ${esc(item.condition)}</p>`:''}</div></article>`).join('')}</div>`;
}
function finalItems(guide) {
  const rows=guide.final_items;
  return Array.isArray(rows)&&rows.length===6&&rows.every(item=>item&&asset('items',item.id)&&typeof item.name==='string'&&typeof item.why==='string')?rows:[];
}
function slotExplanation(item) {
  return `<h4>${esc(item.name)}</h4>${itemEvidence(item)}<p>${esc(item.why)}</p>${item.condition?`<p class="build-condition"><strong>Когда:</strong> ${esc(item.condition)}</p>`:''}`;
}
function inventory(rows,selectedSlot,note) {
  if(rows.length!==6)return '';
  return `<section class="build-inventory" aria-labelledby="build-inventory-heading"><div class="build-inventory-heading"><h3 id="build-inventory-heading">План на 6 слотов</h3><p>${esc(note||'Авторский ориентир Narma. Адаптируй сборку к матчу: предметы можно заменить под противников и свою задачу.')}</p></div><div class="build-inventory-grid" role="group" aria-label="Шесть предметов в инвентаре">${rows.map((item,index)=>`<button type="button" class="build-slot" data-build-slot="${index}" aria-pressed="${index===selectedSlot}" aria-controls="build-slot-detail" aria-label="Слот ${index+1}: ${esc(item.name)}">${picture('items',item.id,item.name)}<span>${esc(item.name)}</span></button>`).join('')}</div><div id="build-slot-detail" class="build-slot-detail" aria-live="polite" aria-atomic="true">${slotExplanation(rows[selectedSlot])}</div></section>`;
}
function imageFallbacks(root) {root.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{img.hidden=true;},{once:true}));}
function checkedDate(value) {const date=new Date(value);return value&&!Number.isNaN(date.getTime())?date.toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'}):null;}
async function getJSON(url,signal) {const response=await fetch(url,{credentials:'omit',signal:signal?AbortSignal.any([signal,AbortSignal.timeout(20000)]):AbortSignal.timeout(20000)});if(!response.ok)throw Error('CONTENT_UNAVAILABLE');return response.json();}

export async function mountBuilds(root) {
  mountedBuilds.get(root)?.();
  const controller=new AbortController();
  let timer=null,disposed=false,refreshing=false;
  let meta=null;
  const cleanup=()=>{disposed=true;clearTimeout(timer);meta?.dispose();controller.abort();document.removeEventListener('visibilitychange',onVisibility);window.removeEventListener('pagehide',onPageHide);window.removeEventListener('pageshow',onPageShow);};
  let refreshPatch=async()=>{};
  const onVisibility=()=>{if(!document.hidden)void refreshPatch();};
  const onPageHide=event=>{clearTimeout(timer);if(!event.persisted)cleanup();};
  const onPageShow=event=>{if(event.persisted)void refreshPatch();};
  mountedBuilds.set(root,cleanup);
  root.innerHTML=`<div class="page-heading"><div><p class="eyebrow">Предмет под игровую задачу</p><h1>Сборки с объяснением</h1><p>Выбери героя и позицию. Разберись, зачем нужен каждый предмет и когда стоит поменять план.</p></div><a class="text-link" href="/heroes">Все герои →</a></div><div id="build-library"><p class="page-status" role="status">Открываем руководства…</p></div>`;
  const content=root.querySelector('#build-library');
  try {
    // A slow community source must not delay the existing authored library.
    const initialWorkshop=getJSON('/api/explore/workshop-builds',controller.signal).then(data=>({data})).catch(()=>({error:true}));
    const [catalog,initialUpdates,initialReviews]=await Promise.all([getJSON('/assets/build-guides.json',controller.signal),getJSON('/api/explore/updates',controller.signal).then(data=>({data})).catch(()=>({error:true})),getJSON('/api/explore/build-reviews',controller.signal).catch(()=>null)]);
    if(disposed)return cleanup;
    let updatesResult=initialUpdates;
    let reviews=initialReviews;
    if(catalog.schema_version!=='narma.build-guides.v1'||!Array.isArray(catalog.guides))throw Error('CATALOG_INVALID');
    const authoredGuides=catalog.guides.filter(g=>/^[a-z0-9-]{1,90}$/.test(g.id)&&asset('heroes',g.hero_slug)&&positions[g.position]);
    if(!authoredGuides.length)throw Error('CATALOG_EMPTY');
    let guides=authoredGuides,workshopFeed=null,workshopLoading=true,workshopFailed=false,workshopReceivedAt=0;
    const params=new URLSearchParams(location.search);
    let query=(params.get('q')||params.get('hero')||'').slice(0,80),position=positions[params.get('position')]?params.get('position'):'';
    let sourceFilter=['narma','workshop'].includes(params.get('source'))?params.get('source'):'all';
    let pendingGuideId=/^steam-\d{1,20}$/.test(params.get('guide')||'')?params.get('guide'):null;
    let selected=guides.find(g=>g.id===params.get('guide'))||guides.find(g=>g.hero_slug===params.get('hero')&&(!position||String(g.position)===position))||null;
    const selectedSlots=new Map();
    const selectedAdaptations=new Map();
    const selectedWorkshopItems=new Map();
    const selectedWorkshopPhases=new Map();
    if(selected&&adaptationOptions(selected).some(row=>row.id===params.get('variant')))selectedAdaptations.set(selected.id,params.get('variant'));
    content.innerHTML=`<div class="build-toolbar"><div class="field"><label for="build-search">Поиск героя или руководства</label><input type="search" id="build-search" maxlength="80" placeholder="Например, Viper" value="${esc(query)}"></div><div class="field"><label for="build-position">Позиция</label><select id="build-position"><option value="">Все позиции</option>${Object.entries(positions).map(([id,label])=>`<option value="${id}"${position===id?' selected':''}>${id} · ${label}</option>`).join('')}</select></div><div class="field"><label for="build-source">Источник руководства</label><select id="build-source"><option value="all"${sourceFilter==='all'?' selected':''}>Все руководства</option><option value="workshop"${sourceFilter==='workshop'?' selected':''}>Сообщество · Steam Workshop</option><option value="narma"${sourceFilter==='narma'?' selected':''}>Narma · с объяснением решений</option></select></div><p class="build-editorial-note">Сборки сообщества показывают покупки автора по этапам игры. Планы Narma объясняют условия выбора. У каждого руководства указаны роль, источник и проверка патча.</p></div><div id="build-coverage" class="build-coverage" role="status" aria-live="polite"></div><div id="build-role-context" aria-live="polite"></div><div class="build-layout"><aside class="build-picker" aria-label="Выбор руководства"><p class="build-count" id="build-count" role="status" aria-live="polite"></p><div id="build-list"></div></aside><section id="build-detail" aria-label="Выбранное руководство"></section></div><aside class="build-meta"><div><p class="eyebrow">Проверяй изменения перед игрой</p><h2>Мета зависит от патча и уровня матчей</h2><p>Сначала проверь, что изменилось у героя, затем сравни его задачи со своим пулом. Популярная сборка не отменяет условия конкретного матча.</p></div><div class="build-meta-links"><a class="button subtle" href="/updates?category=patch">Изменения и новости Valve →</a><a class="text-link" href="https://www.dotabuff.com/heroes/meta" target="_blank" rel="noopener noreferrer">Статистика по рангам · Dotabuff ↗</a><a class="text-link" href="https://dota2protracker.com/meta" target="_blank" rel="noopener noreferrer">Матчи 7000+ MMR · Dota2ProTracker ↗</a></div></aside>`;
    const detail=content.querySelector('#build-detail');
    const workshopStatusFeed=()=>{
      const feed=updatesResult.data,checked=Date.parse(feed?.checked_at||'');
      const officialFresh=feed?.stale===false&&Array.isArray(feed.errors)&&feed.errors.length===0&&Number.isFinite(checked)&&checked<=Date.now()+300000&&Date.now()-checked<30*60*1000;
      const latest=officialFresh?feed.latest_patch?.version:(Date.now()-workshopReceivedAt<30*60*1000?workshopFeed?.latest_patch:null);
      return {...(workshopFeed||{}),latest_patch:latest||null};
    };
    const renderCoverage=()=>{
      const host=content.querySelector('#build-coverage');
      if(workshopLoading&&!workshopFeed){host.textContent='Загружаем сборки сообщества. Учебные планы Narma уже доступны.';return;}
      if(!workshopFeed){host.textContent='Сборки сообщества сейчас не загрузились. Учебные планы Narma доступны; загрузку повторим автоматически.';return;}
      const statusFeed=workshopStatusFeed();
      const heroCount=new Set(workshopFeed.guides.map(guide=>guide.hero_slug)).size;
      const currentCount=workshopFeed.guides.filter(guide=>workshopFreshness(guide,statusFeed).state==='current_patch').length;
      const samePatchCount=statusFeed.latest_patch?workshopFeed.guides.filter(guide=>guide.source_patch===statusFeed.latest_patch).length:0;
      const sourceFresh=!workshopFailed&&workshopFeed.stale===false;
      const patchSummary=statusFeed.latest_patch?`${samePatchCount} для патча ${esc(statusFeed.latest_patch)}`:'Текущий патч не подтверждён';
      const recentSummary=sourceFresh&&statusFeed.latest_patch?` · ${currentCount} обновлены авторами за последние 30 дней`:'';
      const checked=checkedDate(workshopFeed.checked_at);
      const markup=`<strong>Сборки сообщества · ${heroCount} из ${workshopFeed.coverage.total_heroes} героев</strong><span>${workshopFeed.guides.length} руководств · ${patchSummary}${recentSummary}${checked?` · Проверка ${esc(checked)}`:''}</span><span>${workshopFailed||workshopFeed.stale?'Показана сохранённая подборка. Обновление источника задерживается.':'Проверяем обновления авторов каждый день. После нового патча устаревшие сборки получают отметку.'} Винрейт и популярность готовых сборок этими источниками не подтверждены.</span>`;
      if(host.innerHTML!==markup)host.innerHTML=markup;
    };
    const roleHost=content.querySelector('#build-role-context'),roleCache=new Map();
    let roleSequence=0,displayedPosition=null;
    const renderRole=async()=>{
      const role=Number(position||selected?.position)||null;
      if(role===displayedPosition&&roleHost.hasChildNodes())return;
      const sequence=++roleSequence;displayedPosition=role;roleHost.replaceChildren();
      if(!role)return;
      roleHost.textContent=`Задачи позиции ${role} · ${positions[role]}…`;
      try{
        let context=roleCache.get(role);
        if(!context){const payload=await getJSON(`/api/explore/learning?position=${role}`,controller.signal);context=payload.role_context;if(context?.position!==role)throw Error('ROLE_UNAVAILABLE');roleCache.set(role,context);}
        if(disposed||sequence!==roleSequence)return;
        const card=roleGuidance(context);roleHost.replaceChildren();if(card)roleHost.append(card);
      }catch{
        if(disposed||sequence!==roleSequence)return;
        roleHost.textContent='Не удалось загрузить задачи позиции. Выбери другую позицию и вернись, чтобы повторить загрузку.';
      }
    };
    const updatePatchLabel=()=>{
      const label=detail.querySelector('.build-patch');
      if(!label||!selected)return;
      if(isWorkshop(selected)){
        const status=workshopFreshness(selected,workshopStatusFeed());
        const date=checkedDate(selected.source_updated_at);
        label.textContent=status.text+(date?` · Обновление автора ${date}`:'');
        label.classList.toggle('is-stale',status.stale);label.dataset.freshness=status.state;
        return;
      }
      const review=reviews?.guides?.[selected.id],evaluated=Date.parse(reviews?.evaluated_at||'');
      const validReview=reviews?.schema_version==='narma.build-reviews.v1'&&Number.isFinite(evaluated)&&evaluated<=Date.now()+300000&&Date.now()-evaluated<120000
        &&review?.verified_patch===selected.verified_patch&&review?.checked_at===selected.checked_at
        &&['reviewed','review_due','patch_changed','unknown'].includes(review.state)&&typeof review.reason==='string';
      const status=validReview?{state:review.state,stale:review.state!=='reviewed',text:review.reason}:buildFreshness(selected,updatesResult.data);
      const date=checkedDate(selected.checked_at);
      label.textContent=status.text+(date?` · Проверка ${date}`:'');
      label.classList.toggle('is-stale',status.stale);
      label.dataset.freshness=status.state;
    };
    const sync=()=>{const p=new URLSearchParams();if(query)p.set('q',query);if(position)p.set('position',position);if(sourceFilter!=='all')p.set('source',sourceFilter);if(pendingGuideId)p.set('guide',pendingGuideId);else if(selected){p.set('guide',selected.id);const variant=selectedAdaptations.get(selected.id);if(variant&&!isWorkshop(selected))p.set('variant',variant);}if(meta&&!isWorkshop(selected)){const preference=meta.preferences();if(preference.source==='STRATZ'){p.set('rank',preference.rank);if(preference.basis!=='guide')p.set('basis',preference.basis);}}history.replaceState(null,'',`/builds${p.size?'?'+p:''}`);};
    meta=createBuildMeta(controller.signal,sync);
    const renderWorkshopGuide=guide=>{
      // Workshop identifiers must never reach the statistical adapter.
      meta?.dispose();meta=null;
      const allItems=Object.keys(WORKSHOP_PHASES).flatMap(key=>guide[key]);
      const stored=selectedWorkshopItems.get(guide.id);
      let chosen=allItems.find(item=>item.id===stored)||guide.final_items[0]||allItems[0];
      const slots=Array.from({length:6},(_,index)=>guide.final_items[index]||null);
      const phases=Object.entries(WORKSHOP_PHASES).filter(([key])=>guide[key].length);
      const requestedPhase=selectedWorkshopPhases.get(guide.id)||'core_items';
      const phase=phases.some(([key])=>key===requestedPhase)?requestedPhase:phases[0]?.[0];
      const phaseItems=phases.map(([key,label])=>`<section class="workshop-phase" data-workshop-phase="${key}"${key!==phase?' hidden':''}><h4>${esc(label)}</h4><div class="workshop-item-row" role="group" aria-label="${esc(label)}">${guide[key].map(item=>`<button type="button" class="workshop-item" data-workshop-item="${esc(item.id)}" aria-pressed="${chosen?.id===item.id}" aria-controls="build-slot-detail">${picture('items',item.id,item.name)}<span>${esc(item.name)}</span></button>`).join('')}</div></section>`).join('');
      const roleNote=guide.position_exact?`Автор указал позицию ${guide.position} · ${positions[guide.position]}.`:
        guide.role==='unknown'?'Автор не указал позицию. Руководство доступно в общем каталоге; для выбранной позиции нужны дополнительные основания.':
        guide.role==='offlane'?'Автор отметил офлейн. Задачи третьей позиции показаны отдельно от списка покупок.':
        `${guide.role==='support'?'Автор отметил поддержку':'Автор отметил кор-роль'}, без точного номера позиции. Подборка применима к группе ${guide.positions.join(' / ')}; отдельная сборка для каждой из этих позиций не подтверждена.`;
      const practicePosition=position||guide.position||'';
      detail.innerHTML=`<article class="build-guide build-guide--workshop" data-guide-id="${esc(guide.id)}" data-guide-source="workshop">
        <header class="build-guide-header">${picture('heroes',guide.hero_slug,guide.hero_name,'build-portrait')}<div><p class="eyebrow">${esc(guideRole(guide))}</p><h2>${esc(guide.hero_name)}</h2><p>${esc(guide.title)}</p></div></header>
        <div class="workshop-attribution"><span>Автор: <strong>${esc(guide.author)}</strong></span><a class="text-link" href="${esc(sourceURL(guide.source_url))}" target="_blank" rel="noopener noreferrer">Оригинал в Steam Workshop ↗</a></div>
        <p class="build-patch"></p><p class="workshop-role-note">${esc(roleNote)}</p>
        <section class="build-inventory" aria-labelledby="build-inventory-heading">
          <div class="build-inventory-heading"><h3 id="build-inventory-heading">План на 6 слотов</h3><p>${esc(guide.final_note||'План слотов Narma из основных покупок автора. Полные этапы руководства показаны ниже.')}</p></div>
          <div class="build-inventory-grid" role="group" aria-label="Шесть слотов инвентаря">${slots.map((item,index)=>item?`<button type="button" class="build-slot" data-build-slot="${index}" data-workshop-item="${esc(item.id)}" aria-pressed="${item.id===chosen?.id}" aria-controls="build-slot-detail" aria-label="Слот ${index+1}: ${esc(item.name)}">${picture('items',item.id,item.name)}<span>${esc(item.name)}</span></button>`:`<div class="build-slot build-slot--empty" aria-label="Слот ${index+1}: не заполнен источником"><span class="build-empty-slot-number">${index+1}</span><span>По ситуации</span></div>`).join('')}</div>
          <div class="workshop-stage-heading"><h3>Покупки по этапам · список автора</h3><p>Выбери предмет, чтобы увидеть, на каком этапе автор его предлагает. Этапы могут включать альтернативы; это не один инвентарь.</p></div>
          <label class="workshop-phase-filter" for="workshop-phase-select">Этап покупки<select id="workshop-phase-select">${phases.map(([key,label])=>`<option value="${key}"${key===phase?' selected':''}>${esc(label)} · ${guide[key].length}</option>`).join('')}</select></label>
          <div class="workshop-phases">${phaseItems}</div><div id="build-slot-detail" class="build-slot-detail" aria-live="polite" aria-atomic="true"></div>
        </section>
        <section class="build-check"><h3>Перед покупкой проверь задачу</h3><p>Какую угрозу закрывает предмет сейчас: вход в драку, выживание, урон или помощь союзнику? Соотнеси список автора со своей ролью и героями противника. План на шесть слотов составлен Narma из предметов руководства; точные минуты покупки и винрейт комплекта здесь не заявлены.</p><div class="button-row"><a class="button primary" href="/practice?topic=items${practicePosition?`&position=${esc(practicePosition)}`:''}">Потренировать выбор предметов →</a><a class="button subtle" href="/replays">Проверить свой матч ↗</a></div></section>
      </article>`;
      const paintChosen=item=>{
        if(!item)return;
        chosen=item;selectedWorkshopItems.set(guide.id,item.id);
        const stages=Object.entries(WORKSHOP_PHASES).filter(([key])=>guide[key].some(row=>row.id===item.id)).map(([,label])=>label);
        detail.querySelector('#build-slot-detail').innerHTML=`<div class="workshop-selected-item">${picture('items',item.id,item.name)}<div><h4>${esc(item.name)}</h4><p><strong>Этапы автора:</strong> ${esc(stages.join(' · '))}</p><p>Это покупка из руководства ${esc(guide.author)}. Точную минуту и условие замены проверяй по своей игре и пояснениям автора.</p></div></div>`;
        detail.querySelectorAll('[data-workshop-item]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.workshopItem===item.id)));
        imageFallbacks(detail.querySelector('#build-slot-detail'));
      };
      detail.querySelectorAll('[data-workshop-item]').forEach(button=>button.addEventListener('click',()=>paintChosen(allItems.find(item=>item.id===button.dataset.workshopItem))));
      detail.querySelector('#workshop-phase-select').addEventListener('change',event=>{
        const key=event.target.value;if(!Object.hasOwn(WORKSHOP_PHASES,key)||!guide[key].length)return;
        selectedWorkshopPhases.set(guide.id,key);
        detail.querySelectorAll('[data-workshop-phase]').forEach(section=>{section.hidden=section.dataset.workshopPhase!==key;});
        paintChosen(guide[key][0]);
      });
      paintChosen(chosen);imageFallbacks(detail);updatePatchLabel();
    };
    const renderDetail=()=>{
      void renderRole();
      if(!selected){
        meta?.dispose();meta=null;
        if(sourceFilter==='workshop'&&workshopLoading){detail.innerHTML='<p class="page-status" role="status">Загружаем руководства сообщества…</p>';return;}
        if(sourceFilter==='workshop'&&!workshopFeed){detail.innerHTML='<div class="build-empty"><h2>Не удалось загрузить сборки сообщества</h2><p>Повтори загрузку или выбери планы Narma в фильтре источника.</p><button type="button" class="button subtle" data-workshop-retry>Повторить загрузку</button></div>';detail.querySelector('[data-workshop-retry]').addEventListener('click',()=>{workshopLoading=true;renderCoverage();renderDetail();void getJSON('/api/explore/workshop-builds',controller.signal).then(data=>receiveWorkshop({data})).catch(()=>receiveWorkshop({error:true}));});return;}
        const normalized=query.trim().toLocaleLowerCase('ru-RU');
        const alternatives=normalized?guides.filter(g=>`${g.hero_name} ${g.title} ${g.hero_slug}`.toLocaleLowerCase('ru-RU').includes(normalized)):[];
        const roleQuery=position?`?position=${position}`:'';
        detail.innerHTML=`<div class="build-empty"><h2>Для этой пары героя и позиции пока нет руководства</h2><p>${position?`Выбрана позиция ${esc(position)} · ${esc(positions[position])}. `:''}Сборку для другой роли нельзя автоматически переносить на выбранную.</p>${alternatives.length?`<p>Для найденного героя доступны другие учебные планы:</p><div class="button-row">${alternatives.map(g=>`<button type="button" class="button subtle" data-supported-guide="${esc(g.id)}">${esc(g.hero_name)} · ${esc(guideRole(g))}</button>`).join('')}</div>`:'<p>Попробуй имя другого героя или открой обучение по выбранной позиции.</p>'}<a class="text-link" href="/learn${roleQuery}">Обучение${position?` · ${esc(positions[position])}`:''} →</a></div>`;
        detail.querySelectorAll('[data-supported-guide]').forEach(button=>button.addEventListener('click',()=>{selected=guides.find(g=>g.id===button.dataset.supportedGuide);position=selected.position?String(selected.position):'';sourceFilter=isWorkshop(selected)?'workshop':'narma';pendingGuideId=null;content.querySelector('#build-position').value=position;content.querySelector('#build-source').value=sourceFilter;render();}));
        return;
      }
      const g=selected;
      if(isWorkshop(g)){renderWorkshopGuide(g);return;}
      if(!meta)meta=createBuildMeta(controller.signal,sync);
      const alternatives=adaptationOptions(g);
      const inventoryItems=finalItems(g),selectedSlot=selectedSlots.get(g.id)||0;
      const date=checkedDate(g.checked_at),freshness=buildFreshness(g,updatesResult.data);
      const samePatch=!freshness.stale,patchText=freshness.text;
      const depth=g.beginner_focus||g.advanced_focus?`<div class="build-depth">${g.beginner_focus?`<div><h3>Если осваиваешь героя</h3><p>${esc(g.beginner_focus)}</p></div>`:''}${g.advanced_focus?`<div><h3>Если база уже получается</h3><p>${esc(g.advanced_focus)}</p></div>`:''}</div>`:'';
      detail.innerHTML=`<article class="build-guide" data-guide-id="${esc(g.id)}"><header class="build-guide-header">${picture('heroes',g.hero_slug,g.hero_name,'build-portrait')}<div><p class="eyebrow">Позиция ${esc(g.position)} · ${esc(positions[g.position])}</p><h2>${esc(g.hero_name)}</h2><p>${esc(g.title)}</p></div></header><p class="build-summary">${esc(g.summary)}</p><p class="build-patch${!samePatch?' is-stale':''}">${esc(patchText)}${date?` · Проверка ${esc(date)}`:''}</p>${g.applicability_note?`<p class="muted">${esc(g.applicability_note)}</p>`:''}<section id="build-statistics" class="build-statistics" aria-label="Статистика и подбор предметов"></section><div id="build-inventory-host"></div><div class="build-cues"><h3>На что смотреть в матче</h3>${list(g.decision_cues)}</div>${depth}<section class="build-section"><h3>Старт и линия</h3>${items(g.starting_items)}${list(g.lane_plan)}</section><section class="build-section"><h3>Основной план покупки</h3><p class="muted">Проверь условие предмета перед тем, как продолжить сборку.</p>${items(g.core_items)}</section><section class="build-section"><h3>Когда поменять сборку</h3>${items(g.situational_items)}</section><div class="build-window"><p class="eyebrow">После ключевой покупки</p><p>${esc(g.power_window)}</p></div><details class="build-avoid"><summary>Каких ошибок избегать</summary>${list(g.avoid)}</details><section class="build-check"><h3>Проверка в следующей игре</h3><p>${esc(g.next_game_check)}</p><div class="button-row"><a class="button primary" href="/practice?position=${g.position}&topic=items">Потренировать решения →</a><a class="button subtle" href="/replays">Разобрать свой матч ↗</a></div></section><details class="build-sources"><summary>Основания руководства и источники</summary><p>Текст Narma объясняет выбор; источники ниже помогают проверить механику и изменения.</p><div>${sources(g.source_refs)}</div></details></article>`;
      const statisticsHost=detail.querySelector('#build-statistics');
      if(alternatives.length){
        const panel=document.createElement('section');panel.className='build-adaptation';
        panel.innerHTML=`<label for="build-situation">Подстрой сборку под матч</label><select id="build-situation"><option value="">Основной план</option>${alternatives.map(row=>`<option value="${esc(row.id)}"${selectedAdaptations.get(g.id)===row.id?' selected':''}>${esc(row.label)}</option>`).join('')}</select><p class="build-adaptation-reason" aria-live="polite"></p>`;
        statisticsHost.before(panel);
      }
      const notes=reviews?.guides?.[g.id]?.patch_notes||g.patch_notes;
      if(Array.isArray(notes)&&notes.length){
        const panel=document.createElement('details');panel.className='build-patch-notes';
        panel.innerHTML=`<summary>Что учтено в патче ${esc(g.verified_patch)}</summary>${list(notes.map(row=>typeof row==='string'?row:row.text))}`;
        detail.querySelector('.build-patch').after(panel);
      }
      let displayedRows=[],inventorySignature=null,lastMeta=[null,null,null];
      const paintInventory=(suggested,note,evidence)=>{
        lastMeta=[suggested,note,evidence];
        const adapted=applyAdaptation(g,selectedAdaptations.get(g.id));
        const rows=suggested||(adapted.option?adapted.rows:inventoryItems).map(item=>({...item,evidence:evidence?.items?.[item.id]}));
        const selector=detail.querySelector('#build-situation');
        if(selector){
          selector.disabled=Boolean(suggested);
          const oldItem=inventoryItems.find(item=>item.id===adapted.option?.replace_item_id);
          detail.querySelector('.build-adaptation-reason').textContent=suggested?'Выбран подбор по статистике. Для сценария матча переключись на учебный план.':adapted.option?`${adapted.option.when} ${oldItem?.name} → ${adapted.option.item.name}.`:'Выбери ситуацию, чтобы увидеть одну замену в инвентаре и её причину. Это авторские варианты Narma.';
        }
        if(!suggested&&adapted.option)note=`${adapted.option.label}. ${adapted.option.when} Остальные пять слотов сохранены; это вариант под условия матча, а не обязательный порядок покупок.`;
        const host=detail.querySelector('#build-inventory-host');
        const signature=JSON.stringify([rows,note||g.final_note]);
        if(signature===inventorySignature)return;
        inventorySignature=signature;
        const sameSlots=displayedRows.length===rows.length&&rows.every((item,index)=>item.id===displayedRows[index]?.id);
        displayedRows=rows;
        if(sameSlots&&host.querySelector('#build-slot-detail')){
          host.querySelector('.build-inventory-heading p').textContent=note||g.final_note;
          host.querySelector('#build-slot-detail').innerHTML=slotExplanation(rows[selectedSlots.get(g.id)||0]);
          return;
        }
        host.innerHTML=inventory(rows,selectedSlots.get(g.id)||0,note||g.final_note);
        host.querySelectorAll('[data-build-slot]').forEach(button=>button.addEventListener('click',()=>{
          const index=Number(button.dataset.buildSlot);
          if(!displayedRows[index])return;
          selectedSlots.set(g.id,index);
          host.querySelectorAll('[data-build-slot]').forEach(slot=>slot.setAttribute('aria-pressed',String(slot===button)));
          host.querySelector('#build-slot-detail').innerHTML=slotExplanation(displayedRows[index]);
        }));
        imageFallbacks(host);
      };
      detail.querySelector('#build-situation')?.addEventListener('change',event=>{
        selectedAdaptations.set(g.id,event.target.value);
        const adaptation=alternatives.find(row=>row.id===event.target.value);
        if(adaptation)selectedSlots.set(g.id,inventoryItems.findIndex(item=>item.id===adaptation.replace_item_id));
        inventorySignature=null;
        paintInventory(...lastMeta);sync();
      });
      meta.mount(detail.querySelector('#build-statistics'),g,paintInventory);
      imageFallbacks(detail);
      updatePatchLabel();
    };
    const render=(preserveAuthoredDetail=false)=>{
      const normalized=query.trim().toLocaleLowerCase('ru-RU');
      const filtered=guides.filter(g=>matchesPosition(g,position)&&(sourceFilter==='all'||(sourceFilter==='workshop')===isWorkshop(g))&&`${g.hero_name} ${g.title} ${g.hero_slug} ${g.author||''}`.toLocaleLowerCase('ru-RU').includes(normalized));
      const rows=[...filtered.filter(guide=>!isWorkshop(guide)),...sortWorkshopGuides(filtered.filter(isWorkshop),workshopStatusFeed(),position)];
      const previousId=selected?.id;
      selected=rows.find(guide=>guide.id===selected?.id)||rows[0]||null;
      content.querySelector('#build-count').textContent=`Руководств: ${rows.length}`;
      const picker=content.querySelector('#build-list');
      picker.innerHTML=rows.map(g=>`<button type="button" class="build-choice" data-guide="${esc(g.id)}" aria-pressed="${g.id===selected?.id}">${picture('heroes',g.hero_slug,g.hero_name)}<span><strong>${esc(g.hero_name)}</strong><small>${esc(guideRole(g))}</small><small class="build-choice-source">${esc(isWorkshop(g)?g.author:'Narma · разбор решений')}</small></span></button>`).join('');
      picker.querySelectorAll('[data-guide]').forEach(button=>button.addEventListener('click',()=>{selected=rows.find(g=>g.id===button.dataset.guide);pendingGuideId=null;picker.querySelectorAll('[data-guide]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));renderDetail();sync();}));
      imageFallbacks(picker);
      if(!preserveAuthoredDetail||!selected||isWorkshop(selected)||selected?.id!==previousId)renderDetail();
      renderCoverage();sync();
    };
    const receiveWorkshop=result=>{
      if(disposed)return;
      workshopLoading=false;
      try{
        if(!result?.data)throw Error('SOURCE_UNAVAILABLE');
        const feed=validateWorkshopFeed(result.data);
        const changed=JSON.stringify(workshopFeed?.guides)!==JSON.stringify(feed.guides);
        workshopFeed=feed;workshopReceivedAt=Date.now();workshopFailed=false;guides=[...authoredGuides,...feed.guides];
        if(pendingGuideId){selected=guides.find(guide=>guide.id===pendingGuideId)||selected;pendingGuideId=null;}
        if(changed)render(true);else{renderCoverage();updatePatchLabel();}
      }catch{workshopFailed=true;renderCoverage();if(!workshopFeed&&sourceFilter==='workshop')renderDetail();}
    };
    content.querySelector('#build-search').addEventListener('input',event=>{query=event.target.value;pendingGuideId=null;render();});
    content.querySelector('#build-position').addEventListener('change',event=>{position=event.target.value;pendingGuideId=null;render();});
    content.querySelector('#build-source').addEventListener('change',event=>{sourceFilter=event.target.value;pendingGuideId=null;render();});
    render();
    void initialWorkshop.then(receiveWorkshop);
    refreshPatch=async()=>{
      if(disposed||refreshing||document.hidden)return;
      clearTimeout(timer);refreshing=true;
      try {const [feed,review,workshop]=await Promise.all([getJSON('/api/explore/updates',controller.signal).catch(()=>null),getJSON('/api/explore/build-reviews',controller.signal).catch(()=>null),getJSON('/api/explore/workshop-builds',controller.signal).then(data=>({data})).catch(()=>({error:true}))]);updatesResult=feed?{data:feed}:{error:true};reviews=review;receiveWorkshop(workshop);}
      catch {updatesResult={error:true};reviews=null;}
      finally {
        refreshing=false;
        if(!disposed){updatePatchLabel();timer=setTimeout(()=>void refreshPatch(),updatesResult.data?.refreshing?5000:60000);}
      }
    };
    document.addEventListener('visibilitychange',onVisibility);
    window.addEventListener('pagehide',onPageHide);
    window.addEventListener('pageshow',onPageShow);
    timer=setTimeout(()=>void refreshPatch(),updatesResult.data?.refreshing?5000:60000);
  } catch {
    if(disposed)return cleanup;
    content.innerHTML='<div class="error-box"><p>Не удалось открыть руководства. Попробуй ещё раз.</p><button type="button" class="button">Повторить загрузку</button></div>';
    content.querySelector('button').addEventListener('click',()=>mountBuilds(root));
  }
  return cleanup;
}
