from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0007_pdf_open_password_enc"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysecuritysettings",
            name="pdf_files_always_use_outside_password",
            field=models.BooleanField(default=True),
        ),
    ]
