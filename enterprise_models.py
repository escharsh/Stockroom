"""Warehouse workflow tables; additive to the upstream inventory schema."""
from datetime import datetime, timezone
from extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    __table_args__ = (db.CheckConstraint("role IN ('admin','manager','operator','viewer')"),)


class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    city = db.Column(db.String(80), nullable=False, default='')
    __table_args__ = (db.UniqueConstraint('owner_id', 'label'),)


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, default='')
    lead_days = db.Column(db.Integer, nullable=False, default=7)
    __table_args__ = (db.UniqueConstraint('owner_id', 'name'), db.CheckConstraint('lead_days BETWEEN 1 AND 90'))


class StockPolicy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), unique=True, nullable=False)
    minimum = db.Column(db.Integer, nullable=False, default=20)
    maximum = db.Column(db.Integer, nullable=False, default=200)
    lead_days = db.Column(db.Integer, nullable=False, default=7)
    __table_args__ = (db.CheckConstraint('minimum >= 0 AND maximum >= minimum'), db.CheckConstraint('lead_days BETWEEN 1 AND 90'))


class Order(db.Model):
    __tablename__ = 'warehouse_order'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='Draft')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    partner = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(80), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lines = db.relationship('OrderLine', backref='order', cascade='all, delete-orphan', order_by='OrderLine.id')
    __table_args__ = (db.CheckConstraint("kind IN ('purchase','sales')"),)

    @property
    def reference(self):
        return f"{'PO' if self.kind == 'purchase' else 'SO'}-{self.id:05d}"

    @property
    def total_paise(self):
        return sum(line.quantity * line.unit_paise for line in self.lines)


class OrderLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('warehouse_order.id'), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    received = db.Column(db.Integer, nullable=False, default=0)
    unit_paise = db.Column(db.Integer, nullable=False)
    item = db.relationship('Item')
    __table_args__ = (db.UniqueConstraint('order_id', 'item_id'), db.CheckConstraint('quantity > 0 AND received >= 0 AND received <= quantity'), db.CheckConstraint('unit_paise >= 0'))


class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    actor = db.relationship('User', foreign_keys=[actor_id])
    action = db.Column(db.String(60), nullable=False)
    entity = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.Text, nullable=False, default='')
    request_key = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint('owner_id', 'request_key'),)
