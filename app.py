import os, secrets, csv, io
from pathlib import Path
from datetime import date, timedelta
from sqlalchemy import func
from enterprise import init_enterprise, access, locations, require_roles, event
from enterprise_models import Order, OrderLine, StockPolicy, AuditEvent
from services import lock_available, held_units
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, session, jsonify, Response
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, login_manager
from models import User, Item, Stock, Movement
from sqlalchemy import update
from forecast import forecast

LOCATIONS = ['A-01 · Main warehouse', 'B-02 · Distribution', 'C-03 · Reserve']

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32), SQLALCHEMY_DATABASE_URI='sqlite:///warehouse.db', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    app.config.update(test_config or {})
    if not os.environ.get('SECRET_KEY'):
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        key_path = Path(app.instance_path) / '.session-key'
        if not key_path.exists():
            try:
                with key_path.open('x') as key_file: key_file.write(secrets.token_hex(32))
            except FileExistsError: pass
        app.config['SECRET_KEY'] = key_path.read_text()
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    @app.before_request
    def protect():
        if 'csrf' not in session: session['csrf'] = secrets.token_hex(24)
        if request.method == 'POST' and request.form.get('csrf') != session['csrf']:
            return 'Invalid form token. Reload the page.', 400

    @app.route('/login', methods=['GET','POST'])
    def login():
        error = None
        if request.method == 'POST':
            user = User.query.filter_by(username=request.form.get('username')).first()
            if user and user.check_password(request.form.get('password','')):
                login_user(user)
                return redirect('/')
            error = 'Incorrect username or password.'
        return render_template('warehouse_login.html', error=error)

    @app.post('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect('/login')

    def owned():
        return Item.query.filter_by(user_id=access()[0])

    @app.get('/')
    @app.get('/inventory')
    @app.get('/stock-operations')
    @app.get('/planning')
    @app.get('/history')
    @login_required
    def home():
        items = owned().order_by(Item.id).all()
        stocks = Stock.query.filter(Stock.item_id.in_([i.id for i in items])).all()
        moves = Movement.query.filter(Movement.item_id.in_([i.id for i in items])).order_by(Movement.created_at.desc(),Movement.id.desc()).all()
        totals = {i.id:sum(s.quantity for s in stocks if s.item_id==i.id) for i in items}
        owner, role = access()
        policies = {p.item_id:p for p in StockPolicy.query.filter(StockPolicy.item_id.in_(list(totals))).all()}
        low = sum(totals[i.id] < (policies[i.id].minimum if i.id in policies else 20) for i in items)
        over = sum(totals[i.id] > (policies[i.id].maximum if i.id in policies else 200) for i in items)
        start = datetime.now(timezone.utc).replace(tzinfo=None).date() - timedelta(days=6)
        chart = []
        for offset in range(7):
            day=start+timedelta(days=offset)
            chart.append({'day':day.strftime('%d %b'),'inbound':sum(m.quantity for m in moves if m.kind=='Receive' and m.created_at.date()==day),'outbound':sum(m.quantity for m in moves if m.kind=='Dispatch' and m.created_at.date()==day)})
        orders = Order.query.filter_by(owner_id=owner).all()
        reserved = {i.id:sum(l.quantity for o in orders if o.kind=='sales' and o.status=='Reserved' for l in o.lines if l.item_id==i.id) for i in items}
        incoming = {i.id:sum(l.quantity-l.received for o in orders if o.kind=='purchase' and o.status in ('Approved','Partially received') for l in o.lines if l.item_id==i.id) for i in items}
        predictions={i.id:forecast(i.id,moves,totals[i.id],lead_days=policies[i.id].lead_days if i.id in policies else 7,incoming=incoming[i.id],reserved=reserved[i.id]) for i in items}
        ranked=sorted(items,key=lambda i:totals[i.id]*i.price,reverse=True)
        total_value=sum(totals[i.id]*i.price for i in items)
        abc={}; cumulative=0
        for item in ranked:
            ratio=cumulative/total_value if total_value else 1
            abc[item.id]='A' if ratio<.8 else 'B' if ratio<.95 else 'C'
            cumulative+=totals[item.id]*item.price
        metrics=dict(open_purchase=sum(o.kind=='purchase' and o.status not in ('Received','Cancelled') for o in orders),
                     awaiting_ship=sum(o.kind=='sales' and o.status=='Reserved' for o in orders),
                     overdue=sum(o.status not in ('Received','Shipped','Cancelled') and o.due_date<date.today() for o in orders),
                     reserved=sum(reserved.values()))
        page={'/':'overview','/inventory':'inventory','/stock-operations':'operations','/planning':'planning','/history':'history'}[request.path]
        activity=AuditEvent.query.filter_by(owner_id=owner).order_by(AuditEvent.id.desc()).limit(6).all()
        return render_template('warehouse.html',page=page,policies=policies,abc=abc,reserved=reserved,incoming=incoming,
            predictions=predictions,items=items,stocks=stocks,moves=moves,totals=totals,low=low,over=over,
            locations=locations(owner),value=total_value,chart=chart,metrics=metrics,activity=activity,orders=orders)

    @app.post('/item')
    @require_roles('admin','manager')
    def add_item():
        try:
            name=request.form.get('name','').strip()
            price=float(request.form.get('price','0'))
            if not name or len(name)>120 or not 0<=price<=100000000: raise ValueError('Enter a name and valid price.')
            if owned().filter_by(name=name).first(): raise ValueError('That product name already exists.')
            item=Item(name=name,category=request.form.get('category','General')[:80],price=price,quantity=0,user_id=current_user.id)
            db.session.add(item); db.session.flush(); event('Product created',f'WH-{item.id:04}',item.name); db.session.commit()
            session['notice']='Product created. Receive stock to add its opening balance.'
        except ValueError as e: session['notice']=str(e)
        return redirect('/inventory')

    @app.post('/movement')
    @require_roles('admin','manager','operator')
    def move():
        try:
            item=owned().filter_by(id=request.form.get('item_id',type=int)).first()
            kind=request.form.get('kind')
            qty=int(request.form.get('quantity','0'))
            source=request.form.get('source'); dest=request.form.get('destination')
            if not item or kind not in ['Receive','Dispatch','Transfer'] or not 0<qty<=1000000: raise ValueError('Select a product and a positive whole quantity.')
            if kind in ['Dispatch','Transfer'] and source not in locations(access()[0]): raise ValueError('Select a source location.')
            if kind in ['Receive','Transfer'] and dest not in locations(access()[0]): raise ValueError('Select a destination location.')
            if kind=='Transfer' and source==dest: raise ValueError('Choose different locations for a transfer.')
            if kind in ['Dispatch','Transfer']:
                lock_available(item.id,source,qty,decrement=True)
            if kind in ['Receive','Transfer']:
                stock=Stock.query.filter_by(item_id=item.id,location=dest).first()
                if stock: stock.quantity+=qty
                else: db.session.add(Stock(item_id=item.id,location=dest,quantity=qty))
            item.quantity += qty if kind=='Receive' else -qty if kind=='Dispatch' else 0
            db.session.add(Movement(item_id=item.id,kind=kind,source=source if kind!='Receive' else 'Supplier',destination=dest if kind!='Dispatch' else 'Customer',quantity=qty,reference=request.form.get('reference','')[:120]))
            event('Stock '+kind,f'WH-{item.id:04}',f'{qty} units; {source} → {dest}')
            db.session.commit(); session['notice']=f'{kind} recorded successfully.'
        except (ValueError,TypeError) as e:
            db.session.rollback(); session['notice']=str(e)
        return redirect('/stock-operations')

    @app.get('/export/<report>')
    @login_required
    def export(report):
        out=io.StringIO(); writer=csv.writer(out)
        def safe(v):
            return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v
        if report=='stock':
            writer.writerow(['SKU','Product','Category','Location','On hand','Reserved','Available','Unit price INR'])
            for i in owned().all():
                for s in Stock.query.filter_by(item_id=i.id).all(): writer.writerow([f'WH-{i.id:04}',safe(i.name),safe(i.category),safe(s.location),s.quantity,db.session.scalar(db.select(held_units(i.id,s.location))),s.quantity-db.session.scalar(db.select(held_units(i.id,s.location))),i.price])
        elif report=='movements':
            writer.writerow(['ID','Timestamp UTC','Product','Type','From','To','Quantity','Reference'])
            for m in Movement.query.join(Item).filter(Item.user_id==access()[0]).all():
                writer.writerow([m.id,m.created_at,safe(db.session.get(Item,m.item_id).name),m.kind,safe(m.source),safe(m.destination),m.quantity,safe(m.reference)])
        else: return 'Report not found',404
        return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename={report}.csv'})

    @app.errorhandler(403)
    def forbidden(error):
        return render_template('forbidden.html',page=''),403

    init_enterprise(app)
    return app

if __name__=='__main__':
    create_app().run(host='127.0.0.1',port=5000,debug=False)
