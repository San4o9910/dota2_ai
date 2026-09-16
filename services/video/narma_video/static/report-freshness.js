let updates;
export async function showReportFreshness(host,report,{current}){
  host.hidden=!report;if(!report)return;
  const build=report.coverage?.engine_build;
  host.textContent=build?`Сборка матча: ${build}. Соответствие текущему патчу пока не подтверждено.`:'Версия матча не определена. Актуальность предметов и механик для текущего патча не подтверждена.';
  const initial=host.textContent;
  try{
    updates??=fetch('/api/explore/updates',{credentials:'same-origin'}).then(async r=>{if(!r.ok)throw Error();return r.json();}).catch(error=>{updates=null;throw error;});
    const data=await updates;if(!current())return;
    const patch=data.latest_patch;if(!patch?.version)return;
    const played=report.played_at_source==='replay'?Date.parse(report.played_at):NaN,published=Date.parse(patch.published_at);
    host.textContent=initial+` Последний известный патч: ${patch.version}.`+(Number.isFinite(played)&&Number.isFinite(published)&&played<published?' Матч сыгран до этого обновления: проверь связанные с изменениями советы.':'')+(data.stale?' Проверка обновлений временно недоступна; показаны сохранённые сведения.':'')+' Перед применением совета о предмете или способности проверь изменения игры.';
    const a=document.createElement('a');a.href='/updates';a.textContent=' Посмотреть обновления';host.append(a);
  }catch{if(current())host.textContent=initial+' Сведения о новых патчах сейчас недоступны.';}
}
