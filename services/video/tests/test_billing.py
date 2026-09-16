from datetime import datetime, timedelta, timezone
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from psycopg.types.json import Jsonb
import pytest
from narma_video import billing
from narma_video.db import database
from test_hero_pool import browser, seed, OWNER


@pytest.fixture
def shop(browser, monkeypatch):
    values={'NARMA_BILLING_MODE':'test','YOOKASSA_SHOP_ID':'123456','YOOKASSA_SECRET_KEY':'synthetic_only_secret',
        'NARMA_SELLER_NAME':'Synthetic seller','NARMA_SUPPORT_EMAIL':'help@example.test','NARMA_TERMS_VERSION':'test-v1',
        'NARMA_TERMS_URL':'https://example.test/terms','NARMA_PRIVACY_URL':'https://example.test/privacy',
        'NARMA_FULFILLMENT_READY':'1','NARMA_RECEIPT_MODE':'external','NARMA_EXTERNAL_RECEIPTS_READY':'1'}
    for key,value in values.items(): monkeypatch.setenv(key,value)
    with database() as con: con.execute("TRUNCATE portal_auth_limits")
    billing.attach_billing(browser.app)
    def unavailable(*args, **kwargs): raise billing.ProviderUnavailable()
    monkeypatch.setattr(billing,'provider',unavailable)
    return browser


def purchase(c, product='five'):
    body={'id':str(uuid4()),'product':product,'accepted':True,'terms_version':'test-v1'}
    response=c.post('/api/billing/orders',json=body)
    assert response.status_code==503
    return body


def payment(row, **changes):
    return {'id':'provider-payment-000001','status':'succeeded','paid':True,'test':row['mode']=='test',
        'amount':billing.money(row['amount']),'recipient':{'account_id':row['shop_id']},'metadata':{'order_id':str(row['id'])},**changes}


def settle(c, body, monkeypatch):
    with database() as con: row=con.execute('SELECT * FROM portal_orders WHERE id=%s',(body['id'],)).fetchone()
    monkeypatch.setattr(billing,'provider',lambda *a,**kw:payment(row))
    response=c.post(f"/api/billing/orders/{body['id']}/refresh",json={})
    assert response.status_code==200,response.text
    return row


def test_configuration_defaults_and_mode_isolation(monkeypatch):
    monkeypatch.delenv('NARMA_BILLING_MODE',raising=False)
    assert not billing.config()['ready']
    assert billing.checkout_url('javascript:alert(1)') is None
    assert billing.checkout_url('https://yookassa.ru.evil.test/pay') is None
    assert billing.checkout_url('https://yookassa.ru/pay')=='https://yookassa.ru/pay'


def test_timeout_retry_webhook_are_idempotent_and_owned(shop,monkeypatch):
    body=purchase(shop)
    data=shop.get('/api/billing').json()
    assert len(data['orders'])==1 and data['balance']==0
    row=settle(shop,body,monkeypatch)
    for _ in range(2):
        assert shop.post('/api/billing/webhook',json={'type':'notification','event':'payment.succeeded','object':payment(row)}).status_code==200
        assert shop.post('/api/billing/orders',json=body).status_code==200
    assert shop.get('/api/billing').json()['balance']==5
    assert shop.post(f'/api/billing/orders/{uuid4()}/refresh',json={}).status_code==404
    conflict=dict(body,product='single')
    assert shop.post('/api/billing/orders',json=conflict).status_code==409
    assert shop.post('/api/billing/orders',json=body,headers={'Origin':'https://evil.test'}).status_code==403


@pytest.mark.parametrize('change',[{'test':False},{'amount':{'value':'0.01','currency':'RUB'}},{'recipient':{'account_id':'999'}},{'metadata':{'order_id':str(uuid4())}},{'paid':False}])
def test_forged_provider_receipt_never_grants_credit(shop,monkeypatch,change):
    body=purchase(shop)
    with database() as con: row=con.execute('SELECT * FROM portal_orders WHERE id=%s',(body['id'],)).fetchone()
    monkeypatch.setattr(billing,'provider',lambda *a,**kw:payment(row,**change))
    assert shop.post(f"/api/billing/orders/{body['id']}/refresh",json={}).status_code==503
    assert shop.get('/api/billing').json()['balance']==0


def test_unknown_old_intent_never_reissues_charge(shop,monkeypatch):
    body=purchase(shop)
    with database() as con: con.execute("UPDATE portal_orders SET created_at=now()-interval '25 hours' WHERE id=%s",(body['id'],))
    def unexpected(*a,**k): raise AssertionError('No repeat POST after the provider idempotence window')
    monkeypatch.setattr(billing,'provider',unexpected)
    assert shop.post(f"/api/billing/orders/{body['id']}/refresh",json={}).status_code==409


@pytest.mark.parametrize('state,coaching,expected',[('failed',None,'released'),('deleted',None,'released'),('ready','unavailable','released'),('ready','ready','consumed')])
def test_all_terminal_paths_settle_once(shop,monkeypatch,state,coaching,expected):
    body=purchase(shop);settle(shop,body,monkeypatch)
    job=seed()
    with database() as con:
        con.execute("UPDATE replay_jobs SET state='queued' WHERE id=%s",(job,))
        con.execute("INSERT INTO portal_credit_uses(id,job_id,order_id,state) VALUES (%s,%s,%s,'held')",(job,job,body['id']))
        con.execute('UPDATE replay_jobs SET state=%s,result_payload=%s WHERE id=%s',(state,Jsonb({'coaching':{'status':coaching}}),job))
        con.execute('UPDATE replay_jobs SET state=%s WHERE id=%s',(state,job))
        assert con.execute('SELECT state FROM portal_credit_uses WHERE id=%s',(job,)).fetchone()['state']==expected
    assert shop.get('/api/billing').json()['balance']==(4 if expected=='consumed' else 5)


def test_refund_freezes_remaining_and_unknown_outcome_stays_frozen(shop,monkeypatch):
    body=purchase(shop);settle(shop,body,monkeypatch)
    result=shop.post(f"/api/billing/orders/{body['id']}/refund",json={'reason':'Не успеваю пользоваться'}).json()['refund']
    assert shop.get('/api/billing').json()['balance']==0
    assert shop.post(f"/api/billing/orders/{body['id']}/refund",json={'reason':'Повторная отправка'}).json()['refund']['id']==result['id']
    assert shop.get('/api/billing/refunds').status_code==403
    with database() as con:
        con.execute("UPDATE portal_refunds SET status='pending',submitted_at=now(),request_payload=%s WHERE id=%s",(Jsonb({'amount':billing.money(79900),'payment_id':'provider-payment-000001'}),result['id']))
    def timeout(*args,**kwargs):raise billing.ProviderUnavailable()
    monkeypatch.setattr(billing,'provider',timeout)
    with pytest.raises(billing.ProviderUnavailable):billing.sync_refund(result['id'],allow_submit=True)
    assert shop.get('/api/billing').json()['balance']==0
    monkeypatch.setattr(billing,'provider',lambda *a,**kw:{'id':'provider-refund-00001','payment_id':'provider-payment-000001','amount':billing.money(79900),'status':'canceled'})
    billing.sync_refund(result['id'],allow_submit=True)
    assert shop.get('/api/billing').json()['balance']==5


def test_reservation_serializes_last_credit_and_test_orders_cannot_fund_live(shop,monkeypatch):
    body=purchase(shop,'single');settle(shop,body,monkeypatch)
    monkeypatch.setenv('NARMA_BILLING_ENFORCE','1')
    monkeypatch.setattr(billing,'config',lambda:{'ready':True,'mode':'live'})
    jobs=[seed(match_id=str(8963624410+i)) for i in range(2)]
    def reserve(job):
        try:
            with database() as con:billing.reserve(con,OWNER,job)
            return 200
        except HTTPException as error:return error.status_code
    assert reserve(jobs[0])==402
    with database() as con:con.execute("UPDATE portal_orders SET mode='live' WHERE id=%s",(body['id'],))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,jobs))
    assert sorted(results)==[200,402]
    with database() as con:
        # Account deletion anonymizes the sale and releases a held attempt.
        con.execute('DELETE FROM portal_accounts WHERE owner_id=%s',(OWNER,))
        assert con.execute('SELECT owner_id FROM portal_orders WHERE id=%s',(body['id'],)).fetchone()['owner_id'] is None
        assert con.execute('SELECT state FROM portal_credit_uses WHERE order_id=%s',(body['id'],)).fetchone()['state']=='released'
