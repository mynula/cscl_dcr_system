import unittest
import os
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
from app.services.auth_service import get_password_hash, create_access_token, verify_password
from app.services.seed_data import seed_database_defaults
from app.services.analytics_service import get_dashboard_summary_metrics, get_calls_by_territory

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


if __name__ == "__main__":
    unittest.main()
