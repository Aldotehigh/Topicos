from .models import Card


def get_order_choice(card):
    if card.category is None:
        return None

    if card.title == 'Wafu Stake' and card.category.name == 'Carne y Pollo':
        return {
            'label': 'Steak doneness',
            'count': 1,
            'options': [
                {'id': value, 'label': label}
                for value, label in (
                    ('rare', 'Rare'), ('medium_rare', 'Medium rare'),
                    ('medium', 'Medium'), ('medium_well', 'Medium well'),
                    ('well_done', 'Well done'),
                )
            ],
        }

    if card.title == 'Mix' and card.category.name == 'Bocadillos Especiales':
        pieces = Card.objects.filter(
            category=card.category, variant_of__isnull=True, is_available=True,
        ).exclude(title='Mix').order_by('title', 'pk')
        return {
            'label': 'Choose three bites',
            'count': 3,
            'options': [{'id': str(piece.pk), 'label': piece.title} for piece in pieces],
        }

    return None
