from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transport", "0066_t_contract_show_summary_intro"),
    ]

    operations = [
        migrations.AddField(
            model_name="t_contract",
            name="recommended_by_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="t_contract",
            name="verified_by_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
