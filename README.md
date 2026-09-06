# NARMA VISION

AI-тренер по Dota 2, который связывает выводы с проверяемыми моментами матча.
Проект собран как закрытый beta-кандидат: demo, authenticated full-analysis
workflow и серверные контуры готовы, но расход OpenAI и платежи включаются
только после проверки развёрнутого staging.

## Что работает сейчас

- **Golden demo матча `8963624400`**: четыре стадии, фиксированный пример для Juggernaut,
  карта и события, золото/опыт, 15 окон драк и тренировочные задачи по
  пяти навыкам. Demo не выдаёт себя за обработку произвольного Match ID.
- **Гейтированный NARMA Scan**: `POST /api/scan` после входа получает Match ID и
  определяет закреплённого игрока на сервере. Возвращается один детерминированный
  числовой момент. Ник задаётся при первой привязке; смена героя не меняет игрока. Это не AI-вывод и не
  утверждение о причине поражения.
- **Основа анализа**: фиксированный bounded GET к OpenDota, строгие
  `NormalizedMatchV1` / `EvidenceBundleV1` / `AnalysisReportV1`, канонические
  SHA-256 hashes и fail-closed адаптер OpenAI Responses API.
- **Полный разбор**: owner-scoped создание, история и просмотр отчёта,
  транзакционный резерв entitlement, lease, ограниченный retry/cooldown,
  ручное восстановление зависшего запуска и точный возврат резерва.
- **Основа данных и биллинга**: D1 migrations, immutable entitlement ledger,
  идемпотентные заказы и разделённые test/live payment gates. Реальные списания
  выключены.
- **Release-проверки**: lint, Worker typecheck, unit tests, production build,
  проверка package contract, security headers и fail-closed dependency audit.

Вопросы тренеру, durable queue, payment reconciliation и возвраты ещё не
реализованы. Ссылки модели на evidence гарантируют целостность ссылок, но не
доказывают истинность свободного текста; поэтому
`ANALYSIS_FULFILLMENT_ENABLED` должен оставаться выключенным до реального
staging-прогона OpenDota/OpenAI, D1 и восстановления после тайм-аутов.

## Локальный запуск

Используйте Node.js `22.13.1`, как в CI.

```bash
npm run install:ci
npm run dev
```

Основная проверка кандидата:

```bash
npm run check
npm run audit:advisory
```

`audit:advisory` требует доступ к npm registry и намеренно завершается ошибкой,
если advisories нельзя получить или проверить.

## NARMA Scan

Scan по умолчанию закрыт. UI и API становятся доступны только когда одновременно
валидны:

| Переменная | Требование |
| --- | --- |
| `SCAN_RUNTIME_ENABLED` | точная строка `true` |
| `SCAN_RATE_LIMIT_SECRET` | уникальный server-only secret из 32+ печатных символов |
| `DB` | настоящий D1 binding |

Запрос ограничен 4 KiB и exact `application/json`; принимается только
same-origin вызов с `CF-Connecting-IP`. IP не сохраняется: для каждого
15-минутного окна хранится отдельный HMAC digest. Лимит — 12 API-вызовов на
окно. В D1 кэшируется только строгий нормализованный payload без имён, Steam
account IDs и чата. Scan не вызывает OpenAI, не создаёт заказ и не расходует
entitlement.

Даже при готовой конфигурации флаг нельзя включать шире закрытого staging до
Workerd/D1 concurrency-теста, проверки edge-header trust, WAF/abuse-защиты и
плановой очистки истёкших buckets.

Server-only адаптер полного AI-разбора и pull-driven job runner реализованы, но
по умолчанию выключены. Контракт принимает числовые факты только как
структурированные `evidenceId` / `metric` / `value` / `unit` claims и сверяет их
с cited evidence по точному значению и единице. Цифры в свободном тексте отчёта
отклоняются; консервативный RU/EN guard также отсекает распространённые числовые
слова, доли, проценты и сравнения. Это defense in depth, а не полная семантическая
проверка естественного языка: интерфейс должен выводить количественные факты
только из проверенных claims.

## Тарифы, зафиксированные для закрытой беты

| Тариф | Цена | Лимит |
| --- | ---: | --- |
| Первый полный разбор | 0 ₽ | 1 матч и 5 вопросов после регистрации |
| Разбор матча | 299 ₽ | 1 матч и 10 вопросов |
| AI-тренер | 799 ₽ / 30 дней | 8 матчей и 40 вопросов |

Цены являются частью серверного каталога, но это не означает, что checkout
готов. `PAYMENTS_ENABLED` и `PAYMENT_SETTLEMENT_ENABLED` остаются `false` до
юридического, D1, reconciliation, refund и test-mode go/no-go. Дополнительно
checkout заблокирован compile-time capability gate, пока не реализована выдача
обещанных тарифами вопросов тренеру.

## Игровая карта

В репозитории хранится игровая карта патча 7.41:

```text
public/maps/7.41/game-map.jpg
```

Изображение Buny154 / Liquipedia, © Valve Corporation. Координаты меток
откалиброваны по башням и базам; пропорции исходного изображения сохранены.
Состояние башен, варды и события меняются по времени поверх статичного растра.
Туман войны недоступен. Источник, калибровка и ограничения описаны в
[docs/MAP_ASSET.md](docs/MAP_ASSET.md).

Gold, XP и интервалы драк используют одну шкалу времени. Для выбранной драки
показаны отдельные изменения золота Radiant и Dire; разница этих изменений
не называется заработком команды. Данные по героям выводятся только при их
наличии в источнике.

## Достоверность

Источник golden fixture — [OpenDota match API](https://api.opendota.com/api/matches/8963624400),
parser version 22. В продукте разделяются:

- факты из доступной телеметрии;
- интерпретация тренера;
- расчётные модели, например движение волн без полного replay.

OpenDota не предоставляет непрерывный помоментный маршрут всех героев и крипов,
поэтому такой маршрут не показывается как факт. NARMA Scan также не называет
выбранный момент «точкой, где игрок отдал матч».

## Структура

- `app/data/match-8963624400.ts` — проверенный golden fixture;
- `components/narma/` — demo и доступный двухшаговый Scan UI;
- `lib/analysis/` — нормализация, evidence, OpenDota и OpenAI contracts;
- `lib/scan/` и `app/api/scan/` — изолированный anonymous Scan runtime;
- `lib/billing/`, `lib/payments/`, `drizzle/` — закрытый payment/data scaffold;
- `docs/RECOVERY_ARCHITECTURE.md` — границы и целевая архитектура;
- `docs/RELEASE_RUNBOOK.md` — обязательные staging и release gates.

## Атрибуция

Координаты объектов основаны на 7.41 data fixture проекта
[dota-interactive-map](https://github.com/leamare/dota-interactive-map) (ISC,
commit `bc73d0e3ea6a421d43780a017aa92e0288c939b5`). Визуальная логика плотных
диаграмм изучалась по [lieflat-charts](https://github.com/larashero3-dotcom/lieflat-charts);
его код и ассеты не копируются. Powered by [Source 2 Viewer](https://s2v.app)
([ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat)).

Dota и графические материалы Dota 2 — товарные знаки и собственность Valve
Corporation. Проект не аффилирован с Valve.
