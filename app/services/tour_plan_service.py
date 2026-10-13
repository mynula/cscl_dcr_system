import json
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.dcr import FactDCR
from app.models.master import Doctor, Territory, VisitType
from app.models.tour_plan import (
    TourPlan,
    TourPlanAudit,
    TourPlanSetting,
    TourPlanTemplate,
    TourPlanVisit,
)
from app.models.user import User


PLAN_STATUSES = {"Draft", "Submitted", "Approved", "Returned", "Published"}
VISIT_STATUSES = {"Planned", "Completed", "Not Visited", "Rescheduled"}
MAX_PLAN_VISITS = 250


class TourPlanValidationError(ValueError):
    pass


def parse_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("A boolean is not a valid integer.")
    parsed = int(value)
    if not isinstance(value, str) and value != parsed:
        raise ValueError("A fractional value is not a valid integer.")
    return parsed


def get_tour_plan_setting(db: Session) -> TourPlanSetting:
    setting = db.query(TourPlanSetting).filter(TourPlanSetting.id == 1).first()
    if setting is None:
        setting = TourPlanSetting(id=1, marketer_self_service=False)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def log_plan_action(
    db: Session,
    plan: TourPlan,
    actor: User,
    action: str,
    details: str | None = None,
) -> None:
    db.add(
        TourPlanAudit(
            plan_id=plan.id,
            actor_id=actor.id,
            action=action,
            details=details,
        )
    )


def validate_plan_period(period_type: str, start: date, end: date) -> None:
    if period_type not in {"weekly", "monthly"}:
        raise TourPlanValidationError("Plan period must be weekly or monthly.")
    if end < start:
        raise TourPlanValidationError("Plan end date must be on or after its start date.")
    if period_type == "weekly" and (end - start).days >= 7:
        raise TourPlanValidationError("A weekly plan may span no more than 7 calendar days.")
    if period_type == "monthly" and (start.year, start.month) != (end.year, end.month):
        raise TourPlanValidationError("A monthly plan must start and end in the same calendar month.")
    if period_type == "monthly" and (start.day != 1 or end.day != monthrange(end.year, end.month)[1]):
        raise TourPlanValidationError("A monthly plan must cover the complete calendar month.")


def validate_plan_visits(
    db: Session,
    territory_id: int,
    period_start: date,
    period_end: date,
    visits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not visits or len(visits) > MAX_PLAN_VISITS:
        raise TourPlanValidationError(
            f"A plan must contain between 1 and {MAX_PLAN_VISITS} planned visits."
        )

    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[date, int]] = set()
    seen_sequences: set[tuple[date, int]] = set()
    for index, raw_visit in enumerate(visits, start=1):
        if not isinstance(raw_visit, dict):
            raise TourPlanValidationError(f"Visit row {index}: expected a visit object.")
        try:
            visit_date = date.fromisoformat(str(raw_visit.get("planned_date", "")))
            doctor_id = parse_integer(raw_visit.get("doctor_id"))
            visit_type_id = parse_integer(raw_visit.get("visit_type_id"))
            raw_sequence = raw_visit.get("sequence")
            sequence = parse_integer(index if raw_sequence in (None, "") else raw_sequence)
        except (TypeError, ValueError) as exc:
            raise TourPlanValidationError(
                f"Visit row {index}: date, doctor, visit type, and sequence are required."
            ) from exc
        if visit_date < period_start or visit_date > period_end:
            raise TourPlanValidationError(f"Visit row {index}: date is outside the plan period.")
        if sequence < 1:
            raise TourPlanValidationError(f"Visit row {index}: sequence must be 1 or greater.")
        if (visit_date, doctor_id) in seen:
            raise TourPlanValidationError(
                f"Visit row {index}: this doctor is already planned for that date."
            )
        if (visit_date, sequence) in seen_sequences:
            raise TourPlanValidationError(
                f"Visit row {index}: sequence numbers must be unique for each date."
            )
        seen.add((visit_date, doctor_id))
        seen_sequences.add((visit_date, sequence))

        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise TourPlanValidationError(f"Visit row {index}: selected doctor does not exist.")
        if not doctor.is_active:
            raise TourPlanValidationError(f"Visit row {index}: selected doctor is inactive.")
        if doctor.territory_id != territory_id:
            raise TourPlanValidationError(
                f"Visit row {index}: selected doctor is not assigned to this plan territory."
            )
        visit_type = db.query(VisitType).filter(
            VisitType.id == visit_type_id,
            VisitType.is_active.is_(True),
        ).first()
        if not visit_type:
            raise TourPlanValidationError(
                f"Visit row {index}: selected call type is unavailable."
            )

        cleaned.append(
            {
                "planned_date": visit_date,
                "sequence": sequence,
                "doctor_id": doctor_id,
                "visit_type_id": visit_type_id,
                "planned_products": str(raw_visit.get("planned_products") or "").strip() or None,
                "planned_indication": str(raw_visit.get("planned_indication") or "").strip() or None,
                "notes": str(raw_visit.get("notes") or "").strip() or None,
            }
        )
    return cleaned


def create_plan(
    db: Session,
    actor: User,
    title: str,
    period_type: str,
    period_start: date,
    period_end: date,
    marketer_id: int,
    territory_id: int,
    visits: list[dict[str, Any]],
    action: str = "created",
) -> TourPlan:
    validate_plan_period(period_type, period_start, period_end)
    marketer = db.query(User).filter(
        User.id == marketer_id,
        User.role == "marketer",
        User.is_active.is_(True),
    ).first()
    if not marketer:
        raise TourPlanValidationError("Select an active marketer account.")
    territory = db.query(Territory).filter(Territory.id == territory_id).first()
    if not territory or not territory.is_active:
        raise TourPlanValidationError("Select an active territory.")
    if marketer.territory_id and marketer.territory_id != territory_id:
        raise TourPlanValidationError("Selected territory does not match the marketer's assigned territory.")
    cleaned_visits = validate_plan_visits(
        db, territory_id, period_start, period_end, visits
    )

    plan = TourPlan(
        title=title.strip() or f"{period_type.title()} tour plan",
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        marketer_id=marketer_id,
        territory_id=territory_id,
        created_by_id=actor.id,
        status="Draft",
    )
    plan.visits = [TourPlanVisit(**visit) for visit in cleaned_visits]
    db.add(plan)
    db.flush()
    log_plan_action(db, plan, actor, action, f"{len(cleaned_visits)} planned visits")
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(
    db: Session,
    plan: TourPlan,
    actor: User,
    title: str,
    period_type: str,
    period_start: date,
    period_end: date,
    marketer_id: int,
    territory_id: int,
    visits: list[dict[str, Any]],
) -> TourPlan:
    if plan.status == "Published" and any(visit.actual_dcr_id for visit in plan.visits):
        raise TourPlanValidationError(
            "A published plan with linked DCRs cannot be edited; create a copy for changes."
        )
    validate_plan_period(period_type, period_start, period_end)
    marketer = db.query(User).filter(
        User.id == marketer_id,
        User.role == "marketer",
        User.is_active.is_(True),
    ).first()
    if not marketer:
        raise TourPlanValidationError("Select an active marketer account.")
    if marketer.territory_id and marketer.territory_id != territory_id:
        raise TourPlanValidationError("Selected territory does not match the marketer's assigned territory.")
    territory = db.query(Territory).filter(Territory.id == territory_id).first()
    if not territory or not territory.is_active:
        raise TourPlanValidationError("Select an active territory.")
    cleaned_visits = validate_plan_visits(
        db, territory_id, period_start, period_end, visits
    )

    plan.title = title.strip() or f"{period_type.title()} tour plan"
    plan.period_type = period_type
    plan.period_start = period_start
    plan.period_end = period_end
    plan.marketer_id = marketer_id
    plan.territory_id = territory_id
    plan.status = "Draft"
    plan.approved_by_id = None
    plan.approved_at = None
    plan.published_by_id = None
    plan.published_at = None
    plan.visits.clear()
    plan.visits.extend(TourPlanVisit(**visit) for visit in cleaned_visits)
    log_plan_action(db, plan, actor, "edited", f"{len(cleaned_visits)} planned visits")
    db.commit()
    db.refresh(plan)
    return plan


def get_plan_for_user(db: Session, plan_id: int, user: User) -> TourPlan | None:
    query = db.query(TourPlan).options(
        selectinload(TourPlan.visits).joinedload(TourPlanVisit.doctor).joinedload(Doctor.hospital),
        selectinload(TourPlan.visits).joinedload(TourPlanVisit.visit_type),
        selectinload(TourPlan.visits).joinedload(TourPlanVisit.actual_dcr),
    ).filter(TourPlan.id == plan_id)
    if user.role == "marketer":
        query = query.filter(TourPlan.marketer_id == user.id)
    return query.first()


def visible_plans_query(db: Session, user: User):
    query = db.query(TourPlan).options(
        joinedload(TourPlan.marketer),
        joinedload(TourPlan.territory),
        selectinload(TourPlan.visits).joinedload(TourPlanVisit.doctor),
    )
    if user.role == "marketer":
        query = query.filter(TourPlan.marketer_id == user.id)
    return query


def plan_visit_actuals(visit: TourPlanVisit) -> dict[str, Any]:
    dcr = visit.actual_dcr
    if dcr is None:
        status = visit.status
        if status == "Planned" and visit.planned_date < date.today():
            status = "Pending DCR"
        return {"status": status, "dcr_number": None, "mismatches": []}

    mismatches = []
    if dcr.report_date != visit.planned_date:
        mismatches.append("date")
    if dcr.doctor_id != visit.doctor_id:
        mismatches.append("doctor")
    if dcr.visit_type_id != visit.visit_type_id:
        mismatches.append("call type")
    if dcr.territory_id != visit.plan.territory_id:
        mismatches.append("territory")
    planned_products = (visit.planned_products or "").strip().casefold()
    actual_products = (dcr.products_discussed or "").strip().casefold()
    if planned_products and planned_products != actual_products:
        mismatches.append("product/therapy")
    if (
        visit.planned_indication
        and visit.planned_indication.strip().casefold()
        != (dcr.primary_indication or "").strip().casefold()
    ):
        mismatches.append("indication")
    return {
        "status": "Completed",
        "dcr_number": dcr.dcr_number,
        "mismatches": mismatches,
    }


def get_plan_report_rows(
    db: Session,
    user: User,
    marketer_id: int | None = None,
    territory_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    query = db.query(TourPlanVisit).join(TourPlan).options(
        joinedload(TourPlanVisit.plan).joinedload(TourPlan.marketer),
        joinedload(TourPlanVisit.plan).joinedload(TourPlan.territory),
        joinedload(TourPlanVisit.doctor).joinedload(Doctor.hospital),
        joinedload(TourPlanVisit.visit_type),
        joinedload(TourPlanVisit.actual_dcr),
    ).filter(TourPlan.status == "Published")
    if user.role == "marketer":
        query = query.filter(TourPlan.marketer_id == user.id)
    elif marketer_id:
        query = query.filter(TourPlan.marketer_id == marketer_id)
    if territory_id:
        query = query.filter(TourPlan.territory_id == territory_id)
    if start_date:
        query = query.filter(TourPlanVisit.planned_date >= start_date)
    if end_date:
        query = query.filter(TourPlanVisit.planned_date <= end_date)
    visits = query.order_by(TourPlanVisit.planned_date, TourPlanVisit.sequence).all()

    rows = []
    for visit in visits:
        actual = plan_visit_actuals(visit)
        rows.append(
            {
                "plan_id": visit.plan_id,
                "plan_title": visit.plan.title,
                "plan_status": visit.plan.status,
                "planned_date": visit.planned_date,
                "planned_doctor": visit.doctor.name,
                "planned_specialty": visit.doctor.specialty,
                "planned_hospital": visit.doctor.hospital.name if visit.doctor.hospital else "",
                "planned_visit_type": visit.visit_type.name,
                "planned_products": visit.planned_products or "",
                "planned_indication": visit.planned_indication or "",
                "marketer_name": visit.plan.marketer.full_name,
                "territory_name": visit.plan.territory.name,
                "visit": visit,
                **actual,
            }
        )
    return rows


def audit_trail(db: Session, plan_id: int) -> list[TourPlanAudit]:
    return (
        db.query(TourPlanAudit)
        .options(joinedload(TourPlanAudit.actor))
        .filter(TourPlanAudit.plan_id == plan_id)
        .order_by(TourPlanAudit.occurred_at.desc(), TourPlanAudit.id.desc())
        .all()
    )


def save_plan_template(
    db: Session,
    plan: TourPlan,
    actor: User,
    name: str,
) -> TourPlanTemplate:
    template_visits = [
        {
            "day_offset": (visit.planned_date - plan.period_start).days,
            "sequence": visit.sequence,
            "doctor_id": visit.doctor_id,
            "visit_type_id": visit.visit_type_id,
            "planned_products": visit.planned_products,
            "planned_indication": visit.planned_indication,
            "notes": visit.notes,
        }
        for visit in plan.visits
    ]
    template = TourPlanTemplate(
        name=name.strip(),
        period_type=plan.period_type,
        territory_id=plan.territory_id,
        visits_json=json.dumps(template_visits),
        created_by_id=actor.id,
    )
    db.add(template)
    log_plan_action(db, plan, actor, "saved_as_template", template.name)
    db.commit()
    db.refresh(template)
    return template
