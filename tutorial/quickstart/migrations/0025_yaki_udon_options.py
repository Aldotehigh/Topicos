from django.db import migrations, models


def configure_yaki_udon(apps, schema_editor):
    Card = apps.get_model('quickstart', 'Card')
    cards = Card.objects.using(schema_editor.connection.alias)
    dishes = cards.filter(category__name='Udon y Soba', variant_of__isnull=True, order_kind='')
    for dish in dishes.only('id', 'title'):
        title = dish.title.casefold().replace(' ', '')
        if title in {'yakiudon', 'yakiudon/soba'}:
            dishes.filter(pk=dish.pk).update(order_kind='yaki_udon')


class Migration(migrations.Migration):
    dependencies = [('quickstart', '0024_translate_existing_menu')]
    operations = [
        migrations.AlterField(
            model_name='card',
            name='order_kind',
            field=models.CharField('Tipo de opciones para pedir', max_length=12, blank=True, choices=[
                ('steak', 'Término de carne'), ('bites_mix', 'Mix de bocadillos'),
                ('kushi_mix', 'Mix de brochetas'), ('edamame', 'Preparación de edamame'),
                ('ramen', 'Caldo de ramen'), ('topping', 'Topping de postre'),
                ('yaki_udon', 'Fideo y proteína de Yaki Udon'),
            ]),
        ),
        migrations.RunPython(configure_yaki_udon, migrations.RunPython.noop),
    ]
