"""Local demand models with rolling-origin validation and no future-data leakage."""
from datetime import datetime, timedelta, timezone
from math import ceil, sqrt


def predict(values, horizon, model):
    if model == 'Moving average':
        return [sum(values[-7:]) / len(values[-7:])] * horizon
    n = len(values)
    mean = sum(values) / n
    center = (n - 1) / 2
    denominator = sum((i - center) ** 2 for i in range(n))
    slope = sum((i - center) * (v - mean) for i, v in enumerate(values)) / denominator if denominator else 0
    return [max(0, mean + slope * (n + i - center)) for i in range(horizon)]


def backtest(values):
    if len(values) < 14:
        return dict(model='Linear regression', mae=None, baseline_mae=None, folds=0)
    errors = {name: [] for name in ('Linear regression', 'Moving average')}
    for cut in range(len(values) - 7, len(values)):
        for name in errors:
            prediction = predict(values[:cut], 1, name)[0]
            errors[name].append(abs(prediction - values[cut]))
    scores = {name: sum(error) / len(error) for name, error in errors.items()}
    winner = min(scores, key=scores.get)
    return dict(model=winner, mae=round(scores[winner], 2), baseline_mae=round(scores['Moving average'], 2), folds=7)


def forecast(item_id, movements, stock, now=None, lead_days=7, incoming=0, reserved=0):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    history = [m for m in movements if m.item_id == item_id and m.created_at.date() <= now.date()]
    empty = dict(daily=0, reorder=0, days=None, quality='No history', model='Not trained', mae=None, baseline_mae=None, folds=0, train_days=0, actual=[], future=[], lead_days=lead_days, incoming=incoming, reserved=reserved)
    if not history:
        return dict(empty, explanation='Record dispatches to train the demand model.')
    n = min(30, (now.date() - min(m.created_at.date() for m in history)).days + 1)
    if n < 7:
        return dict(empty, quality='Limited history', explanation='At least 7 calendar days are needed. No forecast is issued yet.')
    dates = [now.date() - timedelta(days=n - 1 - i) for i in range(n)]
    y = [sum(m.quantity for m in history if m.kind == 'Dispatch' and m.created_at.date() == d) for d in dates]
    validation = backtest(y)
    future = predict(y, max(7, lead_days), validation['model'])
    daily = sum(future[:7]) / 7
    avg = sum(y) / n
    deviation = sqrt(sum((value - avg) ** 2 for value in y) / n)
    target = ceil(sum(future[:lead_days]) + deviation * sqrt(lead_days))
    free = max(0, stock - reserved)
    position = free + incoming
    explanation = (f"{validation['model']} fitted to {n} calendar days, including zero-demand days. "
                   f"Reorder target: {lead_days}-day demand + variability buffer. "
                   f"Inventory position: {stock} on hand − {reserved} reserved + {incoming} approved incoming = {position}. "
                   f"Suggested order: max(0, {target} target − {position} position). "
                   "Daily totals include the current UTC day, which may be incomplete. ")
    explanation += ('Model selected using seven one-day rolling-origin backtests; each prediction uses earlier days only. Reported error is model-selection validation, not an independent test-set result.' if validation['folds'] else 'Fewer than 14 days: validation is unavailable and regression is provisional.')
    return dict(daily=round(daily, 1), reorder=max(0, target - position), days=round(free / daily, 1) if daily else None,
                quality='Early estimate' if n < 14 else f'{n} days / 7 backtests', explanation=explanation,
                train_days=n, actual=y[-14:], future=[round(v, 1) for v in future[:7]], lead_days=lead_days,
                incoming=incoming, reserved=reserved, **validation)
