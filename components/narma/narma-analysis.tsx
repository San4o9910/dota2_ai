"use client";

/* eslint-disable @next/next/no-img-element */

import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  Coins,
  Crosshair,
  Database,
  Eye,
  Flag,
  Gem,
  Info,
  Layers3,
  Menu,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  Route,
  Send,
  Shield,
  Sparkles,
  Swords,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import AccountControl, { type ViewerSummary } from "@/components/narma/account-control";
import PricingSection from "@/components/narma/pricing-section";

import {
  AXES,
  AXIS_COPY,
  EVENTS,
  FIGHTS,
  GOLD_ADV,
  HEROES,
  MAP_OBJECTS,
  MATCH,
  STAGES,
  WARDS,
  XP_ADV,
  formatTime,
  heroImage,
  type AxisKey,
  type Fight,
  type Hero,
  type Side,
  type StageKey,
} from "@/app/data/match-8963624400";

type LayerKey = "heroes" | "vision" | "structures" | "objectives" | "camps" | "creeps";
type MapMode = "coach" | "vision" | "full";

type TrainingDrill = {
  id: string;
  title: string;
  axis: string;
  why: string;
  evidence: string;
  steps: string[];
  metric: string;
  dose: string;
  moment: number;
};

const LAYERS: Array<{ key: LayerKey; label: string }> = [
  { key: "heroes", label: "Герои / смерти" },
  { key: "vision", label: "Варды" },
  { key: "structures", label: "Постройки" },
  { key: "objectives", label: "Объекты и руны" },
  { key: "camps", label: "Лагеря" },
  { key: "creeps", label: "Волны крипов · модель" },
];

export const TRAINING_PLAN: Record<StageKey, {
  goal: string;
  result: string;
  drills: TrainingDrill[];
}> = {
  draft: {
    goal: "До выхода крипов понимать, как ваша пятёрка выигрывает карту и чего ей нельзя отдавать.",
    result: "За 30 секунд назвать инициатора, главную угрозу врага и план первой общей драки.",
    drills: [
      {
        id: "draft-win-condition",
        title: "Собрать план драфта в трёх фразах",
        axis: "Макро · микро",
        why: "Без общего плана Radiant было проще согласиться на удобный Dire бой 5×5, где работали Centaur, Black Hole, Requiem и Eclipse.",
        evidence: "Матч 8963624400: Dire имел более простой массовый контроль и быстрее превращал победу в строения.",
        steps: [
          "Назовите героя, который начинает ваш хороший бой.",
          "Назовите способность врага, из-за которой нельзя стоять вместе.",
          "Решите заранее: после победы вы забираете башню, Roshan или две линии фарма.",
        ],
        metric: "План сформулирован до 0:00 и помещается в 30 секунд.",
        dose: "Перед каждой из следующих 5 игр",
        moment: 0,
      },
      {
        id: "draft-formation",
        title: "Назначить игрока вне первой волны контроля",
        axis: "Передвижения · микро",
        why: "Против Enigma один герой обязан стоять отдельно и иметь возможность прервать или переждать Black Hole.",
        evidence: "На 43:06 сгруппированная тройка Radiant попала под Black Hole с BKB.",
        steps: [
          "Определите, кто из пяти не показывает позицию до начала Black Hole.",
          "Отметьте безопасный угол входа относительно основной четвёрки.",
          "После каждой драки проверьте: этот герой вошёл раньше или позже ключевой способности?",
        ],
        metric: "В 4 из 5 драк ключевой страхующий герой не попадает в первый массовый контроль.",
        dose: "5 командных драк",
        moment: 2586,
      },
    ],
  },
  laning: {
    goal: "Не путать равный счёт по убийствам с равной линией: главный ориентир — крипы, уровни и состояние башни.",
    result: "К 10:00 не отдавать большой разрыв по добитым крипам ради ротаций без продолжения.",
    drills: [
      {
        id: "lane-last-hits",
        title: "Три десятиминутки на стабильный фарм",
        axis: "Ресурсы · микро",
        why: "Убийства не закрывают потерянные волны. В этом матче при счёте 6–6 Dire уже вёл на 4 705 золота.",
        evidence: "На 10:00 у команд было 190 против 92 LH; на центре SF имел 63/8, а Windranger — 18/4.",
        steps: [
          "Сыграйте 10 минут в тренировочном лобби без предметов на урон.",
          "После каждого промаха назовите причину: анимация, агр крипов или лишнее движение.",
          "Повторите ещё два раза и запишите лучший и средний результат, а не только рекорд.",
        ],
        metric: "Кор: не меньше 55 LH к 10:00; саппорт: не пропустить pull/stack-окно ради бесполезной ротации.",
        dose: "3 подхода по 10 минут",
        moment: 600,
      },
      {
        id: "lane-rotation-price",
        title: "Посчитать цену каждой ротации",
        axis: "Передвижения · макро",
        why: "Хорошая драка может быть плохим обменом, если свободный кор забирает волну и башню.",
        evidence: "Ротация Radiant на 7:01 дала 2–1, но Shadow Fiend без давления забрал центральную T1 на 7:41.",
        steps: [
          "Перед уходом с линии посмотрите, где находится следующая волна.",
          "Назовите продолжение ротации: руна, башня, вард или возврат на фарм.",
          "Через 40 секунд сравните полученное с потерянными крипами и уроном по своей башне.",
        ],
        metric: "Не терять больше одной полной волны без убийства ключевого героя или объекта.",
        dose: "Контроль первых 3 ротаций в матче",
        moment: 421,
      },
    ],
  },
  mid: {
    goal: "Начинать драку только после короткой проверки реальной силы команд и следующей цели.",
    result: "Каждый вход имеет понятную причину: численность, важный предмет, способность или выгодная позиция.",
    drills: [
      {
        id: "mid-power-check",
        title: "Пятисекундная проверка перед контактом",
        axis: "Ресурсы · микро",
        why: "При заметном отставании равный по числу героев бой начинается не с нуля — соперник уже сильнее предметами и уровнями.",
        evidence: "К 26:00 Dire имел +13 668 золота; драки 15:24 и 16:40 закрепили его Blink-тайминги.",
        steps: [
          "Посчитайте видимых союзников и врагов: входить можно только при понятной численности.",
          "Проверьте свои BKB/ультимейты и два последних показанных ключевых предмета врага.",
          "Скажите вслух одно основание для входа; если его нет — покажите линии и разойдитесь.",
        ],
        metric: "Ноль равных 5×5 без информации о ключевой способности или предметном преимуществе.",
        dose: "Перед каждой дракой 12:00–30:00",
        moment: 1000,
      },
      {
        id: "mid-vision-objective",
        title: "Связать вард с конкретной целью",
        axis: "Вижен · макро",
        why: "Вард ценен не сам по себе: он должен дать безопасный вход к Tormentor, башне, Roshan или в чужой лес.",
        evidence: "Dire связал выигранные драки, контроль подходов и Tormentor на 25:50.",
        steps: [
          "До постановки назовите объект и опасный путь соперника к нему.",
          "Поставьте обзор на подход, а не в центр уже контролируемой зоны.",
          "В течение минуты либо заберите цель, либо снимите риск и вернитесь к линиям.",
        ],
        metric: "Не меньше 70% ключевых вардов приводят к объекту или безопасному фарму в течение 60 секунд.",
        dose: "5 осмысленных вардов",
        moment: 1550,
      },
    ],
  },
  late: {
    goal: "После большого объекта или потерянной драки остановить инерцию и снова собрать команду в пять героев.",
    result: "Ни одного нового контакта без полного состава, buyback-плана и готовых ключевых кнопок.",
    drills: [
      {
        id: "late-aegis-reset",
        title: "Команда «сброс» после потери Aegis",
        axis: "Макро · передвижения",
        why: "Aegis даёт вторую жизнь, но не делает следующий бой автоматически хорошим. После его снятия условия нужно оценить заново.",
        evidence: "Roshan на 38:46 был правильным; после снятия Aegis в 42:30 Radiant не отошёл и принял 3×4 на 43:06.",
        steps: [
          "Сразу после снятия Aegis один игрок говорит: «сброс, считаем живых».",
          "Проверьте таймеры смерти, телепорты, buyback и готовность основных ультимейтов.",
          "До восстановления пяти героев защищайте линии издалека и не переходите реку за новой целью.",
        ],
        metric: "После потери Aegis команда не начинает новый бой, пока не восстановит безопасный состав.",
        dose: "Отработать в 3 поздних играх",
        moment: 2550,
      },
      {
        id: "late-buyback",
        title: "Один общий выход вместо цепочки dieback",
        axis: "Ресурсы · микро",
        why: "Разрозненные buyback дают сопернику несколько лёгких мини-драк вместо одной полноценной защиты.",
        evidence: "После 43:06 три buyback Radiant закончились повторными смертями и потерей всех трёх линий казарм.",
        steps: [
          "Перед buyback назовите защищаемый объект и игроков, которые выходят одновременно.",
          "Если объект уже нельзя спасти, сохраните buyback и готовьте следующую линию обороны.",
          "После возвращения дождитесь общей позиции; не телепортируйтесь по одному в уже проигранную зону.",
        ],
        metric: "Ноль одиночных dieback; каждый buyback либо сохраняет объект, либо создаёт полноценный бой 5×5.",
        dose: "Проверять каждое решение после 35:00",
        moment: 2604,
      },
    ],
  },
};

const ICONS: Record<AxisKey, typeof Route> = {
  movement: Route,
  vision: Eye,
  resources: Coins,
  macro: Flag,
  micro: Crosshair,
};

const MAP_LABELS: Record<string, string> = {
  roshan: "R",
  tormentor: "T",
  wisdom: "W",
  lotus: "L",
  gate: "G",
  bounty: "B",
  power: "P",
  watcher: "◉",
  outpost: "O",
  shop: "$",
  tower: "◆",
  ancient: "A",
  camp: "•",
};

function stageAtTime(time: number): StageKey {
  if (time <= 0) return "draft";
  if (time <= 720) return "laning";
  if (time <= 1800) return "mid";
  return "late";
}

function signed(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toLocaleString("ru-RU")}`;
}

function sideLead(value: number) {
  if (value === 0) return "Равенство";
  return `${value > 0 ? "Radiant" : "Dire"} +${Math.abs(value).toLocaleString("ru-RU")}`;
}

function worldToPercent(x: number, y: number) {
  const bound = 9472;
  return {
    left: ((x + bound) / (bound * 2)) * 100,
    top: (1 - (y + bound) / (bound * 2)) * 100,
  };
}

function gridToPercent(x: number, y: number) {
  return { left: (x / 256) * 100, top: (1 - y / 256) * 100 };
}

function HeroPortrait({ hero, small = false }: { hero: Hero; small?: boolean }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`hero-portrait ${hero.side === "R" ? "radiant" : "dire"} ${small ? "small" : ""}`}>
      {!failed ? (
        <img src={heroImage(hero.slug)} alt={hero.name} onError={() => setFailed(true)} />
      ) : (
        <span aria-hidden="true">{hero.name.slice(0, 2).toUpperCase()}</span>
      )}
    </span>
  );
}

function ResourceChart({ time }: { time: number }) {
  const width = 920;
  const height = 280;
  const plotTop = 22;
  const plotBottom = 238;
  const max = 46000;
  const zero = (plotTop + plotBottom) / 2;
  const xAt = (i: number) => 34 + (i / 47) * (width - 62);
  const yAt = (v: number) => zero - (v / max) * ((plotBottom - plotTop) / 2);
  const path = (values: number[]) => values.map((v, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
  const minute = Math.min(47, Math.max(0, Math.round(time / 60)));
  const bands = [
    { from: 0, to: 12, label: "Лайнинг" },
    { from: 12, to: 30, label: "Мид" },
    { from: 30, to: 47, label: "Лейт" },
  ];

  return (
    <div className="chart-wrap" role="img" aria-label="Поминутное преимущество Radiant по золоту и опыту">
      <svg viewBox={`0 0 ${width} ${height}`} className="resource-chart">
        <defs>
          <linearGradient id="goldGlow" x1="0" x2="1">
            <stop offset="0" stopColor="#c7a764" stopOpacity="0.42" />
            <stop offset="1" stopColor="#f0d18b" />
          </linearGradient>
          <filter id="softGlow"><feGaussianBlur stdDeviation="2" result="b" /><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        {bands.map((band, index) => (
          <g key={band.label}>
            <rect x={xAt(band.from)} y={plotTop} width={xAt(band.to) - xAt(band.from)} height={plotBottom - plotTop} className={index % 2 ? "chart-band alt" : "chart-band"} />
            <text x={(xAt(band.from) + xAt(band.to)) / 2} y="270" textAnchor="middle" className="chart-label">{band.label}</text>
          </g>
        ))}
        {[23000, 0, -23000, -46000].map((tick) => (
          <g key={tick}>
            <line x1="34" x2={width - 28} y1={yAt(tick)} y2={yAt(tick)} className={tick === 0 ? "chart-zero" : "chart-grid"} />
            <text x="4" y={yAt(tick) + 4} className="chart-tick">{tick === 0 ? "0" : `${tick > 0 ? "+" : "−"}${Math.abs(tick / 1000)}k`}</text>
          </g>
        ))}
        <text x="40" y="17" className="chart-side radiant-text">Radiant</text>
        <text x="40" y="252" className="chart-side dire-text">Dire</text>
        <path d={path(XP_ADV)} className="chart-line xp" />
        <path d={path(GOLD_ADV)} className="chart-line gold" filter="url(#softGlow)" />
        <line x1={xAt(minute)} x2={xAt(minute)} y1={plotTop} y2={plotBottom} className="chart-cursor" />
        <circle cx={xAt(minute)} cy={yAt(GOLD_ADV[minute])} r="5" className="chart-dot gold" />
        <circle cx={xAt(minute)} cy={yAt(XP_ADV[minute])} r="5" className="chart-dot xp" />
      </svg>
      <div className="chart-legend">
        <span><i className="gold" />Золото: <strong>{sideLead(GOLD_ADV[minute])}</strong></span>
        <span><i className="xp" />Опыт: <strong>{sideLead(XP_ADV[minute])}</strong></span>
        <span className="data-note">Поминутно · OpenDota</span>
      </div>
    </div>
  );
}

function FightImpactChart({ active, onSelect }: { active: Fight; onSelect: (time: number) => void }) {
  const max = 7000;
  return (
    <div className="fight-chart" aria-label="Разница золота, полученного командами в каждом окне драки">
      {FIGHTS.map((fight, index) => {
        const delta = fight.radiant.gold - fight.dire.gold;
        const height = Math.max(4, Math.abs(delta) / max * 100);
        return (
          <button
            key={fight.start}
            className={fight.start === active.start ? "active" : ""}
            onClick={() => onSelect(fight.start)}
            style={{ "--bar-height": `${height}%` } as React.CSSProperties}
            title={`${formatTime(fight.start)}: ${delta >= 0 ? "Radiant" : "Dire"} +${Math.abs(delta).toLocaleString("ru-RU")} золота за окно`}
            aria-label={`Драка ${index + 1}, ${formatTime(fight.start)}`}
          >
            <span className={delta >= 0 ? "bar radiant" : "bar dire"} />
            <small>{index + 1}</small>
          </button>
        );
      })}
    </div>
  );
}

function LaneCreeps({ time }: { time: number }) {
  const lanes = [
    { r: { x: 18 + (time % 60) / 60 * 35, y: 77 - (time % 60) / 60 * 38 }, d: { x: 82 - (time % 60) / 60 * 35, y: 20 + (time % 60) / 60 * 38 } },
    { r: { x: 23 + (time % 60) / 60 * 28, y: 76 - (time % 60) / 60 * 27 }, d: { x: 77 - (time % 60) / 60 * 28, y: 23 + (time % 60) / 60 * 27 } },
    { r: { x: 30 + (time % 60) / 60 * 42, y: 84 - (time % 60) / 60 * 17 }, d: { x: 72 - (time % 60) / 60 * 42, y: 17 + (time % 60) / 60 * 17 } },
  ];
  return (
    <>
      {lanes.flatMap((lane, i) => ([
        <span key={`r${i}`} className="creep-marker radiant" style={{ left: `${lane.r.x}%`, top: `${lane.r.y}%` }} title="Волна Radiant · расчётная модель" />,
        <span key={`d${i}`} className="creep-marker dire" style={{ left: `${lane.d.x}%`, top: `${lane.d.y}%` }} title="Волна Dire · расчётная модель" />,
      ]))}
    </>
  );
}

type NarmaAnalysisProps = {
  viewer: ViewerSummary | null;
  signInHref: string;
  signOutHref: string;
};

export default function NarmaAnalysis({ viewer, signInHref, signOutHref }: NarmaAnalysisProps) {
  const [selectedStage, setSelectedStage] = useState<StageKey>("laning");
  const [selectedAxis, setSelectedAxis] = useState<AxisKey>("resources");
  const [selectedHeroId, setSelectedHeroId] = useState<number | null>(null);
  const [time, setTime] = useState(461);
  const [playing, setPlaying] = useState(false);
  const [mapMode, setMapMode] = useState<MapMode>("coach");
  const [mapReady, setMapReady] = useState(true);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [matchPanel, setMatchPanel] = useState(false);
  const [matchIdDraft, setMatchIdDraft] = useState("");
  const [matchNotice, setMatchNotice] = useState("");
  const [trainingStage, setTrainingStage] = useState<StageKey>("laning");
  const [completedDrills, setCompletedDrills] = useState<Record<string, boolean>>({});
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    heroes: true,
    vision: true,
    structures: true,
    objectives: true,
    camps: false,
    creeps: true,
  });
  const [chatText, setChatText] = useState("");
  const [coachReply, setCoachReply] = useState("Выберите героя — тогда я отделю ваши решения от командных и разберу их по пяти осям.");

  const stage = STAGES.find((item) => item.key === selectedStage) ?? STAGES[1];
  const training = TRAINING_PLAN[trainingStage];
  const completedCount = Object.values(completedDrills).filter(Boolean).length;
  const totalDrills = Object.values(TRAINING_PLAN).reduce((sum, item) => sum + item.drills.length, 0);
  const selectedHero = HEROES.find((hero) => hero.id === selectedHeroId) ?? null;
  const minute = Math.min(47, Math.max(0, Math.round(time / 60)));
  const activeFight = useMemo(() => FIGHTS.reduce((closest, fight) => {
    const currentGap = Math.min(Math.abs(time - fight.start), Math.abs(time - fight.end));
    const closestGap = Math.min(Math.abs(time - closest.start), Math.abs(time - closest.end));
    return currentGap < closestGap ? fight : closest;
  }, FIGHTS[0]), [time]);

  const wardSide: Side | null = selectedHero ? selectedHero.side : null;
  const recentWards = WARDS.filter((ward) => {
    const inWindow = ward.t <= time + 20 && ward.t >= time - 420;
    if (!inWindow) return false;
    if (mapMode === "full" || mapMode === "coach") return true;
    return wardSide ? ward.side === wardSide : ward.side === "R";
  }).sort((a, b) => a.t - b.t).slice(-24);
  const fightFocus = useMemo(() => {
    const total = activeFight.deaths.reduce((point, death) => ({ x: point.x + death.x, y: point.y + death.y }), { x: 0, y: 0 });
    return gridToPercent(total.x / activeFight.deaths.length, total.y / activeFight.deaths.length);
  }, [activeFight]);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setTime((current) => {
        const next = Math.min(MATCH.duration, current + 5);
        setSelectedStage(stageAtTime(next));
        if (next >= MATCH.duration) setPlaying(false);
        return next;
      });
    }, 300);
    return () => window.clearInterval(timer);
  }, [playing]);

  const chooseStage = (key: StageKey) => {
    const next = STAGES.find((item) => item.key === key)!;
    setSelectedStage(key);
    setTrainingStage(key);
    setTime(next.focusTime);
    setPlaying(false);
  };

  const seek = (next: number) => {
    setTime(next);
    setSelectedStage(stageAtTime(next));
  };

  const openTrainingMoment = (moment: number) => {
    seek(moment);
    window.requestAnimationFrame(() => document.getElementById("analysis")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const sendQuestion = (value = chatText) => {
    if (!value.trim()) return;
    const question = value.toLowerCase();
    if (question.includes("43") || question.includes("просел")) {
      setCoachReply("Roshan не был ошибкой. На 42:30 Shadow Fiend снял Aegis и убил Ogre. Вместо полного отхода Radiant на 43:06 принял бой 3×4 без Juggernaut и Ogre: 0–3, −6 586 золота за окно и buyback Windranger. Именно отсюда начался обвал.");
    } else if (question.includes("вижен") || question.includes("вард")) {
      setCoachReply("Количество вардов было почти равным: 20/37 у Radiant против 21/36 у Dire. Решающая драка 43:06 произошла рядом с Observer и Sentry Radiant, поэтому проблема была не в отсутствии обзора, а в решении принять бой неполным составом.");
    } else if (question.includes("10k") || question.includes("−10") || question.includes("-10")) {
      setCoachReply("При отставании около 10k не ищите равный 5×5. Покажите две линии, заставьте соперника разделиться, проверьте ключевые способности и входите только с численным перевесом. В этом матче Radiant именно так создал 5×3 и правильно забрал Roshan на 38:46.");
    } else if (selectedHero) {
      setCoachReply(`${selectedHero.name}, ${stage.label.toLowerCase()}: ${AXIS_COPY[selectedStage][selectedAxis]} Основание — parsed-события матча; точные перемещения появятся после импорта полного .dem.`);
    } else {
      setCoachReply(`Командный вывод, ${stage.label.toLowerCase()}: ${AXIS_COPY[selectedStage][selectedAxis]} Чтобы перейти от команды к вашим личным решениям, выберите своего героя.`);
    }
    setChatText("");
  };

  return (
    <main className="narma-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NARMA VISION — наверх">
          <span className="brand-mark"><Swords size={16} /></span>
          <span><b>NARMA</b> VISION</span>
          <small>AI-ТРЕНЕР ДЛЯ DOTA 2</small>
        </a>
        <nav aria-label="Основная навигация">
          <a className="active" href="#analysis">Анализ матча</a>
          <a href="#timeline">Хронология</a>
          <a href="#progress">План тренировки</a>
          <a href="#coach">AI-тренер</a>
          <a href="#pricing">Тарифы</a>
        </nav>
        <div className="topbar-actions">
          <AccountControl viewer={viewer} signInHref={signInHref} signOutHref={signOutHref} />
          <button className="new-analysis" onClick={() => setMatchPanel(true)}><span>+</span> Новый анализ</button>
        </div>
        <button className="icon-button menu-button" aria-label={mobileMenu ? "Закрыть меню" : "Открыть меню"} aria-expanded={mobileMenu} onClick={() => setMobileMenu((current) => !current)}><Menu size={20} /></button>
        {mobileMenu && <div className="mobile-nav">
          <a href="#analysis" onClick={() => setMobileMenu(false)}>Анализ матча</a>
          <a href="#timeline" onClick={() => setMobileMenu(false)}>Хронология</a>
          <a href="#progress" onClick={() => setMobileMenu(false)}>План тренировки</a>
          <a href="#coach" onClick={() => setMobileMenu(false)}>AI-тренер</a>
          <a href="#pricing" onClick={() => setMobileMenu(false)}>Тарифы и аккаунт</a>
          <button onClick={() => { setMobileMenu(false); setMatchPanel(true); }}>+ Новый анализ</button>
        </div>}
      </header>

      {matchPanel && (
        <div className="match-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setMatchPanel(false); }}>
          <form className="match-dialog surface" onSubmit={(event) => {
            event.preventDefault();
            if (matchIdDraft.trim() === String(MATCH.id)) {
              setMatchPanel(false);
              setMatchNotice("");
              window.scrollTo({ top: 0, behavior: "smooth" });
            } else {
              setMatchNotice("В этой версии собран первый эталонный матч 8963624400. Универсальный загрузчик Match ID — следующий отдельный модуль.");
            }
          }}>
            <button type="button" className="dialog-close" onClick={() => setMatchPanel(false)} aria-label="Закрыть">×</button>
            <p className="eyebrow">Новый анализ</p>
            <h2>Введите Match ID</h2>
            <p>Сейчас можно повторно открыть первый доказательный матч. Неподдержанные ID не будут подменены выдуманными данными.</p>
            <label><span>Match ID</span><input inputMode="numeric" value={matchIdDraft} onChange={(event) => { setMatchIdDraft(event.target.value.replace(/\D/g, "")); setMatchNotice(""); }} placeholder="8963624400" autoFocus /></label>
            {matchNotice && <div className="dialog-notice"><Info size={15} />{matchNotice}</div>}
            <button className="dialog-submit" type="submit">Открыть анализ <ChevronRight size={17} /></button>
          </form>
        </div>
      )}

      <div className="page" id="top">
        <section className="match-card surface">
          <div className="match-result">
            <span className="status-dot" />
            <div>
              <p>Матч {MATCH.id} · {MATCH.date} · патч {MATCH.patch}</p>
              <h1>Командный разбор <span>{selectedHero ? `· ${selectedHero.name}` : "до выбора героя"}</span></h1>
            </div>
          </div>
          <div className="scoreboard" aria-label={`Счёт ${MATCH.score.radiant}:${MATCH.score.dire}, победа Dire`}>
            <span className="radiant-score">{MATCH.score.radiant}</span>
            <small>{MATCH.durationLabel}<br />RANKED · ALL DRAFT</small>
            <span className="dire-score">{MATCH.score.dire}</span>
          </div>
          <div className="source-badge"><CheckCircle2 size={16} /> parsed v22</div>
          <div className="hero-prompt">
            <div>
              <strong>{selectedHero ? `Вы играли за ${selectedHero.name}` : "Кем вы играли?"}</strong>
              <span>{selectedHero ? `Позиция ${selectedHero.position} · ${selectedHero.lane.toLowerCase()} линия` : "Выберите героя для персональной аналитики"}</span>
            </div>
            {selectedHero && <button className="text-button" onClick={() => setSelectedHeroId(null)}>Сбросить</button>}
          </div>
          <div className="hero-grid">
            {HEROES.map((hero) => (
              <button
                key={hero.id}
                className={`hero-choice ${selectedHeroId === hero.id ? "selected" : ""}`}
                onClick={() => setSelectedHeroId(hero.id)}
                aria-pressed={selectedHeroId === hero.id}
                title={`${hero.name} — ${hero.kills}/${hero.deaths}/${hero.assists}`}
              >
                <HeroPortrait hero={hero} />
                <span>{hero.name}</span>
                <small>{hero.kills}/{hero.deaths}/{hero.assists}</small>
              </button>
            ))}
          </div>
        </section>

        <section className="stage-nav surface" aria-label="Стадии матча">
          {STAGES.map((item, index) => (
            <button key={item.key} className={item.key === selectedStage ? "active" : ""} onClick={() => chooseStage(item.key)}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{item.label}</strong><small>{item.interval}</small></div>
            </button>
          ))}
        </section>

        <section className="stage-intro" id="analysis">
          <div>
            <p className="eyebrow">{stage.label} · {stage.interval}</p>
            <h2>{stage.verdict}</h2>
            <p>{stage.explanation}</p>
          </div>
          <div className="stage-kpis">
            <div><small>Золото к {formatTime(time)}</small><strong className={GOLD_ADV[minute] >= 0 ? "radiant-text" : "dire-text"}>{sideLead(GOLD_ADV[minute])}</strong></div>
            <div><small>Опыт к {formatTime(time)}</small><strong className={XP_ADV[minute] >= 0 ? "radiant-text" : "dire-text"}>{sideLead(XP_ADV[minute])}</strong></div>
            <div><small>Достоверность</small><strong>Высокая</strong></div>
          </div>
        </section>

        <section className="analysis-grid">
          <article className="map-card surface">
            <div className="section-head map-head">
              <div><p className="eyebrow">Интерактивная карта · {formatTime(time)}</p><h3>Карта решений</h3></div>
              <div className="mode-switch" aria-label="Режим карты">
                {(["coach", "vision", "full"] as MapMode[]).map((mode) => (
                  <button key={mode} className={mapMode === mode ? "active" : ""} onClick={() => setMapMode(mode)}>
                    {mode === "coach" ? "Фокус тренера" : mode === "vision" ? `Вижен ${selectedHero?.side === "D" ? "Dire" : "Radiant"}` : "Все данные"}
                  </button>
                ))}
              </div>
            </div>

            <div className="map-layout">
              <div className="map-stage">
                {mapReady ? (
                  <img className="game-map" src="/generated/dota/7.41/minimap.png" alt="Карта Dota 2 версии 7.41, извлечённая из игровых материалов" onError={() => setMapReady(false)} />
                ) : (
                  <div className="map-missing"><AlertTriangle /><strong>Игровая карта не импортирована</strong><span>Поместите экспорт клиента в public/generated/dota/7.41/minimap.png</span></div>
                )}
                <div className="map-vignette" />

                {layers.structures && MAP_OBJECTS.filter((item) => item.layer === "structures").map((item, index) => {
                  const pos = worldToPercent(item.x, item.y);
                  return <span key={`s${index}`} className={`map-object ${item.kind}`} style={{ left: `${pos.left}%`, top: `${pos.top}%` }} title={item.label}>{MAP_LABELS[item.kind]}</span>;
                })}
                {layers.objectives && MAP_OBJECTS.filter((item) => item.layer === "objectives").map((item, index) => {
                  const pos = worldToPercent(item.x, item.y);
                  return <span key={`o${index}`} className={`map-object ${item.kind}`} style={{ left: `${pos.left}%`, top: `${pos.top}%` }} title={item.label}>{MAP_LABELS[item.kind]}</span>;
                })}
                {layers.camps && MAP_OBJECTS.filter((item) => item.layer === "camps").map((item, index) => {
                  const pos = worldToPercent(item.x, item.y);
                  return <span key={`c${index}`} className="map-object camp" style={{ left: `${pos.left}%`, top: `${pos.top}%` }} title={item.label}>•</span>;
                })}
                {layers.vision && recentWards.map((ward, index) => {
                  const pos = gridToPercent(ward.x, ward.y);
                  return <span key={`${ward.t}-${index}`} className={`ward-marker ${ward.type} ${ward.side === "R" ? "radiant" : "dire"}`} style={{ left: `${pos.left}%`, top: `${pos.top}%` }} title={`${ward.type === "obs" ? "Observer" : "Sentry"} ${ward.side === "R" ? "Radiant" : "Dire"}, установлен ${formatTime(ward.t)}`}>{ward.type === "obs" ? "●" : "◇"}</span>;
                })}
                {layers.heroes && activeFight.deaths.map((death, index) => {
                  const hero = HEROES.find((item) => item.id === death.heroId)!;
                  const pos = gridToPercent(death.x, death.y);
                  return <span key={`${activeFight.start}-${death.heroId}-${index}`} className="death-marker" style={{ left: `${pos.left}%`, top: `${pos.top}%` }} title={`${hero.name}: подтверждённая позиция смерти в драке ${formatTime(activeFight.start)}`}><HeroPortrait hero={hero} small /><i>×</i></span>;
                })}
                {layers.creeps && <LaneCreeps time={time} />}

                <div className="coach-pin" style={{ left: `${fightFocus.left}%`, top: `${fightFocus.top}%` }}>
                  <BrainCircuit size={15} /><span>{selectedStage === "late" ? "43:06 · не принимать бой 3×4" : selectedStage === "mid" ? "Драка · проверить Black Hole" : "Локальный итог не равен выигранной карте"}</span>
                </div>
                <div className="map-roster" aria-label="Состав матча; непрерывные позиции героев требуют полного replay">
                  <span>Состав</span>
                  {HEROES.map((hero) => <button key={hero.id} onClick={() => setSelectedHeroId(hero.id)} title={`${hero.name}: выбрать перспективу`}><HeroPortrait hero={hero} small /></button>)}
                </div>
              </div>

              <aside className="map-controls">
                <div className="control-title"><Layers3 size={16} /> Слои</div>
                {LAYERS.map((layer) => (
                  <label key={layer.key} className="layer-toggle">
                    <input type="checkbox" checked={layers[layer.key]} onChange={() => setLayers((current) => ({ ...current, [layer.key]: !current[layer.key] }))} />
                    <span>{layer.label}</span>
                  </label>
                ))}
                <div className="map-data-note"><Database size={15} /><span><b>Факт:</b> объекты, строения, точки вардов и места смертей.<br /><b>Модель:</b> положение волн крипов.</span></div>
              </aside>
            </div>

            <div className="playback">
              <button className="play-button" onClick={() => setPlaying((current) => !current)} aria-label={playing ? "Пауза" : "Воспроизвести"}>{playing ? <Pause size={17} /> : <Play size={17} />}</button>
              <button className="reset-button" onClick={() => seek(stage.focusTime)} aria-label="Вернуться к фокусу стадии"><RotateCcw size={16} /></button>
              <span>{formatTime(time)}</span>
              <input type="range" min="0" max={MATCH.duration} value={time} onChange={(event) => seek(Number(event.target.value))} aria-label="Время матча" style={{ "--progress": `${time / MATCH.duration * 100}%` } as React.CSSProperties} />
              <span>{MATCH.durationLabel}</span>
            </div>

            <div className="map-legend">
              <span><i className="legend-object roshan">R</i>Roshan</span><span><i className="legend-object tormentor">T</i>Tormentor</span><span><i className="legend-object wisdom">W</i>Wisdom</span><span><i className="legend-object lotus">L</i>Lotus</span><span><i className="legend-object gate">G</i>Twin Gate</span><span><i className="legend-object watcher">◉</i>Watcher</span><span><i className="legend-object camp">•</i>Лагерь</span>
            </div>
          </article>

          <aside className="insight-stack">
            <article className="coach-card surface">
              <div className="section-head"><div><p className="eyebrow">Вердикт AI-тренера</p><h3>{selectedHero ? selectedHero.name : "Командный обзор"}</h3></div><span className="confidence"><CheckCircle2 size={14} /> факт</span></div>
              <p className="coach-verdict">{AXIS_COPY[selectedStage][selectedAxis]}</p>
              {selectedHero && <div className="hero-stats" aria-label={`Итоговые показатели ${selectedHero.name}`}>
                <div><small>K / D / A</small><strong>{selectedHero.kills} / {selectedHero.deaths} / {selectedHero.assists}</strong></div>
                <div><small>GPM / XPM</small><strong>{selectedHero.gpm} / {selectedHero.xpm}</strong></div>
                <div><small>Net worth</small><strong>{selectedHero.networth.toLocaleString("ru-RU")}</strong></div>
                <div><small>Obs / Sentry</small><strong>{selectedHero.wards} / {selectedHero.sentries}</strong></div>
              </div>}
              <div className="evidence-list">
                {stage.evidence.map((item) => <div key={item}><CheckCircle2 size={15} /><span>{item}</span></div>)}
              </div>
              {!selectedHero && <button className="select-hint" onClick={() => document.querySelector(".hero-grid")?.scrollIntoView({ behavior: "smooth" })}><Users size={17} /> Выбрать своего героя <ChevronRight size={17} /></button>}
            </article>

            <article className="balance-card surface">
              <div className="section-head"><div><p className="eyebrow">Баланс сил</p><h3>Драка {formatTime(activeFight.start)}–{formatTime(activeFight.end)}</h3></div><Swords size={20} /></div>
              <div className="global-lead">
                <div><span>Золото до окна · вся команда</span><strong className={GOLD_ADV[Math.min(47, Math.floor(activeFight.start / 60))] >= 0 ? "radiant-text" : "dire-text"}>{sideLead(GOLD_ADV[Math.min(47, Math.floor(activeFight.start / 60))])}</strong></div>
                <div><span>Опыт до окна · вся команда</span><strong className={XP_ADV[Math.min(47, Math.floor(activeFight.start / 60))] >= 0 ? "radiant-text" : "dire-text"}>{sideLead(XP_ADV[Math.min(47, Math.floor(activeFight.start / 60))])}</strong></div>
              </div>
              <div className="versus-grid">
                <div><small>Radiant</small><strong>{activeFight.radiant.kills}–{activeFight.radiant.deaths}</strong><span>{signed(activeFight.radiant.gold)} золота</span><span>{signed(activeFight.radiant.xp)} XP</span></div>
                <b>VS</b>
                <div><small>Dire</small><strong>{activeFight.dire.kills}–{activeFight.dire.deaths}</strong><span>{signed(activeFight.dire.gold)} золота</span><span>{signed(activeFight.dire.xp)} XP</span></div>
              </div>
              <p className="fine-print"><Info size={14} /> «До окна» — общий перевес команды. Золото и XP ниже — полученные внутри зафиксированного окна. Локальный состав рядом с дракой появится из полного replay.</p>
            </article>

            <article className="axis-card surface">
              <p className="eyebrow">Пять осей анализа</p>
              <div className="axis-list">
                {AXES.map((axis) => {
                  const Icon = ICONS[axis.key];
                  return <button key={axis.key} className={selectedAxis === axis.key ? "active" : ""} onClick={() => setSelectedAxis(axis.key)}><Icon size={18} /><span><strong>{axis.label}</strong><small>{axis.short}</small></span><ChevronRight size={16} /></button>;
                })}
              </div>
            </article>
          </aside>
        </section>

        <section className="timeline-section surface" id="timeline">
          <div className="section-head"><div><p className="eyebrow">Не три момента, а весь матч</p><h3>Хронология объектов и переломов</h3></div><span className="data-note">нажмите событие → карта синхронизируется</span></div>
          <div className="event-track">
            {EVENTS.map((event) => (
              <button key={`${event.t}-${event.title}`} className={Math.abs(time - event.t) < 30 ? "active" : ""} onClick={() => seek(event.t)}>
                <time>{formatTime(event.t)}</time>
                <i className={event.type} />
                <strong>{event.title}</strong>
                <span>{event.detail}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="charts-grid">
          <article className="chart-card surface">
            <div className="section-head"><div><p className="eyebrow">Экономика и темп</p><h3>Преимущество золота и опыта</h3></div><span className="confidence"><Database size={14} /> 48 срезов</span></div>
            <ResourceChart time={time} />
          </article>

          <article className="fight-impact-card surface">
            <div className="section-head"><div><p className="eyebrow">15 командных драк</p><h3>Кто забирал золото в окне</h3></div><Swords size={19} /></div>
            <FightImpactChart active={activeFight} onSelect={seek} />
            <div className="fight-callout">
              <span>Выбрано · {formatTime(activeFight.start)}</span>
              <strong>{activeFight.radiant.gold - activeFight.dire.gold >= 0 ? "Radiant" : "Dire"} +{Math.abs(activeFight.radiant.gold - activeFight.dire.gold).toLocaleString("ru-RU")}</strong>
              <small>золота за окно, не запас до драки</small>
            </div>
            <div className="vision-summary">
              <div><Eye size={16} /><span>Observer</span><b>Radiant 20</b><b>Dire 21</b></div>
              <div><Shield size={16} /><span>Sentry</span><b>Radiant 37</b><b>Dire 36</b></div>
            </div>
          </article>
        </section>

        <section className="progress-section" id="progress">
          <div className="section-head training-title">
            <div><p className="eyebrow">Перенос в следующую игру</p><h2>План тренировки по четырём стадиям</h2></div>
            <div
              className="training-progress"
              role="progressbar"
              aria-label="Прогресс плана тренировки"
              aria-valuemin={0}
              aria-valuemax={totalDrills}
              aria-valuenow={completedCount}
              aria-valuetext={`Выполнено ${completedCount} из ${totalDrills} упражнений`}
            >
              <span><b>{completedCount}</b> / {totalDrills}</span>
              <i><em style={{ width: `${completedCount / totalDrills * 100}%` }} /></i>
              <small>упражнений выполнено</small>
            </div>
          </div>

          <div className="training-stage-tabs" role="group" aria-label="Стадия для плана тренировки">
            {STAGES.map((item, index) => (
              <button
                key={item.key}
                aria-pressed={trainingStage === item.key}
                className={trainingStage === item.key ? "active" : ""}
                onClick={() => setTrainingStage(item.key)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{item.label}</strong>
                <small>{item.interval}</small>
              </button>
            ))}
          </div>

          <div className="training-summary surface">
            <div>
              <p className="eyebrow">Цель стадии</p>
              <h3>{training.goal}</h3>
            </div>
            <div>
              <p className="eyebrow">Что должно измениться</p>
              <p>{training.result}</p>
              <span>{selectedHero
                ? selectedHero.side === "R"
                  ? `Персональный фокус: ${selectedHero.name}, позиция ${selectedHero.position}`
                  : `${selectedHero.name} играл за Dire: ниже показано, какие ошибки соперника помогли вашей команде победить.`
                : "Командный план Radiant. Выберите своего героя наверху — добавим правильную перспективу игрока."}</span>
            </div>
          </div>

          <div className="drill-grid">
            {training.drills.map((drill, index) => {
              const done = Boolean(completedDrills[drill.id]);
              return (
                <article key={drill.id} className={`training-drill surface ${done ? "done" : ""}`}>
                  <div className="drill-head">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div><small>{drill.axis}</small><h3>{drill.title}</h3></div>
                    <button
                      className="drill-check"
                      aria-pressed={done}
                      onClick={() => setCompletedDrills((current) => ({ ...current, [drill.id]: !done }))}
                    >
                      <CheckCircle2 size={17} /> {done ? "Выполнено" : "Отметить"}
                    </button>
                  </div>

                  <div className="drill-context">
                    <div><strong>Почему это важно</strong><p>{drill.why}</p></div>
                    <div><strong>Основание из матча</strong><p>{drill.evidence}</p></div>
                  </div>

                  <div className="drill-steps">
                    <strong>Как тренировать</strong>
                    <ol>{drill.steps.map((step) => <li key={step}>{step}</li>)}</ol>
                  </div>

                  <div className="drill-footer">
                    <div><small>Проверка результата</small><strong>{drill.metric}</strong></div>
                    <div><small>Объём</small><strong>{drill.dose}</strong></div>
                    <button onClick={() => openTrainingMoment(drill.moment)}>Показать момент {formatTime(drill.moment)} <ChevronRight size={16} /></button>
                  </div>
                </article>
              );
            })}
          </div>

          <div className="section-head compact-head"><div><p className="eyebrow">Быстрая памятка</p><h3>Три обязательных правила из этого матча</h3></div></div>
          <div className="action-grid">
            <article className="surface"><span>01</span><Route /><h3>Перед контактом</h3><p>Сверьте общий перевес золота/XP, число видимых героев и готовность ключевых предметов.</p><small>Критерий: назвать причину входа до нажатия smoke</small></article>
            <article className="surface"><span>02</span><Eye /><h3>Связать обзор с целью</h3><p>Вард должен отвечать на вопрос: кто входит, откуда и какой объект команда забирает дальше.</p><small>Критерий: объект не дальше 60 секунд от постановки</small></article>
            <article className="surface"><span>03</span><Gem /><h3>Сброс после Aegis</h3><p>Если Aegis уже снят, не продолжайте бой по инерции. Отойдите и дождитесь полного состава до следующего входа.</p><small>Критерий: никаких новых контактов, пока живы не все пять</small></article>
          </div>
        </section>

        <PricingSection
          isAuthenticated={Boolean(viewer)}
          signInHref={signInHref}
          onStartTrial={() => setMatchPanel(true)}
        />

        <section className="coach-chat surface" id="coach">
          <div className="coach-avatar"><BrainCircuit /></div>
          <div className="chat-copy"><p className="eyebrow">AI-тренер по этому матчу</p><h2>Спросите «почему», а не получите лозунг</h2><p>{coachReply}</p></div>
          <div className="quick-prompts">
            {["Почему просели после 43:00?", "Где не хватило вижена?", "Что делать при −10k?"].map((prompt) => <button key={prompt} onClick={() => sendQuestion(prompt)}>{prompt}</button>)}
          </div>
          <div className="chat-input">
            <MessageCircle size={19} />
            <input value={chatText} onChange={(event) => setChatText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") sendQuestion(); }} placeholder="Задайте вопрос по матчу…" aria-label="Вопрос AI-тренеру" />
            <button onClick={() => sendQuestion()} aria-label="Отправить вопрос"><Send size={18} /></button>
          </div>
        </section>

        <footer>
          <span><Sparkles size={15} /> NARMA VISION · первый доказательный матч</span>
          <span>OpenDota parsed data · координаты карты 7.41 · без выдуманной точности</span>
        </footer>
      </div>
    </main>
  );
}
