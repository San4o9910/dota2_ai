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

export const MATCH = {
  id: 8963624400,
  date: "24 августа 2026",
  duration: 2829,
  durationLabel: "47:09",
  patch: "7.41",
  score: { radiant: 43, dire: 55 },
  winner: "Dire",
  source: "OpenDota parser v22",
} as const;

export const HEROES: Hero[] = [
  { id: 105, slug: "techies", name: "Techies", player: "geli mogeli", side: "R", slot: 0, position: 5, lane: "Нижняя", kills: 7, deaths: 12, assists: 19, gpm: 393, xpm: 658, level: 23, networth: 13801, wards: 18, sentries: 29 },
  { id: 8, slug: "juggernaut", name: "Juggernaut", player: "Frezirofshik", side: "R", slot: 1, position: 1, lane: "Нижняя", kills: 6, deaths: 11, assists: 17, gpm: 630, xpm: 893, level: 26, networth: 26707, wards: 0, sentries: 0 },
  { id: 84, slug: "ogre_magi", name: "Ogre Magi", player: "лужа спермы XXL", side: "R", slot: 2, position: 4, lane: "Верхняя", kills: 8, deaths: 10, assists: 20, gpm: 509, xpm: 807, level: 25, networth: 18423, wards: 1, sentries: 7 },
  { id: 21, slug: "windrunner", name: "Windranger", player: "RaVen-", side: "R", slot: 3, position: 2, lane: "Центр", kills: 9, deaths: 8, assists: 11, gpm: 542, xpm: 793, level: 25, networth: 21433, wards: 1, sentries: 1 },
  { id: 81, slug: "chaos_knight", name: "Chaos Knight", player: "Papa_Prima", side: "R", slot: 4, position: 3, lane: "Верхняя", kills: 9, deaths: 14, assists: 9, gpm: 450, xpm: 685, level: 24, networth: 18989, wards: 0, sentries: 0 },
  { id: 62, slug: "bounty_hunter", name: "Bounty Hunter", player: "Validol", side: "D", slot: 128, position: 4, lane: "Нижняя", kills: 1, deaths: 13, assists: 24, gpm: 356, xpm: 502, level: 21, networth: 14708, wards: 14, sentries: 25 },
  { id: 11, slug: "nevermore", name: "Shadow Fiend", player: "Deko", side: "D", slot: 129, position: 2, lane: "Центр", kills: 28, deaths: 4, assists: 9, gpm: 956, xpm: 1512, level: 30, networth: 42986, wards: 2, sentries: 2 },
  { id: 96, slug: "centaur", name: "Centaur Warrunner", player: "rar141", side: "D", slot: 130, position: 3, lane: "Нижняя", kills: 9, deaths: 13, assists: 31, gpm: 528, xpm: 1039, level: 27, networth: 24147, wards: 0, sentries: 0 },
  { id: 33, slug: "enigma", name: "Enigma", player: "вебкаменщик", side: "D", slot: 131, position: 5, lane: "Верхняя", kills: 10, deaths: 6, assists: 11, gpm: 684, xpm: 927, level: 27, networth: 28958, wards: 5, sentries: 9 },
  { id: 48, slug: "luna", name: "Luna", player: "It's is my life", side: "D", slot: 132, position: 1, lane: "Верхняя", kills: 7, deaths: 7, assists: 11, gpm: 727, xpm: 1034, level: 27, networth: 31278, wards: 0, sentries: 0 },
];

export const STAGES: Array<{
  key: StageKey;
  label: string;
  interval: string;
  from: number;
  to: number;
  focusTime: number;
  verdict: string;
  explanation: string;
  evidence: string[];
}> = [
  {
    key: "draft",
    label: "Драфт",
    interval: "до 0:00",
    from: -90,
    to: 0,
    focusTime: 0,
    verdict: "По данным матча видны составы, но не командный план.",
    explanation: "OpenDota подтверждает выбранных героев и оценивает роли с линиями. Он не записывает, что команда хотела получить от драфта и кто за какое решение отвечал. Поэтому здесь NARMA задаёт вопросы, а не придумывает план за игроков.",
    evidence: ["10 героев подтверждены матчем", "Роли и линии — оценка OpenDota", "Намерения и переговоры в данных отсутствуют"],
  },
  {
    key: "laning",
    label: "Лайнинг",
    interval: "0:00–12:00",
    from: 0,
    to: 720,
    focusTime: 461,
    verdict: "Равный счёт по убийствам скрывал большой разрыв по крипам.",
    explanation: "На 10:00 у Dire было 190 добиваний против 92. В центре Shadow Fiend имел 63/8 LH/DN, Windranger — 18/4. Драка началась в 7:01, а центральная T1 Radiant упала в 7:41. Причину ротации и качество исполнения покажет только replay.",
    evidence: ["Dire +4 705 золота на 10:00", "Mid: SF +45 LH и +2 459 золота", "T1 Radiant mid пал на 7:41"],
  },
  {
    key: "mid",
    label: "Мид-гейм",
    interval: "12:00–30:00",
    from: 720,
    to: 1800,
    focusTime: 1550,
    verdict: "Две неудачные драки подряд закрепили отставание Radiant.",
    explanation: "В драке с 15:24 Radiant потерял пятерых, Dire — троих. В следующем окне с 16:40 Radiant потерял ещё троих без ответного убийства. В 25:50 отмечено убийство Tormentor командой Dire. К 26:00 перевес Dire достиг 13 668 золота.",
    evidence: ["Драка 16:40: Dire 3–0", "−13 668 золота Radiant на 26:00", "Tormentor Dire: 25:50"],
  },
  {
    key: "late",
    label: "Лейт-гейм",
    interval: "30:00–47:09",
    from: 1800,
    to: 2829,
    focusTime: 2609,
    verdict: "После потери Aegis и двух союзников Radiant принял бой 3×4.",
    explanation: "На 38:46 Radiant забрал Roshan и отдал Aegis Juggernaut. В 42:30 Aegis был снят, затем погибли Juggernaut и Ogre. В 43:06 оставшаяся тройка вступила в бой против четырёх и проиграла его 0–3. Данные показывают последовательность, но не намерение команды.",
    evidence: ["Aegis Juggernaut: 38:46", "43:06: бой 3×4, Radiant 0–3", "Buyback Windranger и повторная смерть отмечены в событиях"],
  },
];

export const AXES: Array<{ key: AxisKey; label: string; short: string }> = [
  { key: "movement", label: "Передвижения", short: "Маршруты и тайминги" },
  { key: "vision", label: "Вардинг и вижен", short: "Обсерверы, сентри, зоны" },
  { key: "resources", label: "Ресурсы", short: "Золото, опыт, объекты" },
  { key: "macro", label: "Макро", short: "Линии и карта" },
  { key: "micro", label: "Микро", short: "Решения в драке" },
];

export const AXIS_COPY: Record<StageKey, Record<AxisKey, string>> = {
  draft: {
    movement: "Стартовый маршрут и распределение игроков в статистике не восстановлены. Для оценки нужен replay и выбранная перспектива.",
    vision: "Координаты первых установок есть, но их цель и фактический обзор нельзя подтвердить без replay.",
    resources: "Пики сами по себе не доказывают, кому был доступен безопасный фарм. Это проверяется по линии.",
    macro: "Командный план не записан. Сначала спросите, какой объект и какое условие команда считала приоритетом.",
    micro: "Нажатия и расстановка в будущих драках не следуют из списка героев. Здесь возможна только гипотеза для проверки.",
  },
  laning: {
    movement: "В 7:01 началась драка, а в 7:41 Shadow Fiend забрал центральную T1. Связаны ли события решением о ротации — вопрос к replay.",
    vision: "Показаны реальные точки установок. Оставался ли конкретный вард активным и что видел игрок, OpenDota не сообщает.",
    resources: "На 10:00 счёт был 6–6, но Dire имел 190 против 92 LH и +4 705 золота. Убийства не компенсировали фарм.",
    macro: "Центральная T1 Radiant упала в 7:41. Как это изменило доступ к карте, по сводной статистике доказать нельзя.",
    micro: "Счёт и смерти видны, но анимации, агр крипов, использование ресурсов и кнопок в этих данных отсутствуют.",
  },
  mid: {
    movement: "Видны время и место двух неудачных драк. Маршруты до контакта и последний показ соперников восстановит replay.",
    vision: "Карта хранит точки установок, но не подтверждает, какой обзор был активен перед Tormentor.",
    resources: "При −13,7k на 26:00 любой равный по числу героев файт начинался с экономического минуса.",
    macro: "В ленте есть T1 Dire снизу и Tormentor Dire. Был ли между ними командный план, сводка не показывает.",
    micro: "Результаты драк в 15:24 и 16:40 подтверждены. Какие способности и цели решили исход, без replay неизвестно.",
  },
  late: {
    movement: "После снятия Aegis погибли Juggernaut и Ogre, затем начался бой 3×4. Почему тройка осталась рядом, данные не объясняют.",
    vision: "Observer и Sentry Radiant были установлены рядом с местом драки ранее. Были ли они активны и давали ли обзор в 43:06, OpenDota не показывает; это можно проверить только по replay .dem.",
    resources: "Перед 43:06 Dire имел +7,5k золота и +11k XP. Внутри окна Radiant уступил ещё 6 586 золота и 9 906 XP.",
    macro: "После боя отмечены buyback Windranger, повторная смерть и последовательное падение построек. Командные вызовы в данных отсутствуют.",
    micro: "Бой 3×4 закончился 0–3. Позиции до начала, выбранные цели и использование способностей покажет replay.",
  },
};

export const GOLD_ADV = [0, -555, -821, -1547, -1423, -2147, -2404, -3353, -3926, -4408, -4705, -3969, -5040, -5161, -4640, -6039, -7231, -8693, -10461, -9482, -9942, -9230, -9705, -11196, -11311, -11374, -13668, -13318, -12791, -13128, -12598, -11762, -9996, -8818, -5562, -5775, -4267, -6318, -8069, -6053, -4922, -5133, -5705, -7524, -13863, -18855, -25969, -33544];
export const XP_ADV = [0, -140, -236, -636, -286, -687, -1286, -1921, -2402, -3159, -3834, -2691, -4219, -3726, -4177, -6351, -9081, -10714, -14349, -12136, -12267, -11104, -11835, -13389, -12528, -13247, -17744, -17627, -17814, -17949, -19467, -17159, -13188, -11583, -1681, -6492, 4143, -1658, -5187, -3180, -2072, -6680, -8770, -11035, -20643, -30832, -37247, -44865];

export type Fight = {
  start: number;
  end: number;
  radiant: { kills: number; deaths: number; gold: number; xp: number; damage: number };
  dire: { kills: number; deaths: number; gold: number; xp: number; damage: number };
  deaths: Array<{ heroId: number; side: Side; x: number; y: number }>;
};

export const FIGHTS: Fight[] = [
  { start: 421, end: 463, radiant: { kills: 2, deaths: 1, gold: 1201, xp: 1476, damage: 1401 }, dire: { kills: 1, deaths: 2, gold: 1980, xp: 1060, damage: 2204 }, deaths: [{heroId:8,side:"R",x:156,y:85},{heroId:62,side:"D",x:155,y:88},{heroId:96,side:"D",x:160,y:94}] },
  { start: 481, end: 524, radiant: { kills: 1, deaths: 2, gold: 800, xp: 1552, damage: 1082 }, dire: { kills: 2, deaths: 1, gold: 1623, xp: 2464, damage: 2809 }, deaths: [{heroId:84,side:"R",x:76,y:144},{heroId:81,side:"R",x:79,y:151},{heroId:33,side:"D",x:80,y:160}] },
  { start: 635, end: 685, radiant: { kills: 2, deaths: 2, gold: 2064, xp: 2737, damage: 2396 }, dire: { kills: 2, deaths: 3, gold: 1657, xp: 2602, damage: 3107 }, deaths: [{heroId:105,side:"R",x:176,y:93},{heroId:8,side:"R",x:179,y:97},{heroId:62,side:"D",x:180,y:105},{heroId:96,side:"D",x:169,y:95},{heroId:33,side:"D",x:79,y:149}] },
  { start: 924, end: 972, radiant: { kills: 3, deaths: 5, gold: 1607, xp: 3175, damage: 5268 }, dire: { kills: 5, deaths: 3, gold: 2893, xp: 5527, damage: 7469 }, deaths: [{heroId:105,side:"R",x:63,y:148},{heroId:8,side:"R",x:83,y:164},{heroId:84,side:"R",x:80,y:165},{heroId:21,side:"R",x:81,y:163},{heroId:81,side:"R",x:83,y:163},{heroId:62,side:"D",x:65,y:157},{heroId:96,side:"D",x:80,y:164},{heroId:33,side:"D",x:85,y:166}] },
  { start: 1000, end: 1043, radiant: { kills: 0, deaths: 3, gold: 437, xp: 1150, damage: 4600 }, dire: { kills: 3, deaths: 0, gold: 2988, xp: 4557, damage: 4847 }, deaths: [{heroId:105,side:"R",x:107,y:107},{heroId:21,side:"R",x:111,y:102},{heroId:81,side:"R",x:109,y:100}] },
  { start: 1100, end: 1144, radiant: { kills: 2, deaths: 3, gold: 3587, xp: 7971, damage: 4770 }, dire: { kills: 3, deaths: 3, gold: 1750, xp: 4604, damage: 6139 }, deaths: [{heroId:105,side:"R",x:154,y:85},{heroId:84,side:"R",x:152,y:77},{heroId:21,side:"R",x:147,y:78},{heroId:62,side:"D",x:157,y:78},{heroId:11,side:"D",x:161,y:86},{heroId:96,side:"D",x:156,y:79}] },
  { start: 1219, end: 1255, radiant: { kills: 2, deaths: 3, gold: 2420, xp: 6031, damage: 4689 }, dire: { kills: 3, deaths: 3, gold: 1934, xp: 5401, damage: 6930 }, deaths: [{heroId:105,side:"R",x:122,y:84},{heroId:8,side:"R",x:122,y:65},{heroId:81,side:"R",x:119,y:73},{heroId:62,side:"D",x:122,y:82},{heroId:11,side:"D",x:120,y:74},{heroId:96,side:"D",x:122,y:81}] },
  { start: 1717, end: 1753, radiant: { kills: 1, deaths: 2, gold: 2462, xp: 3698, damage: 5442 }, dire: { kills: 2, deaths: 2, gold: 2000, xp: 5401, damage: 6964 }, deaths: [{heroId:105,side:"R",x:133,y:81},{heroId:81,side:"R",x:138,y:79},{heroId:96,side:"D",x:128,y:81},{heroId:33,side:"D",x:134,y:97}] },
  { start: 1822, end: 1889, radiant: { kills: 4, deaths: 3, gold: 4698, xp: 14712, damage: 14483 }, dire: { kills: 3, deaths: 4, gold: 2017, xp: 8995, damage: 12006 }, deaths: [{heroId:105,side:"R",x:92,y:164},{heroId:8,side:"R",x:85,y:158},{heroId:81,side:"R",x:94,y:159},{heroId:62,side:"D",x:97,y:156},{heroId:11,side:"D",x:94,y:164},{heroId:96,side:"D",x:92,y:163},{heroId:48,side:"D",x:90,y:179}] },
  { start: 1961, end: 2016, radiant: { kills: 4, deaths: 0, gold: 5528, xp: 13390, damage: 8985 }, dire: { kills: 0, deaths: 4, gold: 381, xp: 2422, damage: 1548 }, deaths: [{heroId:62,side:"D",x:116,y:148},{heroId:96,side:"D",x:116,y:162},{heroId:33,side:"D",x:96,y:173},{heroId:48,side:"D",x:108,y:174}] },
  { start: 2147, end: 2184, radiant: { kills: 1, deaths: 2, gold: 1559, xp: 4916, damage: 7640 }, dire: { kills: 2, deaths: 1, gold: 3060, xp: 9044, damage: 6811 }, deaths: [{heroId:8,side:"R",x:168,y:136},{heroId:84,side:"R",x:169,y:134},{heroId:62,side:"D",x:176,y:141}] },
  { start: 2317, end: 2377, radiant: { kills: 3, deaths: 2, gold: 3804, xp: 11334, damage: 10787 }, dire: { kills: 2, deaths: 3, gold: 1734, xp: 9780, damage: 12689 }, deaths: [{heroId:84,side:"R",x:154,y:121},{heroId:81,side:"R",x:152,y:122},{heroId:62,side:"D",x:148,y:140},{heroId:96,side:"D",x:150,y:122},{heroId:33,side:"D",x:155,y:137}] },
  { start: 2533, end: 2570, radiant: { kills: 1, deaths: 2, gold: 975, xp: 8279, damage: 2589 }, dire: { kills: 2, deaths: 1, gold: 3988, xp: 10200, damage: 7284 }, deaths: [{heroId:8,side:"R",x:81,y:160},{heroId:84,side:"R",x:81,y:149},{heroId:62,side:"D",x:80,y:158}] },
  { start: 2586, end: 2624, radiant: { kills: 0, deaths: 3, gold: -1311, xp: 191, damage: 3019 }, dire: { kills: 3, deaths: 0, gold: 5275, xp: 10097, damage: 8891 }, deaths: [{heroId:105,side:"R",x:111,y:112},{heroId:21,side:"R",x:110,y:116},{heroId:81,side:"R",x:103,y:102}] },
  { start: 2654, end: 2697, radiant: { kills: 1, deaths: 3, gold: 138, xp: 5112, damage: 7948 }, dire: { kills: 3, deaths: 1, gold: 5539, xp: 15075, damage: 10877 }, deaths: [{heroId:8,side:"R",x:68,y:125},{heroId:84,side:"R",x:68,y:111},{heroId:21,side:"R",x:69,y:103},{heroId:48,side:"D",x:68,y:121}] },
];

export const EVENTS = [
  { t: 165, type: "fight", title: "First Blood — Enigma", detail: "Dire открыл счёт" },
  { t: 461, type: "tower", title: "T1 Radiant mid", detail: "Shadow Fiend" },
  { t: 783, type: "tower", title: "T1 Dire top", detail: "Chaos Knight" },
  { t: 1390, type: "tower", title: "T1 Radiant top", detail: "Luna" },
  { t: 1550, type: "tormentor", title: "Tormentor — Dire", detail: "Centaur Warrunner" },
  { t: 1564, type: "tower", title: "T1 Dire bot", detail: "Radiant creeps" },
  { t: 1921, type: "tower", title: "T1 Dire mid", detail: "Windranger" },
  { t: 2045, type: "tower", title: "T2 Dire top", detail: "Juggernaut" },
  { t: 2326, type: "roshan", title: "Roshan — Radiant", detail: "Aegis → Juggernaut" },
  { t: 2550, type: "pivot", title: "Aegis снят", detail: "SF убил Juggernaut, затем Ogre" },
  { t: 2586, type: "fight", title: "Решающий бой 3×4", detail: "Radiant 0–3" },
  { t: 2604, type: "buyback", title: "Buyback Windranger", detail: "повторная смерть 44:42" },
  { t: 2624, type: "tower", title: "T2 Radiant mid", detail: "Centaur Warrunner" },
  { t: 2635, type: "tower", title: "T2 Radiant top", detail: "Shadow Fiend" },
  { t: 2663, type: "tower", title: "T2 Radiant bot", detail: "Shadow Fiend" },
  { t: 2693, type: "tower", title: "T3 Radiant top", detail: "Enigma" },
  { t: 2702, type: "barracks", title: "Казармы Radiant top", detail: "Обе стороны линии" },
  { t: 2751, type: "barracks", title: "Казармы Radiant mid", detail: "Обе стороны линии" },
  { t: 2768, type: "barracks", title: "Казармы Radiant bot", detail: "Обе стороны линии" },
  { t: 2829, type: "ancient", title: "Ancient Radiant", detail: "Победа Dire" },
] as const;

export type WardEvent = { t: number; x: number; y: number; type: "obs" | "sen"; side: Side; heroId: number };
export const WARDS: WardEvent[] = [
  { t: -18, x: 98, y: 87.9, type: "obs", side: "D", heroId: 62 },
  { t: -13, x: 117.9, y: 126.2, type: "obs", side: "R", heroId: 21 },
  { t: 3, x: 123.6, y: 129.9, type: "sen", side: "R", heroId: 21 },
  { t: 8, x: 156.6, y: 85.7, type: "sen", side: "D", heroId: 62 },
  { t: 41, x: 159.6, y: 84.8, type: "sen", side: "R", heroId: 105 },
  { t: 64, x: 83.1, y: 160.5, type: "sen", side: "R", heroId: 84 },
  { t: 119, x: 174.5, y: 85.3, type: "sen", side: "R", heroId: 105 },
  { t: 182, x: 86.5, y: 161.6, type: "sen", side: "D", heroId: 33 },
  { t: 187, x: 123.9, y: 125.6, type: "sen", side: "D", heroId: 11 },
  { t: 234, x: 174.3, y: 88.1, type: "obs", side: "R", heroId: 105 },
  { t: 268, x: 126.5, y: 118.8, type: "obs", side: "D", heroId: 11 },
  { t: 305, x: 80.3, y: 151.5, type: "sen", side: "R", heroId: 84 },
  { t: 341, x: 93.2, y: 164.5, type: "obs", side: "D", heroId: 33 },
  { t: 418, x: 164.9, y: 94, type: "sen", side: "R", heroId: 105 },
  { t: 445, x: 158.2, y: 96.9, type: "obs", side: "R", heroId: 105 },
  { t: 458, x: 180.4, y: 98.1, type: "sen", side: "R", heroId: 105 },
  { t: 460, x: 187.9, y: 93.6, type: "obs", side: "R", heroId: 105 },
  { t: 478, x: 157.2, y: 82.3, type: "sen", side: "R", heroId: 105 },
  { t: 496, x: 143.9, y: 98.3, type: "sen", side: "D", heroId: 62 },
  { t: 505, x: 133.7, y: 95.7, type: "obs", side: "D", heroId: 62 },
  { t: 518, x: 108.2, y: 98.7, type: "obs", side: "D", heroId: 62 },
  { t: 527, x: 128.5, y: 109.7, type: "obs", side: "D", heroId: 62 },
  { t: 573, x: 146.8, y: 90.2, type: "sen", side: "R", heroId: 105 },
  { t: 594, x: 174.2, y: 88.2, type: "obs", side: "R", heroId: 105 },
  { t: 635, x: 175.4, y: 84.7, type: "sen", side: "R", heroId: 105 },
  { t: 663, x: 178.6, y: 95.1, type: "sen", side: "D", heroId: 62 },
  { t: 712, x: 86.1, y: 151.1, type: "obs", side: "R", heroId: 105 },
  { t: 727, x: 114.2, y: 150.4, type: "obs", side: "D", heroId: 62 },
  { t: 729, x: 94.8, y: 174.7, type: "obs", side: "R", heroId: 105 },
  { t: 811, x: 101.6, y: 134.1, type: "obs", side: "R", heroId: 105 },
  { t: 830, x: 141.6, y: 88.1, type: "obs", side: "D", heroId: 62 },
  { t: 1004, x: 94, y: 120.1, type: "obs", side: "R", heroId: 105 },
  { t: 1040, x: 107.2, y: 95.5, type: "obs", side: "D", heroId: 62 },
  { t: 1085, x: 117.9, y: 94.1, type: "obs", side: "R", heroId: 105 },
  { t: 1197, x: 126.7, y: 119.3, type: "obs", side: "D", heroId: 11 },
  { t: 1310, x: 153.8, y: 66.1, type: "obs", side: "D", heroId: 62 },
  { t: 1321, x: 101.5, y: 133.4, type: "obs", side: "R", heroId: 105 },
  { t: 1512, x: 136.7, y: 104.2, type: "obs", side: "R", heroId: 105 },
  { t: 1538, x: 65, y: 166.3, type: "obs", side: "D", heroId: 62 },
  { t: 1544, x: 75.4, y: 184.4, type: "obs", side: "D", heroId: 62 },
  { t: 1628, x: 118, y: 93.8, type: "obs", side: "R", heroId: 105 },
  { t: 1641, x: 94.3, y: 120, type: "obs", side: "R", heroId: 105 },
  { t: 1714, x: 145, y: 84.5, type: "obs", side: "D", heroId: 62 },
  { t: 1752, x: 151.8, y: 89.8, type: "obs", side: "R", heroId: 84 },
  { t: 1787, x: 150.3, y: 115.6, type: "obs", side: "D", heroId: 62 },
  { t: 1938, x: 115.3, y: 149, type: "obs", side: "R", heroId: 105 },
  { t: 2083, x: 136.3, y: 155.8, type: "obs", side: "D", heroId: 33 },
  { t: 2104, x: 115.6, y: 157.3, type: "obs", side: "D", heroId: 33 },
  { t: 2117, x: 150.4, y: 115.8, type: "obs", side: "D", heroId: 62 },
  { t: 2124, x: 101.7, y: 133.7, type: "obs", side: "R", heroId: 105 },
  { t: 2173, x: 148.3, y: 118.1, type: "obs", side: "R", heroId: 105 },
  { t: 2225, x: 149.8, y: 115.8, type: "sen", side: "D", heroId: 62 },
  { t: 2263, x: 137.6, y: 103.3, type: "obs", side: "R", heroId: 105 },
  { t: 2265, x: 142.1, y: 108.4, type: "sen", side: "R", heroId: 105 },
  { t: 2265, x: 142.7, y: 100.7, type: "obs", side: "D", heroId: 62 },
  { t: 2288, x: 141.4, y: 137.5, type: "sen", side: "R", heroId: 105 },
  { t: 2482, x: 117.9, y: 94.1, type: "obs", side: "R", heroId: 105 },
  { t: 2482, x: 117.9, y: 94.1, type: "sen", side: "R", heroId: 105 },
  { t: 2535, x: 134, y: 153, type: "sen", side: "D", heroId: 33 },
  { t: 2536, x: 136.2, y: 155.8, type: "obs", side: "D", heroId: 33 },
  { t: 2538, x: 120, y: 150.2, type: "sen", side: "D", heroId: 33 },
  { t: 2542, x: 109.3, y: 161.6, type: "sen", side: "D", heroId: 33 },
  { t: 2664, x: 100.6, y: 121.8, type: "sen", side: "D", heroId: 33 },
  { t: 2665, x: 94.1, y: 119.9, type: "obs", side: "D", heroId: 33 },
  { t: 722, x: 119.1, y: 152.8, type: "sen", side: "D", heroId: 62 },
  { t: 726, x: 90.7, y: 165.1, type: "sen", side: "R", heroId: 105 },
  { t: 743, x: 106.5, y: 162.8, type: "sen", side: "R", heroId: 105 },
  { t: 743, x: 123.3, y: 124.4, type: "sen", side: "D", heroId: 62 },
  { t: 806, x: 132.6, y: 102.9, type: "sen", side: "D", heroId: 62 },
  { t: 813, x: 96.6, y: 131.9, type: "sen", side: "R", heroId: 105 },
  { t: 825, x: 111.3, y: 114.4, type: "sen", side: "R", heroId: 105 },
  { t: 897, x: 134.2, y: 100.7, type: "sen", side: "R", heroId: 105 },
  { t: 984, x: 136.3, y: 155.6, type: "sen", side: "D", heroId: 33 },
  { t: 998, x: 133.3, y: 99.3, type: "sen", side: "D", heroId: 62 },
  { t: 1003, x: 144.7, y: 91.5, type: "sen", side: "D", heroId: 62 },
  { t: 1016, x: 118, y: 94.1, type: "sen", side: "D", heroId: 62 },
  { t: 1045, x: 110.3, y: 89.5, type: "sen", side: "D", heroId: 62 },
  { t: 1051, x: 119.7, y: 104.1, type: "sen", side: "D", heroId: 62 },
  { t: 1066, x: 151.7, y: 123.3, type: "sen", side: "D", heroId: 62 },
  { t: 1086, x: 115.3, y: 95.4, type: "sen", side: "R", heroId: 105 },
  { t: 1095, x: 134, y: 100.9, type: "sen", side: "R", heroId: 105 },
  { t: 1102, x: 145.4, y: 88.6, type: "sen", side: "R", heroId: 84 },
  { t: 1163, x: 121.6, y: 121.6, type: "sen", side: "R", heroId: 84 },
  { t: 1196, x: 125.1, y: 124.8, type: "sen", side: "D", heroId: 11 },
  { t: 1297, x: 178.7, y: 69.8, type: "sen", side: "D", heroId: 62 },
  { t: 1316, x: 155, y: 67, type: "sen", side: "D", heroId: 62 },
  { t: 1322, x: 96.6, y: 131.6, type: "sen", side: "R", heroId: 105 },
  { t: 1345, x: 156.8, y: 89.1, type: "sen", side: "D", heroId: 62 },
  { t: 1479, x: 134.7, y: 101.3, type: "sen", side: "D", heroId: 62 },
  { t: 1495, x: 135.1, y: 102.3, type: "sen", side: "R", heroId: 105 },
  { t: 1522, x: 137.1, y: 79.7, type: "sen", side: "R", heroId: 105 },
  { t: 1523, x: 78, y: 185.5, type: "sen", side: "D", heroId: 62 },
  { t: 1527, x: 69.8, y: 174.6, type: "sen", side: "D", heroId: 62 },
  { t: 1540, x: 175.1, y: 71.3, type: "sen", side: "R", heroId: 105 },
  { t: 1573, x: 179.3, y: 69.7, type: "sen", side: "D", heroId: 62 },
  { t: 1625, x: 112.3, y: 114.3, type: "sen", side: "R", heroId: 84 },
  { t: 1626, x: 118.8, y: 91.2, type: "sen", side: "R", heroId: 105 },
  { t: 1634, x: 94.2, y: 119.9, type: "sen", side: "R", heroId: 84 },
  { t: 1676, x: 143.5, y: 109, type: "sen", side: "D", heroId: 62 },
  { t: 1678, x: 122.1, y: 124.5, type: "sen", side: "R", heroId: 105 },
  { t: 1682, x: 134.8, y: 100.6, type: "sen", side: "D", heroId: 62 },
  { t: 1745, x: 143.1, y: 78.4, type: "sen", side: "R", heroId: 84 },
  { t: 1791, x: 152.1, y: 123.6, type: "sen", side: "D", heroId: 62 },
  { t: 1808, x: 127.6, y: 109.1, type: "sen", side: "D", heroId: 62 },
  { t: 1932, x: 97.3, y: 131.5, type: "sen", side: "R", heroId: 105 },
  { t: 1935, x: 107.9, y: 141.8, type: "sen", side: "R", heroId: 105 },
  { t: 1940, x: 118.6, y: 151.4, type: "sen", side: "R", heroId: 105 },
  { t: 2013, x: 108.3, y: 163.5, type: "sen", side: "R", heroId: 105 },
  { t: 2081, x: 140.7, y: 154.2, type: "sen", side: "D", heroId: 33 },
  { t: 2096, x: 122.2, y: 152.5, type: "sen", side: "D", heroId: 33 },
  { t: 2131, x: 145.3, y: 109.9, type: "sen", side: "D", heroId: 62 },
  { t: 2175, x: 150.3, y: 121.2, type: "sen", side: "R", heroId: 105 },
  { t: 2177, x: 163.8, y: 133.8, type: "sen", side: "D", heroId: 33 },
  { t: 2181, x: 145.7, y: 113.5, type: "sen", side: "R", heroId: 105 },
];

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
