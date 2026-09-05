# Приём платежей NARMA VISION в России

Статус на 4 сентября 2026 года: в репозитории есть локальный безопасный
scaffold для ЮKassa, но приём денег не готов к включению. В коде нет реальных
ключей, все feature flags по умолчанию выключены, возвраты и автоматическая
сверка ещё не реализованы.

## Что реализовано

- Серверный каталог фиксирует цены: разовый разбор — 299 ₽, AI-тренер на
  30 дней — 799 ₽. Цена, версия продукта, число разборов/вопросов и срок
  сохраняются в заказе и не меняются вслед за будущим каталогом.
- Браузер передаёт только продукт, Match ID и UUID попытки. Сервер создаёт свой
  order ID, использует его как ключ идемпотентности ЮKassa и сохраняет SHA-256
  контракта запроса, включая окружение и режим платежа.
- Ответ ЮKassa читается потоково с лимитом 64 KiB, требует JSON и проверяется по
  типам. Timeout/stream errors и provider `401`/`402` становятся внутренним
  dependency `503`, а не ошибкой входа или баланса пользователя.
- До выдачи `confirmationUrl` ответ провайдера сверяется с неизменяемым
  snapshot заказа: order ID, продукт, Match ID, сумма, RUB и test/live mode.
  Несовпадение привязывается к заказу для расследования, переводит fulfillment
  в `manual_review` и не отправляет пользователя на оплату.
- Webhook не доверяет входному статусу: сервер повторно получает платёж у
  ЮKassa и сверяет order ID, сумму, RUB, продукт, магазин и поле `test`.
- Новые продажи и settlement разделены. Остановка checkout не мешает принять
  webhook по уже созданному платежу.
- `entitlement_ledger` хранит неизменяемые grants/reservations/
  consume/releases с идемпотентными ключами и bucket expiry. Разрешить одну
  reservation можно только один раз; SQL-триггеры блокируют поддельный release,
  изменение и удаление журнала.
- Физическое имя старой таблицы `orders` сохранено для совместимости. Миграция
  сохраняет старые строки, но помечает их `environment=unknown` и
  `payment_mode=unknown`: такие платежи нельзя автоматически settlement-ить без
  ручной сверки.
- Финансовые записи не каскадно удаляются. У пользователя есть `status` и
  `deleted_at`; штатное удаление должно быть soft-delete. Даже при ошибочном
  hard-delete заказ остаётся, а его `user_id` обнуляется.
- Уникальный индекс блокирует второй заказ `coach_30_days` не только во время
  checkout, но и в окне `succeeded` до подтверждённого начисления. Более строгий
  индекс создаётся до удаления прежнего, поэтому существующий дубль останавливает
  миграцию без снятия старой защиты.
- Добавлены схемы `provider_events`, `refunds`, `source_matches`,
  `analysis_jobs`, `analysis_reports` и durable `rate_limit_buckets`. Наличие
  таблицы не означает, что refund/reconciliation/online-analysis уже работают.

Первый профиль получает opening entries на один бесплатный разбор и пять
вопросов. Старые профили получают миграционный opening balance. Поля счётчиков
в `users` сохранены только для совместимости миграции; API аккаунта вычисляет
доступный баланс из неистёкших строк ledger. Поэтому reserve/release сразу
отражаются в интерфейсе и второго источника истины нет.

## Предохранители окружения

Все булевы значения включаются только точной строкой `true`; пропущенное или
неверное значение означает `false`.

| Переменная | Назначение |
| --- | --- |
| `APP_ENVIRONMENT` | Короткое имя изолированного окружения, например `staging` |
| `APP_ORIGIN` | Канонический HTTPS origin для return URL, без path/query |
| `PAYMENT_MODE` | Только `test` или `live`; записывается в каждый новый заказ |
| `YOOKASSA_TEST_SHOP_ID`, `YOOKASSA_TEST_SECRET_KEY` | Только тестовый магазин |
| `YOOKASSA_LIVE_SHOP_ID`, `YOOKASSA_LIVE_SECRET_KEY` | Только live-магазин |
| `ANALYSIS_RUNTIME_ENABLED` | API новых анализов готов принимать задания |
| `ANALYSIS_FULFILLMENT_ENABLED` | Очередь и безопасное списание entitlement готовы |
| `PAYMENTS_ENABLED` | Разрешить создание новых платежей |
| `PAYMENT_SETTLEMENT_ENABLED` | Разрешить проверку webhook существующих платежей |

Checkout откроется только когда одновременно валидны окружение, HTTPS origin,
режим и его отдельные credentials, а также включены `PAYMENTS_ENABLED`,
`ANALYSIS_RUNTIME_ENABLED` и `ANALYSIS_FULFILLMENT_ENABLED`.

Settlement зависит только от `PAYMENT_SETTLEMENT_ENABLED`, валидного окружения,
режима и credentials этого режима. Это позволяет поставить продажи на паузу,
не потеряв завершение ранее созданных заказов. Test и live должны использовать
разные D1 databases и разные secrets; один набор ключей не подменяет другой.

## Тарифы закрытой беты

| Тариф | Цена | Лимит |
| --- | ---: | --- |
| Первый разбор | 0 ₽ | 1 полный матч и 5 вопросов после регистрации |
| Разбор матча | 299 ₽ | 1 полный матч и 10 вопросов |
| AI-тренер | 799 ₽ / 30 дней | 8 полных матчей и 40 вопросов |

Подписка на старте задумана как доступ на 30 дней без автопродления. Повторное
открытие готового отчёта не должно списывать второй кредит. Эти продуктовые
условия требуют интеграционных тестов полного analysis lifecycle до продаж.

## Что блокирует реальные списания

1. Оформить статус продавца, публичные реквизиты, оферту, privacy/consent,
   правила возврата, контакты и чеки.
2. Реализовать и проверить очередь анализа, atomic reserve/consume/release,
   восстановление зависших jobs и повторное открытие отчёта.
3. Добавить отдельные test/live D1 databases и secrets; выполнить отрицательный
   тест, что клиент не может подделать identity headers.
4. Прогнать тестовые платежи: success, cancel, duplicate/out-of-order webhook,
   mode mismatch, amount mismatch, provider timeout и webhook раньше binding.
5. Реализовать reconciliation для payment succeeded без fulfillment, а также
   operator runbook. Сейчас неактивный пользователь переводит fulfillment в
   `manual_review`, а не получает entitlement автоматически.
6. Реализовать `refund.succeeded`, reversal policy и сверку возвратов. Таблица
   `refunds` сейчас только data-readiness.
7. Заменить неатомарный checkout rate-count на durable atomic bucket и добавить
   edge/IP защиту. Таблица для hashed bucket keys есть, route ещё не переведён.
8. Проверить миграции и payment flow под Workerd/D1, а не только Node SQLite,
   затем провести юридический и операционный go/no-go review.

До завершения списка все четыре бизнес-флага должны оставаться `false`.

## Почему не криптовалюта и не скины

Для российской версии не планируется показывать BTC/USDT-кошелёк или принимать
скины как оплату. Такой контур требует отдельной письменной проверки юриста,
бухгалтера и платёжного провайдера; Steam также не является платёжным счётом и
ограничивает внешнюю коммерческую автоматизацию предметов.

## Справочные источники для финального legal review

- ЮKassa: https://yookassa.ru/developers/payment-acceptance/getting-started/quick-start
- ЮKassa, webhook: https://yookassa.ru/developers/using-api/webhooks
- ЮKassa, подготовка сайта: https://yookassa.ru/docs/support/payments/onboarding/arrangement
- ЮKassa для самозанятых: https://yookassa.ru/platezhi-dlya-samozanyatyh/
- Steam Subscriber Agreement: https://store.steampowered.com/subscriber_agreement/
- Steam Online Conduct: https://store.steampowered.com/online_conduct/

Ссылки — ориентиры для проверки, а не юридическое заключение.
