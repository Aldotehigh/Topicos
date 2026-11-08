from decimal import Decimal
import unicodedata
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from .models import PromotionDay


def business_date():
    zone = ZoneInfo(getattr(settings, 'RESTAURANT_TIME_ZONE', 'America/Mexico_City'))
    return timezone.now().astimezone(zone).date()


def normalized(text):
    return ''.join(char for char in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(char))


def current_promotion():
    day = business_date()
    calendar = PromotionDay.objects.filter(date=day).first()
    state = 'not_monday' if day.weekday() else 'calendar_unconfirmed' if calendar is None else 'active' if calendar.eligible else 'suspended'
    return {'date': str(day), 'active': state == 'active', 'state': state}


def eligible_product(card):
    if card.monday_promotion_excluded or (card.variant_of_id and card.variant_of.monday_promotion_excluded):
        return False
    category = normalized(card.category.name) if card.category else ''
    if not ('makimono' in category or category in ('sushi', 'sushis')):
        return False
    if card.presentation not in ('', 'full') or 'media orden' in normalized(card.title):
        return False
    name = normalized(card.title).replace(' roll', '').strip()
    return name not in {'coco', 'don jorge', 'roca', 'rocca', 'tesoro', 'crunchy'}


def price_lines(lines, active):
    remaining = [line for line in lines if line.status != 'declined']
    subtotal = sum((line.quantity * line.unit_price for line in remaining), Decimal('0'))
    discounts = {line.id: Decimal('0') for line in remaining}
    if active:
        units = [
            (line.unit_price, line.id)
            for line in remaining if line.promotion_eligible
            for _ in range(line.quantity)
        ]
        units.sort(key=lambda item: (-item[0], item[1]))
        for price, line_id in units[1::2]:
            discounts[line_id] += price
    discount = sum(discounts.values(), Decimal('0'))
    return subtotal, discount, subtotal - discount, discounts


def order_price(order):
    subtotal, discount, total, _ = price_lines(list(order.lines.all()), order.promotion_active)
    tip = (total * order.tip_percent / 100).quantize(Decimal('0.01'))
    payment = getattr(order, 'payment', None)
    if payment:
        subtotal, discount, total, tip = payment.subtotal, payment.discount, payment.total, payment.tip_amount
    return {
        'subtotal': str(subtotal), 'discount': str(discount), 'total': str(total),
        'tip': str(tip), 'grand_total': str(total + tip),
        'promotion_applied': discount > 0, 'paid': payment is not None,
    }
