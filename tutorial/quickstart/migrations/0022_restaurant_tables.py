from django.db import migrations
import unicodedata


def seed_restaurant(apps, schema_editor):
    alias = schema_editor.connection.alias
    Table = apps.get_model('quickstart', 'DiningTable')
    for zone, groups in [
        ('terrace', {2: ['40','41','42','52','73','70B'], 4: ['50','70A','80','81','72'], 6: ['51','71'], 15: ['60']}),
        ('salon', {2: ['30','31','32','22','10','11','12'], 6: ['20'], 4: ['21A','21B']}),
    ]:
        for capacity, labels in groups.items():
            for label in labels:
                Table.objects.using(alias).get_or_create(label=label, defaults={'zone': zone, 'capacity': capacity})
    Category = apps.get_model('quickstart', 'Category')
    sushi_names = {'nigiris', 'sashimi', 'makimonos tradicionales', 'makimonos especiales', 'temakis', 'bocadillos especiales'}
    def normalize(value):
        return ''.join(c for c in unicodedata.normalize('NFD', value) if not unicodedata.combining(c)).strip().casefold()
    sushi_ids = [c.pk for c in Category.objects.using(alias).all() if normalize(c.name) in sushi_names]
    Category.objects.using(alias).filter(pk__in=sushi_ids).update(area='sushi')
    Card = apps.get_model('quickstart', 'Card')
    product_ids = Card.objects.using(alias).filter(category_id__in=sushi_ids).values('pk')
    Line = apps.get_model('quickstart', 'TableOrderLine')
    Line.objects.using(alias).filter(product_id__in=product_ids, status__in=['review','received','preparing','ready']).update(area='sushi')
    # Old lines did not always retain their product FK. Only route unambiguous titles.
    for line in Line.objects.using(alias).filter(product__isnull=True, status__in=['review','received','preparing','ready']):
        areas = set(Card.objects.using(alias).filter(title=line.title).values_list('category__area', flat=True))
        if areas == {'sushi'}:
            Line.objects.using(alias).filter(pk=line.pk).update(area='sushi')


class Migration(migrations.Migration):
    dependencies = [('quickstart', '0021_sushi_reservations')]
    operations = [migrations.RunPython(seed_restaurant, migrations.RunPython.noop)]
