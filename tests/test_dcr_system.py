import unittest
import os
import io
import json
from html import unescape
from datetime import date, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from pydantic import ValidationError

from app.database import Base, ensure_table_columns, get_db
from app.config import Settings
from app.main import app
from app.models.user import User
from app.models.master import Territory, Hospital, Doctor, VisitType
from app.models.dcr import FactDCR
from app.models.tour_plan import (
    TourPlan,
    TourPlanAudit,
    TourPlanImport,
    TourPlanSetting,
    TourPlanVisit,
)
from app.services.auth_service import get_password_hash, create_access_token, verify_password
from app.services.seed_data import seed_database_defaults
from app.services.analytics_service import get_dashboard_summary_metrics, get_calls_by_territory
from openpyxl import Workbook

from sqlalchemy.pool import StaticPool

# Create an in-memory SQLite engine for unit tests with StaticPool
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


class TestCSCLDCRSystem(unittest.TestCase):

    def test_00_vercel_defaults_to_production_configuration(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None)

        with patch.dict(
            os.environ,
            {
                "VERCEL": "1",
                "DATABASE_URL": "postgresql://deploy:placeholder@db.example.com/app",
                "SECRET_KEY": "test-only-production-key-with-more-than-32-characters",
            },
            clear=True,
        ):
            production_settings = Settings(_env_file=None)
        self.assertEqual(production_settings.APP_ENV, "production")
        self.assertTrue(production_settings.secure_cookies)
        self.assertFalse(production_settings.debug_enabled)

    def test_00_schema_migration_adds_missing_dcr_columns(self):
        """Upgrade an existing DCR table when newer model columns are missing."""
        legacy_engine = create_engine("sqlite:///:memory:")
        with legacy_engine.begin() as connection:
            connection.execute(text("CREATE TABLE fact_dcr (id INTEGER PRIMARY KEY)"))

        ensure_table_columns(FactDCR.__table__, legacy_engine)

        actual_columns = {
            column["name"] for column in inspect(legacy_engine).get_columns("fact_dcr")
        }
        expected_columns = {column.name for column in FactDCR.__table__.columns}
        self.assertTrue(expected_columns.issubset(actual_columns))
        legacy_engine.dispose()

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)
        with TestingSessionLocal() as session:
            seed_database_defaults(session)

    def test_01_health_and_root_redirect(self):
        """Test root endpoint redirects to login for unauthenticated visitors."""
        response = client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["location"])
        login_page = client.get("/auth/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn("/static/images/company-logo.webp", login_page.text)
        logo_response = client.get("/static/images/company-logo.webp")
        self.assertEqual(logo_response.status_code, 200)
        self.assertEqual(logo_response.headers["content-type"], "image/webp")
        self.assertNotIn(">Sign In</a>", login_page.text)
        self.assertNotIn("Default Credentials (Development)", login_page.text)

    def test_02_auth_login_success(self):
        """Test authentication for admin user sets access_token cookie."""
        response = client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("access_token", response.cookies)

    def test_03_auth_login_failure(self):
        """Test invalid credentials returns 400 error."""
        response = client.post(
            "/auth/login",
            data={"username": "admin", "password": "wrongpassword"},
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid username or password", response.text)

    def test_04_cascading_dropdowns(self):
        """Test HTMX cascading endpoints for hospitals and doctors by territory."""
        # Login first
        login_res = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        cookie = login_res.cookies.get("access_token")

        with TestingSessionLocal() as db:
            territory = db.query(Territory).first()
            self.assertIsNotNone(territory)
            t_id = territory.id

        # Test cascading hospitals
        hosp_res = client.get(
            f"/dcr/cascading/hospitals?territory_id={t_id}",
            cookies={"access_token": cookie}
        )
        self.assertEqual(hosp_res.status_code, 200)
        self.assertIn("<option", hosp_res.text)

        # Test cascading doctors
        doc_res = client.get(
            f"/dcr/cascading/doctors?territory_id={t_id}",
            cookies={"access_token": cookie}
        )
        self.assertEqual(doc_res.status_code, 200)
        self.assertIn("<option", doc_res.text)

    def test_05_dcr_submission_via_htmx(self):
        """Test HTMX DCR submission returns inline success alert with DCR number."""
        login_res = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        cookie = login_res.cookies.get("access_token")

        with TestingSessionLocal() as db:
            territory = db.query(Territory).first()
            hospital = db.query(Hospital).first()
            doctor = db.query(Doctor).first()
            visit_type = db.query(VisitType).first()

        form_response = client.get("/dcr/form", cookies={"access_token": cookie})
        self.assertEqual(form_response.status_code, 200)
        self.assertIn('name="primary_indication"', form_response.text)
        self.assertIn('name="visit_outcome"', form_response.text)
        self.assertIn('name="estimated_patient_count"', form_response.text)

        submit_data = {
            "report_date": date.today().isoformat(),
            "territory_id": territory.id,
            "hospital_id": hospital.id if hospital else "",
            "doctor_id": doctor.id,
            "visit_type_id": visit_type.id,
            "products_discussed": "StemPro-X Clinical Trial",
            "samples_given": "1 demo vial",
            "call_notes": "Discussed protocol and hospital supply schedule.",
            "doctor_feedback": "Approved protocol.",
            "primary_indication": "Orthopedic / Osteoarthritis",
            "visit_outcome": "Strong Referral Potential",
            "estimated_patient_count": "27",
            "referral_opportunity": "true",
            "expected_referral_type": "Cellular therapy",
            "expected_referral_date": date.today().isoformat(),
            "referral_status": "Expected",
            "cme_planned": "true",
            "cme_topic": "Regenerative medicine",
            "doctor_question": "What is the expected recovery time?",
            "commercial_concern": "Treatment affordability",
            "competitor_intelligence": "Competitor launched a new program",
            "next_action": "Share clinical evidence",
        }

        response = client.post(
            "/dcr/",
            data=submit_data,
            headers={"HX-Request": "true"},
            cookies={"access_token": cookie}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("submission-success-banner", response.text)
        self.assertIn("DCR-", response.text)
        with TestingSessionLocal() as db:
            dcr = db.query(FactDCR).order_by(FactDCR.id.desc()).first()
            self.assertEqual(dcr.primary_indication, "Orthopedic / Osteoarthritis")
            self.assertEqual(dcr.visit_outcome, "Strong Referral Potential")
            self.assertEqual(dcr.estimated_patient_count, 27)
            self.assertTrue(dcr.referral_opportunity)
            self.assertEqual(dcr.expected_referral_type, "Cellular therapy")
            self.assertEqual(dcr.referral_status, "Expected")
            self.assertTrue(dcr.cme_planned)
            self.assertEqual(dcr.cme_topic, "Regenerative medicine")
            self.assertEqual(dcr.competitor_intelligence, "Competitor launched a new program")
            self.assertEqual(dcr.next_action, "Share clinical evidence")
        list_response = client.get("/dcr/list", cookies={"access_token": cookie})
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("Orthopedic / Osteoarthritis", list_response.text)
        self.assertIn("27", list_response.text)

        json_response = client.post(
            "/dcr/",
            json={
                "report_date": date.today().isoformat(),
                "territory_id": territory.id,
                "doctor_id": doctor.id,
                "visit_type_id": visit_type.id,
                "primary_indication": "Pain Management & Rehabilitation",
                "visit_outcome": "Positive / Interested",
                "estimated_patient_count": 4,
                "referral_opportunity": True,
                "cme_planned": True,
                "cme_topic": "Clinical outcomes",
            },
            cookies={"access_token": cookie},
        )
        self.assertEqual(json_response.status_code, 201)
        self.assertEqual(
            json_response.json()["primary_indication"],
            "Pain Management & Rehabilitation",
        )
        self.assertEqual(json_response.json()["estimated_patient_count"], 4)

    def test_06_master_admin_crud(self):
        """Test admin master data endpoints for territory and doctor creation."""
        login_res = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        cookie = login_res.cookies.get("access_token")

        # Create new territory
        new_terr = {
            "code": "TERR-SYL-01",
            "name": "Sylhet Sadar & Osmani Medical",
            "region": "Sylhet",
            "description": "Northeastern regional coverage"
        }
        res = client.post(
            "/admin/territories",
            data=new_terr,
            cookies={"access_token": cookie},
            headers={"HX-Request": "true"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("TERR-SYL-01", res.text)

    def test_07_analytics_kpis(self):
        """Test analytics KPIs computation and territory breakdown."""
        with TestingSessionLocal() as db:
            metrics = get_dashboard_summary_metrics(db)
            self.assertGreater(metrics["total_calls_all_time"], 0)
            self.assertGreater(metrics["total_territories"], 0)

            territory_data = get_calls_by_territory(db)
            self.assertIsInstance(territory_data, list)
            self.assertGreater(len(territory_data), 0)

    def test_08_oauth2_token_endpoint(self):
        """Test /auth/token programmatic login returns bearer token and user object."""
        response = client.post(
            "/auth/token",
            data={"username": "admin", "password": "admin123"}
        )
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertIn("access_token", json_data)
        self.assertEqual(json_data["token_type"], "bearer")
        self.assertEqual(json_data["user"]["username"], "admin")

    def test_09_marketer_role_restriction_on_admin(self):
        """Test marketer cannot access admin master data management (403 forbidden)."""
        # Login as marketer1
        client.cookies.clear()
        client.post("/auth/login", data={"username": "marketer1", "password": "marketer123"})
        
        # Marketer attempts to access admin dashboard
        response = client.get("/admin", follow_redirects=False)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Administrative privileges required", response.text)

    def test_10_dashboard_api_metrics(self):
        """Test analytics payloads and marketer-specific dashboard scoping."""
        client.cookies.clear()
        marketer_login = client.post(
            "/auth/login",
            data={"username": "marketer1", "password": "marketer123"},
        )
        with TestingSessionLocal() as db:
            marketer = db.query(User).filter(User.username == "marketer1").one()
            doctor = db.query(Doctor).filter(
                Doctor.territory_id == marketer.territory_id
            ).first()
            visit_type = db.query(VisitType).first()
            territory_id = marketer.territory_id
        marketer_dcr = client.post(
            "/dcr/",
            data={
                "report_date": date.today().isoformat(),
                "territory_id": territory_id,
                "doctor_id": doctor.id,
                "visit_type_id": visit_type.id,
                "products_discussed": "Test-Therapy",
                "primary_indication": "Orthopedic / Osteoarthritis",
                "visit_outcome": "Positive / Interested",
                "estimated_patient_count": "3",
                "referral_opportunity": "true",
                "next_followup_date": (date.today() - timedelta(days=3)).isoformat(),
                "next_action": "Call doctor with clinical update",
                "doctor_question": "Is the protocol suitable for older adults?",
                "commercial_concern": "Treatment affordability",
                "competitor_intelligence": "Competitor launched an alternative program",
            },
            cookies={"access_token": marketer_login.cookies.get("access_token")},
        )
        self.assertEqual(marketer_dcr.status_code, 201)

        client.cookies.clear()
        client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        dashboard_page = client.get("/dashboard")
        self.assertEqual(dashboard_page.status_code, 200)
        dashboard_html = unescape(dashboard_page.text)
        for section_title in (
            "Executive Overview",
            "Marketer Scorecard",
            "Doctor Coverage",
            "Referral Funnel",
            "Indication & Therapy",
            "Territory Yield",
            "Follow-up Control",
            "Market Intelligence",
        ):
            self.assertIn(section_title, dashboard_html)
        self.assertEqual(client.get("/admin/settings").status_code, 404)

        response = client.get("/dashboard/api/metrics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("metrics", data)
        self.assertIn("calls_by_territory", data)
        self.assertIn("doctor_frequency", data)
        self.assertIn("daily_trend", data)
        self.assertIn("referral_funnel", data)
        self.assertIn("indication_therapy", data)
        self.assertIn("product_demand", data)
        self.assertIn("marketer_scorecard", data)
        self.assertIn("doctor_coverage", data)
        self.assertIn("territory_performance", data)
        self.assertIn("market_intelligence", data)
        self.assertGreaterEqual(data["follow_up_control"]["overdue_count"], 1)
        self.assertGreaterEqual(data["referral_funnel"]["total_opportunities"], 1)
        self.assertGreaterEqual(data["referral_funnel"]["estimated_candidates"], 3)
        self.assertIn(
            "Orthopedic / Osteoarthritis",
            [item["indication"] for item in data["indication_therapy"]],
        )
        self.assertIn(
            "Test-Therapy",
            [item["product"] for item in data["product_demand"]],
        )
        marketer_scorecard = next(
            item for item in data["marketer_scorecard"]
            if item["marketer_name"] == "Tanvir Ahmed"
        )
        self.assertEqual(marketer_scorecard["call_count"], 1)
        self.assertEqual(marketer_scorecard["estimated_candidates"], 3)
        territory_row = next(
            item for item in data["territory_performance"]
            if item["territory_id"] == territory_id
        )
        self.assertGreaterEqual(territory_row["call_count"], 1)
        self.assertGreaterEqual(territory_row["productive_count"], 1)
        self.assertGreaterEqual(territory_row["referral_count"], 1)
        self.assertGreaterEqual(territory_row["candidate_count"], 3)
        self.assertGreaterEqual(data["market_intelligence"]["reported_entries"], 1)

        client.cookies.clear()
        client.post("/auth/login", data={"username": "marketer1", "password": "marketer123"})
        marketer_data = client.get("/dashboard/api/metrics").json()
        self.assertEqual(marketer_data["metrics"]["total_calls_all_time"], 1)
        self.assertTrue(
            sum(row["call_count"] for row in marketer_data["calls_by_territory"]) == 1
        )
        self.assertEqual(len(marketer_data["doctor_frequency"]), 1)
        self.assertEqual(marketer_data["referral_funnel"]["total_opportunities"], 1)
        self.assertEqual(len(marketer_data["indication_therapy"]), 1)
        self.assertEqual(marketer_data["product_demand"][0]["product"], "Test-Therapy")
        self.assertEqual(marketer_data["market_intelligence"]["reported_entries"], 1)
        self.assertEqual(marketer_data["market_intelligence"]["competitor_mentions"], 1)
        self.assertEqual(
            marketer_data["market_intelligence"]["observations"][0]["doctor_question"],
            "Is the protocol suitable for older adults?",
        )
        self.assertEqual(len(marketer_data["marketer_scorecard"]), 1)
        self.assertEqual(marketer_data["marketer_scorecard"][0]["call_count"], 1)
        self.assertEqual(sum(item["call_count"] for item in marketer_data["territory_performance"]), 1)
        self.assertEqual(
            sum(item["productive_count"] for item in marketer_data["territory_performance"]),
            1,
        )
        self.assertEqual(
            sum(item["visited_doctors"] for item in marketer_data["doctor_coverage"]),
            1,
        )
        follow_up_control = marketer_data["follow_up_control"]
        self.assertEqual(follow_up_control["open_count"], 1)
        self.assertEqual(follow_up_control["overdue_count"], 1)
        self.assertEqual(follow_up_control["tasks"][0]["next_action"], "Call doctor with clinical update")

        with TestingSessionLocal() as db:
            marketer = db.query(User).filter(User.username == "marketer1").one()
            own_dcr = db.query(FactDCR).filter(
                FactDCR.user_id == marketer.id,
                FactDCR.next_action == "Call doctor with clinical update",
            ).one()
            other_dcr = db.query(FactDCR).filter(
                FactDCR.user_id != marketer.id,
                FactDCR.next_followup_date.is_not(None),
            ).first()
            own_dcr_id = own_dcr.id
            other_dcr_id = other_dcr.id

        forbidden_complete = client.post(f"/dcr/{other_dcr_id}/follow-up/complete")
        self.assertEqual(forbidden_complete.status_code, 403)
        completed = client.post(f"/dcr/{own_dcr_id}/follow-up/complete")
        self.assertEqual(completed.status_code, 200)
        self.assertIn("marked complete", completed.json()["message"])
        self.assertEqual(client.get("/dashboard/api/metrics").json()["follow_up_control"]["open_count"], 0)
        with TestingSessionLocal() as db:
            completed_dcr = db.query(FactDCR).filter(FactDCR.id == own_dcr_id).one()
            self.assertTrue(completed_dcr.followup_completed)
            self.assertIsNotNone(completed_dcr.followup_completed_at)

    def test_11_dcr_list_filtering(self):
        """Test /dcr/list renders reports with territory filter."""
        client.cookies.clear()
        client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        response = client.get("/dcr/list?territory_id=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Call Reports Log", response.text)

    def test_12_admin_can_create_each_role_and_manager_cannot_manage_users(self):
        """Only admins can assign roles; all three roles can be created."""
        client.cookies.clear()
        client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        admin_page = client.get("/admin")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("Create User Account", admin_page.text)

        for role in ("admin", "manager", "marketer"):
            username = f"role_test_{role}"
            response = client.post(
                "/admin/users",
                data={
                    "username": username,
                    "email": f"{username}@example.com",
                    "full_name": f"Test {role.title()}",
                    "password": "test-password-123",
                    "role": role,
                    "territory_id": "",
                },
                headers={"HX-Request": "true"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn(username, response.text)
            with TestingSessionLocal() as db:
                user = db.query(User).filter(User.username == username).one()
                self.assertEqual(user.role, role)
                self.assertTrue(verify_password("test-password-123", user.hashed_password))

        client.cookies.clear()
        manager_login = client.post(
            "/auth/login",
            data={"username": "role_test_manager", "password": "test-password-123"},
        )
        self.assertEqual(manager_login.status_code, 200)
        self.assertEqual(client.get("/admin/users").status_code, 403)
        forbidden_create = client.post(
            "/admin/users",
            data={
                "username": "manager_created_user",
                "email": "manager_created_user@example.com",
                "full_name": "Should Not Be Created",
                "password": "test-password-123",
                "role": "admin",
            },
        )
        self.assertEqual(forbidden_create.status_code, 403)

    def test_12_admin_delete_endpoint(self):
        """Test HTMX DELETE endpoint for admin master data."""
        client.cookies.clear()
        client.post("/auth/login", data={"username": "admin", "password": "admin123"})
        
        # Create a disposable visit type to delete
        with TestingSessionLocal() as db:
            vt = VisitType(name="Temporary Visit Type", description="To be deleted", is_active=True)
            db.add(vt)
            db.commit()
            db.refresh(vt)
            vt_id = vt.id

        delete_res = client.delete(f"/admin/visit-types/{vt_id}")
        self.assertEqual(delete_res.status_code, 200)

        # Verify deletion in db
        with TestingSessionLocal() as db:
            found = db.query(VisitType).filter(VisitType.id == vt_id).first()
            self.assertIsNone(found)

    def test_13_user_can_change_password(self):
        client.cookies.clear()
        login = client.post(
            "/auth/login",
            data={
                "username": "role_test_manager",
                "password": "test-password-123",
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/auth/change-password").status_code, 200)

        wrong_current = client.post(
            "/auth/change-password",
            data={
                "current_password": "wrong-current-password",
                "new_password": "Vercel-Safe-Password-2026!",
                "confirm_password": "Vercel-Safe-Password-2026!",
            },
        )
        self.assertEqual(wrong_current.status_code, 400)

        mismatch = client.post(
            "/auth/change-password",
            data={
                "current_password": "test-password-123",
                "new_password": "Vercel-Safe-Password-2026!",
                "confirm_password": "Vercel-Safe-Password-2025!",
            },
        )
        self.assertEqual(mismatch.status_code, 400)

        changed = client.post(
            "/auth/change-password",
            data={
                "current_password": "test-password-123",
                "new_password": "Vercel-Safe-Password-2026!",
                "confirm_password": "Vercel-Safe-Password-2026!",
            },
        )
        self.assertEqual(changed.status_code, 200)
        self.assertIn("Password updated successfully", changed.text)

        client.get("/auth/logout")
        new_login = client.post(
            "/auth/login",
            data={
                "username": "role_test_manager",
                "password": "Vercel-Safe-Password-2026!",
            },
            follow_redirects=False,
        )
        self.assertEqual(new_login.status_code, 302)

    def test_14_tour_plan_permissions_review_publish_and_dcr_linkage(self):
        client.cookies.clear()
        with TestingSessionLocal() as db:
            marketer = db.query(User).filter(User.username == "marketer1").first()
            territory = db.query(Territory).filter(Territory.id == marketer.territory_id).first()
            doctors = db.query(Doctor).filter(Doctor.territory_id == territory.id).order_by(Doctor.id).limit(2).all()
            visit_type = db.query(VisitType).filter(VisitType.is_active.is_(True)).first()
            other_marketer = User(
                username="tour_plan_other_marketer",
                email="tour-plan-other@example.test",
                hashed_password=get_password_hash("tour-plan-password"),
                full_name="Other Tour Plan Marketer",
                role="marketer",
                territory_id=territory.id,
                is_active=True,
            )
            db.add(other_marketer)
            unassigned_marketer = User(
                username="tour_plan_unassigned_marketer",
                email="tour-plan-unassigned@example.test",
                hashed_password=get_password_hash("tour-plan-password"),
                full_name="Unassigned Tour Plan Marketer",
                role="marketer",
                is_active=True,
            )
            db.add(unassigned_marketer)
            db.commit()
            marketer_id = marketer.id
            other_marketer_id = other_marketer.id
            territory_id = territory.id
            doctor_id = doctors[0].id
            second_doctor_id = doctors[1].id
            visit_type_id = visit_type.id
            hospital_id = doctors[0].hospital_id
            second_hospital_id = doctors[1].hospital_id

        today = date.today()
        period_start = today - timedelta(days=today.weekday())
        period_end = period_start + timedelta(days=6)
        rows = [
            {
                "planned_date": today.isoformat(),
                "sequence": 1,
                "doctor_id": doctor_id,
                "visit_type_id": visit_type_id,
                "planned_products": "StemPro-X",
                "planned_indication": "Orthopedic / Osteoarthritis",
                "notes": "Discuss evidence",
            },
            {
                "planned_date": today.isoformat(),
                "sequence": 2,
                "doctor_id": second_doctor_id,
                "visit_type_id": visit_type_id,
                "planned_products": "StemPro-Y",
                "planned_indication": "Orthopedic",
                "notes": "Automatic matching visit",
            },
        ]
        admin_login = client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        self.assertEqual(admin_login.status_code, 302)
        initial_setting = client.get("/tour-plan")
        self.assertEqual(initial_setting.status_code, 200)
        with TestingSessionLocal() as db:
            setting = db.query(TourPlanSetting).filter(TourPlanSetting.id == 1).first()
            self.assertIsNotNone(setting)
            self.assertFalse(setting.marketer_self_service)

        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "marketer1", "password": "marketer123"},
            follow_redirects=False,
        )
        self.assertEqual(client.get("/tour-plan/new").status_code, 403)
        self.assertEqual(
            client.post(
                "/tour-plan/settings",
                data={"marketer_self_service": "true"},
            ).status_code,
            403,
        )

        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        self.assertEqual(
            client.post(
                "/tour-plan/settings",
                data={"marketer_self_service": "true"},
                follow_redirects=False,
            ).status_code,
            303,
        )
        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={
                "username": "tour_plan_unassigned_marketer",
                "password": "tour-plan-password",
            },
            follow_redirects=False,
        )
        self.assertEqual(client.get("/tour-plan/new").status_code, 403)
        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        create_plan_response = client.post(
            "/tour-plan",
            data={
                "title": "Weekly DCR Integration Test",
                "period_type": "weekly",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "territory_id": territory_id,
                "marketer_id": marketer_id,
                "visits_json": json.dumps(rows),
            },
            follow_redirects=False,
        )
        self.assertEqual(create_plan_response.status_code, 303, create_plan_response.text)
        plan_id = int(create_plan_response.headers["location"].rsplit("/", 1)[1])

        other_rows = [{**rows[0], "planned_products": "Other marketer plan"}]
        other_plan_response = client.post(
            "/tour-plan",
            data={
                "title": "Other Marketer Plan",
                "period_type": "weekly",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "territory_id": territory_id,
                "marketer_id": other_marketer_id,
                "visits_json": json.dumps(other_rows),
            },
            follow_redirects=False,
        )
        self.assertEqual(other_plan_response.status_code, 303, other_plan_response.text)
        other_plan_id = int(other_plan_response.headers["location"].rsplit("/", 1)[1])
        competing_plan_response = client.post(
            "/tour-plan",
            data={
                "title": "Competing same-day visit",
                "period_type": "weekly",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "territory_id": territory_id,
                "marketer_id": marketer_id,
                "visits_json": json.dumps([other_rows[0]]),
            },
            follow_redirects=False,
        )
        self.assertEqual(competing_plan_response.status_code, 303, competing_plan_response.text)
        competing_plan_id = int(competing_plan_response.headers["location"].rsplit("/", 1)[1])

        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "marketer1", "password": "marketer123"},
            follow_redirects=False,
        )
        self.assertEqual(client.get(f"/tour-plan/{plan_id}").status_code, 200)
        self.assertEqual(client.get(f"/tour-plan/{other_plan_id}").status_code, 404)
        self.assertEqual(
            client.post(f"/tour-plan/{plan_id}/submit", follow_redirects=False).status_code,
            303,
        )
        self.assertEqual(
            client.post(f"/tour-plan/{competing_plan_id}/submit", follow_redirects=False).status_code,
            303,
        )

        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        self.assertEqual(
            client.post(f"/tour-plan/{plan_id}/approve", follow_redirects=False).status_code,
            303,
        )
        self.assertEqual(
            client.post(f"/tour-plan/{plan_id}/publish", follow_redirects=False).status_code,
            303,
        )
        self.assertEqual(
            client.post(f"/tour-plan/{competing_plan_id}/approve", follow_redirects=False).status_code,
            303,
        )
        self.assertEqual(
            client.post(f"/tour-plan/{competing_plan_id}/publish", follow_redirects=False).status_code,
            303,
        )

        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "marketer1", "password": "marketer123"},
            follow_redirects=False,
        )
        with TestingSessionLocal() as db:
            plan = db.query(TourPlan).filter(TourPlan.id == plan_id).first()
            visit_id = next(visit.id for visit in plan.visits if visit.doctor_id == doctor_id)
            second_visit_id = next(visit.id for visit in plan.visits if visit.doctor_id == second_doctor_id)
            competing_visit_id = next(
                visit.id
                for visit in db.query(TourPlanVisit).join(TourPlan).filter(
                    TourPlan.id == competing_plan_id
                ).all()
            )
        prefilled_form = client.get(f"/dcr/form?planned_visit_id={visit_id}")
        self.assertEqual(prefilled_form.status_code, 200, prefilled_form.text)
        self.assertIn(f'value="{visit_id}" selected', prefilled_form.text)
        self.assertIn(f'value="{doctor_id}" selected', prefilled_form.text)
        self.assertIn(f'value="{visit_type_id}" selected', prefilled_form.text)
        self.assertIn(f'value="{today.isoformat()}"', prefilled_form.text)
        options = client.get(
            f"/tour-plan/visits/options?report_date={today.isoformat()}&doctor_id={doctor_id}"
        )
        self.assertEqual(options.status_code, 200)
        self.assertIn(f"value='{visit_id}'", options.text)
        self.assertIn(f"value='{competing_visit_id}'", options.text)
        ambiguous_call = client.post(
            "/dcr/",
            data={
                "report_date": today.isoformat(),
                "territory_id": territory_id,
                "hospital_id": hospital_id or "",
                "doctor_id": doctor_id,
                "visit_type_id": visit_type_id,
                "products_discussed": "Unplanned actual product",
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(ambiguous_call.status_code, 200, ambiguous_call.text)
        self.assertIn("Unplanned call", ambiguous_call.text)
        dcr_response = client.post(
            "/dcr/",
            data={
                "report_date": today.isoformat(),
                "territory_id": territory_id,
                "hospital_id": hospital_id or "",
                "doctor_id": doctor_id,
                "visit_type_id": visit_type_id,
                "products_discussed": "Different actual product",
                "primary_indication": "Different actual indication",
                "planned_visit_id": visit_id,
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(dcr_response.status_code, 200, dcr_response.text)
        self.assertIn("submission-success-banner", dcr_response.text)
        self.assertIn("Weekly DCR Integration Test", dcr_response.text)
        auto_matched_call = client.post(
            "/dcr/",
            data={
                "report_date": today.isoformat(),
                "territory_id": territory_id,
                "hospital_id": second_hospital_id or "",
                "doctor_id": second_doctor_id,
                "visit_type_id": visit_type_id,
                "products_discussed": "StemPro-Y",
                "primary_indication": "Orthopedic",
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(auto_matched_call.status_code, 200, auto_matched_call.text)
        self.assertIn("Weekly DCR Integration Test", auto_matched_call.text)
        with TestingSessionLocal() as db:
            visit = db.query(TourPlanVisit).filter(TourPlanVisit.id == visit_id).first()
            self.assertEqual(visit.status, "Completed")
            self.assertIsNotNone(visit.actual_dcr_id)
            automatically_matched_visit = db.query(TourPlanVisit).filter(
                TourPlanVisit.id == second_visit_id
            ).first()
            self.assertEqual(automatically_matched_visit.status, "Completed")
            self.assertIsNotNone(automatically_matched_visit.actual_dcr_id)
            self.assertEqual(
                db.query(TourPlan).filter(TourPlan.id == plan_id).first().status,
                "Published",
            )
            actions = {
                audit.action
                for audit in db.query(TourPlanAudit).filter(TourPlanAudit.plan_id == plan_id)
            }
            self.assertTrue({"created", "submitted", "approve", "publish", "visit_completed"} <= actions)
        report = client.get("/tour-plan/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn("product/therapy", report.text)
        self.assertIn("1", report.text)

    def test_15_tour_plan_rejects_duplicate_daily_sequence_and_preserves_form(self):
        client.cookies.clear()
        client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        with TestingSessionLocal() as db:
            marketer = db.query(User).filter(User.username == "marketer1").first()
            territory_id = marketer.territory_id
            doctors = db.query(Doctor).filter(Doctor.territory_id == territory_id).limit(2).all()
            visit_type_id = db.query(VisitType).filter(VisitType.is_active.is_(True)).first().id
        self.assertGreaterEqual(len(doctors), 2)
        today = date.today()
        start = today - timedelta(days=today.weekday())
        rows = [
            {
                "planned_date": today.isoformat(),
                "sequence": 1,
                "doctor_id": doctor.id,
                "visit_type_id": visit_type_id,
            }
            for doctor in doctors
        ]
        response = client.post(
            "/tour-plan",
            data={
                "title": "Duplicate sequence should remain visible",
                "period_type": "weekly",
                "period_start": start.isoformat(),
                "period_end": (start + timedelta(days=6)).isoformat(),
                "territory_id": territory_id,
                "marketer_id": marketer.id,
                "visits_json": json.dumps(rows),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("sequence numbers must be unique", response.text)
        self.assertIn("Duplicate sequence should remain visible", response.text)
        self.assertIn(doctors[0].name, response.text)
        malformed_rows = client.post(
            "/tour-plan",
            data={
                "title": "Malformed visit payload",
                "period_type": "weekly",
                "period_start": start.isoformat(),
                "period_end": (start + timedelta(days=6)).isoformat(),
                "territory_id": territory_id,
                "marketer_id": marketer.id,
                "visits_json": json.dumps(["not an object"]),
            },
        )
        self.assertEqual(malformed_rows.status_code, 400)
        self.assertIn("expected a visit object", malformed_rows.text)

    def test_16_tour_plan_csv_and_xlsx_import_preview_and_confirm(self):
        client.cookies.clear()
        client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        with TestingSessionLocal() as db:
            marketer = db.query(User).filter(User.username == "marketer1").first()
            territory_id = marketer.territory_id
            doctor = db.query(Doctor).filter(Doctor.territory_id == territory_id).first()
            visit_type_id = db.query(VisitType).filter(VisitType.is_active.is_(True)).first().id
        today = date.today()
        start = today - timedelta(days=today.weekday())
        form = {
            "title": "CSV imported plan",
            "period_type": "weekly",
            "period_start": start.isoformat(),
            "period_end": (start + timedelta(days=6)).isoformat(),
            "territory_id": str(territory_id),
            "marketer_id": str(marketer.id),
        }
        csv_content = (
            "planned_date,sequence,doctor_id,visit_type_id,planned_products,planned_indication,notes\n"
            f"{today.isoformat()},1,{doctor.id},{visit_type_id},StemPro-X,Orthopedic,Imported visit\n"
            f"{today.isoformat()},2,999999,{visit_type_id},,,Unknown doctor\n"
        )
        preview = client.post(
            "/tour-plan/import/preview",
            data=form,
            files={"upload": ("tour-plan.csv", csv_content, "text/csv")},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("Row 3", preview.text)
        self.assertIn("selected doctor does not exist", preview.text)
        with TestingSessionLocal() as db:
            batch = db.query(TourPlanImport).order_by(TourPlanImport.created_at.desc()).first()
            batch_id = batch.id
        confirm = client.post(f"/tour-plan/import/{batch_id}/confirm", follow_redirects=False)
        self.assertEqual(confirm.status_code, 303, confirm.text)
        with TestingSessionLocal() as db:
            imported_plan = db.query(TourPlan).filter(TourPlan.title == "CSV imported plan").first()
            self.assertIsNotNone(imported_plan)
            self.assertEqual(imported_plan.audits[0].action, "imported")

        workbook = Workbook()
        sheet = workbook.active
        sheet.append([
            "planned_date", "sequence", "doctor_id", "visit_type_id",
            "planned_products", "planned_indication", "notes",
        ])
        sheet.append([today.isoformat(), 1, doctor.id, visit_type_id, "StemPro-X", "Ortho", "XLSX visit"])
        file_buffer = io.BytesIO()
        workbook.save(file_buffer)
        xlsx_form = {**form, "title": "XLSX imported plan"}
        xlsx_preview = client.post(
            "/tour-plan/import/preview",
            data=xlsx_form,
            files={"upload": ("tour-plan.xlsx", file_buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(xlsx_preview.status_code, 200, xlsx_preview.text)
        self.assertIn("StemPro-X", xlsx_preview.text)
        malformed = client.post(
            "/tour-plan/import/preview",
            data=xlsx_form,
            files={"upload": ("broken.xlsx", b"not a workbook", "application/octet-stream")},
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertIn("Could not read", malformed.text)

    def test_17_admin_can_publish_assigned_draft_and_marketer_can_start_its_dcr(self):
        client.cookies.clear()
        with TestingSessionLocal() as db:
            marketer = db.query(User).filter(User.username == "marketer1").first()
            doctor = db.query(Doctor).filter(
                Doctor.territory_id == marketer.territory_id
            ).first()
            visit_type = db.query(VisitType).filter(VisitType.is_active.is_(True)).first()
            marketer_id = marketer.id
            territory_id = marketer.territory_id
            doctor_id = doctor.id
            visit_type_id = visit_type.id
        today = date.today()
        period_start = today - timedelta(days=today.weekday())
        admin_login = client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        self.assertEqual(admin_login.status_code, 302)
        created = client.post(
            "/tour-plan",
            data={
                "title": "Admin Draft Publish Test",
                "period_type": "weekly",
                "period_start": period_start.isoformat(),
                "period_end": (period_start + timedelta(days=6)).isoformat(),
                "territory_id": territory_id,
                "marketer_id": marketer_id,
                "visits_json": json.dumps([{
                    "planned_date": today.isoformat(),
                    "sequence": 1,
                    "doctor_id": doctor_id,
                    "visit_type_id": visit_type_id,
                }]),
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        plan_id = int(created.headers["location"].rsplit("/", 1)[1])
        draft_detail = client.get(f"/tour-plan/{plan_id}")
        self.assertEqual(draft_detail.status_code, 200)
        self.assertIn("Publish Draft for Marketer", draft_detail.text)
        published = client.post(
            f"/tour-plan/{plan_id}/publish",
            follow_redirects=False,
        )
        self.assertEqual(published.status_code, 303, published.text)
        with TestingSessionLocal() as db:
            plan = db.query(TourPlan).filter(TourPlan.id == plan_id).first()
            self.assertEqual(plan.status, "Published")
            visit_id = plan.visits[0].id
            self.assertEqual(plan.audits[-1].action, "publish")

        client.get("/auth/logout")
        client.post(
            "/auth/login",
            data={"username": "marketer1", "password": "marketer123"},
            follow_redirects=False,
        )
        detail = client.get(f"/tour-plan/{plan_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(f"/dcr/form?planned_visit_id={visit_id}", detail.text)
        form = client.get(f"/dcr/form?planned_visit_id={visit_id}")
        self.assertEqual(form.status_code, 200, form.text)
        self.assertIn("Admin Draft Publish Test", form.text)
        self.assertIn(f'value="{doctor_id}" selected', form.text)


if __name__ == "__main__":
    unittest.main()
