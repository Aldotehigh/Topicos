
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0004_admin_cleanup'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='food_preferences',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
