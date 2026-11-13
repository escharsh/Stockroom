"""Add a reconciled synthetic workflow scenario once; preserve existing records."""
from datetime import datetime, timezone, timedelta, date
from app import create_app, LOCATIONS
from extensions import db
from models import User, Item, Movement
from enterprise_models import Supplier, Order, OrderLine, AuditEvent, Membership
from services import transition

app=create_app()
with app.app_context():
    admin=User.query.filter_by(username='admin').first()
    marker='workflow-scenario-v2'
    if not admin:
        raise SystemExit('Run seed_demo.py first.')
    if AuditEvent.query.filter_by(owner_id=admin.id,request_key=marker).first():
        print('Workflow scenario already exists; no data changed.')
    else:
        items=Item.query.filter_by(user_id=admin.id).order_by(Item.id).limit(8).all()
        if len(items)<8: raise SystemExit('The workflow scenario needs the original eight sample products.')
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        # Each sample receipt is matched by an equal dispatch. Net stock effect is zero.
        for j,item in enumerate(items):
            for day in range(30):
                qty=2+(j%4)+(29-day)//5+((day*3+j)%4)
                stamp=now-timedelta(days=day)
                loc=LOCATIONS[j%3]
                db.session.add(Movement(item_id=item.id,kind='Receive',source='Historical supplier',destination=loc,quantity=qty,reference='SAMPLE-HISTORY',created_at=stamp-timedelta(seconds=1)))
                db.session.add(Movement(item_id=item.id,kind='Dispatch',source=loc,destination='Historical customer',quantity=qty,reference='SAMPLE-HISTORY',created_at=stamp))
        suppliers=[]
        for name,lead in [('Apex Industrial Supply',7),('Northline Packaging',5),('Meridian Safety Products',10)]:
            supplier=Supplier.query.filter_by(owner_id=admin.id,name=name).first()
            if not supplier:
                supplier=Supplier(owner_id=admin.id,name=name,email='orders@'+name.split()[0].lower()+'.example',lead_days=lead);db.session.add(supplier)
            suppliers.append(supplier)
        db.session.flush()
        def create(kind,partner,location,lines,status='Draft',supplier=None,days=5):
            o=Order(owner_id=admin.id,created_by=admin.id,kind=kind,partner=partner,location=location,supplier_id=supplier.id if supplier else None,due_date=date.today()+timedelta(days=days))
            for item,quantity in lines: o.lines.append(OrderLine(item_id=item.id,quantity=quantity,unit_paise=round(item.price*100)))
            db.session.add(o);db.session.flush()
            if status=='Approved': transition(o,'approve')
            db.session.flush()
            db.session.add(AuditEvent(owner_id=admin.id,actor_id=admin.id,action='Sample order initialized',entity=o.reference,detail='Synthetic workflow scenario'))
            return o
        create('purchase',suppliers[0].name,LOCATIONS[0],[(items[2],40),(items[3],60)],supplier=suppliers[0])
        create('purchase',suppliers[1].name,LOCATIONS[2],[(items[5],80),(items[6],30)],status='Approved',supplier=suppliers[1],days=-2)
        partial=create('purchase',suppliers[2].name,LOCATIONS[1],[(items[1],50),(items[4],40)],status='Approved',supplier=suppliers[2],days=3)
        transition(partial,'receive',{str(partial.lines[0].id):20,str(partial.lines[1].id):10})
        so=create('sales','Riverside Distribution',LOCATIONS[1],[(items[1],8),(items[4],5)],days=2)
        transition(so,'reserve')
        create('sales','Metro Fulfillment Services',LOCATIONS[0],[(items[0],10),(items[3],25)],days=4)
        for username,role in [('ops.manager','manager'),('warehouse.ops','operator'),('warehouse.viewer','viewer')]:
            if not User.query.filter_by(username=username).first():
                u=User(username=username);u.set_password('Stockroom@2026');db.session.add(u);db.session.flush()
                db.session.add(Membership(user_id=u.id,owner_id=admin.id,role=role))
        db.session.add(AuditEvent(owner_id=admin.id,actor_id=admin.id,action='Workspace initialized',entity='Operational scenario',detail='Synthetic historical movements, purchase and customer orders, and role accounts. Not real business data.',request_key=marker))
        db.session.commit()
        print('Workflow scenario initialized. Existing data preserved.')
