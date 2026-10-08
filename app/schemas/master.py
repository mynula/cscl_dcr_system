from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


# Territory Schemas
class TerritoryBase(BaseModel):
    code: str
    name: str
    region: str
    description: Optional[str] = None


class TerritoryCreate(TerritoryBase):
    pass


class TerritoryUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    region: Optional[str] = None
    description: Optional[str] = None


class TerritoryResponse(TerritoryBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Hospital Schemas
class HospitalBase(BaseModel):
    code: str
    name: str
    type: Optional[str] = "General Hospital"
    address: Optional[str] = None
    phone: Optional[str] = None
    territory_id: int


class HospitalCreate(HospitalBase):
    pass


class HospitalUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    territory_id: Optional[int] = None


class HospitalResponse(HospitalBase):
    id: int
    territory_name: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Doctor Schemas
class DoctorBase(BaseModel):
    name: str
    qualification: Optional[str] = None
    specialty: str
    designation: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    chamber_address: Optional[str] = None
    territory_id: int
    hospital_id: Optional[int] = None


class DoctorCreate(DoctorBase):
    pass


class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    qualification: Optional[str] = None
    specialty: Optional[str] = None
    designation: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    chamber_address: Optional[str] = None
    territory_id: Optional[int] = None
    hospital_id: Optional[int] = None


class DoctorResponse(DoctorBase):
    id: int
    territory_name: Optional[str] = None
    hospital_name: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# VisitType Schemas
class VisitTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class VisitTypeCreate(VisitTypeBase):
    pass


class VisitTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class VisitTypeResponse(VisitTypeBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
