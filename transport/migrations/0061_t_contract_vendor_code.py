from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transport', '0060_invoice_rr_number_alter_dispatch_dep_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='t_contract',
            name='vendor_code',
            field=models.CharField(max_length=100, blank=True, null=True),
        ),
    ]
