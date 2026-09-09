// Authored alternatives describe a decision, never a measured win-rate ranking.
const incompatible=[['dragon_lance','hurricane_pike'],['force_staff','hurricane_pike'],['maelstrom','mjollnir'],['maelstrom','gungir'],['witch_blade','devastator'],['cyclone','wind_waker'],['blink','overwhelming_blink'],['urn_of_shadows','spirit_vessel']];
export function adaptationOptions(guide){
  const base=guide?.final_items;
  if(!Array.isArray(base)||base.length!==6)return [];
  const seen=new Set();
  return (Array.isArray(guide.adaptations)?guide.adaptations:[]).filter(option=>{
    if(!option||!/^[a-z0-9-]{1,80}$/.test(option.id)||seen.has(option.id)||!option.label||!option.when)return false;
    const item=option.item;
    if(!item||!/^[a-z0-9_]{1,80}$/.test(item.id)||!item.name||!item.why)return false;
    if(base.filter(row=>row.id===option.replace_item_id).length!==1)return false;
    const ids=base.map(row=>row.id===option.replace_item_id?item.id:row.id);
    if(new Set(ids).size!==6||incompatible.some(pair=>pair.every(id=>ids.includes(id))))return false;
    seen.add(option.id);return true;
  });
}
export function applyAdaptation(guide,id){
  const option=adaptationOptions(guide).find(row=>row.id===id);
  if(!option)return {rows:guide.final_items,option:null};
  return {rows:guide.final_items.map(item=>item.id===option.replace_item_id?option.item:item),option};
}
