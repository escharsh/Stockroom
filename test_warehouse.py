import pytest
from app import create_app, LOCATIONS
from models import User, Item, Stock, Movement
from extensions import db
from forecast import forecast
from datetime import datetime, timedelta

@pytest.fixture
def setup():
    app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:'})
    with app.app_context():
        u=User(username='test');u.set_password('password');db.session.add(u);db.session.flush()
        i=Item(name='Widget',quantity=10,price=5,user_id=u.id);db.session.add(i);db.session.flush()
        db.session.add(Stock(item_id=i.id,location=LOCATIONS[0],quantity=10));db.session.commit()
        client=app.test_client();client.get('/login')
        with client.session_transaction() as s: token=s['csrf']
        client.post('/login',data={'csrf':token,'username':'test','password':'password'})
        yield app,client,token,i.id

def post(setup,**extra):
    app,c,token,i=setup
    return c.post('/movement',data=dict(csrf=token,item_id=i,source=LOCATIONS[0],destination=LOCATIONS[1],**extra),follow_redirects=True)

def test_transfer_conserves_stock(setup):
    response=post(setup,kind='Transfer',quantity=4)
    assert response.status_code==200
    assert sum(s.quantity for s in Stock.query.all())==10
    assert db.session.get(Item,setup[3]).quantity==10
    assert Movement.query.count()==1
    assert sorted(s.quantity for s in Stock.query.all())==[4,6]

@pytest.mark.parametrize('quantity',['11','0','-2','1.5','abc'])
def test_invalid_dispatch_is_atomic(setup,quantity):
    assert post(setup,kind='Dispatch',quantity=quantity).status_code==200
    assert Stock.query.first().quantity==10
    assert Movement.query.count()==0

def test_receive_and_dispatch_reconcile(setup):
    post(setup,kind='Receive',quantity=8)
    post(setup,kind='Dispatch',quantity=3)
    assert sum(s.quantity for s in Stock.query.all())==15
    assert db.session.get(Item,setup[3]).quantity==15
    assert Movement.query.count()==2

def test_security_and_export(setup):
    app,c,token,i=setup
    assert c.post('/movement',data={'quantity':1}).status_code==400
    assert c.get('/export/stock').status_code==200
    other=User(username='other');other.set_password('password');db.session.add(other);db.session.flush()
    foreign=Item(name='Secret',quantity=0,user_id=other.id);db.session.add(foreign);db.session.commit()
    c.post('/movement',data={'csrf':token,'kind':'Receive','quantity':5,'item_id':foreign.id,'destination':LOCATIONS[0]})
    assert foreign.quantity==0
    assert b'Secret' not in c.get('/').data
    c.post('/logout',data={'csrf':token})
    assert c.get('/').status_code==302

def test_forecast_constant_demand():
    now=datetime(2026,10,30,12)
    moves=[Movement(item_id=1,kind='Dispatch',quantity=5,created_at=now-timedelta(days=i)) for i in range(7)]
    f=forecast(1,moves,10,now)
    assert f['daily']==5 and f['reorder']==25 and f['days']==2
    assert forecast(1,moves[:2],10,now)['quality']=='Limited history'
    assert forecast(1,[],10,now)['quality']=='No history'
