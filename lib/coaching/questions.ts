import type {EvidenceBundleV1,EvidenceItemV1} from "@/lib/analysis/contracts";
const LABELS:Record<string,string>={kills:"Убийства",deaths:"Смерти",assists:"Помощи",gold_delta:"Изменение золота",xp_delta:"Полученный опыт",damage:"Урон",radiant_gold_advantage:"Перевес Radiant по золоту",radiant_xp_advantage:"Перевес Radiant по опыту",gold_per_minute:"GPM",xp_per_minute:"XPM",net_worth:"Ценность предметов",last_hits:"Добивания",denies:"Денаи"};
export function answerFromMatch(bundle:EvidenceBundleV1,question:string,time:number|null,playerSlot:number) {
  const text=question.toLocaleLowerCase("ru-RU");
  if(/почему|из-за|причин|bkb|бкб|нажал|обзор|вижен|камер|маршрут|позици|способност|кулдаун/.test(text))return {text:"В этой сводке нет точного обзора команды, перемещений, камеры и состояния способностей в выбранный момент. По ней нельзя установить причину решения или смерти. Откройте реплей со своей камеры перед эпизодом: какую цель вы хотели получить и что видели?",evidenceIds:[] as string[],time:null};
  let candidates:EvidenceItemV1[]=bundle.evidence.filter(e=>e.kind==="fight"||e.kind==="economy"||e.kind==="objective");
  if(/золот|gold|опыт|xp|эконом/.test(text)) candidates=bundle.evidence.filter(e=>e.kind==="economy");
  else if(/геро|мой|мои|gpm|xpm|добив|крип/.test(text))candidates=bundle.evidence.filter(e=>e.kind==="player"&&e.playerSlot===playerSlot);
  else if(/драк|бой|бою|сраж/.test(text))candidates=bundle.evidence.filter(e=>e.kind==="fight");
  const at=(e:EvidenceItemV1)=>e.time?.type==="point" ? e.time.seconds : e.time?.type==="window" ? e.time.startSeconds : 0;
  const selected=candidates.sort((a,b)=>time===null ? at(a)-at(b) : Math.abs(at(a)-time)-Math.abs(at(b)-time))[0];
  if(!selected)return {text:"В сохранённом разборе нет подходящего замера. Выберите эпизод на хронологии или загрузите полный реплей.",evidenceIds:[] as string[],time:null};
  const facts=selected.values.filter(v=>v.unit!=="hero_id"&&v.unit!=="item_id"&&v.unit!=="flag").slice(0,10).map(v=>`${LABELS[v.metric]??v.metric.replaceAll("_"," ")}: ${v.value.toLocaleString("ru-RU")}`);
  return {text:`Показатели выбранного события:\n${facts.join("\n")}\nЭто наблюдаемые значения, а не объяснение причины ошибки.`,evidenceIds:[selected.id],time:selected.time};
}
