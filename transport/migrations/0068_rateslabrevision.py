# Generated manually for diesel rate revision feature

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0001_initial"),
        ("transport", "0067_t_contract_footer_name_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="RateSlabRevision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "rate_category",
                    models.CharField(
                        choices=[
                            ("kilometer_wise", "Kilometer-Wise"),
                            ("incometax_wise", "Incometax-Wise"),
                            ("cumulative_wise", "Cumulative-Wise"),
                            ("district_wise", "District-Wise"),
                            ("taluka_wise", "Taluka-Wise"),
                        ],
                        max_length=30,
                    ),
                ),
                ("from_km", models.BigIntegerField(blank=True, null=True)),
                ("to_km", models.BigIntegerField(blank=True, null=True)),
                (
                    "district_name",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                (
                    "taluka_name",
                    models.CharField(blank=True, max_length=50, null=True),
                ),
                ("choice", models.CharField(default="mt", max_length=20)),
                (
                    "base_value",
                    models.DecimalField(decimal_places=4, max_digits=12),
                ),
                (
                    "adjustment_type",
                    models.CharField(
                        choices=[("increase", "Increase"), ("decrease", "Decrease")],
                        max_length=10,
                    ),
                ),
                (
                    "adjustment_amount",
                    models.DecimalField(decimal_places=4, max_digits=12),
                ),
                (
                    "updated_value",
                    models.DecimalField(decimal_places=4, max_digits=12),
                ),
                ("effective_from", models.DateField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company_id",
                    models.ForeignKey(
                        default=None,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="company.company_user",
                    ),
                ),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rate_revisions",
                        to="transport.t_contract",
                    ),
                ),
            ],
            options={
                "ordering": ["-effective_from", "-created_at"],
                "indexes": [
                    models.Index(
                        fields=["contract", "rate_category", "from_km", "to_km"],
                        name="transport_r_contrac_8a1f2d_idx",
                    ),
                    models.Index(
                        fields=["contract", "rate_category", "effective_from"],
                        name="transport_r_contrac_9b3e4f_idx",
                    ),
                ],
            },
        ),
    ]
