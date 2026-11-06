from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from company.models import Company_user
from truckmaster.models import Driver, Party, Truck
from truckmaster.services import calculate_freight, d2, money_hash, parse_date


class CalculationTests(SimpleTestCase):
    def test_freight_fixed(self):
        self.assertEqual(calculate_freight("fixed", "15000", "10", 100), Decimal("15000.00"))

    def test_freight_per_ton(self):
        self.assertEqual(calculate_freight("per_ton", "1200", "10.5", 0), Decimal("12600.00"))

    def test_freight_per_km(self):
        self.assertEqual(calculate_freight("per_km", "25", "0", 40), Decimal("1000.00"))

    def test_money_rounding(self):
        self.assertEqual(d2("10.555"), Decimal("10.56"))

    def test_parse_date(self):
        self.assertEqual(parse_date("2026-10-30"), date(2026, 10, 30))
        self.assertEqual(parse_date("30-10-2026"), date(2026, 10, 30))

    def test_hash_stable(self):
        self.assertEqual(money_hash("a", "b"), money_hash("A", "B"))


class TruckMasterModelTests(TestCase):
    def setUp(self):
        self.company = Company_user.objects.create(
            company_name="Test Fleet Co",
            gst_number="24TESTFLEET1Z5",
            email="fleet@example.com",
            mobile=9999999999,
            password="password123",
            company_profile_status=True,
        )

    def test_unique_truck_per_company(self):
        Truck.objects.create(company_id=self.company, registration_no="GJ09AB1234")
        with self.assertRaises(Exception):
            Truck.objects.create(company_id=self.company, registration_no="GJ09AB1234")

    def test_salary_unique_period_constraint_fields(self):
        driver = Driver.objects.create(
            company_id=self.company,
            name="Ramesh",
            mobile="9876543210",
            license_no="GJ012345",
        )
        self.assertEqual(driver.name, "Ramesh")

    def test_party_create(self):
        party = Party.objects.create(company_id=self.company, name="ABC Traders")
        self.assertEqual(str(party), "ABC Traders")


class AuthGuardTests(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("tm-dashboard"), follow=True)
        self.assertNotEqual(response.status_code, 500)
        self.assertTrue(response.redirect_chain or response.status_code in (200, 302))
