"use client";

import {
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
  Pause,
  Play,
  RotateCcw,
  Route,
  Sparkles,
  Swords,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useTrainingProgress } from "@/components/narma/use-training-progress";
import MatchEconomyTimeline from "@/components/narma/match-economy-timeline";
import ReplayMapView from "@/components/narma/replay-map";
import { DEMO_REPLAY_MAP } from "@/lib/replay/demo-map";
import AccountControl, { type ViewerSummary } from "@/components/narma/account-control";
import NarmaScanFlow from "@/components/narma/narma-scan-flow";
import { setEstimatedMapData, useEstimatedMapData } from "@/components/narma/use-estimated-map-data";
import { useModalDialog } from "@/components/narma/use-modal-dialog";

import {
  AXES,
  AXIS_COPY,
  EVENTS,
  FIGHTS,
  GOLD_ADV,
  HEROES,
  MATCH,
  STAGES,
  XP_ADV,
  formatTime,
  type AxisKey,
  type StageKey,
} from "@/app/data/match-8963624400";

import { TRAINING_PLAN } from "@/app/data/training-plan";
export { TRAINING_PLAN } from "@/app/data/training-plan";

type LayerKey = "heroes" | "vision" | "structures" | "objectives" | "camps" | "creeps";
type MapMode = "coach" | "vision" | "full";

const LAYERS: Array<{ key: LayerKey; label: string }> = [
  { key: "vision", label: "Варды" },
  { key: "structures", label: "Постройки" },
  { key: "camps", label: "Лесные лагеря" },
];

const ICONS: Record<AxisKey, typeof Route> = {
  movement: Route,
  vision: Eye,
  resources: Coins,
  macro: Flag,
  micro: Crosshair,
};

function stageAtTime(time: number): StageKey {
  if (time <= 0) return "draft";
  if (time <= 720) return "laning";
  if (time <= 1800) return "mid";
  return "late";
}

function sideLead(value: number) {
  if (value === 0) return "Равенство";
  return `${value > 0 ? "Radiant" : "Dire"} +${Math.abs(value).toLocaleString("ru-RU")}`;
}

export function resourceMinuteAt(time: number) {
  return Math.min(47, Math.max(0, Math.floor(time / 60)));
}

const DEMO_ECONOMY=GOLD_ADV.map((gold,i)=>({timeSeconds:i*60,radiantGoldAdvantage:gold,radiantXpAdvantage:XP_ADV[i]??null}));
const DEMO_FIGHTS=FIGHTS.map((fight,index)=>({id:`fight.${String(index).padStart(4,"0")}`,startSeconds:fight.start,endSeconds:fight.end,
  radiant:{...fight.radiant,goldDelta:fight.radiant.gold,xpDelta:fight.radiant.xp},
  dire:{...fight.dire,goldDelta:fight.dire.gold,xpDelta:fight.dire.xp},
}));

type NarmaAnalysisProps = {
  viewer: ViewerSummary | null;
  signInHref: string;
  signOutHref: string;
  scanEnabled?: boolean;
};

export default function NarmaAnalysis({
  viewer,
  signInHref,
  signOutHref,
  scanEnabled = false,
}: NarmaAnalysisProps) {
  const [selectedStage, setSelectedStage] = useState<StageKey>("laning");
  const [selectedAxis, setSelectedAxis] = useState<AxisKey>("resources");
  const selectedHeroId = HEROES.find(hero=>hero.name === "Juggernaut")?.id ?? HEROES[0].id;
  const [time, setTime] = useState(461);
  const [playing, setPlaying] = useState(false);
  const [mapMode, setMapMode] = useState<MapMode>("coach");
  const [mobileMenu, setMobileMenu] = useState(false);
  const [matchPanel, setMatchPanel] = useState(false);
  const [matchIdDraft, setMatchIdDraft] = useState("");
  const [matchNotice, setMatchNotice] = useState("");
  const [trainingStage, setTrainingStage] = useState<StageKey>("laning");
  const trainingProgress = useTrainingProgress("demo:8963624400",!!viewer);
  const completedDrills = trainingProgress.completed;
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    heroes: true,
    vision: true,
    structures: true,
    objectives: true,
    camps: true,
    creeps: false,
  });
  const showEstimatedMapData = useEstimatedMapData();

  const matchDialogRef = useRef<HTMLDivElement>(null);
  const matchReturnFocusRef = useRef<HTMLElement | null>(null);

  const openMatchDialog = useCallback(() => {
    matchReturnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    setMatchPanel(true);
  }, []);
  const closeMatchDialog = useCallback(() => setMatchPanel(false), []);

  useModalDialog(matchPanel, matchDialogRef, matchReturnFocusRef, closeMatchDialog);

  const stage = STAGES.find((item) => item.key === selectedStage) ?? STAGES[1];
  const training = TRAINING_PLAN[trainingStage];
  const currentTimelineEvent = useMemo(() => {
    const closest = EVENTS.reduce((best, event) => (
      Math.abs(time - event.t) < Math.abs(time - best.t) ? event : best
    ));
    return Math.abs(time - closest.t) < 30 ? closest : null;
  }, [time]);
  const completedCount = Object.values(completedDrills).filter(Boolean).length;
  const totalDrills = Object.values(TRAINING_PLAN).reduce((sum, item) => sum + item.drills.length, 0);
  const selectedHero = HEROES.find((hero) => hero.id === selectedHeroId) ?? null;
  const minute = resourceMinuteAt(time);
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
    setPlaying(false);
    setTime(next);
    setSelectedStage(stageAtTime(next));
  };

  const openTrainingMoment = (moment: number) => {
    seek(moment);
    window.requestAnimationFrame(() => document.getElementById("analysis")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const toggleLayer = (key: LayerKey) => {
    if (key === "creeps") {
      setEstimatedMapData(!showEstimatedMapData);
      return;
    }
    setLayers((current) => {
      const next = !current[key];
      return { ...current, [key]: next };
    });
  };


  return (
    <main className="narma-shell" id="main-content" tabIndex={-1}>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="NARMA VISION — наверх">
          <span className="brand-mark"><Swords size={16} /></span>
          <span><b>NARMA</b> VISION</span>
          <small>РАЗБОР МАТЧА</small>
        </a>
        <nav aria-label="Основная навигация">
          <a href="#analysis">Карта</a>
          <a href="#timeline">События</a>
          <a href="#progress">Тренировка</a>
          <a href="#coach">Тренер</a>
          <Link href="/pricing">Тарифы</Link>
        </nav>
        <div className="topbar-actions">
          <AccountControl viewer={viewer} signInHref={signInHref} signOutHref={signOutHref} />
          <button type="button" className="new-analysis" onClick={openMatchDialog}><span aria-hidden="true">+</span> Новый анализ</button>
        </div>
        <button type="button" className="icon-button menu-button" aria-label={mobileMenu ? "Закрыть меню" : "Открыть меню"} aria-expanded={mobileMenu} aria-controls="mobile-navigation" onClick={() => setMobileMenu((current) => !current)}><Menu size={20} /></button>
        {mobileMenu && <nav className="mobile-nav" id="mobile-navigation" aria-label="Мобильная навигация">
          <a href="#analysis" onClick={() => setMobileMenu(false)}>Карта</a>
          <a href="#timeline" onClick={() => setMobileMenu(false)}>События</a>
          <a href="#progress" onClick={() => setMobileMenu(false)}>Тренировка</a>
          <a href="#coach" onClick={() => setMobileMenu(false)}>Тренер</a>
          <Link href="/pricing" onClick={() => setMobileMenu(false)}>Тарифы</Link>
          {viewer
            ? <><Link href="/replays">Загрузить .dem</Link><Link href="/account" onClick={() => setMobileMenu(false)}>Аккаунт и настройки</Link></>
            : <a href={signInHref} target="_top" onClick={() => setMobileMenu(false)}>Войти</a>}
          <button type="button" onClick={() => { setMobileMenu(false); openMatchDialog(); }}>+ Новый анализ</button>
        </nav>}
      </header>

      {matchPanel && (
        <div className="match-modal" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) closeMatchDialog(); }}>
          <div
            className="match-dialog surface"
            ref={matchDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="match-dialog-title"
            aria-describedby="match-dialog-description"
            tabIndex={-1}
          >
            <button type="button" className="dialog-close" onClick={closeMatchDialog} aria-label="Закрыть окно нового анализа">×</button>
            {scanEnabled ? (
              <NarmaScanFlow />
            ) : (
              <form
                noValidate
                onSubmit={(event) => {
                  event.preventDefault();
                  const normalizedMatchId = matchIdDraft.trim();
                  if (!/^\d{8,12}$/.test(normalizedMatchId)) {
                    setMatchNotice("Match ID должен содержать от 8 до 12 цифр.");
                  } else if (normalizedMatchId === String(MATCH.id)) {
                    closeMatchDialog();
                    setMatchNotice("");
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  } else {
                    setMatchNotice("Этот Match ID пока не поддерживается. Доступен матч 8963624400.");
                  }
                }}
              >
                <p className="eyebrow">Новый анализ</p>
                <h2 id="match-dialog-title">Введите Match ID</h2>
                <p id="match-dialog-description">Здесь открыт подготовленный пример. Свой ник и Match ID можно указать в разделе «Мои разборы».</p>
                <p className="field-help" id="match-id-help">Доступный Match ID: 8963624400. Формат — от 8 до 12 цифр.</p>
                <label htmlFor="match-id"><span>Match ID</span></label>
                <input
                  id="match-id"
                  name="matchId"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={12}
                  required
                  data-dialog-initial-focus
                  value={matchIdDraft}
                  aria-invalid={Boolean(matchNotice)}
                  aria-describedby={matchNotice ? "match-id-help match-id-error" : "match-id-help"}
                  onChange={(event) => { setMatchIdDraft(event.target.value.replace(/\D/g, "").slice(0, 12)); setMatchNotice(""); }}
                  placeholder="8963624400"
                />
                {matchNotice && <div className="dialog-notice" id="match-id-error" role="alert"><Info size={15} aria-hidden="true" />{matchNotice}</div>}
                <button className="dialog-submit" type="submit">Открыть пример <ChevronRight size={17} /></button>
                <Link className="price-button secondary" href="/analyses">Мой ник и мои матчи</Link>
              </form>
            )}
          </div>
        </div>
      )}

      <div className="page" id="top">
        <section className="match-card surface">
          <div className="match-result">
            <span className="status-dot" />
            <div>
              <p>Матч {MATCH.id} · {MATCH.date} · патч {MATCH.patch}</p>
              <h1>Разбор матча <span>{selectedHero ? `· ${selectedHero.name}` : "· командный"}</span></h1>
            </div>
          </div>
          <div className="scoreboard" aria-label={`Счёт ${MATCH.score.radiant}:${MATCH.score.dire}, победа Dire`}>
            <span className="radiant-score">{MATCH.score.radiant}</span>
            <small>{MATCH.durationLabel}<br />RANKED · ALL DRAFT</small>
            <span className="dire-score">{MATCH.score.dire}</span>
          </div>
          <div className="source-badge"><Database size={16} /> OpenDota</div>
          <div className="hero-prompt">
            <div><strong>Пример разбора · {selectedHero?.name}</strong><span>Это подготовленный пример. Свои матчи разбирайте по закреплённому нику.</span></div>
            <Link className="price-button secondary" href="/analyses">Указать мой ник</Link>
          </div>
        </section>

        <section className="stage-nav surface" aria-label="Стадии матча">
          {STAGES.map((item, index) => (
            <button type="button" key={item.key} className={item.key === selectedStage ? "active" : ""} aria-pressed={item.key === selectedStage} onClick={() => chooseStage(item.key)}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{item.label}</strong><small>{item.interval}</small></div>
            </button>
          ))}
        </section>

        <section className="data-scope surface" aria-label="Какие данные есть в разборе">
          <Database size={19} aria-hidden="true" />
          <p><strong>Данные матча:</strong> экономика, объекты и места смертей из OpenDota.</p>
          <p><strong>Без replay .dem не видно:</strong> точные маршруты, нажатия, камеру и намерение игрока.</p>
        </section>

        <section className="stage-intro" id="analysis">
          <div>
            <p className="eyebrow">{stage.label} · {stage.interval}</p>
            <h2>{stage.verdict}</h2>
            <p>{stage.explanation}</p>
          </div>
          <div className="stage-kpis" aria-label={`Срез ресурсов на ${formatTime(minute * 60)}`}>
            <div className="gold"><small><i aria-hidden="true" />Gold · срез {formatTime(minute * 60)}</small><strong>{sideLead(GOLD_ADV[minute])}</strong></div>
            <div className="xp"><small><i aria-hidden="true" />XP · срез {formatTime(minute * 60)}</small><strong>{sideLead(XP_ADV[minute])}</strong></div>
          </div>
        </section>

        <section className="analysis-grid">
          <article className="map-card surface">
            <div className="section-head map-head">
              <div><p className="eyebrow">Карта · {formatTime(time)}</p><h3>Что происходило на карте</h3></div>
              <div className="mode-switch" aria-label="Режим карты">
                {(["coach", "vision", "full"] as MapMode[]).map((mode) => (
                  <button type="button" key={mode} className={mapMode === mode ? "active" : ""} aria-pressed={mapMode === mode} onClick={() => setMapMode(mode)}>
                    {mode === "coach" ? "Фокус тренера" : mode === "vision" ? `Варды ${selectedHero?.side === "D" ? "Dire" : "Radiant"}` : "Все данные"}
                  </button>
                ))}
              </div>
            </div>

            <div className="map-layout">
              <ReplayMapView data={DEMO_REPLAY_MAP} time={time} perspective={mapMode === "vision" ? (selectedHero?.side === "D" ? "dire" : "radiant") : "all"} structures={layers.structures} wards={layers.vision} camps={layers.camps} />

              <aside className="map-controls">
                <div className="control-title"><Layers3 size={16} /> Слои</div>
                {LAYERS.map((layer) => (
                  <label key={layer.key} className="layer-toggle">
                    <input type="checkbox" checked={layer.key === "creeps" ? showEstimatedMapData : layers[layer.key]} onChange={() => toggleLayer(layer.key)} />
                    <span>{layer.label}</span>
                  </label>
                ))}
                <div className="map-data-note"><Database size={15} /><span><b>Из матча:</b> подтверждённые разрушения.<br /><b>Варды скрыты:</b> в примере нет времени их снятия.</span></div>
              </aside>
            </div>

            <div className="playback">
              <button type="button" className="play-button" onClick={() => setPlaying((current) => !current)} aria-label={playing ? "Пауза" : "Воспроизвести"} aria-pressed={playing}>{playing ? <Pause size={17} /> : <Play size={17} />}</button>
              <button type="button" className="reset-button" onClick={() => seek(stage.focusTime)} aria-label="Вернуться к фокусу стадии"><RotateCcw size={16} /></button>
              <span>{formatTime(time)}</span>
              <input type="range" min="0" max={MATCH.duration} value={time} onChange={(event) => seek(Number(event.target.value))} aria-label="Время матча" style={{ "--progress": `${time / MATCH.duration * 100}%` } as React.CSSProperties} />
              <span>{MATCH.durationLabel}</span>
            </div>


          </article>

          <aside className="insight-stack">
            <article className="coach-card surface">
              <div className="section-head"><div><p className="eyebrow">Главный вывод</p><h3>{selectedHero ? selectedHero.name : "Командный обзор"}</h3></div><span className="confidence"><Sparkles size={14} /> интерпретация</span></div>
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
            </article>

            <article className="axis-card surface">
              <p className="eyebrow">Разбор по игре</p>
              <div className="axis-list">
                {AXES.map((axis) => {
                  const Icon = ICONS[axis.key];
                  return <button type="button" key={axis.key} className={selectedAxis === axis.key ? "active" : ""} aria-pressed={selectedAxis === axis.key} onClick={() => setSelectedAxis(axis.key)}><Icon size={18} /><span><strong>{axis.label}</strong><small>{axis.short}</small></span><ChevronRight size={16} /></button>;
                })}
              </div>
            </article>
          </aside>
        </section>

        <section className="timeline-resources surface" id="economy">
          <div className="section-head"><div><p className="eyebrow">Gold + XP · одна шкала</p><h3>Золото и драки по времени</h3></div><span className="confidence"><Database size={14} /> OpenDota</span></div>
          <MatchEconomyTimeline samples={DEMO_ECONOMY} fights={DEMO_FIGHTS} duration={MATCH.duration} time={time} onSeek={seek}/>
        </section>

        <section className="timeline-section surface" id="timeline">
          <div className="section-head"><div><p className="eyebrow">События матча</p><h3>Башни, объекты и драки</h3></div><span className="data-note">выберите событие — карта перейдёт к нему</span></div>
          <div className="event-track">
            {EVENTS.map((event) => (
              <button type="button" key={`${event.t}-${event.title}`} className={currentTimelineEvent === event ? "active" : ""} aria-current={currentTimelineEvent === event ? "true" : undefined} onClick={() => seek(event.t)}>
                <time>{formatTime(event.t)}</time>
                <i className={event.type} />
                <strong>{event.title}</strong>
                <span>{event.detail}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="progress-section" id="progress">
          <div className="section-head training-title">
            <div><p className="eyebrow">Что потренировать</p><h2>План на следующие игры</h2></div>
            <div
              className="training-progress"
              role="progressbar"
              aria-label="Прогресс плана тренировки"
              aria-valuemin={0}
              aria-valuemax={totalDrills}
              aria-valuenow={completedCount}
              aria-valuetext={`Выполнено ${completedCount} из ${totalDrills} упражнений`}
            >
              <span><b>{completedCount}</b> / {totalDrills}</span><span className="training-save-status" role="status">{trainingProgress.status}</span>
              <i><em style={{ width: `${completedCount / totalDrills * 100}%` }} /></i>
              <small>упражнений выполнено</small>
            </div>
          </div>

          <div className="training-stage-tabs" role="group" aria-label="Стадия для плана тренировки">
            {STAGES.map((item, index) => (
              <button
                type="button"
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
                  ? `Перспектива Radiant: ${selectedHero.name}, позиция ${selectedHero.position}`
                  : `Перспектива Dire: ${selectedHero.name}. Ниже показано, какие ошибки Radiant помогли Dire победить.`
                : "Командный план Radiant. Выберите героя наверху, чтобы увидеть его перспективу."}</span>
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
                      type="button"
                      className="drill-check"
                      aria-pressed={done}
                      disabled={trainingProgress.saving}
                      onClick={() => void trainingProgress.toggle(drill.id,!done)}
                    >
                      <CheckCircle2 size={17} /> {done ? "Выполнено" : "Отметить"}
                    </button>
                  </div>

                  <div className="drill-context">
                    <div><strong>Почему это важно</strong><p>{drill.why}</p></div>
                    <div><strong>Основание из матча</strong><p>{drill.evidence}</p></div>
                  </div>

                  <div className="drill-method">
                    <div><small>Сначала ответьте</small><strong>{drill.reflectionQuestion}</strong></div>
                    <div><small>Правило решения</small><p>{drill.decisionRule}</p></div>
                  </div>

                  <div className="drill-steps">
                    <strong>Как тренировать</strong>
                    <ol>{drill.steps.map((step) => <li key={step}>{step}</li>)}</ol>
                  </div>

                  <div className="drill-footer">
                    <div><small>Проверка результата</small><strong>{drill.metric}</strong></div>
                    <div><small>Объём</small><strong>{drill.dose}</strong></div>
                    <button type="button" onClick={() => openTrainingMoment(drill.moment)}>Показать момент {formatTime(drill.moment)} <ChevronRight size={16} /></button>
                  </div>
                </article>
              );
            })}
          </div>

          <div className="section-head compact-head"><div><p className="eyebrow">Перед следующей игрой</p><h3>Как разбирать решения</h3></div></div>
          <div className="action-grid">
            <article className="surface"><span>01</span><Route /><h3>Сначала намерение</h3><p>До просмотра результата скажите, чего хотели добиться и на какой информации строили решение.</p><small>Проверка: цель и условие можно назвать одной фразой</small></article>
            <article className="surface"><span>02</span><Eye /><h3>Одна главная ошибка</h3><p>Ищите самый ранний управляемый момент, который повторяется, а не перечисляйте всё плохое в матче.</p><small>Проверка: после разбора остаётся один конкретный навык</small></article>
            <article className="surface"><span>03</span><Gem /><h3>Решение отдельно от исхода</h3><p>Сравните входные условия, альтернативу и цену риска. Победа в драке сама по себе не делает решение хорошим.</p><small>Проверка: есть правило «если — то» и способ проверить его</small></article>
          </div>
        </section>

        <section className="coach-chat surface" id="coach">
          <div className="coach-avatar"><BrainCircuit /></div>
          <div className="chat-copy"><h2>Разобрать свой матч</h2><p>Загрузите реплей или укажите Match ID. Вопросы и отметки упражнений сохранятся вместе с вашим разбором.</p><Link href="/replays">Загрузить .dem</Link> · <Link href="/analyses">Разобрать по Match ID</Link></div>
        </section>

        <footer>
          <span><Sparkles size={15} /> NARMA VISION · матч {MATCH.id}</span>
          <span>Данные: OpenDota. Для точных маршрутов и нажатий нужен replay .dem.</span>
        </footer>
      </div>
    </main>
  );
}
