"use client";

import {
  AlertTriangle,
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  Clock3,
  History,
  LoaderCircle,
  RefreshCw,
  Swords,
} from "lucide-react";
import Link from "next/link";
import PlayerIdentityPanel from "@/components/narma/player-identity-panel";
import type { PlayerTarget } from "@/lib/dota/player-identity";
import ReportFollowup from "@/components/narma/report-followup";
import MatchReplayPanel from "@/components/narma/match-replay-panel";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  AnalysisDetailSchema,
  AnalysisHistorySchema,
  PublicAnalysisJobSchema,
  type AnalysisDetail,
  type PublicAnalysisJob,
} from "@/lib/analyses/contracts";

type AnalysisWorkspaceProps = {
  initialMatchId?: string;
  initialReplayId?: string;
  acceptingJobs: boolean;
  fulfillmentReady: boolean;
};

type RequestState = "idle" | "loading" | "error";

const STATE_LABELS: Record<PublicAnalysisJob["state"], string> = {
  queued: "Ожидает запуска",
  running: "Формируется",
  ready: "Готов",
  failed: "Не завершён",
  canceled: "Отменён",
};

const REPORT_KIND_LABELS = {
  inference: "Данные матча",
  advice: "Что проверить",
} as const;

const REPORT_STAGE_LABELS = {
  draft: "Драфт",
  laning: "Линия",
  mid: "Середина игры",
  late: "Поздняя игра",
  overall: "Весь матч",
} as const;

const REPORT_CONFIDENCE_LABELS = {
  low: "Вопрос для просмотра реплея",
  medium: "Нужна проверка по реплею",
  high: "Показатели из матча",
} as const;

const METRIC_LABELS: Record<string, string> = {
  assists: "Помощи",
  deaths: "Смерти",
  denies: "Добивания своих",
  duration: "Длительность",
  gold_per_minute: "Золото в минуту",
  kills: "Убийства",
  last_hits: "Добивания",
  net_worth: "Итоговое золото",
  observer_wards: "Observer wards",
  sentry_wards: "Sentry wards",
  xp_per_minute: "Опыт в минуту",
};

const UNIT_LABELS: Record<string, string> = {
  count: "",
  damage: " урона",
  gold: " золота",
  gpm: " GPM",
  score: "",
  seconds: " сек.",
  xp: " опыта",
  xpm: " XPM",
};

function formatDate(value: string) {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("ru-RU", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

function messageFromPayload(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") return fallback;
  const error = (payload as { error?: unknown }).error;
  if (typeof error === "string") return error;
  if (!error || typeof error !== "object") return fallback;
  const message = (error as { message?: unknown }).message;
  return typeof message === "string" && message.trim() ? message : fallback;
}

function retryAfterSeconds(response: Response) {
  const value = response.headers.get("Retry-After");
  if (!value || !/^\d{1,4}$/.test(value)) return null;
  const seconds = Number(value);
  return Number.isSafeInteger(seconds) && seconds > 0
    ? Math.min(3600, seconds)
    : null;
}

function mergeJob(jobs: PublicAnalysisJob[], next: PublicAnalysisJob) {
  const without = jobs.filter((job) => job.id !== next.id);
  return [next, ...without].sort((left, right) =>
    right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id));
}

function claimRows(item: AnalysisDetail["report"] extends infer Report
  ? Report extends { items: Array<infer Item> }
    ? Item
    : never
  : never) {
  const claims = (item as unknown as {
    claims?: Array<{ evidenceId: string; metric: string; value: number; unit: string }>;
  }).claims;
  return Array.isArray(claims) ? claims : [];
}

export default function AnalysisWorkspace({
  initialMatchId = "",
  initialReplayId = "",
  acceptingJobs,
  fulfillmentReady,
}: AnalysisWorkspaceProps) {
  const [replayTime,setReplayTime] = useState(0);
  const [matchId, setMatchId] = useState(initialMatchId);
  const [target,setTarget]=useState<PlayerTarget|null>(null);
  const [bindingBusy,setBindingBusy]=useState(false);
  const [jobs, setJobs] = useState<PublicAnalysisJob[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [historyState, setHistoryState] = useState<RequestState>("loading");
  const [selected, setSelected] = useState<AnalysisDetail | null>(null);
  const [detailState, setDetailState] = useState<RequestState>("idle");
  const [createState, setCreateState] = useState<RequestState>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [cancelId, setCancelId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [retryGate, setRetryGate] = useState<{ jobId: string; until: number } | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const alive = useRef(true);

  const loadHistory = useCallback(async (cursor?: string) => {
    if (!cursor) setHistoryState("loading");
    try {
      const query = new URLSearchParams({ limit: "20" });
      if (cursor) query.set("cursor", cursor);
      const response = await fetch(`/api/analyses?${query}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(messageFromPayload(payload, "История недоступна."));
      const parsed = AnalysisHistorySchema.parse(payload);
      if (!alive.current) return;
      setJobs((current) => cursor
        ? [...current, ...parsed.jobs.filter((job) => !current.some((item) => item.id === job.id))]
        : parsed.jobs);
      setNextCursor(parsed.nextCursor);
      setHistoryState("idle");
    } catch (error) {
      if (!alive.current) return;
      setHistoryState("error");
      setNotice(error instanceof Error ? error.message : "История недоступна.");
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const timer = window.setTimeout(() => void loadHistory(), 0);
    return () => {
      window.clearTimeout(timer);
      alive.current = false;
    };
  }, [loadHistory]);

  useEffect(() => {
    if (!retryGate) return;
    const retryUntil = retryGate.until;
    const tick = () => {
      const current = Date.now();
      setClock(current);
      if (current >= retryUntil) setRetryGate(null);
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [retryGate]);

  const loadDetail = useCallback(async (id: string) => {
    setDetailState("loading");
    setNotice("");
    try {
      const response = await fetch(`/api/analyses/${id}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(messageFromPayload(payload, "Анализ недоступен."));
      const detail = AnalysisDetailSchema.parse(payload);
      if (!alive.current) return;
      setSelected(detail);
      setJobs((current) => mergeJob(current, detail.job));
      setDetailState("idle");
    } catch (error) {
      if (!alive.current) return;
      setDetailState("error");
      setNotice(error instanceof Error ? error.message : "Анализ недоступен.");
    }
  }, []);

  const runAnalysis = useCallback(async (id: string) => {
    setRunId(id);
    setNotice("");
    try {
      const response = await fetch(`/api/analyses/${id}/run`, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const retryAfter = retryAfterSeconds(response);
      if (retryAfter !== null) {
        setRetryGate({ jobId: id, until: Date.now() + retryAfter * 1000 });
      }
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(messageFromPayload(payload, "Не удалось запустить анализ."));
      if (!payload || typeof payload !== "object") throw new Error("Сервер вернул повреждённый ответ.");
      const detail = AnalysisDetailSchema.parse({
        job: (payload as { job?: unknown }).job,
        report: (payload as { report?: unknown }).report ?? null,
      });
      if (!alive.current) return;
      setSelected(detail);
      setJobs((current) => mergeJob(current, detail.job));
      const runOutcome = (payload as { runOutcome?: unknown }).runOutcome;
      if (detail.job.state === "queued") {
        setNotice(detail.job.failure?.message ?? "Задание сохранено для безопасного повторного запуска.");
      } else if (detail.job.state === "running" && runOutcome === "busy") {
        setNotice(retryAfter === null
          ? "Задание ещё выполняется. Повторите проверку немного позже."
          : `Задание ещё выполняется. Повторная проверка доступна через ${retryAfter} сек.`);
      }
    } catch (error) {
      if (!alive.current) return;
      setNotice(error instanceof Error ? error.message : "Не удалось запустить анализ.");
    } finally {
      if (alive.current) setRunId(null);
    }
  }, []);

  const createAnalysis = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedMatchId = matchId.trim();
    if(!target || target.matchId!==normalizedMatchId) {setNotice("Найдите свой профиль в этом матче.");return;}
    if (!/^\d{8,12}$/.test(normalizedMatchId)) {
      setNotice("Match ID должен содержать от восьми до двенадцати цифр.");
      return;
    }
    setCreateState("loading");
    setNotice("");
    try {
      const response = await fetch("/api/analyses", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ matchId: normalizedMatchId }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(messageFromPayload(payload, "Не удалось создать анализ."));
      if (!payload || typeof payload !== "object") throw new Error("Сервер вернул повреждённый ответ.");
      const job = PublicAnalysisJobSchema.parse((payload as { job?: unknown }).job);
      if (!alive.current) return;
      setJobs((current) => mergeJob(current, job));
      setSelected({ job, report: null });
      setMatchId("");
      if (fulfillmentReady && job.state === "queued") await runAnalysis(job.id);
      else if (!fulfillmentReady) {
        setNotice("Задание сохранено. Генерация отчёта остаётся выключенной до проверки staging.");
      }
    } catch (error) {
      if (!alive.current) return;
      setNotice(error instanceof Error ? error.message : "Не удалось создать анализ.");
      setCreateState("error");
      return;
    }
    if (alive.current) setCreateState("idle");
  };

  const cancelAnalysis = async (id: string) => {
    setCancelId(id);
    setNotice("");
    try {
      const response = await fetch(`/api/analyses/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(messageFromPayload(payload, "Не удалось отменить задание."));
      if (!payload || typeof payload !== "object") throw new Error("Сервер вернул повреждённый ответ.");
      const detail = AnalysisDetailSchema.parse({
        job: (payload as { job?: unknown }).job,
        report: (payload as { report?: unknown }).report ?? null,
      });
      if (!alive.current) return;
      setSelected(detail);
      setJobs((current) => mergeJob(current, detail.job));
      setNotice(detail.job.state === "canceled"
        ? "Задание отменено; зарезервированный разбор возвращён."
        : "Выполняющееся или завершённое задание уже нельзя отменить.");
    } catch (error) {
      if (!alive.current) return;
      setNotice(error instanceof Error ? error.message : "Не удалось отменить задание.");
    } finally {
      if (alive.current) setCancelId(null);
    }
  };

  const selectedJob = selected?.job ?? null;
  const selectedRetryGate = retryGate?.jobId === selectedJob?.id ? retryGate : null;
  const retryRemaining = selectedRetryGate
    ? Math.max(0, Math.ceil((selectedRetryGate.until - clock) / 1000))
    : 0;
  const canRun = fulfillmentReady
    && selectedJob
    && selectedJob.state === "queued"
    && selectedJob.attempt < selectedJob.maxAttempts
    && retryRemaining === 0;
  const canRecover = fulfillmentReady
    && selectedJob?.state === "running"
    && retryRemaining === 0;

  return (
    <main className="analysis-workspace" id="main-content" tabIndex={-1}>
      <header className="analysis-workspace-header">
        <Link className="brand" href="/" aria-label="NARMA VISION — на главную">
          <span className="brand-mark"><Swords size={16} /></span>
          <span><b>NARMA</b> VISION</span>
          <small>ПОЛНЫЕ РАЗБОРЫ</small>
        </Link>
        <Link className="analysis-back" href="/replays">Загрузить .dem</Link>
        <Link className="analysis-back" href="/account"><ArrowLeft size={17} /> Аккаунт</Link>
      </header>

      <div className="analysis-workspace-grid">
        <section className="analysis-create surface" aria-labelledby="create-analysis-title">
          <p className="eyebrow">Новый полный разбор</p>
          <h1 id="create-analysis-title">Мой разбор матча</h1>
          <p>Выберите матч из OpenDota или загрузите реплей. В разбор попадут показатели этого матча и эпизоды для проверки.</p>
          <form onSubmit={createAnalysis} noValidate>
            <label htmlFor="full-analysis-match-id">Match ID</label>
            <input
              id="full-analysis-match-id"
              disabled={bindingBusy}
              name="matchId"
              inputMode="numeric"
              autoComplete="off"
              maxLength={12}
              required
              value={matchId}
              aria-describedby="full-analysis-help"
              onChange={(event) => {
                setMatchId(event.target.value.replace(/\D/g, "").slice(0, 12));
                setNotice("");setTarget(null);
              }}
              placeholder="8963624400"
            />
            <small id="full-analysis-help">От восьми до двенадцати цифр из клиента Dota&nbsp;2.</small>

            <PlayerIdentityPanel matchId={matchId} initialReplayId={initialReplayId} onResolved={setTarget} onBusyChange={setBindingBusy} />

            <button type="submit" disabled={!acceptingJobs || createState === "loading" || !target || target.matchId!==matchId}>
              {createState === "loading"
                ? <><LoaderCircle className="spin" aria-hidden="true" /> Резервируем разбор…</>
                : <>Создать задание <ChevronRight aria-hidden="true" /></>}
            </button>
          </form>
          {!acceptingJobs && (
            <div className="analysis-gate-note"><AlertTriangle aria-hidden="true" /> Новые разборы пока недоступны. Сохранённые отчёты можно открыть ниже.</div>
          )}
          {notice && <p className="analysis-notice" role="status" aria-live="polite">{notice}</p>}
        </section>

        <section className="analysis-history surface" aria-labelledby="analysis-history-title">
          <div className="analysis-section-title">
            <div><p className="eyebrow">История</p><h2 id="analysis-history-title">Мои разборы</h2></div>
            <button type="button" onClick={() => void loadHistory()} aria-label="Обновить историю" disabled={historyState === "loading"}>
              <RefreshCw className={historyState === "loading" ? "spin" : ""} aria-hidden="true" />
            </button>
          </div>
          <div className="analysis-history-list" aria-live="polite">
            {historyState === "loading" && jobs.length === 0 && <p><LoaderCircle className="spin" /> Загружаем историю…</p>}
            {historyState === "error" && jobs.length === 0 && <p><AlertTriangle /> История временно недоступна.</p>}
            {historyState === "idle" && jobs.length === 0 && <p><History /> Здесь появятся созданные вами разборы.</p>}
            {jobs.map((job) => (
              <button
                type="button"
                key={job.id}
                className={selectedJob?.id === job.id ? "selected" : ""}
                aria-current={selectedJob?.id === job.id ? "true" : undefined}
                onClick={() => void loadDetail(job.id)}
              >
                <span><strong>Матч {job.matchId}</strong><small>Мой игрок · {formatDate(job.createdAt)}</small></span>
                <span className={`analysis-state ${job.state}`}>{STATE_LABELS[job.state]}</span>
              </button>
            ))}
          </div>
          {nextCursor && (
            <button className="analysis-load-more" type="button" onClick={() => void loadHistory(nextCursor)} disabled={historyState === "loading"}>
              Показать ещё
            </button>
          )}
        </section>

        <section className="analysis-detail surface" aria-labelledby="analysis-detail-title">
          {!selectedJob && (
            <div className="analysis-empty"><BrainCircuit /><h2 id="analysis-detail-title">Выберите разбор</h2><p>Статус задания и доказательный отчёт появятся здесь.</p></div>
          )}
          {selectedJob && (
            <>
              <div className="analysis-detail-head">
                <div>
                  <p className="eyebrow">Матч {selectedJob.matchId}</p>
                  <h2 id="analysis-detail-title">Перспектива слота {selectedJob.playerSlot}</h2>
                  <p><Clock3 /> Попытка {selectedJob.attempt} из {selectedJob.maxAttempts}</p>
                </div>
                <span className={`analysis-state ${selectedJob.state}`}>{STATE_LABELS[selectedJob.state]}</span>
              </div>

              {detailState === "loading" && <p className="analysis-detail-loading" role="status"><LoaderCircle className="spin" /> Загружаем разбор…</p>}
              {selectedJob.failure && (
                <div className="analysis-failure" role="status"><AlertTriangle /><span><strong>{selectedJob.failure.retryable ? "Можно повторить" : "Задание завершено"}</strong>{selectedJob.failure.message}</span></div>
              )}
              {selectedJob.state === "queued" && (
                <div className="analysis-queued">
                  <p>Кредит зарезервирован и не будет списан повторно. При окончательной ошибке резерв возвращается.</p>
                  <button type="button" disabled={!canRun || runId === selectedJob.id} onClick={() => void runAnalysis(selectedJob.id)}>
                    {runId === selectedJob.id
                      ? <><LoaderCircle className="spin" /> Формируем отчёт…</>
                      : retryRemaining > 0
                        ? <><Clock3 /> Повторить через {retryRemaining} сек.</>
                        : <><BrainCircuit /> Запустить формирование</>}
                  </button>
                  <button
                    className="analysis-cancel"
                    type="button"
                    disabled={runId === selectedJob.id || cancelId === selectedJob.id}
                    onClick={() => void cancelAnalysis(selectedJob.id)}
                  >
                    {cancelId === selectedJob.id ? "Возвращаем резерв…" : "Отменить и вернуть резерв"}
                  </button>
                  {!fulfillmentReady && <small>Анализ временно недоступен. Сохранённые разборы остаются в истории.</small>}
                </div>
              )}
              {selectedJob.state === "running" && (
                <div className="analysis-queued">
                  <p role="status"><LoaderCircle className="spin" /> Задание выполняется. Если запрос прервался, его можно безопасно восстановить после окончания текущей попытки.</p>
                  <button
                    type="button"
                    disabled={!canRecover || runId === selectedJob.id}
                    onClick={() => void runAnalysis(selectedJob.id)}
                  >
                    {runId === selectedJob.id
                      ? <><LoaderCircle className="spin" /> Проверяем…</>
                      : retryRemaining > 0
                        ? <><Clock3 /> Проверить через {retryRemaining} сек.</>
                        : <><RefreshCw /> Проверить и восстановить</>}
                  </button>
                  <button
                    className="analysis-cancel"
                    type="button"
                    disabled={runId === selectedJob.id || cancelId === selectedJob.id}
                    onClick={() => void cancelAnalysis(selectedJob.id)}
                  >
                    {cancelId === selectedJob.id ? "Проверяем возврат…" : "Проверить тайм-аут и отменить"}
                  </button>
                </div>
              )}
              {selected?.report && (
                <div className="analysis-report">
                  <MatchReplayPanel key={selected.job.id} detail={selected} time={replayTime} onSeek={setReplayTime}/>
                  <div className="analysis-report-proof"><CheckCircle2 /> Цифры сверены с данными матча. Где данных не хватает, разбор говорит об этом прямо.</div>
                  {selected.report.items.map((item) => (
                    <article key={item.id} className={`analysis-report-item ${item.kind}`}>
                      <div>
                        <span>{REPORT_KIND_LABELS[item.kind]}</span>
                        <span>{REPORT_STAGE_LABELS[item.stage]}</span>
                        <span>{REPORT_CONFIDENCE_LABELS[item.confidence]}</span>
                      </div>
                      <h3>{item.title}</h3>
                      {item.time && <button type="button" onClick={()=>{setReplayTime(item.time!.type==="point" ? item.time!.seconds : item.time!.startSeconds);document.getElementById("match-replay")?.scrollIntoView({behavior:"smooth"});}}>Показать эпизод</button>}
                      <p>{item.body}</p>
                      {claimRows(item).length > 0 && (
                        <dl aria-label="Цифры из матча">
                          {claimRows(item).map((claim) => (
                            <div key={`${claim.evidenceId}:${claim.metric}:${claim.unit}`}>
                              <dt>{METRIC_LABELS[claim.metric] ?? claim.metric}</dt>
                              <dd>{claim.value}{UNIT_LABELS[claim.unit] ?? ` ${claim.unit}`}</dd>
                            </div>
                          ))}
                        </dl>
                      )}
                      {item.limitations.length > 0 && (
                        <div className="analysis-item-limitations">
                          <strong>Чего здесь не видно</strong>
                          <ul>{item.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
                        </div>
                      )}
                      <details className="analysis-evidence">
                        <summary>Проверить источники данных</summary>
                        <small>{item.evidenceIds.join(", ")}</small>
                      </details>
                    </article>
                  ))}
                  <ReportFollowup key={selected.job.id} jobId={selected.job.id} report={selected.report} time={replayTime} onSeek={setReplayTime}/>
                  {selected.report.limitations.length > 0 && (
                    <aside><strong>Ограничения отчёта</strong><ul>{selected.report.limitations.map((item) => <li key={item}>{item}</li>)}</ul></aside>
                  )}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
