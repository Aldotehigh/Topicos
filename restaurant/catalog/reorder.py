"""Build a current-menu cart preview without creating or changing an order."""
from collections import Counter
from .order_choices import get_order_profile, resolve_order_options
from rest_framework.exceptions import ValidationError


def rebuild_line(line):
    card = line.product
    if not card:
        return None, 'This product is no longer on the menu.'
    parent = card.variant_of or card
    if not card.is_available or not parent.is_available:
        return None, 'This presentation is currently unavailable.'
    if not parent.category or parent.category.area not in ('kitchen', 'bar', 'sushi'):
        return None, 'This product is no longer on the menu.'
    option_card = card if card.presentation == 'combo' else parent
    profile = get_order_profile(option_card)
    # Old orders saved labels rather than option IDs. Restore only unambiguous
    # exact matches and validate them against today's recipe and option rules.
    choices = {}
    labels = list(line.selections or [])
    options_by_label = {}
    for group in profile['groups']:
        for option in group['options']:
            options_by_label.setdefault(option['label'], []).append((group['key'], option['id']))
    for label in labels:
        matches = options_by_label.get(label, [])
        if len(matches) > 1:
            return None, 'The options changed. Customize this product again from the menu.'
        if matches:
            key, value = matches[0]
            choices.setdefault(key, []).append(value)
    try:
        profile, restored_labels, price, _ = resolve_order_options(option_card, choices, [])
    except ValidationError:
        return None, 'The options changed. Customize this product again from the menu.'
    if Counter(restored_labels) != Counter(labels):
        return None, 'The options changed. Customize this product again from the menu.'
    allowed = card.allowed_removals or parent.allowed_removals or []
    if set(line.removals or []) - set(allowed) or (line.removals and not profile['show_removals']):
        return None, 'The ingredient removals changed. Customize this product again from the menu.'
    if not profile['highest_price']:
        price = card.price
    if not 1 <= line.quantity <= 20:
        return None, 'Choose the quantity again from the menu.'
    return {
        'cardId': card.pk, 'title': card.title, 'price': str(price),
        'quantity': line.quantity, 'removals': line.removals or [],
        'selections': [], 'choices': choices, 'allergy': line.allergy or '',
        'course': profile['course'], 'option_labels': restored_labels,
        'previous_price': str(line.unit_price), 'price_changed': price != line.unit_price,
    }, None


def reorder_preview(order):
    ready, unavailable = [], []
    for line in order.lines.select_related('product__category', 'product__variant_of__category').all():
        if line.status == 'declined':
            unavailable.append({'title': line.title, 'reason': 'This item was declined in the original order.'})
            continue
        item, reason = rebuild_line(line)
        if item:
            ready.append(item)
        else:
            unavailable.append({'title': line.title, 'reason': reason})
    return {'order_id': order.pk, 'lines': ready, 'unavailable': unavailable}
