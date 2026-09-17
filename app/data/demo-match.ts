export type Side = "R" | "D";
export type StageKey = "draft" | "laning" | "mid" | "late";
export type AxisKey = "movement" | "vision" | "resources" | "macro" | "micro";

export type Hero = {
  id: number;
  slug: string;
  name: string;
  player: string;
  side: Side;
  slot: number;
  position: number;
  lane: string;
  kills: number;
  deaths: number;
  assists: number;
  gpm: number;
  xpm: number;
  level: number;
  networth: number;
  wards: number;
  sentries: number;
};

// Authored teaching scenario. No real match, player identity or match-derived telemetry.
export const MATCH = {
  id: "training-example", date: "Учебный сценарий", duration: 2400,
  durationLabel: "40:00", patch: "7.41", score: { radiant: 24, dire: 30 },
  winner: "Dire", source: "Вымышленные учебные данные",
} as const;

const lineup: Array<[number,string,string,Side,number,number]> = [
  [8,"juggernaut","Juggernaut","R",0,1], [25,"lina","Lina","R",1,2],
  [2,"axe","Axe","R",2,3], [26,"lion","Lion","R",3,4],
  [5,"crystal_maiden","Crystal Maiden","R",4,5],
  [18,"sven","Sven","D",128,1], [22,"zuus","Zeus","D",129,2],
  [29,"tidehunter","Tidehunter","D",130,3], [20,"vengefulspirit","Vengeful Spirit","D",131,4],
  [30,"witch_doctor","Witch Doctor","D",132,5],
];
export const HEROES: Hero[] = lineup.map(([id,slug,name,side,slot,position],i) => ({
  id,slug,name,side,slot,position,player:`Учебный игрок ${i+1}`,
  lane:position===2?"Центр":position===1||position===5?"Лёгкая":"Сложная",
  kills:side==="R"?[8,6,4,3,3][i]:[10,8,5,4,3][i-5],
  deaths:side==="R"?[4,5,6,7,8][i]:[3,4,5,6,6][i-5],
  assists:8+position*2,gpm:650-position*55,xpm:780-position*50,
  level:26-position,networth:28000-position*3000,
  wards:position>=4?4:0,sentries:position>=4?6:0,
}));
export const AXES: Array<{ key: AxisKey; label: string; short: string }> = [
  {key:"movement",label:"Передвижения",short:"Маршруты и тайминги"},
  {key:"vision",label:"Вардинг и вижен",short:"Обзор и неизвестность"},
  {key:"resources",label:"Ресурсы",short:"Золото и опыт"},
  {key:"macro",label:"Макро",short:"Линии и карта"},
  {key:"micro",label:"Микро",short:"Решения в драке"},
];
export const STAGES: Array<{key:StageKey;label:string;interval:string;from:number;to:number;focusTime:number;verdict:string;explanation:string;evidence:string[]}> = [
  {key:"draft",label:"Драфт",interval:"до 0:00",from:-90,to:0,focusTime:0,
    verdict:"Начни с задачи своего героя.",explanation:"В учебном примере выбран состав из десяти героев. Объясни задачу линии и условие для первого перемещения. Это упражнение, а не вывод о конкретном игроке.",evidence:["Состав придуман для демонстрации","Командные намерения не заданы"]},
  {key:"laning",label:"Лайнинг",interval:"0:00–12:00",from:0,to:720,focusTime:420,
    verdict:"Сравни пользу выхода с ценой потерянной волны.",explanation:"Представь, что союзники зовут в драку, а к твоей башне идёт волна. Назови доступные варианты и информацию, которой не хватает. Ответ зависит от состояния конкретного матча.",evidence:["Учебная развилка: волна или помощь","Ни один вариант не объявлен универсальным"]},
  {key:"mid",label:"Мид-гейм",interval:"12:00–30:00",from:720,to:1800,focusTime:1200,
    verdict:"Перед выходом за реку проверь обзор и путь отхода.",explanation:"В вымышленном эпизоде несколько соперников не видны. Остановись перед выходом, оцени поддержку союзников и выбери безопасный следующий шаг. Риск сам по себе не доказывает ошибку.",evidence:["Сценарий составлен вручную","Положение невидимых героев неизвестно"]},
  {key:"late",label:"Лейт-гейм",interval:"30:00–40:00",from:1800,to:2400,focusTime:2100,
    verdict:"Перед боем проверь готовность команды.",explanation:"Учебная команда начинает бой при разном количестве доступных героев. Сначала перечисли известные условия, затем выбери: принять бой, отступить или обменять объект. Итоговый счёт не заменяет оценку решения.",evidence:["Показана условная последовательность событий","Выводы не описывают реального пользователя"]},
];
const axisCopy: Record<AxisKey,string> = {
  movement:"Назови маршрут, альтернативу и сигнал для смены решения. Точные перемещения в этом учебном наборе отсутствуют.",
  vision:"Точки вардов придуманы для демонстрации. Их фактический обзор и время снятия не заданы.",
  resources:"Числа и графики вымышлены. Используй их для знакомства с форматом сравнения, а не как оценку своей игры.",
  macro:"Свяжи действие с целью команды. При недостатке информации сначала сформулируй уточняющий вопрос.",
  micro:"Нажатия и исполнение не реконструированы. Для личного вывода потребуется собственный реплей.",
};
export const AXIS_COPY: Record<StageKey,Record<AxisKey,string>> = {
  draft:{...axisCopy},laning:{...axisCopy},mid:{...axisCopy},late:{...axisCopy},
};
// Deterministic authored curves, not transformed measurements from a real match.
export const GOLD_ADV = Array.from({length:41},(_,minute)=>minute<15?minute*80:1200-(minute-15)*360);
export const XP_ADV = Array.from({length:41},(_,minute)=>minute<15?minute*100:1500-(minute-15)*420);
export type Fight = {
  start:number;end:number;
  radiant:{kills:number;deaths:number;gold:number;xp:number;damage:number};
  dire:{kills:number;deaths:number;gold:number;xp:number;damage:number};
  deaths:Array<{heroId:number;side:Side;x:number;y:number}>;
};
export const FIGHTS: Fight[] = [480,1200,2100].map((start,i)=>({
  start,end:start+30,
  radiant:{kills:1,deaths:2,gold:600+i*100,xp:800+i*200,damage:2200+i*1000},
  dire:{kills:2,deaths:1,gold:900+i*150,xp:1200+i*250,damage:3000+i*1100},
  deaths:[{heroId:26,side:"R",x:110+i*8,y:120+i*6},{heroId:2,side:"R",x:114+i*8,y:122+i*6},{heroId:20,side:"D",x:120+i*8,y:128+i*6}],
}));
export const EVENTS = [
  {t:480,type:"fight",title:"Учебная драка у линии",detail:"Вымышленная ситуация для выбора следующего действия"},
  {t:900,type:"tower",title:"T1 Dire bot",detail:"Условное событие: башня разрушена"},
  {t:1200,type:"fight",title:"Учебный выход за реку",detail:"Проверь доступную информацию до решения"},
  {t:1800,type:"tower",title:"T1 Radiant mid",detail:"Условное событие: башня разрушена"},
  {t:2100,type:"fight",title:"Учебная проверка готовности к бою",detail:"Сравни участие и отступление"},
  {t:2400,type:"ancient",title:"Конец учебного сценария",detail:"Победа Dire — условный результат"},
];
export type WardEvent = {t:number;x:number;y:number;type:"obs"|"sen";side:Side;heroId:number};
export const WARDS: WardEvent[] = Array.from({length:40},(_,i)=>({
  t:60+i*55,x:90+(i%5)*18,y:85+(i%7)*12,
  type:i%5<2?"obs":"sen",side:i%2===0?"R":"D",heroId:[26,20,5,30][i%4],
}));

export type MapObject = { x: number; y: number; kind: string; label: string; layer: "structures" | "objectives" | "camps" };

export const MAP_OBJECTS: MapObject[] = [
  { x: 2831, y: -2740, kind: "roshan", label: "Логово Roshan", layer: "objectives" },
  { x: -3194, y: 2395, kind: "roshan", label: "Логово Roshan", layer: "objectives" },
  { x: -7680, y: 6336, kind: "tormentor", label: "Tormentor", layer: "objectives" },
  { x: 7744, y: -6208, kind: "tormentor", label: "Tormentor", layer: "objectives" },
  { x: -8088, y: 768, kind: "wisdom", label: "Руна мудрости", layer: "objectives" },
  { x: 8167, y: -1142, kind: "wisdom", label: "Руна мудрости", layer: "objectives" },
  { x: -7548, y: 4209, kind: "lotus", label: "Lotus Pool", layer: "objectives" },
  { x: 7504, y: -4405, kind: "lotus", label: "Lotus Pool", layer: "objectives" },
  { x: -6458, y: 7599, kind: "gate", label: "Twin Gate", layer: "objectives" },
  { x: 6426, y: -7314, kind: "gate", label: "Twin Gate", layer: "objectives" },
  { x: -996, y: 4431, kind: "bounty", label: "Bounty Rune", layer: "objectives" },
  { x: 595, y: -4660, kind: "bounty", label: "Bounty Rune", layer: "objectives" },
  { x: -1640, y: 1112, kind: "power", label: "Power Rune", layer: "objectives" },
  { x: 1180, y: -1216, kind: "power", label: "Power Rune", layer: "objectives" },
  ...[
    [-6464,6656],[-671,7130],[-1527,3926],[-7808,1056],[-3483,34],[2718,-657],[7918,-1524],[1032,-4260],[6528,-6592],[768,-7648],
  ].map(([x,y]) => ({ x, y, kind: "watcher", label: "Watcher", layer: "objectives" as const })),
  ...[[-4096,-448],[3392,-448]].map(([x,y]) => ({ x, y, kind: "outpost", label: "Outpost", layer: "objectives" as const })),
  ...[[-7542,-6171],[6697,6809],[-5080,1948],[4886,-1208]].map(([x,y]) => ({ x, y, kind: "shop", label: "Магазин / таверна", layer: "objectives" as const })),
  ...[
    [-3952,-6112],[-4640,-4144],[-6592,-3408],[-360,-6256],[4860,-6379],[-3190,-2926],[-6501,-872],[-6336,1856],[-5712,-4864],
    [4944,4776],[-128,6016],[-5275,6036],[2496,2112],[524,652],[6400,384],[6336,3032],[3552,5776],[4272,3759],[5280,4432],[-5392,-5192],[-1544,-1408],[6269,-2240],
  ].map(([x,y]) => ({ x, y, kind: "tower", label: "Башня", layer: "structures" as const })),
  ...[[-5920,-5352],[5528,5000]].map(([x,y]) => ({ x, y, kind: "ancient", label: "Ancient", layer: "structures" as const })),
  ...[
    [-852,4940],[3392,-1408],[3978,-5027],[7928,-120],[-4824,3915],[4649,-3699],[-1454,-3356],[186,-5197],[-5015,-96],[4352,48],[-1983,-4815],[1224,4176],[-4013,992],[-720,-7696],[336,7696],[1064,2580],[8430,1263],[-8313,-553],[-2880,7376],[-2596,3850],[2768,-8336],[1922,-3975],[-3911,4829],[-8023,-1838],[2016,7896],[-2415,-8402],[4416,-8432],[-4208,8336],
  ].map(([x,y], i) => ({ x, y, kind: "camp", label: `Лагерь крипов ${i + 1}`, layer: "camps" as const })),
];

export const formatTime = (seconds: number) => {
  const safe = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
};

export const heroImage = (slug: string) =>
  `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/${slug}.png`;
