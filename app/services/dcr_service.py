from datetime import date, datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.dcr import FactDCR
from app.models.user import User
from app.models.master import Territory, Hospital, Doctor, VisitType
from app.schemas.dcr import DcrCreate, DcrResponse


def generate_dcr_number(db: Session, report_date: date) -> str:
    """Generate sequential daily DCR number like DCR-20261006-0001."""
    date_str = report_date.strftime("%Y%m%d")
    prefix = f"DCR-{date_str}-"
    
    # Find count of records created for this date
    count = db.query(FactDCR).filter(FactDCR.report_date == report_date).count()
    next_seq = count + 1
    dcr_number = f"{prefix}{next_seq:04d}"
    
    # Ensure uniqueness in case of race condition
    while db.query(FactDCR).filter(FactDCR.dcr_number == dcr_number).first():
        next_seq += 1
        dcr_number = f"{prefix}{next_seq:04d}"
        
    return dcr_number


def create_dcr(db: Session, dcr_in: DcrCreate, user_id: int) -> FactDCR:
    """Create and persist a new FactDCR entry."""
    dcr_number = generate_dcr_number(db, dcr_in.report_date)
    
    db_dcr = FactDCR(
        dcr_number=dcr_number,
        report_date=dcr_in.report_date,
        user_id=user_id,
        territory_id=dcr_in.territory_id,
        hospital_id=dcr_in.hospital_id if dcr_in.hospital_id and dcr_in.hospital_id > 0 else None,
        doctor_id=dcr_in.doctor_id,
        visit_type_id=dcr_in.visit_type_id,
        products_discussed=dcr_in.products_discussed,
        samples_given=dcr_in.samples_given,
        call_notes=dcr_in.call_notes,
        doctor_feedback=dcr_in.doctor_feedback,
        next_followup_date=dcr_in.next_followup_date,
        primary_indication=dcr_in.primary_indication,
        visit_outcome=dcr_in.visit_outcome,
        estimated_patient_count=dcr_in.estimated_patient_count,
        referral_opportunity=dcr_in.referral_opportunity,
        expected_referral_type=dcr_in.expected_referral_type,
        expected_referral_date=dcr_in.expected_referral_date,
        referral_status=dcr_in.referral_status,
        cme_planned=dcr_in.cme_planned,
        cme_topic=dcr_in.cme_topic,
        doctor_question=dcr_in.doctor_question,
        commercial_concern=dcr_in.commercial_concern,
        competitor_intelligence=dcr_in.competitor_intelligence,
        next_action=dcr_in.next_action,
        status="Submitted"
    )
    db.add(db_dcr)
    db.commit()
    db.refresh(db_dcr)
    return db_dcr


def get_dcrs(
    db: Session,
    current_user: User,
    territory_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 100
) -> List[FactDCR]:
    """Retrieve DCR records with role-based filtering."""
    query = db.query(FactDCR)

    # If field marketer, only show their own records (or territory)
    if current_user.role == "marketer":
        query = query.filter(FactDCR.user_id == current_user.id)
    elif territory_id:
        query = query.filter(FactDCR.territory_id == territory_id)

    if doctor_id:
        query = query.filter(FactDCR.doctor_id == doctor_id)
    if start_date:
        query = query.filter(FactDCR.report_date >= start_date)
    if end_date:
        query = query.filter(FactDCR.report_date <= end_date)

    return query.order_by(FactDCR.report_date.desc(), FactDCR.id.desc()).limit(limit).all()


def format_dcr_for_display(dcr: FactDCR) -> dict:
    """Format DCR model with relational label strings for Jinja2 templates."""
    return {
        "id": dcr.id,
        "dcr_number": dcr.dcr_number,
        "report_date": dcr.report_date.strftime("%d-%b-%Y") if dcr.report_date else "",
        "marketer_name": dcr.user.full_name if dcr.user else "N/A",
        "territory_name": dcr.territory.name if dcr.territory else "N/A",
        "hospital_name": dcr.hospital.name if dcr.hospital else "Direct Chamber",
        "doctor_name": dcr.doctor.name if dcr.doctor else "N/A",
        "doctor_specialty": dcr.doctor.specialty if dcr.doctor else "",
        "visit_type_name": dcr.visit_type.name if dcr.visit_type else "Regular",
        "products_discussed": dcr.products_discussed or "None",
        "samples_given": dcr.samples_given or "None",
        "call_notes": dcr.call_notes or "",
        "doctor_feedback": dcr.doctor_feedback or "",
        "next_followup_date": dcr.next_followup_date.strftime("%d-%b-%Y") if dcr.next_followup_date else None,
        "followup_completed": dcr.followup_completed,
        "followup_completed_at": dcr.followup_completed_at.isoformat() if dcr.followup_completed_at else None,
        "primary_indication": dcr.primary_indication or "",
        "visit_outcome": dcr.visit_outcome or "",
        "estimated_patient_count": dcr.estimated_patient_count or 0,
        "referral_opportunity": dcr.referral_opportunity,
        "expected_referral_type": dcr.expected_referral_type or "",
        "expected_referral_date": dcr.expected_referral_date.strftime("%d-%b-%Y") if dcr.expected_referral_date else None,
        "referral_status": dcr.referral_status or "",
        "cme_planned": dcr.cme_planned,
        "cme_topic": dcr.cme_topic or "",
        "doctor_question": dcr.doctor_question or "",
        "commercial_concern": dcr.commercial_concern or "",
        "competitor_intelligence": dcr.competitor_intelligence or "",
        "next_action": dcr.next_action or "",
        "status": dcr.status
    }
