"""Transactional business rules shared by order processing and stock movements."""
from sqlalchemy import select, func, update
from extensions import db
from models import Stock, Movement, Item
from enterprise_models import Order, OrderLine


def held_units(item_id, location):
    return (select(func.coalesce(func.sum(OrderLine.quantity), 0))
            .join(Order, Order.id == OrderLine.order_id)
            .where(Order.kind == 'sales', Order.status == 'Reserved',
                   OrderLine.item_id == item_id, Order.location == location).scalar_subquery())


def available(item_id, location):
    stock = Stock.query.filter_by(item_id=item_id, location=location).first()
    held = db.session.scalar(select(held_units(item_id, location))) or 0
    return (stock.quantity if stock else 0) - held


def lock_available(item_id, location, quantity, decrement=False):
    # One conditional write takes the SQLite writer lock before reserving stock.
    # Concurrent reserve/dispatch transactions re-evaluate the reservation subquery.
    value = Stock.quantity - quantity if decrement else Stock.quantity
    result = db.session.execute(update(Stock).where(
        Stock.item_id == item_id, Stock.location == location,
        Stock.quantity >= held_units(item_id, location) + quantity
    ).values(quantity=value).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ValueError('Insufficient available stock. Reserved units cannot be dispatched or transferred.')


def credit(item_id, location, quantity):
    result = db.session.execute(update(Stock).where(
        Stock.item_id == item_id, Stock.location == location
    ).values(quantity=Stock.quantity + quantity).execution_options(synchronize_session=False))
    if not result.rowcount:
        db.session.add(Stock(item_id=item_id, location=location, quantity=quantity))
    db.session.execute(update(Item).where(Item.id == item_id).values(quantity=Item.quantity + quantity))


def record(item_id, kind, source, destination, quantity, reference):
    db.session.add(Movement(item_id=item_id, kind=kind, source=source,
                            destination=destination, quantity=quantity, reference=reference))


def transition(order, action, quantities=None):
    """Caller commits the audit event and every stock/order change together."""
    if order.kind == 'purchase':
        if action == 'approve' and order.status == 'Draft':
            order.status = 'Approved'
        elif action == 'cancel' and order.status in ('Draft', 'Approved'):
            order.status = 'Cancelled'
        elif action == 'receive' and order.status in ('Approved', 'Partially received'):
            changed = False
            for line in order.lines:
                qty = int((quantities or {}).get(str(line.id), '0') or '0')
                if qty < 0 or qty > line.quantity - line.received:
                    raise ValueError('Receipt exceeds the outstanding quantity or contains a negative number.')
                if qty:
                    line.received += qty
                    credit(line.item_id, order.location, qty)
                    record(line.item_id, 'Receive', order.partner, order.location, qty, order.reference)
                    changed = True
            if not changed:
                raise ValueError('Enter a positive received quantity for at least one line.')
            order.status = 'Received' if all(l.received == l.quantity for l in order.lines) else 'Partially received'
        else:
            raise ValueError('This action is not allowed in the current purchase order state.')
    else:
        if action == 'reserve' and order.status == 'Draft':
            for line in order.lines:
                lock_available(line.item_id, order.location, line.quantity)
            order.status = 'Reserved'
        elif action == 'ship' and order.status == 'Reserved':
            # The order retains its reservation until every decrement succeeds.
            for line in order.lines:
                result = db.session.execute(update(Stock).where(
                    Stock.item_id == line.item_id, Stock.location == order.location,
                    Stock.quantity >= line.quantity
                ).values(quantity=Stock.quantity - line.quantity).execution_options(synchronize_session=False))
                if result.rowcount != 1:
                    raise ValueError('Stock discrepancy: shipment was not posted. Review warehouse balances.')
                db.session.execute(update(Item).where(Item.id == line.item_id).values(quantity=Item.quantity - line.quantity))
                record(line.item_id, 'Dispatch', order.location, order.partner, line.quantity, order.reference)
            order.status = 'Shipped'
        elif action == 'cancel' and order.status in ('Draft', 'Reserved'):
            order.status = 'Cancelled'
        else:
            raise ValueError('This action is not allowed in the current sales order state.')
