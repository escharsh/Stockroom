from app import create_app, LOCATIONS
from extensions import db
from models import User, Item, Stock, Movement
from datetime import datetime, timedelta, timezone
app=create_app()
with app.app_context():
    if User.query.filter_by(username='admin').first():
        print('Demo already exists; no data changed.')
    else:
        user=User(username='admin',email='admin@example.test'); user.set_password('College@123')
        db.session.add(user); db.session.flush()
        products=[('Industrial safety helmet','Safety',45,349),('Cordless barcode scanner','Electronics',14,2499),('Heavy duty storage bin','Storage',280,599),('Packing tape · 48 mm','Packaging',160,89),('Nitrile safety gloves','Safety',9,249),('Thermal shipping labels','Packaging',124,199),('Pallet stretch wrap','Packaging',76,449),('Digital weighing scale','Electronics',32,3299)]
        for j,(name,category,qty,price) in enumerate(products):
            item=Item(name=name,category=category,quantity=qty,price=price,user_id=user.id); db.session.add(item); db.session.flush()
            # Opening receipts and dispatches reconcile exactly to the current balance.
            for k in range(7):
                amount=qty+21 if k==0 else 0
                if amount: db.session.add(Movement(item_id=item.id,kind='Receive',source='Supplier',destination=LOCATIONS[j%3],quantity=amount,reference='DEMO-OPEN',created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=6)))
                db.session.add(Movement(item_id=item.id,kind='Dispatch',source=LOCATIONS[j%3],destination='Customer',quantity=3,reference=f'DEMO-{j}-{k}',created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=6-k)))
            db.session.add(Stock(item_id=item.id,location=LOCATIONS[j%3],quantity=qty))
        db.session.commit(); print('Demo ready: admin / College@123')
