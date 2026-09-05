"use client";

import { ChevronRight, Info, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  formatScanMetricValue,
  formatScanStat,
  formatScanTime,
  isJsonResponseMediaType,
  parseScanError,
  parseScanSuccess,
  scanKindLabel,
  scanMetricLabel,
  scanSideLabel,
  type ScanChoosePlayerResponse,
  type ScanPreview,
} from "@/components/narma/scan-presentation";

const MATCH_ID_PATTERN = /^[1-9]\d{7,11}$/;
const MAX_RESPONSE_CHARACTERS = 64 * 1024;

type Phase = "match" | "player" | "preview";
type LastRequest = { matchId: string; playerSlot?: number };
type RequestError = { message: string; retryable: boolean; requestId: string | null };

class ScanUiError extends Error {
  readonly retryable: boolean;
  readonly requestId: string | null;

  constructor(message: string, retryable = true, requestId: string | null = null) {
    super(message);
    this.name = "ScanUiError";
    this.retryable = retryable;
    this.requestId = requestId;
  }
}

function fallbackError(status: number): RequestError {
  if (status === 400) return { message: "Проверьте Match ID или выбранную перспективу.", retryable: false, requestId: null };
  if (status === 404) return { message: "Матч не найден или ещё не разобран OpenDota.", retryable: false, requestId: null };
  if (status === 413) return { message: "Запрос отклонён из-за размера.", retryable: false, requestId: null };
  if (status === 429) return { message: "Слишком много Scan-запросов. Попробуйте позже.", retryable: true, requestId: null };
  if (status === 503) return { message: "NARMA Scan временно недоступен. Попробуйте позже.", retryable: true, requestId: null };
  return { message: "Не удалось получить данные матча. Попробуйте ещё раз.", retryable: true, requestId: null };
}

async function readBoundedJson(response: Response): Promise<unknown> {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_CHARACTERS) {
    throw new ScanUiError("Сервер вернул слишком большой ответ.");
  }
  if (!isJsonResponseMediaType(response.headers.get("content-type"))) {
    throw new ScanUiError("Сервер вернул ответ в неожиданном формате.");
  }
  let text = "";
  if (!response.body) {
    text = await response.text();
    if (text.length > MAX_RESPONSE_CHARACTERS) {
      throw new ScanUiError("Сервер вернул слишком большой ответ.");
    }
  } else {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let receivedBytes = 0;
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        receivedBytes += chunk.value.byteLength;
        if (receivedBytes > MAX_RESPONSE_CHARACTERS) {
          await reader.cancel();
          throw new ScanUiError("Сервер вернул слишком большой ответ.");
        }
        text += decoder.decode(chunk.value, { stream: true });
      }
      text += decoder.decode();
    } finally {
      reader.releaseLock();
    }
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ScanUiError("Сервер вернул повреждённый ответ.");
  }
}

export default function NarmaScanFlow() {
  const [phase, setPhase] = useState<Phase>("match");
  const [matchIdDraft, setMatchIdDraft] = useState("");
  const [match, setMatch] = useState<ScanChoosePlayerResponse["match"] | null>(null);
  const [players, setPlayers] = useState<ScanChoosePlayerResponse["players"]>([]);
  const [selectedPlayerSlot, setSelectedPlayerSlot] = useState<number | null>(null);
  const [preview, setPreview] = useState<ScanPreview | null>(null);
  const [pending, setPending] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Введите Match ID, чтобы загрузить состав матча.");
  const [requestError, setRequestError] = useState<RequestError | null>(null);
  const [lastRequest, setLastRequest] = useState<LastRequest | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);
  const matchInputRef = useRef<HTMLInputElement>(null);
  const playerHeadingRef = useRef<HTMLHeadingElement>(null);
  const previewHeadingRef = useRef<HTMLHeadingElement>(null);

  const cancelActiveRequest = useCallback((announce: boolean) => {
    requestSequenceRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setPending(false);
    if (announce) {
      setStatusMessage("Загрузка отменена. Можно изменить выбор и повторить запрос.");
    }
  }, []);

  useEffect(() => () => {
    requestSequenceRef.current += 1;
    controllerRef.current?.abort();
  }, []);

  useEffect(() => {
    const target = phase === "match"
      ? matchInputRef.current
      : phase === "player"
        ? playerHeadingRef.current
        : previewHeadingRef.current;
    const animationFrame = window.requestAnimationFrame(() => target?.focus());
    return () => window.cancelAnimationFrame(animationFrame);
  }, [phase]);

  const reset = useCallback(() => {
    cancelActiveRequest(false);
    setPhase("match");
    setMatchIdDraft("");
    setMatch(null);
    setPlayers([]);
    setSelectedPlayerSlot(null);
    setPreview(null);
    setRequestError(null);
    setStatusMessage("Введите Match ID, чтобы загрузить состав матча.");
    setLastRequest(null);
  }, [cancelActiveRequest]);

  const requestScan = useCallback(async (request: LastRequest) => {
    cancelActiveRequest(false);
    const controller = new AbortController();
    const sequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = sequence;
    controllerRef.current = controller;
    setLastRequest(request);
    setPending(true);
    setRequestError(null);
    setStatusMessage(request.playerSlot === undefined
      ? "Загружаем состав матча…"
      : "Выбираем один фактический момент…");

    try {
      const response = await fetch("/api/scan", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
      const payload = await readBoundedJson(response);
      if (sequence !== requestSequenceRef.current) return;

      if (!response.ok) {
        const apiError = parseScanError(payload);
        const error = apiError
          ? { message: apiError.error.message, retryable: apiError.error.retryable, requestId: apiError.error.requestId }
          : fallbackError(response.status);
        throw new ScanUiError(error.message, error.retryable, error.requestId);
      }

      const result = parseScanSuccess(payload);
      if (!result) throw new ScanUiError("Сервер вернул ответ в неожиданном формате.");
      if (result.status === "choose_player") {
        if (result.match.matchId !== request.matchId || request.playerSlot !== undefined) {
          throw new ScanUiError("Ответ сервера не соответствует запросу.");
        }
        setMatch(result.match);
        setPlayers(result.players);
        setSelectedPlayerSlot(null);
        setPhase("player");
        setStatusMessage("Состав загружен. Выберите перспективу одного из десяти игроков.");
        return;
      }

      if (result.preview.matchId !== request.matchId
        || result.preview.playerSlot !== request.playerSlot) {
        throw new ScanUiError("Ответ сервера не соответствует выбранному матчу или игроку.");
      }
      setPreview(result.preview);
      setPhase("preview");
      setStatusMessage("Фактический момент готов.");
    } catch (error) {
      if (sequence !== requestSequenceRef.current) return;
      if (error instanceof DOMException && error.name === "AbortError") {
        setStatusMessage("Загрузка отменена. Можно изменить выбор и повторить запрос.");
        return;
      }
      const knownError = error instanceof ScanUiError
        ? error
        : new ScanUiError("Не удалось связаться с NARMA Scan. Проверьте соединение и повторите запрос.");
      setRequestError({
        message: knownError.message,
        retryable: knownError.retryable,
        requestId: knownError.requestId,
      });
      setStatusMessage(`Ошибка: ${knownError.message}`);
    } finally {
      if (sequence === requestSequenceRef.current) {
        controllerRef.current = null;
        setPending(false);
      }
    }
  }, [cancelActiveRequest]);

  const submitMatch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const matchId = matchIdDraft.trim();
    if (!MATCH_ID_PATTERN.test(matchId)) {
      setRequestError({
        message: "Match ID должен содержать от 8 до 12 цифр и не начинаться с нуля.",
        retryable: false,
        requestId: null,
      });
      setStatusMessage("Проверьте формат Match ID.");
      return;
    }
    void requestScan({ matchId });
  };

  const submitPlayer = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!match || selectedPlayerSlot === null) {
      setRequestError({ message: "Выберите перспективу игрока.", retryable: false, requestId: null });
      setStatusMessage("Выберите перспективу игрока.");
      return;
    }
    void requestScan({ matchId: match.matchId, playerSlot: selectedPlayerSlot });
  };

  const retry = () => {
    if (lastRequest) void requestScan(lastRequest);
  };

  const errorPanel = requestError && (
    <div className="scan-error" id="scan-error" role="alert">
      <Info size={16} aria-hidden="true" />
      <div>
        <strong>Scan не завершён</strong>
        <p>{requestError.message}</p>
        {requestError.requestId && <small>Код запроса: {requestError.requestId}</small>}
      </div>
      {requestError.retryable && lastRequest && (
        <button type="button" onClick={retry} disabled={pending}>Повторить</button>
      )}
    </div>
  );

  return (
    <div className="scan-flow">
      <p className="eyebrow">Бесплатный NARMA Scan</p>
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{statusMessage}</p>

      {phase === "match" && (
        <form noValidate onSubmit={submitMatch} aria-busy={pending}>
          <h2 id="match-dialog-title">Введите Match ID</h2>
          <p id="match-dialog-description">Scan загрузит публичные данные матча и попросит выбрать перспективу. Регистрация не нужна.</p>
          <p className="field-help" id="scan-match-id-help">Формат — от 8 до 12 цифр. Данные берутся из OpenDota.</p>
          <label htmlFor="scan-match-id"><span>Match ID</span></label>
          <input
            ref={matchInputRef}
            id="scan-match-id"
            name="matchId"
            inputMode="numeric"
            autoComplete="off"
            maxLength={12}
            required
            data-dialog-initial-focus
            value={matchIdDraft}
            disabled={pending}
            aria-invalid={Boolean(requestError)}
            aria-describedby={requestError ? "scan-match-id-help scan-error" : "scan-match-id-help"}
            onChange={(event) => {
              setMatchIdDraft(event.target.value.replace(/\D/g, "").slice(0, 12));
              setRequestError(null);
            }}
            placeholder="8963624400"
          />
          {errorPanel}
          <div className="scan-actions">
            {pending ? (
              <button className="dialog-secondary" type="button" onClick={() => cancelActiveRequest(true)}>Отменить загрузку</button>
            ) : (
              <button className="dialog-submit" type="submit">Загрузить состав <ChevronRight size={17} aria-hidden="true" /></button>
            )}
          </div>
        </form>
      )}

      {phase === "player" && match && (
        <form noValidate onSubmit={submitPlayer} aria-busy={pending}>
          <h2 ref={playerHeadingRef} id="match-dialog-title" tabIndex={-1}>Выберите перспективу</h2>
          <p id="match-dialog-description">Матч {match.matchId} · {formatScanTime(match.durationSeconds)}. Имена игроков и героев пока не загружаются: показываем Hero ID и K/D/A.</p>
          <fieldset className="scan-roster" disabled={pending}>
            <legend>Десять игроков матча</legend>
            {players.map((player) => (
              <label key={player.playerSlot} className={`scan-player ${player.side}`}>
                <input
                  type="radio"
                  name="playerSlot"
                  value={player.playerSlot}
                  checked={selectedPlayerSlot === player.playerSlot}
                  onChange={() => { setSelectedPlayerSlot(player.playerSlot); setRequestError(null); }}
                />
                <span>
                  <strong>{scanSideLabel(player.side)} · Hero ID {player.heroId}</strong>
                  <small>K/D/A {formatScanStat(player.kills)}/{formatScanStat(player.deaths)}/{formatScanStat(player.assists)} · убийства {formatScanStat(player.kills)}, смерти {formatScanStat(player.deaths)}, помощи {formatScanStat(player.assists)}</small>
                </span>
              </label>
            ))}
          </fieldset>
          {errorPanel}
          <div className="scan-actions split">
            <button className="dialog-secondary" type="button" onClick={reset}><RotateCcw size={16} aria-hidden="true" /> Другой матч</button>
            {pending ? (
              <button className="dialog-secondary" type="button" onClick={() => cancelActiveRequest(true)}>Отменить загрузку</button>
            ) : (
              <button className="dialog-submit" type="submit" disabled={selectedPlayerSlot === null}>Показать момент <ChevronRight size={17} aria-hidden="true" /></button>
            )}
          </div>
        </form>
      )}

      {phase === "preview" && preview && (
        <section className="scan-preview" aria-labelledby="match-dialog-title">
          <h2 ref={previewHeadingRef} id="match-dialog-title" tabIndex={-1}>Один факт из матча</h2>
          <p id="match-dialog-description">Это наблюдение из доступных чисел. Scan не утверждает, что момент решил исход матча.</p>
          <div className="scan-preview-lead">
            <span>{scanKindLabel(preview.kind)}</span>
            <strong>{formatScanTime(preview.atSeconds)}</strong>
            <small>{scanSideLabel(preview.team)}</small>
          </div>
          {preview.metrics.length > 0 ? (
            <dl className="scan-metrics">
              {preview.metrics.map((metric) => (
                <div key={`${metric.metric}-${metric.unit}`}>
                  <dt>{scanMetricLabel(metric.metric)}</dt>
                  <dd>{formatScanMetricValue(metric)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="scan-empty-metrics">Для этого момента нет дополнительных числовых метрик.</p>
          )}
          <p className="scan-evidence">Источник в пакете матча: <code>{preview.selectedEvidenceId}</code></p>
          <div className="scan-actions split">
            <button className="dialog-secondary" type="button" onClick={() => { setPreview(null); setPhase("player"); setStatusMessage("Выберите другую перспективу."); }}>
              Другая перспектива
            </button>
            <button className="dialog-submit" type="button" onClick={reset}><RotateCcw size={16} aria-hidden="true" /> Новый Scan</button>
          </div>
        </section>
      )}
    </div>
  );
}
