from datetime import date, datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.master import Territory, Hospital, Doctor, VisitType
from app.models.dcr import FactDCR
from app.schemas.dcr import DcrCreate, DcrResponse
from app.services.auth_service import get_current_user
from app.services.dcr_service import create_dcr, get_dcrs, format_dcr_for_display

router = APIRouter(prefix="/dcr", tags=["Daily Call Report"])
templates = Jinja2Templates(directory="app/templates")


# --- DCR Form Page ---
@router.get("/form", response_class=HTMLResponse)
async def dcr_form_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Render the DCR submission form with pre-populated territory & visit type data."""
    # Pre-select territory if user is assigned to one
    user_territory_id = current_user.territory_id
    
    territories = db.query(Territory).order_by(Territory.name).all()
    visit_types = db.query(VisitType).filter(VisitType.is_active == True).order_by(VisitType.name).all()

    # Pre-fetch hospitals and doctors if user has an assigned territory
    hospitals = []
    doctors = []
    if user_territory_id:
        hospitals = db.query(Hospital).filter(Hospital.territory_id == user_territory_id).order_by(Hospital.name).all()
        doctors = db.query(Doctor).filter(Doctor.territory_id == user_territory_id).order_by(Doctor.name).all()

    today_str = date.today().isoformat()

    return templates.TemplateResponse(
        request=request,
        name="dcr/form.html",
        context={
            "user": current_user,
            "territories": territories,
            "visit_types": visit_types,
            "hospitals": hospitals,
            "doctors": doctors,
            "user_territory_id": user_territory_id,
            "today_date": today_str
        }
    )


# --- Cascading Dropdown: Hospitals by Territory ---
@router.get("/cascading/hospitals", response_class=HTMLResponse)
async def get_cascading_hospitals(
    request: Request,
    territory_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return HTML options for hospitals in the selected territory."""
    if not territory_id:
        return "<option value=''>-- Select Hospital (Optional) --</option>"
    
    hospitals = db.query(Hospital).filter(Hospital.territory_id == territory_id).order_by(Hospital.name).all()
    
    options = ["<option value=''>-- Select Hospital (Optional) --</option>"]
    for h in hospitals:
        options.append(f"<option value='{h.id}'>{h.name} ({h.type})</option>")
    
    return HTMLResponse(content="\n".join(options))


# --- Cascading Dropdown: Doctors by Territory and optional Hospital ---
@router.get("/cascading/doctors", response_class=HTMLResponse)
async def get_cascading_doctors(
    request: Request,
    territory_id: Optional[int] = None,
    hospital_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return HTML options for doctors filtered by territory and optional hospital."""
    if not territory_id:
        return "<option value=''>-- First Select a Territory --</option>"
    
    query = db.query(Doctor).filter(Doctor.territory_id == territory_id)
    if hospital_id and hospital_id > 0:
        query = query.filter(Doctor.hospital_id == hospital_id)
        
    doctors = query.order_by(Doctor.name).all()
    
    if not doctors:
        return "<option value=''>No doctors found in this selection</option>"

    options = ["<option value=''>-- Select Doctor --</option>"]
    for d in doctors:
        spec_text = f" - {d.specialty}" if d.specialty else ""
        options.append(f"<option value='{d.id}'>{d.name}{spec_text}</option>")
    
    return HTMLResponse(content="\n".join(options))


# --- DCR Submission Endpoint (HTMX & JSON) ---
@router.post("/", response_model=DcrResponse)
@router.post("", response_model=DcrResponse)
async def submit_dcr(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Form fields
    report_date: Optional[str] = Form(None),
    territory_id: Optional[int] = Form(None),
    hospital_id: Optional[int] = Form(None),
    doctor_id: Optional[int] = Form(None),
    visit_type_id: Optional[int] = Form(None),
    products_discussed: Optional[str] = Form(None),
    samples_given: Optional[str] = Form(None),
    call_notes: Optional[str] = Form(None),
    doctor_feedback: Optional[str] = Form(None),
    next_followup_date: Optional[str] = Form(None),
    primary_indication: Optional[str] = Form(None),
    visit_outcome: Optional[str] = Form(None),
    estimated_patient_count: int = Form(0, ge=0),
    referral_opportunity: bool = Form(False),
    expected_referral_type: Optional[str] = Form(None),
    expected_referral_date: Optional[str] = Form(None),
    referral_status: Optional[str] = Form(None),
    cme_planned: bool = Form(False),
    cme_topic: Optional[str] = Form(None),
    doctor_question: Optional[str] = Form(None),
    commercial_concern: Optional[str] = Form(None),
    competitor_intelligence: Optional[str] = Form(None),
    next_action: Optional[str] = Form(None),
    # Optional JSON payload
    payload: Optional[DcrCreate] = None
):
    """
    Handle DCR submission asynchronously via HTMX or JSON REST API.
    Returns inline HTMX feedback with generated DCR number or JSON response.
    """
    is_htmx = bool(request.headers.get("hx-request"))

    try:
        if payload is None and request.headers.get("content-type", "").startswith("application/json"):
            json_payload = await request.json()
            if isinstance(json_payload, dict) and "payload" in json_payload:
                json_payload = json_payload["payload"]
            payload = DcrCreate.model_validate(json_payload)

        # Extract fields from form or json payload
        if payload is not None:
            parsed_date = payload.report_date
            t_id = payload.territory_id
            h_id = payload.hospital_id
            d_id = payload.doctor_id
            v_id = payload.visit_type_id
            p_disc = payload.products_discussed
            s_given = payload.samples_given
            c_notes = payload.call_notes
            d_feed = payload.doctor_feedback
            nf_date = payload.next_followup_date
            indication = payload.primary_indication
            outcome = payload.visit_outcome
            patient_count = payload.estimated_patient_count
            referral_opp = payload.referral_opportunity
            referral_type = payload.expected_referral_type
            referral_date = payload.expected_referral_date
            referral_state = payload.referral_status
            planned_cme = payload.cme_planned
            topic = payload.cme_topic
            doctor_q = payload.doctor_question
            commercial_issue = payload.commercial_concern
            competitor_info = payload.competitor_intelligence
            action = payload.next_action
        else:
            if not report_date or not territory_id or not doctor_id or not visit_type_id:
                raise ValueError("Missing required fields: Date, Territory, Doctor, and Visit Type are mandatory.")
            
            parsed_date = datetime.strptime(report_date, "%Y-%m-%d").date()
            t_id = territory_id
            h_id = hospital_id if hospital_id and hospital_id > 0 else None
            d_id = doctor_id
            v_id = visit_type_id
            p_disc = products_discussed.strip() if products_discussed else None
            s_given = samples_given.strip() if samples_given else None
            c_notes = call_notes.strip() if call_notes else None
            d_feed = doctor_feedback.strip() if doctor_feedback else None
            nf_date = datetime.strptime(next_followup_date, "%Y-%m-%d").date() if next_followup_date else None
            indication = primary_indication.strip() if primary_indication else None
            outcome = visit_outcome
            patient_count = estimated_patient_count
            referral_opp = referral_opportunity
            referral_type = expected_referral_type.strip() if expected_referral_type else None
            referral_date = datetime.strptime(expected_referral_date, "%Y-%m-%d").date() if expected_referral_date else None
            referral_state = referral_status.strip() if referral_status else None
            planned_cme = cme_planned
            topic = cme_topic.strip() if cme_topic else None
            doctor_q = doctor_question.strip() if doctor_question else None
            commercial_issue = commercial_concern.strip() if commercial_concern else None
            competitor_info = competitor_intelligence.strip() if competitor_intelligence else None
            action = next_action.strip() if next_action else None

        dcr_create = DcrCreate(
            report_date=parsed_date,
            territory_id=t_id,
            hospital_id=h_id,
            doctor_id=d_id,
            visit_type_id=v_id,
            products_discussed=p_disc,
            samples_given=s_given,
            call_notes=c_notes,
            doctor_feedback=d_feed,
            next_followup_date=nf_date,
            primary_indication=indication,
            visit_outcome=outcome,
            estimated_patient_count=patient_count,
            referral_opportunity=referral_opp,
            expected_referral_type=referral_type,
            expected_referral_date=referral_date,
            referral_status=referral_state,
            cme_planned=planned_cme,
            cme_topic=topic,
            doctor_question=doctor_q,
            commercial_concern=commercial_issue,
            competitor_intelligence=competitor_info,
            next_action=action,
            user_id=current_user.id
        )

        dcr_record = create_dcr(db, dcr_create, current_user.id)

        if is_htmx:
            formatted = format_dcr_for_display(dcr_record)
            return templates.TemplateResponse(
                request=request,
                name="dcr/partials/submission_success.html",
                context={
                    "dcr": formatted,
                    "success": True,
                    "message": f"DCR Record #{dcr_record.dcr_number} submitted successfully!"
                }
            )

        # Return JSON
        res_data = format_dcr_for_display(dcr_record)
        return JSONResponse(content=res_data, status_code=status.HTTP_201_CREATED)

    except Exception as e:
        if is_htmx:
            return templates.TemplateResponse(
                request=request,
                name="dcr/partials/submission_error.html",
                context={
                    "error_message": str(e)
                },
                status_code=status.HTTP_400_BAD_REQUEST
            )
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{dcr_id}/follow-up/complete")
async def complete_follow_up(
    request: Request,
    dcr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark an open follow-up complete, enforcing marketer ownership."""
    dcr = db.query(FactDCR).filter(FactDCR.id == dcr_id).first()
    if not dcr:
        raise HTTPException(status_code=404, detail="DCR record not found.")
    if current_user.role == "marketer" and dcr.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only complete your own follow-ups.")
    if dcr.next_followup_date is None:
        raise HTTPException(status_code=409, detail="This DCR has no scheduled follow-up.")

    if not dcr.followup_completed:
        dcr.followup_completed = True
        dcr.followup_completed_at = datetime.now(timezone.utc)
        db.commit()

    if request.headers.get("hx-request"):
        return Response(content="", status_code=status.HTTP_200_OK)
    return JSONResponse(
        content={"message": "Follow-up marked complete.", "dcr_id": dcr.id},
        status_code=status.HTTP_200_OK,
    )


# --- DCR Listing Page ---
@router.get("/list", response_class=HTMLResponse)
async def list_dcrs_page(
    request: Request,
    territory_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Display history of call reports with filtering."""
    s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    raw_dcrs = get_dcrs(
        db=db,
        current_user=current_user,
        territory_id=territory_id,
        doctor_id=doctor_id,
        start_date=s_date,
        end_date=e_date
    )

    formatted_dcrs = [format_dcr_for_display(d) for d in raw_dcrs]
    territories = db.query(Territory).order_by(Territory.name).all()

    return templates.TemplateResponse(
        request=request,
        name="dcr/list.html",
        context={
            "user": current_user,
            "dcrs": formatted_dcrs,
            "territories": territories,
            "selected_territory_id": territory_id,
            "start_date": start_date or "",
            "end_date": end_date or ""
        }
    )
