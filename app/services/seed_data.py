from datetime import date, timedelta
import logging
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.master import Territory, Hospital, Doctor, VisitType
from app.models.dcr import FactDCR
from app.services.auth_service import get_password_hash

logger = logging.getLogger(__name__)


def seed_database_defaults(db: Session):
    """Seed initial territories, hospitals, doctors, visit types, users, and sample DCRs if empty."""
    # 1. Seed Visit Types
    if db.query(VisitType).count() == 0:
        visit_types = [
            VisitType(name="Regular Call", description="Standard routine promotional visit"),
            VisitType(name="Product Presentation", description="Detailed product introduction and clinical presentation"),
            VisitType(name="Follow-up Call", description="Follow-up on previous commitment or sample experience"),
            VisitType(name="Sample Delivery", description="Delivery of medical samples and literature"),
            VisitType(name="CME / Scientific Meeting", description="Invitation and discussion regarding scientific conferences"),
        ]
        db.add_all(visit_types)
        db.commit()
        logger.info("Default visit types seeded.")

    # 2. Seed Territories
    if db.query(Territory).count() == 0:
        territories = [
            Territory(
                code="TERR-DHK-01",
                name="Gulshan & Banani Zone",
                region="Dhaka North",
                description="High-tier corporate hospitals and specialized clinics"
            ),
            Territory(
                code="TERR-DHK-02",
                name="Dhanmondi & Green Road Zone",
                region="Dhaka Central",
                description="Dense medical hub with key opinion leaders and medical colleges"
            ),
            Territory(
                code="TERR-DHK-03",
                name="Shahbagh & Old Dhaka Zone",
                region="Dhaka South",
                description="Government medical colleges (BSMMU, DMCH, Mitford)"
            ),
            Territory(
                code="TERR-CTG-01",
                name="Chittagong Medical Zone",
                region="Chittagong",
                description="Chittagong Medical College & Panchlaish medical zone"
            )
        ]
        db.add_all(territories)
        db.commit()
        logger.info("Default territories seeded.")

    # Fetch territories for foreign keys
    t1 = db.query(Territory).filter(Territory.code == "TERR-DHK-01").first()
    t2 = db.query(Territory).filter(Territory.code == "TERR-DHK-02").first()
    t3 = db.query(Territory).filter(Territory.code == "TERR-DHK-03").first()
    t4 = db.query(Territory).filter(Territory.code == "TERR-CTG-01").first()

    # 3. Seed Hospitals
    if db.query(Hospital).count() == 0 and t1 and t2 and t3:
        hospitals = [
            Hospital(
                code="HOSP-UHL-01",
                name="United Hospital Limited",
                type="Specialized Hospital",
                address="Plot 15, Road 71, Gulshan, Dhaka",
                phone="+880 2-8836444",
                territory_id=t1.id
            ),
            Hospital(
                code="HOSP-EVR-01",
                name="Evercare Hospital Dhaka",
                type="Multispecialty Hospital",
                address="Plot 81, Block E, Bashundhara, Dhaka",
                phone="+880 2-8431661",
                territory_id=t1.id
            ),
            Hospital(
                code="HOSP-SQR-01",
                name="Square Hospital Limited",
                type="Multispecialty Hospital",
                address="18/F, Bir Uttam Qazi Nuruzzaman Sarak, West Panthapath, Dhaka",
                phone="+880 2-8144400",
                territory_id=t2.id
            ),
            Hospital(
                code="HOSP-LBA-01",
                name="Labaid Specialized Hospital",
                type="Cardiac & Specialized",
                address="House 06, Road 04, Dhanmondi, Dhaka",
                phone="+880 2-9676356",
                territory_id=t2.id
            ),
            Hospital(
                code="HOSP-BSM-01",
                name="BSMMU (PG Hospital)",
                type="Government Medical University",
                address="Shahbagh, Dhaka",
                phone="+880 2-9661051",
                territory_id=t3.id
            ),
            Hospital(
                code="HOSP-DMCH-01",
                name="Dhaka Medical College Hospital",
                type="Government Medical College",
                address="Secretariat Road, Dhaka",
                phone="+880 2-55165088",
                territory_id=t3.id
            )
        ]
        db.add_all(hospitals)
        db.commit()
        logger.info("Default hospitals seeded.")

    # 4. Seed Doctors
    if db.query(Doctor).count() == 0 and t1 and t2 and t3:
        h1 = db.query(Hospital).filter(Hospital.code == "HOSP-UHL-01").first()
        h2 = db.query(Hospital).filter(Hospital.code == "HOSP-SQR-01").first()
        h3 = db.query(Hospital).filter(Hospital.code == "HOSP-BSM-01").first()

        doctors = [
            Doctor(
                name="Prof. Dr. N. A. M. Momenuzzaman",
                qualification="MBBS, FCPS (Med), MD (Cardiology)",
                specialty="Cardiology",
                designation="Chief Consultant Cardiologist",
                phone="01711000001",
                email="momenuzzaman@example.com",
                territory_id=t1.id,
                hospital_id=h1.id if h1 else None
            ),
            Doctor(
                name="Dr. Afzalur Rahman",
                qualification="MBBS, MD (Card), PhD (Card)",
                specialty="Interventional Cardiology",
                designation="Professor & Senior Consultant",
                phone="01711000002",
                email="afzalur@example.com",
                territory_id=t1.id,
                hospital_id=h1.id if h1 else None
            ),
            Doctor(
                name="Prof. Dr. Quazi Tarikul Islam",
                qualification="MBBS, FCPS, FACP, FRCP",
                specialty="Internal Medicine",
                designation="Professor of Medicine",
                phone="01711000003",
                email="tarikul@example.com",
                territory_id=t2.id,
                hospital_id=h2.id if h2 else None
            ),
            Doctor(
                name="Dr. Mirza Nazim Uddin",
                qualification="MBBS, FCPS (Medicine)",
                specialty="Internal Medicine & Critical Care",
                designation="Senior Consultant",
                phone="01711000004",
                email="nazim@example.com",
                territory_id=t2.id,
                hospital_id=h2.id if h2 else None
            ),
            Doctor(
                name="Prof. Dr. ABM Abdullah",
                qualification="MBBS, MRCP (UK), FRCP (Edin)",
                specialty="Internal Medicine",
                designation="Emeritus Professor & Dean",
                phone="01711000005",
                email="abdullah@example.com",
                territory_id=t3.id,
                hospital_id=h3.id if h3 else None
            ),
            Doctor(
                name="Prof. Dr. Md. Titu Miah",
                qualification="MBBS, FCPS, FACP",
                specialty="Hematology & Stem Cell",
                designation="Principal & Professor",
                phone="01711000006",
                email="titu@example.com",
                territory_id=t3.id,
                hospital_id=h3.id if h3 else None
            )
        ]
        db.add_all(doctors)
        db.commit()
        logger.info("Default doctors seeded.")

    # 5. Seed Users (Admin and Marketer)
    admin_user = db.query(User).filter(User.username == "admin").first()
    if not admin_user:
        admin_user = User(
            username="admin",
            email="admin@concordpharma.com",
            hashed_password=get_password_hash("admin123"),
            full_name="System Administrator",
            role="admin",
            employee_id="EMP-ADM-001",
            phone="01700000000",
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        logger.info("Admin user 'admin' created with password 'admin123'.")

    marketer_user = db.query(User).filter(User.username == "marketer1").first()
    if not marketer_user and t1:
        marketer_user = User(
            username="marketer1",
            email="marketer1@concordpharma.com",
            hashed_password=get_password_hash("marketer123"),
            full_name="Tanvir Ahmed",
            role="marketer",
            employee_id="EMP-MKT-101",
            phone="01711223344",
            is_active=True,
            territory_id=t1.id
        )
        db.add(marketer_user)
        db.commit()
        logger.info("Marketer user 'marketer1' created with password 'marketer123'.")

    # 6. Seed Sample DCRs if none exist
    if db.query(FactDCR).count() == 0 and admin_user:
        all_docs = db.query(Doctor).all()
        all_vts = db.query(VisitType).all()
        today = date.today()

        sample_dcrs = []
        dcr_counter = 1
        for i, doc in enumerate(all_docs):
            call_day = today - timedelta(days=(i % 5))
            vt = all_vts[i % len(all_vts)]
            dcr_num = f"DCR-{call_day.strftime('%Y%m%d')}-{dcr_counter:04d}"
            dcr_counter += 1

            sample_dcrs.append(
                FactDCR(
                    dcr_number=dcr_num,
                    report_date=call_day,
                    user_id=admin_user.id,
                    territory_id=doc.territory_id,
                    hospital_id=doc.hospital_id,
                    doctor_id=doc.id,
                    visit_type_id=vt.id,
                    products_discussed="StemPro-X Regenerative Infusion, CellRegen-500",
                    samples_given="2 Starter Kits, Product Dossier",
                    call_notes=f"Detailed review of regenerative cellular efficacy with {doc.name}.",
                    doctor_feedback="Very receptive to clinical data; agreed to prescribe for trial cohort.",
                    next_followup_date=call_day + timedelta(days=14),
                    status="Submitted"
                )
            )

        db.add_all(sample_dcrs)
        db.commit()
        logger.info("Sample DCR records seeded.")
