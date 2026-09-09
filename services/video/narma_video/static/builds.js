import {createBuildMeta,itemEvidence} from './build-meta.js';
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const positions = {1:'Керри',2:'Мидер',3:'Офлейнер',4:'Поддержка',5:'Полная поддержка'};
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
    const [catalog,initialUpdates]=await Promise.all([getJSON('/assets/build-guides.json',controller.signal),getJSON('/api/explore/updates',controller.signal).then(data=>({data})).catch(()=>({error:true}))]);
    if(disposed)return cleanup;
    let updatesResult=initialUpdates;
    if(catalog.schema_version!=='narma.build-guides.v1'||!Array.isArray(catalog.guides))throw Error('CATALOG_INVALID');
    const guides=catalog.guides.filter(g=>/^[a-z0-9-]{1,90}$/.test(g.id)&&asset('heroes',g.hero_slug)&&positions[g.position]);
    if(!guides.length)throw Error('CATALOG_EMPTY');
    const params=new URLSearchParams(location.search);
    let query=(params.get('q')||params.get('hero')||'').slice(0,80),position=positions[params.get('position')]?params.get('position'):'';
    let selected=guides.find(g=>g.id===params.get('guide'))||guides.find(g=>g.hero_slug===params.get('hero')&&(!position||String(g.position)===position))||null;
    const selectedSlots=new Map();
    content.innerHTML=`<div class="build-toolbar"><div class="field"><label for="build-search">Поиск героя или руководства</label><input type="search" id="build-search" maxlength="80" placeholder="Например, Viper" value="${esc(query)}"></div><div class="field"><label for="build-position">Позиция</label><select id="build-position"><option value="">Все позиции</option>${Object.entries(positions).map(([id,label])=>`<option value="${id}"${position===id?' selected':''}>${id} · ${label}</option>`).join('')}</select></div><p class="build-editorial-note">Руководства Narma: условия выбора и действия в игре. Статистический рейтинг героев здесь не рассчитывается.</p></div><div class="build-layout"><aside class="build-picker" aria-label="Выбор руководства"><p class="build-count" id="build-count" role="status" aria-live="polite"></p><div id="build-list"></div></aside><section id="build-detail" aria-label="Выбранное руководство"></section></div><aside class="build-meta"><div><p class="eyebrow">Проверяй изменения перед игрой</p><h2>Мета зависит от патча и уровня матчей</h2><p>Сначала проверь, что изменилось у героя, затем сравни его задачи со своим пулом. Популярная сборка не отменяет условия конкретного матча.</p></div><div class="build-meta-links"><a class="button subtle" href="/updates?category=patch">Изменения и новости Valve →</a><a class="text-link" href="https://www.dotabuff.com/heroes/meta" target="_blank" rel="noopener noreferrer">Статистика по рангам · Dotabuff ↗</a><a class="text-link" href="https://dota2protracker.com/meta" target="_blank" rel="noopener noreferrer">Матчи 7000+ MMR · Dota2ProTracker ↗</a></div></aside>`;
    const detail=content.querySelector('#build-detail');
    const updatePatchLabel=()=>{
      const label=detail.querySelector('.build-patch');
      if(!label||!selected)return;
      const status=buildFreshness(selected,updatesResult.data);
      const date=checkedDate(selected.checked_at);
      label.textContent=status.text+(date?` · Проверка ${date}`:'');
      label.classList.toggle('is-stale',status.stale);
      label.dataset.freshness=status.state;
    };
    const sync=()=>{const p=new URLSearchParams();if(query)p.set('q',query);if(position)p.set('position',position);if(selected)p.set('guide',selected.id);if(meta){const preference=meta.preferences();p.set('rank',preference.rank);if(preference.basis!=='guide')p.set('basis',preference.basis);}history.replaceState(null,'',`/builds${p.size?'?'+p:''}`);};
    meta=createBuildMeta(controller.signal,sync);
    const renderDetail=()=>{
      if(!selected){detail.innerHTML='<p class="empty-message">По этим условиям руководств пока нет. Попробуй другую позицию или имя.</p>';return;}
      const g=selected;
      const inventoryItems=finalItems(g),selectedSlot=selectedSlots.get(g.id)||0;
      const date=checkedDate(g.checked_at),freshness=buildFreshness(g,updatesResult.data);
      const samePatch=!freshness.stale,patchText=freshness.text;
      const depth=g.beginner_focus||g.advanced_focus?`<div class="build-depth">${g.beginner_focus?`<div><h3>Если осваиваешь героя</h3><p>${esc(g.beginner_focus)}</p></div>`:''}${g.advanced_focus?`<div><h3>Если база уже получается</h3><p>${esc(g.advanced_focus)}</p></div>`:''}</div>`:'';
      detail.innerHTML=`<article class="build-guide" data-guide-id="${esc(g.id)}"><header class="build-guide-header">${picture('heroes',g.hero_slug,g.hero_name,'build-portrait')}<div><p class="eyebrow">Позиция ${esc(g.position)} · ${esc(positions[g.position])}</p><h2>${esc(g.hero_name)}</h2><p>${esc(g.title)}</p></div></header><p class="build-summary">${esc(g.summary)}</p><p class="build-patch${!samePatch?' is-stale':''}">${esc(patchText)}${date?` · Проверка ${esc(date)}`:''}</p>${g.applicability_note?`<p class="muted">${esc(g.applicability_note)}</p>`:''}<section id="build-statistics" class="build-statistics" aria-label="Статистика и подбор предметов"></section><div id="build-inventory-host"></div><div class="build-cues"><h3>На что смотреть в матче</h3>${list(g.decision_cues)}</div>${depth}<section class="build-section"><h3>Старт и линия</h3>${items(g.starting_items)}${list(g.lane_plan)}</section><section class="build-section"><h3>Основной план покупки</h3><p class="muted">Проверь условие предмета перед тем, как продолжить сборку.</p>${items(g.core_items)}</section><section class="build-section"><h3>Когда поменять сборку</h3>${items(g.situational_items)}</section><div class="build-window"><p class="eyebrow">После ключевой покупки</p><p>${esc(g.power_window)}</p></div><details class="build-avoid"><summary>Каких ошибок избегать</summary>${list(g.avoid)}</details><section class="build-check"><h3>Проверка в следующей игре</h3><p>${esc(g.next_game_check)}</p><div class="button-row"><a class="button primary" href="/practice?position=${g.position}&topic=items">Потренировать решения →</a><a class="button subtle" href="/replays">Разобрать свой матч ↗</a></div></section><details class="build-sources"><summary>Основания руководства и источники</summary><p>Текст Narma объясняет выбор; источники ниже помогают проверить механику и изменения.</p><div>${sources(g.source_refs)}</div></details></article>`;
      let displayedRows=[],inventorySignature=null;
      const paintInventory=(suggested,note,evidence)=>{
        const rows=suggested||inventoryItems.map(item=>({...item,evidence:evidence?.items?.[item.id]}));
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
      meta.mount(detail.querySelector('#build-statistics'),g,paintInventory);
      imageFallbacks(detail);
      updatePatchLabel();
    };
    const render=()=>{
      const normalized=query.trim().toLocaleLowerCase('ru-RU');
      const rows=guides.filter(g=>(!position||String(g.position)===position)&&`${g.hero_name} ${g.title} ${g.hero_slug}`.toLocaleLowerCase('ru-RU').includes(normalized));
      if(!selected||!rows.some(g=>g.id===selected.id))selected=rows[0]||null;
      content.querySelector('#build-count').textContent=`Руководств: ${rows.length}`;
      const picker=content.querySelector('#build-list');
      picker.innerHTML=rows.map(g=>`<button type="button" class="build-choice" data-guide="${esc(g.id)}" aria-pressed="${g.id===selected?.id}">${picture('heroes',g.hero_slug,g.hero_name)}<span><strong>${esc(g.hero_name)}</strong><small>${esc(g.position)} · ${esc(positions[g.position])}</small></span></button>`).join('');
      picker.querySelectorAll('[data-guide]').forEach(button=>button.addEventListener('click',()=>{selected=rows.find(g=>g.id===button.dataset.guide);picker.querySelectorAll('[data-guide]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));renderDetail();sync();}));
      imageFallbacks(picker);renderDetail();sync();
    };
    content.querySelector('#build-search').addEventListener('input',event=>{query=event.target.value;render();});
    content.querySelector('#build-position').addEventListener('change',event=>{position=event.target.value;render();});
    render();
    refreshPatch=async()=>{
      if(disposed||refreshing||document.hidden)return;
      clearTimeout(timer);refreshing=true;
      try {updatesResult={data:await getJSON('/api/explore/updates',controller.signal)};}
      catch {updatesResult={error:true};}
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
