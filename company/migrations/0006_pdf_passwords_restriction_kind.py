from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0005_employee_security_system"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysecuritysettings",
            name="pdf_password_inside",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddField(
            model_name="companysecuritysettings",
            name="pdf_password_outside",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddField(
            model_name="afterhourspreviewrequest",
            name="restriction_kind",
            field=models.CharField(
                choices=[
                    ("office_hours", "Outside office hours"),
                    ("outside_location", "Outside office location"),
                ],
                default="office_hours",
                max_length=30,
            ),
        ),
    ]
