from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transport", "0065_t_contract_summary_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="t_contract",
            name="show_summary_intro",
            field=models.BooleanField(default=False),
        ),
    ]
