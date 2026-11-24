from django.db import migrations


def remove_unused_legacy_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    alias = schema_editor.connection.alias
    for group in Group.objects.using(alias).filter(name='topicos 2'):
        if not group.user_set.using(alias).exists() and not group.permissions.using(alias).exists():
            group.delete(using=alias)


class Migration(migrations.Migration):
    dependencies = [('catalog', '0003_restaurant_tables')]
    operations = [migrations.RunPython(remove_unused_legacy_group, migrations.RunPython.noop)]
