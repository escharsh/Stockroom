"""Order processing, warehouse configuration, access control and audit views."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from uuid import uuid4, UUID
from flask import Blueprint, render_template, request, session, redirect, abort, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError, OperationalError
from extensions import db
from models import User, Item, Stock
from enterprise_models import Membership, Warehouse, Supplier, StockPolicy, Order, OrderLine, AuditEvent
from services import available, transition

bp = Blueprint('enterprise', __name__)
DEFAULT_LOCATIONS = ['A-01 · Main warehouse', 'B-02 · Distribution', 'C-03 · Reserve']


def access():
    member = Membership.query.filter_by(user_id=current_user.id).first()
    return (member.owner_id, member.role) if member else (current_user.id, 'admin')


def locations(owner):
    rows = Warehouse.query.filter_by(owner_id=owner).order_by(Warehouse.id).all()
    return [w.label for w in rows] or DEFAULT_LOCATIONS.copy()


def require_roles(*roles):
    def decorate(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if access()[1] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def event(action, entity, detail=''):
    owner, _ = access()
    db.session.add(AuditEvent(owner_id=owner, actor_id=current_user.id,
                              action=action, entity=entity, detail=detail))


def command(*roles):
    """Authorization, replay protection, audit and transaction boundary."""
    def decorate(fn):
        @wraps(fn)
        @require_roles(*roles)
        def wrapped(*args, **kwargs):
            owner, _ = access()
            target = request.form.get('return_to', '/orders/purchase')
            if target not in ('/orders/purchase', '/orders/sales', '/network', '/team', '/inventory'):
                target = '/orders/purchase'
            try:
                key = str(UUID(request.form.get('request_key', '')))
                if AuditEvent.query.filter_by(owner_id=owner, request_key=key).first():
                    session['notice'] = 'This request was already processed. No duplicate transaction was created.'
                    return redirect(target)
                entry = AuditEvent(owner_id=owner, actor_id=current_user.id,
                                   action=fn.__name__.replace('_', ' ').title(),
                                   entity='Workspace', request_key=key)
                db.session.add(entry)
                db.session.flush()  # acquires writer lock before order/stock reads
                message, entity, detail = fn(owner, *args, **kwargs)
                entry.entity, entry.detail = entity, detail
                db.session.commit()
                session['notice'] = message
            except (ValueError, TypeError) as error:
                db.session.rollback()
                session['notice'] = str(error) or 'Invalid request. Reload the form and try again.'
            except IntegrityError:
                db.session.rollback()
                session['notice'] = 'Duplicate request or record. Nothing was posted twice.'
            except OperationalError:
                db.session.rollback()
                session['notice'] = 'The warehouse is processing another transaction. Retry this request.'
            return redirect(target)
        return wrapped
    return decorate


@bp.app_context_processor
def context():
    owner, role = access() if current_user.is_authenticated else (None, None)
    return dict(role=role, workspace_owner=owner, new_key=lambda: str(uuid4()),
                money=lambda paise: f'₹{paise / 100:,.2f}',
                can_manage=role in ('admin', 'manager'), can_operate=role in ('admin', 'manager', 'operator'),
                today=date.today())


@bp.get('/orders/<kind>')
@bp.get('/orders/<kind>/new')
@login_required
def orders(kind):
    if kind not in ('purchase', 'sales'):
        abort(404)
    owner, active_role = access()
    compose_only=request.path.endswith('/new') or request.args.get('item_id') is not None
    if compose_only and active_role not in ('admin','manager'): abort(403)
    orders = Order.query.filter_by(owner_id=owner, kind=kind).order_by(Order.id.desc()).all()
    items = Item.query.filter_by(user_id=owner).order_by(Item.name).all()
    suppliers = Supplier.query.filter_by(owner_id=owner).order_by(Supplier.name).all()
    return render_template('orders.html', kind=kind, orders=orders, items=items,
                           suppliers=suppliers, locations=locations(owner), available=available, page=kind,
                           prefill_quantity=min(1000000,max(1,request.args.get('quantity',1,type=int))),
                           prefill_item_id=request.args.get('item_id',type=int), compose_only=compose_only)


@bp.post('/orders/create/<kind>')
@command('admin', 'manager')
def create_order(owner, kind):
    if kind not in ('purchase', 'sales'):
        raise ValueError('Unknown order type.')
    location = request.form.get('location')
    if location not in locations(owner):
        raise ValueError('Choose a warehouse in this workspace.')
    supplier_id = None
    if kind == 'purchase':
        supplier = Supplier.query.filter_by(owner_id=owner, id=request.form.get('supplier_id', type=int)).first()
        if not supplier:
            raise ValueError('Select a supplier from the directory.')
        partner, supplier_id = supplier.name, supplier.id
    else:
        partner = request.form.get('partner', '').strip()
        if not 2 <= len(partner) <= 120:
            raise ValueError('Enter a customer name between 2 and 120 characters.')
    due = date.fromisoformat(request.form.get('due_date', ''))
    item_ids = request.form.getlist('product_id')
    quantities = request.form.getlist('line_quantity')
    if not 1 <= len(item_ids) <= 20 or len(item_ids) != len(quantities):
        raise ValueError('An order must contain between 1 and 20 product lines.')
    order = Order(owner_id=owner, kind=kind, partner=partner, supplier_id=supplier_id,
                  location=location, due_date=due, created_by=current_user.id)
    db.session.add(order)
    seen = set()
    for raw_id, raw_qty in zip(item_ids, quantities):
        if not raw_id and not raw_qty:
            continue
        item = Item.query.filter_by(user_id=owner, id=int(raw_id)).first()
        qty = int(raw_qty)
        if not item or item.id in seen or not 0 < qty <= 1000000:
            raise ValueError('Each line needs a distinct product and a positive whole quantity.')
        seen.add(item.id)
        paise = int((Decimal(str(item.price)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        order.lines.append(OrderLine(item_id=item.id, quantity=qty, unit_paise=paise))
    if not seen:
        raise ValueError('Add at least one product line.')
    db.session.flush()
    return f'{order.reference} created as draft.', order.reference, f'{len(seen)} lines; {partner}; warehouse {location}'


@bp.post('/orders/<int:order_id>/<action>')
@command('admin', 'manager', 'operator')
def process_order(owner, order_id, action):
    order = Order.query.filter_by(id=order_id, owner_id=owner).first()
    if not order:
        raise ValueError('Order not found in this workspace.')
    if access()[1] == 'operator' and action not in ('receive', 'ship'):
        abort(403)
    previous = order.status
    quantities = {str(line.id): request.form.get(f'received_{line.id}', '0') for line in order.lines}
    transition(order, action, quantities)
    return f'{order.reference}: {order.status}.', order.reference, f'{previous} → {order.status}; action={action}'


@bp.get('/network')
@login_required
def network():
    owner, _ = access()
    warehouses = Warehouse.query.filter_by(owner_id=owner).all()
    items = Item.query.filter_by(user_id=owner).all()
    stocks = Stock.query.filter(Stock.item_id.in_([i.id for i in items])).all()
    return render_template('network.html', warehouses=warehouses, stocks=stocks,
                           suppliers=Supplier.query.filter_by(owner_id=owner).all(), page='network')


@bp.post('/network/warehouse')
@command('admin', 'manager')
def create_warehouse(owner):
    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()
    city = request.form.get('city', '').strip()
    if not 2 <= len(code) <= 12 or not 2 <= len(name) <= 50 or len(city) > 80:
        raise ValueError('Use a warehouse code of 2–12 characters and a name of 2–50 characters.')
    label = f'{code} · {name}'
    # Preserve the historical default locations before appending the first custom one.
    if not Warehouse.query.filter_by(owner_id=owner).first():
        db.session.add_all([Warehouse(owner_id=owner, label=l) for l in DEFAULT_LOCATIONS])
    if label in locations(owner) or any(l.split(' · ')[0] == code for l in locations(owner)):
        raise ValueError('Warehouse code already exists.')
    db.session.add(Warehouse(owner_id=owner, label=label, city=city))
    return 'Warehouse added to the network.', code, label


@bp.post('/network/supplier')
@command('admin', 'manager')
def create_supplier(owner):
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    lead = int(request.form.get('lead_days', '7'))
    if not 2 <= len(name) <= 120 or len(email) > 120 or not 1 <= lead <= 90:
        raise ValueError('Provide a valid supplier name and lead time of 1–90 days.')
    if email and ('@' not in email or '.' not in email.split('@')[-1]):
        raise ValueError('Enter a valid contact email or leave it blank.')
    db.session.add(Supplier(owner_id=owner, name=name, email=email, lead_days=lead))
    return 'Supplier added.', name, f'Lead time: {lead} days'


@bp.post('/policy/<int:item_id>')
@command('admin', 'manager')
def save_policy(owner, item_id):
    item = Item.query.filter_by(id=item_id, user_id=owner).first()
    if not item:
        raise ValueError('Product not found.')
    minimum = int(request.form.get('minimum', '20'))
    maximum = int(request.form.get('maximum', '200'))
    lead = int(request.form.get('lead_days', '7'))
    if not 0 <= minimum <= maximum <= 1000000 or not 1 <= lead <= 90:
        raise ValueError('Set minimum ≤ maximum and a lead time between 1 and 90 days.')
    policy = StockPolicy.query.filter_by(item_id=item.id).first()
    if not policy:
        policy = StockPolicy(item_id=item.id)
        db.session.add(policy)
    policy.minimum, policy.maximum, policy.lead_days = minimum, maximum, lead
    return 'Stock policy updated.', f'WH-{item_id:04}', f'min={minimum}, max={maximum}, lead_days={lead}'


@bp.get('/team')
@require_roles('admin')
def team():
    owner, _ = access()
    members = db.session.query(User, Membership).join(Membership, User.id == Membership.user_id).filter(Membership.owner_id == owner).all()
    return render_template('team.html', members=members, page='team')


@bp.post('/team/create')
@command('admin')
def create_member(owner):
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role')
    if not 3 <= len(username) <= 64 or len(password) < 12 or len(password) > 128 or role not in ('manager', 'operator', 'viewer'):
        raise ValueError('Use a username of 3–64 characters and a password of 12–128 characters; choose a staff role.')
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    db.session.add(Membership(user_id=user.id, owner_id=owner, role=role))
    return 'Team member created.', username, f'Role: {role}'


@bp.get('/audit')
@require_roles('admin', 'manager')
def audit():
    owner, _ = access()
    page = max(1, request.args.get('page', 1, type=int))
    events = AuditEvent.query.filter_by(owner_id=owner).order_by(AuditEvent.id.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template('audit.html', events=events, page='audit')


def init_enterprise(app):
    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
        owners = User.query.filter(~User.id.in_(db.session.query(Membership.user_id))).all()
        for user in owners:
            if not Warehouse.query.filter_by(owner_id=user.id).first():
                labels = set(DEFAULT_LOCATIONS)
                labels.update(s.location for s in Stock.query.join(Item).filter(Item.user_id == user.id).all())
                db.session.add_all([Warehouse(owner_id=user.id, label=label) for label in sorted(labels)])
        db.session.commit()
