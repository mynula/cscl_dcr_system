from datetime import date, timedelta
import re
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import Integer, case, desc, func, or_
from sqlalchemy.sql import and_

from app.models.dcr import FactDCR
from app.models.master import Territory, Hospital, Doctor, VisitType
from app.models.user import User


def get_dashboard_summary_metrics(
    db: Session,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Calculate key performance indicators for the management dashboard."""
    today = date.today()
    first_day_of_month = today.replace(day=1)

    total_calls_all_time_query = db.query(func.count(FactDCR.id))
    total_calls_today_query = db.query(func.count(FactDCR.id)).filter(FactDCR.report_date == today)
    total_calls_this_month_query = db.query(func.count(FactDCR.id)).filter(FactDCR.report_date >= first_day_of_month)
    unique_doctors_query = db.query(func.count(func.distinct(FactDCR.doctor_id)))
    active_marketers_query = db.query(func.count(func.distinct(FactDCR.user_id)))

    if user_id is not None:
        total_calls_all_time_query = total_calls_all_time_query.filter(FactDCR.user_id == user_id)
        total_calls_today_query = total_calls_today_query.filter(FactDCR.user_id == user_id)
        total_calls_this_month_query = total_calls_this_month_query.filter(FactDCR.user_id == user_id)
        unique_doctors_query = unique_doctors_query.filter(FactDCR.user_id == user_id)
        active_marketers_query = active_marketers_query.filter(FactDCR.user_id == user_id)

    total_calls_all_time = total_calls_all_time_query.scalar() or 0
    total_calls_today = total_calls_today_query.scalar() or 0
    total_calls_this_month = total_calls_this_month_query.scalar() or 0
    unique_doctors_covered = unique_doctors_query.scalar() or 0
    total_doctors_master = db.query(func.count(Doctor.id)).scalar() or 0
    coverage_rate = round((unique_doctors_covered / total_doctors_master * 100), 1) if total_doctors_master > 0 else 0.0

    active_marketers = active_marketers_query.scalar() or 0
    total_territories = db.query(func.count(Territory.id)).scalar() or 0

    return {
        "total_calls_all_time": total_calls_all_time,
        "total_calls_today": total_calls_today,
        "total_calls_this_month": total_calls_this_month,
        "unique_doctors_covered": unique_doctors_covered,
        "total_doctors_master": total_doctors_master,
        "coverage_rate": coverage_rate,
        "active_marketers": active_marketers,
        "total_territories": total_territories,
    }


def get_calls_by_territory(
    db: Session,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Aggregate DCR call counts grouped by territory."""
    dcr_join = Territory.id == FactDCR.territory_id
    if user_id is not None:
        dcr_join = dcr_join & (FactDCR.user_id == user_id)

    results = (
        db.query(
            Territory.id,
            Territory.code,
            Territory.name,
            Territory.region,
            func.count(FactDCR.id).label("call_count")
        )
        .outerjoin(FactDCR, dcr_join)
        .group_by(Territory.id, Territory.code, Territory.name, Territory.region)
        .order_by(desc("call_count"))
        .all()
    )

    total_calls = sum(r.call_count for r in results) or 1
    output = []
    for r in results:
        percentage = round((r.call_count / total_calls) * 100, 1)
        output.append({
            "territory_id": r.id,
            "code": r.code,
            "name": r.name,
            "region": r.region,
            "call_count": r.call_count,
            "percentage": percentage
        })
    return output


def get_doctor_visit_frequency(
    db: Session,
    limit: int = 10,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Aggregate top visited doctors with call frequencies and last interaction."""
    query = (
        db.query(
            Doctor.id,
            Doctor.name,
            Doctor.specialty,
            Hospital.name.label("hospital_name"),
            Territory.name.label("territory_name"),
            func.count(FactDCR.id).label("visit_count"),
            func.max(FactDCR.report_date).label("last_visit_date")
        )
        .join(FactDCR, Doctor.id == FactDCR.doctor_id)
        .outerjoin(Hospital, Doctor.hospital_id == Hospital.id)
        .outerjoin(Territory, Doctor.territory_id == Territory.id)
    )
    if user_id is not None:
        query = query.filter(FactDCR.user_id == user_id)
    results = (
        query
        .group_by(Doctor.id, Doctor.name, Doctor.specialty, Hospital.name, Territory.name)
        .order_by(desc("visit_count"))
        .limit(limit)
        .all()
    )

    output = []
    for r in results:
        output.append({
            "doctor_id": r.id,
            "doctor_name": r.name,
            "specialty": r.specialty,
            "hospital_name": r.hospital_name or "Chamber",
            "territory_name": r.territory_name or "N/A",
            "visit_count": r.visit_count,
            "last_visit_date": r.last_visit_date.strftime("%d-%b-%Y") if r.last_visit_date else "N/A"
        })
    return output


def get_calls_by_visit_type(
    db: Session,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Aggregate call distribution across different visit types."""
    query = (
        db.query(
            VisitType.name,
            func.count(FactDCR.id).label("call_count")
        )
        .join(FactDCR, VisitType.id == FactDCR.visit_type_id)
    )
    if user_id is not None:
        query = query.filter(FactDCR.user_id == user_id)
    results = (
        query
        .group_by(VisitType.name)
        .order_by(desc("call_count"))
        .all()
    )

    total_calls = sum(r.call_count for r in results) or 1
    output = []
    for r in results:
        percentage = round((r.call_count / total_calls) * 100, 1)
        output.append({
            "visit_type": r.name,
            "call_count": r.call_count,
            "percentage": percentage
        })
    return output


def get_daily_activity_trend(
    db: Session,
    days: int = 7,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Get day-by-day call counts for recent days."""
    start_date = date.today() - timedelta(days=days - 1)
    query = (
        db.query(
            FactDCR.report_date,
            func.count(FactDCR.id).label("call_count")
        )
        .filter(FactDCR.report_date >= start_date)
    )
    if user_id is not None:
        query = query.filter(FactDCR.user_id == user_id)
    results = (
        query
        .group_by(FactDCR.report_date)
        .order_by(FactDCR.report_date.asc())
        .all()
    )

    data_map = {r.report_date: r.call_count for r in results}
    trend = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        trend.append({
            "date": d.strftime("%d %b"),
            "date_iso": d.isoformat(),
            "count": data_map.get(d, 0)
        })
    return trend


def get_referral_funnel(
    db: Session,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Aggregate referral opportunity counts and estimated candidates by status."""
    query = (
        db.query(
            FactDCR.referral_status,
            func.count(FactDCR.id).label("opportunity_count"),
            func.coalesce(func.sum(FactDCR.estimated_patient_count), 0).label("candidate_count"),
        )
        .filter(FactDCR.referral_opportunity.is_(True))
    )
    if user_id is not None:
        query = query.filter(FactDCR.user_id == user_id)
    rows = query.group_by(FactDCR.referral_status).all()

    counts = {
        "identified": {"opportunity_count": 0, "candidate_count": 0},
        "expected": {"opportunity_count": 0, "candidate_count": 0},
        "in progress": {"opportunity_count": 0, "candidate_count": 0},
        "converted": {"opportunity_count": 0, "candidate_count": 0},
        "closed": {"opportunity_count": 0, "candidate_count": 0},
    }
    for row in rows:
        key = (row.referral_status or "Identified").strip().casefold()
        status_counts = counts.setdefault(key, {"opportunity_count": 0, "candidate_count": 0})
        status_counts["opportunity_count"] += row.opportunity_count
        status_counts["candidate_count"] += row.candidate_count

    statuses = [
        {
            "status": name.title(),
            "opportunity_count": values["opportunity_count"],
            "candidate_count": values["candidate_count"],
        }
        for name, values in counts.items()
    ]
    return {
        "total_opportunities": sum(item["opportunity_count"] for item in statuses),
        "estimated_candidates": sum(item["candidate_count"] for item in statuses),
        "statuses": statuses,
    }


def get_indication_therapy_breakdown(
    db: Session,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Aggregate call volume, candidates, and referrals for each indication."""
    query = db.query(
        FactDCR.primary_indication,
        func.count(FactDCR.id).label("call_count"),
        func.coalesce(func.sum(FactDCR.estimated_patient_count), 0).label("candidate_count"),
        func.coalesce(func.sum(FactDCR.referral_opportunity.cast(Integer)), 0).label("referral_count"),
    ).filter(FactDCR.primary_indication.is_not(None), FactDCR.primary_indication != "")
    if user_id is not None:
        query = query.filter(FactDCR.user_id == user_id)
    rows = (
        query
        .group_by(FactDCR.primary_indication)
        .order_by(desc("call_count"), FactDCR.primary_indication)
        .all()
    )

    total_calls = sum(row.call_count for row in rows) or 1
    return [
        {
            "indication": row.primary_indication,
            "call_count": row.call_count,
            "candidate_count": row.candidate_count,
            "referral_count": row.referral_count,
            "percentage": round(row.call_count / total_calls * 100, 1),
        }
        for row in rows
    ]


def get_product_demand(
    db: Session,
    limit: int = 10,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Count product mentions in the comma-, semicolon-, or line-separated DCR field."""
    query = db.query(FactDCR.products_discussed).filter(
        FactDCR.products_discussed.is_not(None),
        FactDCR.products_discussed != "",
    )
    if user_id is not None:
        query = query.filter(FactDCR.user_id == user_id)

    products: Dict[str, Dict[str, Any]] = {}
    for (product_text,) in query.all():
        seen_in_call = set()
        for raw_name in re.split(r"[,;\n]+", product_text):
            name = re.sub(r"\s+", " ", raw_name).strip()
            key = name.casefold()
            if not key or key in seen_in_call:
                continue
            seen_in_call.add(key)
            product = products.setdefault(key, {"product": name, "call_count": 0})
            product["call_count"] += 1

    return sorted(
        products.values(),
        key=lambda item: (-item["call_count"], item["product"].casefold())
    )[:limit]


def get_marketer_scorecard(
    db: Session,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Summarize month-to-date field activity by active marketer."""
    today = date.today()
    first_day_of_month = today.replace(day=1)
    dcr_join = and_(
        User.id == FactDCR.user_id,
        FactDCR.report_date >= first_day_of_month,
        FactDCR.report_date <= today,
    )
    if user_id is not None:
        dcr_join = and_(dcr_join, FactDCR.user_id == user_id)

    query = (
        db.query(
            User.id.label("user_id"),
            User.full_name.label("marketer_name"),
            func.count(FactDCR.id).label("call_count"),
            func.count(func.distinct(FactDCR.doctor_id)).label("doctors_visited"),
            func.coalesce(
                func.sum(case((FactDCR.referral_opportunity.is_(True), 1), else_=0)),
                0,
            ).label("referral_opportunities"),
            func.coalesce(func.sum(FactDCR.estimated_patient_count), 0).label("estimated_candidates"),
        )
        .outerjoin(FactDCR, dcr_join)
        .filter(User.role == "marketer", User.is_active.is_(True))
    )
    if user_id is not None:
        query = query.filter(User.id == user_id)

    rows = (
        query
        .group_by(User.id, User.full_name)
        .order_by(desc("call_count"), User.full_name)
        .all()
    )
    return [
        {
            "user_id": row.user_id,
            "marketer_name": row.marketer_name,
            "call_count": row.call_count,
            "doctors_visited": row.doctors_visited,
            "referral_opportunities": row.referral_opportunities,
            "estimated_candidates": row.estimated_candidates,
        }
        for row in rows
    ]


def get_doctor_coverage(
    db: Session,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Measure monthly doctor coverage by territory."""
    today = date.today()
    first_day_of_month = today.replace(day=1)
    dcr_join = and_(
        Doctor.id == FactDCR.doctor_id,
        FactDCR.report_date >= first_day_of_month,
        FactDCR.report_date <= today,
    )
    if user_id is not None:
        dcr_join = and_(dcr_join, FactDCR.user_id == user_id)

    rows = (
        db.query(
            Territory.id.label("territory_id"),
            Territory.name.label("territory_name"),
            func.count(func.distinct(Doctor.id)).label("total_doctors"),
            func.count(func.distinct(FactDCR.doctor_id)).label("visited_doctors"),
        )
        .outerjoin(Doctor, Territory.id == Doctor.territory_id)
        .outerjoin(FactDCR, dcr_join)
        .group_by(Territory.id, Territory.name)
        .order_by(Territory.name)
        .all()
    )
    return [
        {
            "territory_id": row.territory_id,
            "territory_name": row.territory_name,
            "total_doctors": row.total_doctors,
            "visited_doctors": row.visited_doctors,
            "coverage_percentage": round(row.visited_doctors / row.total_doctors * 100, 1)
            if row.total_doctors
            else 0.0,
        }
        for row in rows
    ]


def get_follow_up_control(
    db: Session,
    user_id: Optional[int] = None,
    limit: int = 25
) -> Dict[str, Any]:
    """Return open follow-ups and due-state counts, scoped to a user when requested."""
    today = date.today()
    open_query = db.query(FactDCR).filter(
        FactDCR.next_followup_date.is_not(None),
        FactDCR.followup_completed.is_(False),
    )
    if user_id is not None:
        open_query = open_query.filter(FactDCR.user_id == user_id)

    overdue_count = open_query.filter(FactDCR.next_followup_date < today).count()
    due_today_count = open_query.filter(FactDCR.next_followup_date == today).count()
    upcoming_count = open_query.filter(FactDCR.next_followup_date > today).count()

    tasks_query = (
        db.query(
            FactDCR,
            User.full_name.label("marketer_name"),
            Doctor.name.label("doctor_name"),
            Territory.name.label("territory_name"),
        )
        .join(User, FactDCR.user_id == User.id)
        .join(Doctor, FactDCR.doctor_id == Doctor.id)
        .join(Territory, FactDCR.territory_id == Territory.id)
        .filter(
            FactDCR.next_followup_date.is_not(None),
            FactDCR.followup_completed.is_(False),
        )
    )
    if user_id is not None:
        tasks_query = tasks_query.filter(FactDCR.user_id == user_id)

    tasks = []
    for dcr, marketer_name, doctor_name, territory_name in (
        tasks_query
        .order_by(FactDCR.next_followup_date.asc(), FactDCR.id.asc())
        .limit(limit)
        .all()
    ):
        followup_date = dcr.next_followup_date
        if followup_date < today:
            due_status = "Overdue"
            days_overdue = (today - followup_date).days
        elif followup_date == today:
            due_status = "Due today"
            days_overdue = 0
        else:
            due_status = "Upcoming"
            days_overdue = 0
        tasks.append({
            "dcr_id": dcr.id,
            "dcr_number": dcr.dcr_number,
            "followup_date": followup_date.isoformat(),
            "due_status": due_status,
            "days_overdue": days_overdue,
            "marketer_name": marketer_name,
            "doctor_name": doctor_name,
            "territory_name": territory_name,
            "next_action": dcr.next_action or "",
        })

    return {
        "open_count": overdue_count + due_today_count + upcoming_count,
        "overdue_count": overdue_count,
        "due_today_count": due_today_count,
        "upcoming_count": upcoming_count,
        "tasks": tasks,
    }


def get_territory_performance(
    db: Session,
    user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Aggregate month-to-date call, productivity, referral, and candidate metrics."""
    today = date.today()
    first_day_of_month = today.replace(day=1)
    dcr_join = and_(
        Territory.id == FactDCR.territory_id,
        FactDCR.report_date >= first_day_of_month,
        FactDCR.report_date <= today,
    )
    if user_id is not None:
        dcr_join = and_(dcr_join, FactDCR.user_id == user_id)

    productive_outcomes = (
        "Strong Referral Potential",
        "Positive / Interested",
        "Referral Expected",
        "CME Interest",
        "Appointment/Meeting Requested",
    )
    rows = (
        db.query(
            Territory.id.label("territory_id"),
            Territory.code.label("territory_code"),
            Territory.name.label("territory_name"),
            func.count(FactDCR.id).label("call_count"),
            func.coalesce(
                func.sum(case((FactDCR.visit_outcome.in_(productive_outcomes), 1), else_=0)),
                0,
            ).label("productive_count"),
            func.coalesce(
                func.sum(case((FactDCR.referral_opportunity.is_(True), 1), else_=0)),
                0,
            ).label("referral_count"),
            func.coalesce(func.sum(FactDCR.estimated_patient_count), 0).label("candidate_count"),
        )
        .outerjoin(FactDCR, dcr_join)
        .group_by(Territory.id, Territory.code, Territory.name)
        .order_by(desc("call_count"), Territory.name)
        .all()
    )
    return [
        {
            "territory_id": row.territory_id,
            "territory_code": row.territory_code,
            "territory_name": row.territory_name,
            "call_count": row.call_count,
            "productive_count": row.productive_count,
            "productive_rate": round(row.productive_count / row.call_count * 100, 1)
            if row.call_count
            else 0.0,
            "referral_count": row.referral_count,
            "candidate_count": row.candidate_count,
        }
        for row in rows
    ]


def get_market_intelligence(
    db: Session,
    user_id: Optional[int] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """Summarize and list recent competitor, commercial, and clinical observations."""
    competitor_present = and_(
        FactDCR.competitor_intelligence.is_not(None),
        func.trim(FactDCR.competitor_intelligence) != "",
    )
    concern_present = and_(
        FactDCR.commercial_concern.is_not(None),
        func.trim(FactDCR.commercial_concern) != "",
    )
    question_present = and_(
        FactDCR.doctor_question.is_not(None),
        func.trim(FactDCR.doctor_question) != "",
    )
    intelligence_present = or_(competitor_present, concern_present, question_present)

    counts_query = db.query(
        func.count(FactDCR.id).label("reported_entries"),
        func.coalesce(func.sum(case((competitor_present, 1), else_=0)), 0).label("competitor_mentions"),
        func.coalesce(func.sum(case((concern_present, 1), else_=0)), 0).label("commercial_concerns"),
        func.coalesce(func.sum(case((question_present, 1), else_=0)), 0).label("doctor_questions"),
    ).filter(intelligence_present)
    if user_id is not None:
        counts_query = counts_query.filter(FactDCR.user_id == user_id)
    counts = counts_query.one()

    observations_query = (
        db.query(
            FactDCR,
            User.full_name.label("marketer_name"),
            Doctor.name.label("doctor_name"),
            Territory.name.label("territory_name"),
        )
        .join(User, FactDCR.user_id == User.id)
        .join(Doctor, FactDCR.doctor_id == Doctor.id)
        .join(Territory, FactDCR.territory_id == Territory.id)
        .filter(intelligence_present)
    )
    if user_id is not None:
        observations_query = observations_query.filter(FactDCR.user_id == user_id)

    observations = [
        {
            "dcr_number": dcr.dcr_number,
            "report_date": dcr.report_date.isoformat(),
            "marketer_name": marketer_name,
            "doctor_name": doctor_name,
            "territory_name": territory_name,
            "competitor_intelligence": dcr.competitor_intelligence or "",
            "commercial_concern": dcr.commercial_concern or "",
            "doctor_question": dcr.doctor_question or "",
            "next_action": dcr.next_action or "",
        }
        for dcr, marketer_name, doctor_name, territory_name in (
            observations_query
            .order_by(FactDCR.report_date.desc(), FactDCR.id.desc())
            .limit(limit)
            .all()
        )
    ]
    return {
        "reported_entries": counts.reported_entries or 0,
        "competitor_mentions": counts.competitor_mentions or 0,
        "commercial_concerns": counts.commercial_concerns or 0,
        "doctor_questions": counts.doctor_questions or 0,
        "observations": observations,
    }
