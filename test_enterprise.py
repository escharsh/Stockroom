from uuid import uuid4
from datetime import date, datetime, timedelta
import pytest
from werkzeug.datastructures import MultiDict
from app import create_app, LOCATIONS
from extensions import db
from models import User, Item, Stock, Movement
from enterprise_models import Supplier, Order, OrderLine, Membership, AuditEvent, Warehouse, StockPolicy
from services import available
from forecast import backtest, forecast
from test_warehouse import setup


def send(env, url, **values):
    app, client, csrf, item_id = env
    data=MultiDict([('csrf',csrf),('request_key',str(uuid4()))])
    for key,value in values.items():
        for v in value if isinstance(value,list) else [value]: data.add(key,str(v))
    return client.post(url,data=data,follow_redirects=True)


def order(env, kind='sales', qty=4, extra=False):
    item=db.session.get(Item,env[3])
    supplier=Supplier.query.first()
    if not supplier:
        supplier=Supplier(owner_id=item.user_id,name='Supplier',lead_days=7);db.session.add(supplier);db.session.commit()
    products=[item.id];quantities=[qty]
    if extra:
        second=Item(name='Second',quantity=2,price=7,user_id=item.user_id);db.session.add(second);db.session.flush()
        db.session.add(Stock(item_id=second.id,location=LOCATIONS[0],quantity=2));db.session.commit()
        products.append(second.id);quantities.append(3)
    response=send(env,f'/orders/create/{kind}',product_id=products,line_quantity=quantities,
                  location=LOCATIONS[0],partner='Customer',supplier_id=supplier.id,due_date=date.today().isoformat())
    assert response.status_code==200
    return Order.query.order_by(Order.id.desc()).first()


def test_partial_receiving_and_over_receipt_rollback(setup):
    po=order(setup,'purchase',10)
    send(setup,f'/orders/{po.id}/approve')
    line=po.lines[0]
    send(setup,f'/orders/{po.id}/receive',**{f'received_{line.id}':4})
    db.session.expire_all()
    assert po.status=='Partially received' and line.received==4
    assert Stock.query.first().quantity==14
    count=AuditEvent.query.count()
    send(setup,f'/orders/{po.id}/receive',**{f'received_{line.id}':7})
    assert line.received==4 and AuditEvent.query.count()==count
    send(setup,f'/orders/{po.id}/cancel')
    assert po.status=='Partially received'
    send(setup,f'/orders/{po.id}/receive',**{f'received_{line.id}':6})
    db.session.expire_all()
    assert po.status=='Received' and line.received==10
    assert Stock.query.first().quantity==20
    assert db.session.get(Item,setup[3]).quantity==20


def test_reservation_blocks_raw_dispatch_and_cancel_releases(setup):
    so=order(setup,qty=8)
    send(setup,f'/orders/{so.id}/reserve')
    assert available(setup[3],LOCATIONS[0])==2
    client=setup[1]
    client.post('/movement',data={'csrf':setup[2],'item_id':setup[3],'kind':'Dispatch','quantity':3,'source':LOCATIONS[0]})
    db.session.expire_all()
    assert Stock.query.first().quantity==10 and so.status=='Reserved'
    send(setup,f'/orders/{so.id}/cancel')
    assert available(setup[3],LOCATIONS[0])==10
    assert so.status=='Cancelled'


def test_multiline_reservation_is_atomic(setup):
    so=order(setup,qty=4,extra=True)
    send(setup,f'/orders/{so.id}/reserve')
    db.session.expire_all()
    assert so.status=='Draft'
    assert available(setup[3],LOCATIONS[0])==10
    assert Stock.query.filter_by(item_id=setup[3]).first().quantity==10


def test_ship_once_even_with_distinct_request_keys(setup):
    so=order(setup,qty=4)
    send(setup,f'/orders/{so.id}/reserve')
    send(setup,f'/orders/{so.id}/ship')
    send(setup,f'/orders/{so.id}/ship')
    db.session.expire_all()
    assert so.status=='Shipped' and Stock.query.first().quantity==6
    assert Movement.query.filter_by(kind='Dispatch').count()==1
    assert available(setup[3],LOCATIONS[0])==6


def test_replayed_receipt_is_not_posted_twice(setup):
    po=order(setup,'purchase',10);send(setup,f'/orders/{po.id}/approve')
    data={'csrf':setup[2],'request_key':str(uuid4()),f'received_{po.lines[0].id}':3}
    for _ in range(2): setup[1].post(f'/orders/{po.id}/receive',data=data)
    db.session.expire_all()
    assert po.lines[0].received==3
    assert Stock.query.first().quantity==13
    assert Movement.query.count()==1


def test_multiline_receipt_rolls_back_every_line_on_failure(setup):
    po=order(setup,'purchase',10,extra=True)
    send(setup,f'/orders/{po.id}/approve')
    before={s.item_id:s.quantity for s in Stock.query.all()}
    send(setup,f'/orders/{po.id}/receive',**{f'received_{po.lines[0].id}':2,f'received_{po.lines[1].id}':4})
    db.session.expire_all()
    assert po.status=='Approved'
    assert all(line.received==0 for line in po.lines)
    assert {s.item_id:s.quantity for s in Stock.query.all()}==before
    assert Movement.query.count()==0


@pytest.mark.parametrize('role',['viewer','operator'])
def test_permission_boundaries(setup,role):
    po=order(setup,'purchase',10)
    owner=db.session.get(Item,setup[3]).user_id
    staff=User(username=role);staff.set_password('long-password');db.session.add(staff);db.session.flush()
    db.session.add(Membership(owner_id=owner,user_id=staff.id,role=role));db.session.commit()
    c=setup[1];c.post('/logout',data={'csrf':setup[2]})
    c.post('/login',data={'csrf':setup[2],'username':role,'password':'long-password'})
    for path in ['/team','/audit','/orders/purchase/new','/orders/sales/new']: assert c.get(path).status_code==403
    assert c.get('/inventory').status_code==200
    assert c.post(f'/orders/{po.id}/approve',data={'csrf':setup[2],'request_key':str(uuid4())}).status_code==403
    assert c.post('/item',data={'csrf':setup[2],'name':'Bad'}).status_code==403
    if role=='viewer':
        assert c.post('/movement',data={'csrf':setup[2]}).status_code==403
    else:
        po.status='Approved';db.session.commit()
        assert c.post(f'/orders/{po.id}/receive',data={'csrf':setup[2],'request_key':str(uuid4()),f'received_{po.lines[0].id}':2}).status_code==302
        db.session.expire_all();assert Stock.query.first().quantity==12


def test_cross_workspace_order_and_supplier_isolation(setup):
    owner=User(username='different');owner.set_password('password');db.session.add(owner);db.session.flush()
    foreign=Order(owner_id=owner.id,created_by=owner.id,kind='sales',partner='Private Customer',location=LOCATIONS[0],due_date=date.today())
    db.session.add(foreign);db.session.commit()
    assert b'Private Customer' not in setup[1].get('/orders/sales').data
    send(setup,f'/orders/{foreign.id}/cancel')
    assert foreign.status=='Draft'


def test_configuration_and_all_pages(setup):
    send(setup,'/network/warehouse',code='D-04',name='Regional hub',city='Pune',return_to='/network')
    assert Warehouse.query.filter_by(label='D-04 · Regional hub').first()
    assert Warehouse.query.count()==4
    send(setup,f'/policy/{setup[3]}',minimum=5,maximum=100,lead_days=10,return_to='/inventory')
    assert StockPolicy.query.first().lead_days==10
    for path in ['/','/inventory','/stock-operations','/planning','/history','/orders/purchase','/orders/sales','/orders/purchase/new','/orders/sales/new','/network','/team','/audit']:
        response=setup[1].get(path)
        assert response.status_code==200,path
        assert b'College project' not in response.data


def test_forecast_to_purchase_prefill(setup):
    item=db.session.get(Item,setup[3])
    db.session.add(Supplier(owner_id=item.user_id,name='Forecast supplier',lead_days=7))
    db.session.commit()
    page=setup[1].get(f'/orders/purchase?item_id={item.id}&quantity=45')
    assert page.status_code==200
    assert f'value="{item.id}" selected'.encode() in page.data
    assert b'aria-label="Order quantity" value="45"' in page.data


def test_model_backtest_and_inventory_position():
    values=[2+i for i in range(30)]
    score=backtest(values)
    assert score['model']=='Linear regression'
    assert score['mae']==0 and score['baseline_mae']>0 and score['folds']==7
    now=datetime(2026,10,30,12)
    moves=[Movement(item_id=1,kind='Dispatch',quantity=5,created_at=now-timedelta(days=i)) for i in range(30)]
    result=forecast(1,moves,10,now,lead_days=7,incoming=15,reserved=4)
    assert result['reorder']==14 and result['days']==1.2
    assert result['folds']==7


def test_concurrent_reservations_do_not_overallocate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'concurrent.db')})
    with app.app_context():
        u=User(username='concurrent');u.set_password('password');db.session.add(u);db.session.flush()
        i=Item(name='Only ten',quantity=10,price=5,user_id=u.id);db.session.add(i);db.session.flush()
        db.session.add(Stock(item_id=i.id,location=LOCATIONS[0],quantity=10))
        orders=[]
        for _ in range(2):
            o=Order(owner_id=u.id,created_by=u.id,kind='sales',partner='Buyer',location=LOCATIONS[0],due_date=date.today())
            o.lines.append(OrderLine(item_id=i.id,quantity=6,unit_paise=500));db.session.add(o);orders.append(o)
        db.session.commit();ids=[o.id for o in orders];item_id=i.id
    barrier=Barrier(2)
    def reserve(order_id):
        with app.test_client() as c:
            c.get('/login')
            with c.session_transaction() as s: token=s['csrf']
            c.post('/login',data={'csrf':token,'username':'concurrent','password':'password'})
            barrier.wait(timeout=10)
            return c.post(f'/orders/{order_id}/reserve',data={'csrf':token,'request_key':str(uuid4())}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(reserve,ids))==[302,302]
    with app.app_context():
        assert Order.query.filter_by(status='Reserved').count()==1
        assert available(item_id,LOCATIONS[0])==4
