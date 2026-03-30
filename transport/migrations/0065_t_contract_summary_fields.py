from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("transport", "0064_alter_dispatch_totalfreight"),
    ]

    operations = [
        migrations.AddField(
            model_name="t_contract",
            name="default_page_wise_summary",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="t_contract",
            name="sac_number",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="t_contract",
            name="summary_footer_note",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]
