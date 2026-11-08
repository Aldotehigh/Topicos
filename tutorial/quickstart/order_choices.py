from decimal import Decimal

from rest_framework.exceptions import ValidationError

from .models import Card


def choice(key, label, options, count=1, distinct=False, optional=False):
    return {
        'key': key, 'label': label, 'count': count, 'distinct': distinct,
        'optional': optional,
        'options': [{'id': key, 'label': text} for key, text in options],
    }


def get_order_profile(card):
    category = card.category.name if card.category else ''
    bar = bool(card.category and card.category.area == 'bar')
    simple = category in ('Nigiris', 'Postres')
    groups = []
    if card.presentation == 'combo':
        proteins = Card.objects.filter(category=card.category, is_available=True,
            presentation__in=['beef', 'chicken', 'white_fish', 'shrimp', 'octopus', 'salmon'],
        ).order_by('id')
        group = choice('proteins', 'Choose two or three proteins',
            [(protein.presentation, protein.title) for protein in proteins], count=3, distinct=True)
        group['min_count'] = 2
        group['warning'] = 'Three proteins share the same portion; each portion may be smaller.'
        groups.append(group)
    if card.order_kind == 'steak':
        groups.append(choice('doneness', 'Steak doneness', [
            ('rare', 'Rare'), ('medium_rare', 'Medium rare'), ('medium', 'Medium'),
            ('medium_well', 'Medium well'), ('well_done', 'Well done'),
        ]))
    if card.order_kind == 'bites_mix':
        pieces = Card.objects.filter(
            category=card.category, variant_of__isnull=True, is_available=True,
        ).exclude(order_kind='bites_mix').order_by('title', 'pk')
        groups.append(choice('bites', 'Choose three bites', [(str(p.pk), p.title) for p in pieces], count=3))
    if card.order_kind == 'kushi_mix':
        pieces = Card.objects.filter(
            category=card.category, variant_of__isnull=True, is_available=True,
        ).exclude(order_kind='kushi_mix').order_by('title', 'pk')
        group = choice('skewers', 'Choose three different skewers',
                       [(str(p.pk), p.title) for p in pieces], count=3, distinct=True)
        group['options'] = [
            {'id': str(p.pk), 'label': p.title, 'price': str(p.price)}
            for p in pieces
        ]
        groups.append(group)
    if card.order_kind == 'edamame':
        groups.append(choice('cooking', 'Preparation', [('steamed', 'Steamed'), ('grilled', 'Grilled')]))
    if card.order_kind == 'ramen':
        groups.append(choice('broth', 'Choose your broth', [('miso', 'Miso'), ('shoyu', 'Shoyu'), ('tonkotsu', 'Tonkotsu')]))
    if card.order_kind == 'topping':
        groups.append(choice('topping', 'Choose a topping', [
            ('none', 'No topping'), ('chocolate', 'Chocolate'),
            ('cajeta', 'Cajeta'), ('blackberry', 'Blackberry'),
        ]))
    cheese = 'gouda' in (card.descripcion or '').lower()
    if category == 'Kushi Age' and (cheese or card.order_kind == 'kushi_mix'):
        group = choice('cheese', 'Cheese substitution', [('cream', 'Replace gouda with cream cheese')], optional=True)
        if card.order_kind == 'kushi_mix':
            group['requires_ids'] = [
                str(p.pk) for p in pieces if 'gouda' in (p.descripcion or '').lower()
            ]
        groups.append(group)
    if bar and category == 'Cocteleria Tradicional':
        groups.append(choice('alcohol', 'Drink options', [('without', 'Request an alcohol-free version')], optional=True))
    course = 'drink' if bar else 'starter' if category in ('Entradas', 'Ceviches', 'Ensaladas', 'Kushi Age', 'Bocadillos Especiales') else 'dessert' if category == 'Postres' else 'main'
    return {
        'groups': groups, 'course': course,
        'show_allergy': not (bar or simple),
        'show_removals': not (bar or simple),
        'highest_price': card.order_kind == 'kushi_mix',
        'notice': 'Three different skewers. The highest selected price applies.' if category == 'Kushi Age' else '',
        'bar': bar,
        'alcohol_free': bar and category == 'Cocteleria Tradicional',
    }


def get_order_choice(card):
    groups = get_order_profile(card)['groups']
    return groups[0] if groups else None


def resolve_order_options(card, submitted, legacy):
    profile = get_order_profile(card)
    groups = profile['groups']
    if legacy and submitted:
        raise ValidationError({'detail': 'Send only one version of the options.'})
    if legacy:
        submitted = {groups[0]['key']: legacy} if groups else {'invalid': legacy}
    if set(submitted) - {group['key'] for group in groups}:
        raise ValidationError({'detail': 'Some options do not belong to this item.'})
    labels = []
    price = card.price
    selected_skewers = submitted.get('skewers', [])
    for group in groups:
        values = submitted.get(group['key'], [])
        options = {option['id']: option for option in group['options']}
        if ((not group['optional'] or values) and not group.get('min_count', group['count']) <= len(values) <= group['count']
            or set(values) - options.keys()
            or group['distinct'] and len(set(values)) != len(values)):
            raise ValidationError({'detail': 'Complete the item options.'})
        if values and 'requires_ids' in group and not set(selected_skewers).intersection(group['requires_ids']):
            raise ValidationError({'detail': 'Select a gouda skewer to change the cheese.'})
        labels.extend(options[value]['label'] for value in values)
        if group['key'] == 'proteins' and len(values) == 3:
            labels.append(group['warning'])
        if group['key'] == 'skewers':
            price = max(Decimal(options[value]['price']) for value in values)
    return profile, labels, price, bool(submitted.get('alcohol'))
