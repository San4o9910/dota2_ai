"""One-off replay credits. Provider calls are explicit, bounded, and idempotent.

Off by default. No payment callback is trusted without retrieving the payment.
New spends and refunds serialize on the owner billing lock (scope 2); they
never acquire a replay row after this lock. Terminal job transitions only move
an existing hold to consumed/released and never create additional spending.
"""
import base64
from datetime import datetime, timezone, timedelta
import json
import os
import re
from urllib import request as http, error as http_error
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from starlette.concurrency import run_in_threadpool
from .db import database
from .web import account_required, csrf, json_body, rate_limit, reject

PRODUCTS = {'single': (1, 19900), 'five': (5, 79900)}
PROVIDER_ID = re.compile(r'^[a-zA-Z0-9_-]{8,80}$')


def config():
    mode = os.getenv('NARMA_BILLING_MODE', 'off')
    shop = os.getenv('YOOKASSA_SHOP_ID', '')
    secret = os.getenv('YOOKASSA_SECRET_KEY', '')
    origin = os.getenv('APP_ORIGIN', '').rstrip('/')
    terms = os.getenv('NARMA_TERMS_URL', '')
    privacy = os.getenv('NARMA_PRIVACY_URL', '')
    seller = os.getenv('NARMA_SELLER_NAME', '')
    support = os.getenv('NARMA_SUPPORT_EMAIL', '')
    version = os.getenv('NARMA_TERMS_VERSION', '')
    ready = (mode in ('test', 'live') and shop.isdigit() and 8 <= len(secret) <= 4096
             and origin.startswith('https://') and bool(seller and version)
             and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', support)
             and all(urlparse(u).scheme == 'https' and urlparse(u).netloc for u in (terms, privacy)))
    # Receipt and fulfillment readiness must be explicitly configured by the
    # merchant. External receipts also require the merchant's fiscal integration.
    receipt = os.getenv('NARMA_RECEIPT_MODE', '')
    ready = bool(ready and receipt in ('yookassa', 'external') and os.getenv('NARMA_FULFILLMENT_READY') == '1')
    if receipt == 'yookassa':
        ready = ready and os.getenv('NARMA_VAT_CODE', '') in {str(i) for i in range(1, 13)} and os.getenv('NARMA_RECEIPT_PAYMENT_MODE') in ('full_payment', 'full_prepayment')
        # Advance receipts require the merchant's separate settlement receipt.
        if os.getenv('NARMA_RECEIPT_PAYMENT_MODE') == 'full_prepayment':
            ready = ready and os.getenv('NARMA_EXTERNAL_RECEIPTS_READY') == '1'
    if receipt == 'external':
        ready = ready and os.getenv('NARMA_EXTERNAL_RECEIPTS_READY') == '1'
    if mode == 'live':
        ready = ready and os.getenv('NARMA_LIVE_PAYMENTS_APPROVED') == '1' and os.getenv('NARMA_BILLING_ENFORCE') == '1'
    return dict(mode=mode, shop=shop, secret=secret, origin=origin, terms=terms, privacy=privacy,
                seller=seller, support=support, version=version, ready=ready, receipt=receipt)


def lock(connection, owner):
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,2))', (owner,))


class NoRedirect(http.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ProviderUnavailable(Exception):
    pass


def provider(method, path, cfg, payload=None, key=None):
    if method not in ('GET', 'POST') or not re.fullmatch(r'/(payments|refunds)(/[a-zA-Z0-9_-]{8,80})?', path):
        raise ProviderUnavailable()
    headers = {'Authorization': 'Basic ' + base64.b64encode(f"{cfg['shop']}:{cfg['secret']}".encode()).decode(), 'Content-Type': 'application/json'}
    if key:
        headers['Idempotence-Key'] = str(key)
    req = http.Request('https://api.yookassa.ru/v3' + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    try:
        with http.build_opener(NoRedirect()).open(req, timeout=35) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (http_error.URLError, OSError, ValueError):
        # Never expose a response body/credential or infer failure from timeout.
        raise ProviderUnavailable() from None


def money(amount):
    return {'value': f'{amount // 100}.{amount % 100:02}', 'currency': 'RUB'}


def receipt_item(amount, quantity=1):
    return {'description': 'Разбор матча NARMA Vision', 'quantity': str(quantity), 'amount': money(amount),
            'vat_code': int(os.environ['NARMA_VAT_CODE']), 'payment_subject': 'service', 'payment_mode': os.environ['NARMA_RECEIPT_PAYMENT_MODE']}


def validate_payment(data, row):
    if (not isinstance(data.get('recipient'), dict) or not isinstance(data.get('metadata'), dict)
            or not PROVIDER_ID.fullmatch(str(data.get('id', '')))
            or (row['payment_id'] and data['id'] != row['payment_id'])
            or data.get('amount') != money(row['amount'])
            or data.get('test') is not (row['mode'] == 'test')
            or (data.get('recipient') or {}).get('account_id') != row['shop_id']
            or (data.get('metadata') or {}).get('order_id') != str(row['id'])
            or data.get('status') not in ('pending', 'waiting_for_capture', 'succeeded', 'canceled')
            or (data.get('status') == 'succeeded' and data.get('paid') is not True)):
        raise ProviderUnavailable()


def checkout_url(value):
    try:
        url = urlparse(value or '')
        return value if url.scheme == 'https' and url.hostname in ('yookassa.ru', 'yoomoney.ru') and not url.username and not url.password and url.port in (None, 443) else None
    except (ValueError, TypeError):
        return None


def sync_order(owner, order_id):
    cfg = config()
    if not cfg['ready']:
        reject(503, 'BILLING_UNAVAILABLE', 'Оплата временно недоступна. История покупок сохранена.')
    try:
        with database() as connection:
            lock(connection, owner)
            row = connection.execute('SELECT * FROM portal_orders WHERE id=%s AND owner_id=%s FOR UPDATE', (order_id, owner)).fetchone()
            if not row:
                reject(404, 'BILLING_ORDER', 'Заказ не найден.')
            if (row['mode'], row['shop_id']) != (cfg['mode'], cfg['shop']):
                reject(409, 'BILLING_STORE_CHANGED', 'Магазин изменился. Обратись в поддержку по номеру заказа.')
            if row['status'] in ('succeeded', 'canceled'):
                return {'order': public_order(row)}
            if row['payment_id']:
                data = provider('GET', '/payments/' + row['payment_id'], cfg)
            else:
                if datetime.now(timezone.utc) - row['created_at'] >= timedelta(hours=23):
                    reject(409, 'BILLING_RECONCILE', 'Статус старого заказа требует проверки поддержки. Повторное списание не запускается.')
                data = provider('POST', '/payments', cfg, row['request_payload'], row['id'])
            validate_payment(data, row)
            status = data['status'] if data['status'] in ('succeeded', 'canceled') else 'pending'
            url = checkout_url((data.get('confirmation') or {}).get('confirmation_url'))
            row = connection.execute('''UPDATE portal_orders SET payment_id=%s,status=%s,checkout_url=COALESCE(%s,checkout_url),updated_at=now()
                WHERE id=%s RETURNING *''', (data['id'], status, url, order_id)).fetchone()
            return {'order': public_order(row)}
    except ProviderUnavailable:
        reject(503, 'BILLING_PENDING', 'Провайдер не подтвердил результат. Заказ сохранён. Нажми «Проверить оплату», не создавая новую покупку.')


def public_order(row):
    return {k: row[k] for k in ('id', 'product', 'units', 'amount', 'mode', 'status', 'checkout_url', 'created_at')}


class Buy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    product: str = Field(pattern=r'^(single|five)$')
    terms_version: str = Field(min_length=1, max_length=100)
    accepted: bool


def buy(account, body):
    cfg = config()
    if not cfg['ready']:
        reject(503, 'BILLING_NOT_READY', 'Продажа разборов пока не открыта.')
    if body.accepted is not True or body.terms_version != cfg['version']:
        reject(409, 'BILLING_TERMS', 'Прочитай и прими текущие условия покупки.')
    if cfg['mode'] == 'live':
        from .openai_budget import status
        budget = status()
        if not budget.get('enabled') or budget.get('frozen_reason') or budget.get('available_microusd', 0) <= 0:
            reject(503, 'BILLING_FULFILLMENT', 'Новые покупки приостановлены: тренер сейчас недоступен.')
    units, amount = PRODUCTS[body.product]
    owner = account['owner_id']
    with database() as connection:
        lock(connection, owner)
        existing = connection.execute('SELECT * FROM portal_orders WHERE id=%s', (body.id,)).fetchone()
        if existing:
            if (existing['owner_id'], existing['product'], existing['terms_version']) != (owner, body.product, body.terms_version):
                reject(409, 'BILLING_CONFLICT', 'Этот номер уже относится к другому заказу.')
        else:
            pending = connection.execute("SELECT id FROM portal_orders WHERE owner_id=%s AND status='pending' AND mode=%s LIMIT 1", (owner, cfg['mode'])).fetchone()
            if pending:
                reject(409, 'BILLING_PENDING_ORDER', 'Сначала проверь незавершённый заказ в истории покупок.')
            count = connection.execute("SELECT count(*) AS n FROM portal_orders WHERE owner_id=%s AND created_at>now()-interval '1 day'", (owner,)).fetchone()['n']
            if count >= 10:
                reject(429, 'BILLING_LIMIT', 'Сегодня создано слишком много заказов. Обратись в поддержку.')
            payload = {'amount': money(amount), 'capture': True, 'confirmation': {'type': 'redirect', 'return_url': cfg['origin'] + '/account'},
                       'description': f'NARMA Vision · {units} разбор(ов)', 'metadata': {'order_id': str(body.id)}, 'save_payment_method': False}
            if cfg['receipt'] == 'yookassa':
                payload['receipt'] = {'customer': {'email': account['email']}, 'items': [receipt_item(amount // units, units)]}
            connection.execute('''INSERT INTO portal_orders(id,owner_id,mode,shop_id,product,units,amount,request_payload,terms_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (body.id, owner, cfg['mode'], cfg['shop'], body.product, units, amount, Jsonb(payload), cfg['version']))
    # Durable intent precedes network I/O. A timeout can be safely reconciled.
    return sync_order(owner, body.id)


BALANCES = '''SELECT o.*,
 (SELECT count(*) FROM portal_credit_uses c WHERE c.order_id=o.id AND c.state='held')::int AS held,
 (SELECT count(*) FROM portal_credit_uses c WHERE c.order_id=o.id AND c.state='consumed')::int AS consumed,
 COALESCE((SELECT r.units FROM portal_refunds r WHERE r.order_id=o.id AND r.status<>'canceled'),0) AS refunded
 FROM portal_orders o WHERE o.owner_id=%s'''


def account_billing(owner):
    cfg = config()
    with database() as connection:
        rows = connection.execute(BALANCES + ' ORDER BY o.created_at DESC LIMIT 100', (owner,)).fetchall()
        totals = connection.execute('SELECT COALESCE(sum(GREATEST(0,units-held-consumed-refunded)),0) AS balance, COALESCE(sum(held),0) AS held FROM (' + BALANCES + " AND o.status='succeeded' AND o.mode=%s) balances", (owner,cfg['mode'])).fetchone()
        refunds = connection.execute('''SELECT r.id,r.order_id,r.units,r.amount,r.status,r.created_at FROM portal_refunds r
            JOIN portal_orders o ON o.id=r.order_id WHERE o.owner_id=%s ORDER BY r.created_at DESC LIMIT 100''', (owner,)).fetchall()
    orders = [{**public_order(r), 'held': r['held'], 'remaining': max(0, r['units']-r['held']-r['consumed']-r['refunded']) if r['status'] == 'succeeded' else 0} for r in rows]
    return {'mode': cfg['mode'], 'checkout_enabled': cfg['ready'],
            'balance': totals['balance'], 'held': totals['held'],
            'orders': orders, 'refunds': refunds, 'seller': cfg['seller'], 'support_email': cfg['support'],
            'terms_url': cfg['terms'], 'privacy_url': cfg['privacy'], 'terms_version': cfg['version'],
            'products': [{'id': key, 'units': value[0], 'amount': value[1]} for key, value in PRODUCTS.items()]}


def reserve(connection, owner, job):
    cfg = config()
    if os.getenv('NARMA_BILLING_ENFORCE') != '1':
        return
    if not cfg['ready'] or cfg['mode'] != 'live':
        reject(503, 'BILLING_NOT_READY', 'Платный разбор временно недоступен. Попытка не списана.')
    lock(connection, owner)
    previous = connection.execute('SELECT * FROM portal_credit_uses WHERE id=%s', (job,)).fetchone()
    if previous:
        if previous['state'] != 'released':
            return
        reject(409, 'BILLING_RETRY_UPLOAD', 'Попытка возвращена. Создай новую загрузку.')
    for row in connection.execute(BALANCES + " AND o.status='succeeded' AND o.mode='live' ORDER BY o.created_at", (owner,)).fetchall():
        if row['units'] > row['held'] + row['consumed'] + row['refunded']:
            connection.execute("INSERT INTO portal_credit_uses(id,job_id,order_id,state) VALUES (%s,%s,%s,'held')", (job, job, row['id']))
            return
    reject(402, 'BILLING_NO_CREDITS', 'Нужен один разбор. Открой покупки в аккаунте или вернись к сохранённым отчётам.')


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=5, max_length=1500)


def request_refund(owner, order_id, body):
    with database() as connection:
        lock(connection, owner)
        rows = connection.execute(BALANCES + ' AND o.id=%s', (owner, order_id)).fetchall()
        if not rows:
            reject(404, 'BILLING_ORDER', 'Заказ не найден.')
        row = rows[0]
        existing = connection.execute('SELECT id,status FROM portal_refunds WHERE order_id=%s', (order_id,)).fetchone()
        if existing:
            return {'refund': existing}
        remaining = row['units'] - row['held'] - row['consumed']
        if row['status'] != 'succeeded' or remaining <= 0 or row['held']:
            reject(409, 'BILLING_REFUND_BUSY', 'Дождись завершения разборов. Здесь можно вернуть неиспользованный остаток; по другим случаям обратись в поддержку.')
        refund_id = uuid4()
        connection.execute('INSERT INTO portal_refunds(id,order_id,units,amount,reason) VALUES (%s,%s,%s,%s,%s)',
                           (refund_id, order_id, remaining, row['amount'] // row['units'] * remaining, body.reason))
    return {'refund': {'id': refund_id, 'status': 'requested'}}


def refund_queue(account):
    from .owner_dashboard import require_owner
    with database() as connection:
        require_owner(connection, account['owner_id'])
        return {'refunds': connection.execute('''SELECT r.*,o.owner_id,o.mode FROM portal_refunds r
            JOIN portal_orders o ON o.id=r.order_id ORDER BY r.created_at DESC LIMIT 100''').fetchall()}


def approve_refund(request, account, refund_id, body):
    from .portal_access import reauthenticated
    cfg = config()
    if not cfg['ready']:
        reject(503, 'BILLING_UNAVAILABLE', 'Магазин временно недоступен.')
    with database() as connection:
        reauthenticated(connection, request, account, body.current_password, owner_only=True)
        row = connection.execute('''SELECT r.*,o.owner_id,o.payment_id,o.mode,o.shop_id,o.request_payload AS payment_request
            FROM portal_refunds r JOIN portal_orders o ON o.id=r.order_id WHERE r.id=%s''', (refund_id,)).fetchone()
        if not row:
            reject(404, 'BILLING_REFUND', 'Возврат не найден.')
        lock(connection, row['owner_id'] or str(row['order_id']))
        row = connection.execute('''SELECT r.*,o.owner_id,o.payment_id,o.mode,o.shop_id,o.request_payload AS payment_request
            FROM portal_refunds r JOIN portal_orders o ON o.id=r.order_id WHERE r.id=%s FOR UPDATE OF r''', (refund_id,)).fetchone()
        if (row['mode'], row['shop_id']) != (cfg['mode'], cfg['shop']):
            reject(409, 'BILLING_STORE_CHANGED', 'Проверь магазин этого заказа.')
        if row['status'] in ('succeeded', 'canceled'):
            return {'status': row['status']}
        if row['submitted_at'] is None:
            payload = {'payment_id': row['payment_id'], 'amount': money(row['amount']), 'description': 'Возврат неиспользованных разборов NARMA Vision'}
            receipt = row['payment_request'].get('receipt')
            if receipt:
                item = dict(receipt['items'][0], quantity=str(row['units']))
                payload['receipt'] = {'customer': receipt['customer'], 'items': [item]}
            connection.execute("UPDATE portal_refunds SET status='pending',submitted_at=now(),request_payload=%s WHERE id=%s", (Jsonb(payload), refund_id))
    return sync_refund(refund_id, allow_submit=True)


def sync_refund(refund_id, *, allow_submit=False):
    cfg = config()
    if not cfg['ready']:
        raise ProviderUnavailable()
    with database() as connection:
        initial = connection.execute('''SELECT o.owner_id,o.id FROM portal_refunds r JOIN portal_orders o ON o.id=r.order_id
            WHERE r.id=%s''', (refund_id,)).fetchone()
        if not initial:
            reject(404, 'BILLING_REFUND', 'Возврат не найден.')
        lock(connection, initial['owner_id'] or str(initial['id']))
        row = connection.execute('''SELECT r.*,o.payment_id,o.mode,o.shop_id FROM portal_refunds r
            JOIN portal_orders o ON o.id=r.order_id WHERE r.id=%s FOR UPDATE OF r''', (refund_id,)).fetchone()
        if (row['mode'], row['shop_id']) != (cfg['mode'], cfg['shop']):
            raise ProviderUnavailable()
        if row['status'] != 'pending':
            return {'status': row['status']}
        if row['provider_id']:
            data = provider('GET', '/refunds/' + row['provider_id'], cfg)
        elif allow_submit and datetime.now(timezone.utc)-row['submitted_at'] < timedelta(hours=23):
            data = provider('POST', '/refunds', cfg, row['request_payload'], row['id'])
        else:
            reject(409, 'BILLING_REFUND_RECONCILE', 'Нужна сверка возврата в кабинете провайдера. Новое списание не выполняется.')
        if (not PROVIDER_ID.fullmatch(str(data.get('id', '')))
                or (row['provider_id'] and data['id'] != row['provider_id'])
                or data.get('payment_id') != row['payment_id'] or data.get('amount') != money(row['amount'])
                or data.get('status') not in ('pending', 'succeeded', 'canceled')):
            raise ProviderUnavailable()
        connection.execute('UPDATE portal_refunds SET provider_id=%s,status=%s,updated_at=now() WHERE id=%s', (data['id'], data['status'], refund_id))
        return {'status': data['status']}


class Hook(BaseModel):
    type: str = Field(max_length=50)
    event: str = Field(max_length=60)
    object: dict


def webhook(body):
    # Payload fields only locate an existing intent. Settlement uses an
    # authenticated provider GET, never the supplied status, amount or owner.
    obj = body.object
    provider_id = obj.get('id')
    if not isinstance(provider_id, str) or not PROVIDER_ID.fullmatch(provider_id):
        return {'received': True}
    if body.event.startswith('payment.'):
        metadata = obj.get('metadata')
        hint = metadata.get('order_id') if isinstance(metadata, dict) else None
        try:
            hint = UUID(hint) if isinstance(hint, str) else None
        except ValueError:
            hint = None
        with database() as connection:
            row = connection.execute('SELECT * FROM portal_orders WHERE payment_id=%s OR id=%s', (provider_id, hint)).fetchone()
        if row and row['owner_id'] and row['status'] == 'pending':
            cfg = config()
            if not cfg['ready'] or (row['mode'], row['shop_id']) != (cfg['mode'], cfg['shop']):
                raise ProviderUnavailable()
            data = provider('GET', '/payments/' + provider_id, cfg)
            validate_payment(data, row)
            with database() as connection:
                lock(connection, row['owner_id'])
                # Bind unknown payment IDs only after identity validation.
                connection.execute('''UPDATE portal_orders SET payment_id=%s WHERE id=%s AND status='pending'
                    AND (payment_id IS NULL OR payment_id=%s)''', (data['id'], row['id'], data['id']))
            sync_order(row['owner_id'], row['id'])
    elif body.event == 'refund.succeeded':
        with database() as connection:
            row = connection.execute('SELECT id FROM portal_refunds WHERE provider_id=%s', (provider_id,)).fetchone()
        if row:
            sync_refund(row['id'])
    return {'received': True}


def attach_billing(app):
    from .portal_access import Reauthenticate
    router = APIRouter(prefix='/api/billing')

    @router.get('')
    def get(account=Depends(account_required)):
        return account_billing(account['owner_id'])

    @router.post('/orders', dependencies=[Depends(csrf)])
    async def purchase(request: Request, account=Depends(account_required)):
        rate_limit(request, 'invite', account['email'])
        return await run_in_threadpool(buy, account, await json_body(request, Buy))

    @router.post('/orders/{order_id:uuid}/refresh', dependencies=[Depends(csrf)])
    def refresh(order_id: UUID, account=Depends(account_required)):
        return sync_order(account['owner_id'], order_id)

    @router.post('/orders/{order_id:uuid}/refund', dependencies=[Depends(csrf)])
    async def refund(order_id: UUID, request: Request, account=Depends(account_required)):
        return await run_in_threadpool(request_refund, account['owner_id'], order_id, await json_body(request, RefundRequest))

    @router.get('/refunds')
    def queue(account=Depends(account_required)):
        return refund_queue(account)

    @router.post('/refunds/{refund_id:uuid}/approve', dependencies=[Depends(csrf)])
    async def approve(refund_id: UUID, request: Request, account=Depends(account_required)):
        try:
            return await run_in_threadpool(approve_refund, request, account, refund_id, await json_body(request, Reauthenticate))
        except ProviderUnavailable:
            reject(503, 'BILLING_REFUND_PENDING', 'Результат возврата пока неизвестен. Остаток остаётся заблокирован до сверки.')

    @router.post('/webhook')
    async def hook(request: Request):
        try:
            return await run_in_threadpool(webhook, await json_body(request, Hook))
        except ProviderUnavailable:
            reject(503, 'BILLING_CALLBACK_RETRY', 'Проверка временно недоступна.')

    app.include_router(router)


def check_chat(connection, owner, job):
    if os.getenv('NARMA_BILLING_ENFORCE') != '1':
        return
    lock(connection, owner)
    credit = connection.execute('''SELECT 1 FROM portal_credit_uses c JOIN portal_orders o ON o.id=c.order_id
        WHERE c.job_id=%s AND c.state='consumed' AND o.owner_id=%s AND o.mode='live' AND o.status='succeeded' ''', (job, owner)).fetchone()
    if not credit:
        reject(402, 'BILLING_CHAT', 'Чат входит в оплаченный разбор. Сохранённый отчёт остаётся доступен.')
    count = connection.execute("SELECT count(*) AS n FROM coach_chat_turns WHERE owner_id=%s AND job_id=%s AND state IN ('running','succeeded')", (owner, job)).fetchone()['n']
    if count >= 40:
        reject(429, 'BILLING_CHAT_LIMIT', 'В этом разборе использованы 40 ответов тренера. Отчёт и история чата сохранены.')
