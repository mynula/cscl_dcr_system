from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.master import Territory, Hospital, Doctor, VisitType
from app.schemas.master import (
    TerritoryCreate, TerritoryResponse,
    HospitalCreate, HospitalResponse,
    DoctorCreate, DoctorResponse,
    VisitTypeCreate, VisitTypeResponse
)
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import (
    get_current_admin_only_user,
    get_current_admin_user,
    get_password_hash,
)

router = APIRouter(prefix="/admin", tags=["Master Admin CRUD"])
templates = Jinja2Templates(directory="app/templates")


# --- Admin Dashboard View ---
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    territories = db.query(Territory).order_by(Territory.name).all()
    hospitals = db.query(Hospital).order_by(Hospital.name).all()
    doctors = db.query(Doctor).order_by(Doctor.name).all()
    visit_types = db.query(VisitType).order_by(VisitType.name).all()
    users = (
        db.query(User).order_by(User.full_name).all()
        if admin_user.role == "admin"
        else []
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/index.html",
        context={
            "user": admin_user,
            "territories": territories,
            "hospitals": hospitals,
            "doctors": doctors,
            "visit_types": visit_types,
            "users": users,
            "active_tab": "territories"
        }
    )


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_only_user)
):
    """List user accounts for administrator account management."""
    return db.query(User).order_by(User.full_name).all()


@router.post("/users")
async def create_user(
    request: Request,
    username: str = Form(..., max_length=50),
    email: EmailStr = Form(..., max_length=100),
    full_name: str = Form(..., max_length=100),
    password: str = Form(..., min_length=8),
    role: str = Form(..., max_length=20),
    employee_id: Optional[str] = Form(None, max_length=30),
    phone: Optional[str] = Form(None, max_length=20),
    territory_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_only_user)
):
    """Create a user account; only administrators may assign roles."""
    username = username.strip()
    email = str(email).strip().lower()
    full_name = full_name.strip()
    role = role.strip().lower()
    employee_id = employee_id.strip() if employee_id else None
    phone = phone.strip() if phone else None

    if not username or not email or not full_name:
        raise HTTPException(status_code=400, detail="Username, email, and full name are required.")
    if role not in {"admin", "manager", "marketer"}:
        raise HTTPException(status_code=400, detail="Role must be admin, manager, or marketer.")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail=f"Username '{username}' already exists.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail=f"Email '{email}' already exists.")
    if employee_id and db.query(User).filter(User.employee_id == employee_id).first():
        raise HTTPException(status_code=400, detail=f"Employee ID '{employee_id}' already exists.")
    if territory_id and not db.query(Territory).filter(Territory.id == territory_id).first():
        raise HTTPException(status_code=400, detail="Selected territory does not exist.")

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=role,
        employee_id=employee_id,
        phone=phone,
        territory_id=territory_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if request.headers.get("hx-request"):
        users = db.query(User).order_by(User.full_name).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/user_table.html",
            context={"users": users}
        )
    return UserResponse.model_validate(user)


# ==============================================================================
# TERRITORY CRUD
# ==============================================================================
@router.get("/territories", response_model=List[TerritoryResponse])
async def list_territories(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    territories = db.query(Territory).order_by(Territory.name).all()
    if "text/html" in request.headers.get("accept", "") and not request.headers.get("hx-request"):
        return RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
    return territories


@router.post("/territories")
async def create_territory(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    region: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    existing = db.query(Territory).filter(Territory.code == code.strip().upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Territory code '{code}' already exists.")

    territory = Territory(
        code=code.strip().upper(),
        name=name.strip(),
        region=region.strip(),
        description=description.strip() if description else None
    )
    db.add(territory)
    db.commit()
    db.refresh(territory)

    if request.headers.get("hx-request"):
        territories = db.query(Territory).order_by(Territory.name).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/territory_table.html",
            context={"territories": territories}
        )
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/territories/{territory_id}")
async def delete_territory(
    request: Request,
    territory_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    territory = db.query(Territory).filter(Territory.id == territory_id).first()
    if not territory:
        raise HTTPException(status_code=404, detail="Territory not found")
    db.delete(territory)
    db.commit()
    return Response(content="", status_code=status.HTTP_200_OK)


# ==============================================================================
# HOSPITAL CRUD
# ==============================================================================
@router.get("/hospitals", response_model=List[HospitalResponse])
async def list_hospitals(
    territory_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    query = db.query(Hospital)
    if territory_id:
        query = query.filter(Hospital.territory_id == territory_id)
    return query.order_by(Hospital.name).all()


@router.post("/hospitals")
async def create_hospital(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    type: str = Form("General Hospital"),
    territory_id: int = Form(...),
    address: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    existing = db.query(Hospital).filter(Hospital.code == code.strip().upper()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Hospital code '{code}' already exists.")

    hospital = Hospital(
        code=code.strip().upper(),
        name=name.strip(),
        type=type.strip(),
        territory_id=territory_id,
        address=address.strip() if address else None,
        phone=phone.strip() if phone else None
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)

    if request.headers.get("hx-request"):
        hospitals = db.query(Hospital).order_by(Hospital.name).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/hospital_table.html",
            context={"hospitals": hospitals}
        )
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/hospitals/{hospital_id}")
async def delete_hospital(
    request: Request,
    hospital_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    db.delete(hospital)
    db.commit()
    return Response(content="", status_code=status.HTTP_200_OK)


# ==============================================================================
# DOCTOR CRUD
# ==============================================================================
@router.get("/doctors", response_model=List[DoctorResponse])
async def list_doctors(
    territory_id: Optional[int] = None,
    hospital_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    query = db.query(Doctor)
    if territory_id:
        query = query.filter(Doctor.territory_id == territory_id)
    if hospital_id:
        query = query.filter(Doctor.hospital_id == hospital_id)
    return query.order_by(Doctor.name).all()


@router.post("/doctors")
async def create_doctor(
    request: Request,
    name: str = Form(...),
    specialty: str = Form(...),
    territory_id: int = Form(...),
    qualification: Optional[str] = Form(None),
    designation: Optional[str] = Form(None),
    hospital_id: Optional[int] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    chamber_address: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    doctor = Doctor(
        name=name.strip(),
        specialty=specialty.strip(),
        territory_id=territory_id,
        qualification=qualification.strip() if qualification else None,
        designation=designation.strip() if designation else None,
        hospital_id=hospital_id if hospital_id and hospital_id > 0 else None,
        phone=phone.strip() if phone else None,
        email=email.strip() if email else None,
        chamber_address=chamber_address.strip() if chamber_address else None
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)

    if request.headers.get("hx-request"):
        doctors = db.query(Doctor).order_by(Doctor.name).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/doctor_table.html",
            context={"doctors": doctors}
        )
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/doctors/{doctor_id}")
async def delete_doctor(
    request: Request,
    doctor_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    db.delete(doctor)
    db.commit()
    return Response(content="", status_code=status.HTTP_200_OK)


# ==============================================================================
# VISIT TYPE CRUD
# ==============================================================================
@router.get("/visit-types", response_model=List[VisitTypeResponse])
async def list_visit_types(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    return db.query(VisitType).order_by(VisitType.name).all()


@router.post("/visit-types")
async def create_visit_type(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    existing = db.query(VisitType).filter(VisitType.name == name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Visit type '{name}' already exists.")

    visit_type = VisitType(
        name=name.strip(),
        description=description.strip() if description else None,
        is_active=True
    )
    db.add(visit_type)
    db.commit()
    db.refresh(visit_type)

    if request.headers.get("hx-request"):
        visit_types = db.query(VisitType).order_by(VisitType.name).all()
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/visit_type_table.html",
            context={"visit_types": visit_types}
        )
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/visit-types/{visit_type_id}")
async def delete_visit_type(
    request: Request,
    visit_type_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    visit_type = db.query(VisitType).filter(VisitType.id == visit_type_id).first()
    if not visit_type:
        raise HTTPException(status_code=404, detail="Visit Type not found")
    db.delete(visit_type)
    db.commit()
    return Response(content="", status_code=status.HTTP_200_OK)
