from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0006_pdf_passwords_restriction_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysecuritysettings",
            name="pdf_open_inside_enc",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="companysecuritysettings",
            name="pdf_open_outside_enc",
            field=models.TextField(blank=True, default=""),
        ),
    ]
