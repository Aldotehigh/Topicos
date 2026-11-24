from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('catalog', '0005_profile_food_preferences')]
    operations = [migrations.AddField(
        model_name='tableorderline', name='food_preferences',
        field=models.JSONField(default=list, blank=True),
    )]
