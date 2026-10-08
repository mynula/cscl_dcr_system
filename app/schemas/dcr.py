from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


VisitOutcome = Literal[
    "Strong Referral Potential",
    "Positive / Interested",
    "Referral Expected",
    "CME Interest",
    "Appointment/Meeting Requested",
    "Follow-up Required",
]


class DcrBase(BaseModel):
    report_date: date
    territory_id: int
    hospital_id: Optional[int] = None
    doctor_id: int
    visit_type_id: int
    products_discussed: Optional[str] = None
    samples_given: Optional[str] = None
    call_notes: Optional[str] = None
    doctor_feedback: Optional[str] = None
    next_followup_date: Optional[date] = None
    followup_completed: Optional[bool] = None
    primary_indication: Optional[str] = Field(default=None, max_length=150)
    visit_outcome: Optional[VisitOutcome] = None
    estimated_patient_count: int = Field(default=0, ge=0)
    referral_opportunity: bool = False
    expected_referral_type: Optional[str] = Field(default=None, max_length=100)
    expected_referral_date: Optional[date] = None
    referral_status: Optional[str] = Field(default=None, max_length=50)
    cme_planned: bool = False
    cme_topic: Optional[str] = Field(default=None, max_length=150)
    doctor_question: Optional[str] = None
    commercial_concern: Optional[str] = None
    competitor_intelligence: Optional[str] = None
    next_action: Optional[str] = None


class DcrCreate(DcrBase):
    user_id: Optional[int] = None  # Filled from authenticated session if not provided


class DcrUpdate(BaseModel):
    report_date: Optional[date] = None
    territory_id: Optional[int] = None
    hospital_id: Optional[int] = None
    doctor_id: Optional[int] = None
    visit_type_id: Optional[int] = None
    products_discussed: Optional[str] = None
    samples_given: Optional[str] = None
    call_notes: Optional[str] = None
    doctor_feedback: Optional[str] = None
    next_followup_date: Optional[date] = None
    followup_completed: Optional[bool] = None
    primary_indication: Optional[str] = Field(default=None, max_length=150)
    visit_outcome: Optional[VisitOutcome] = None
    estimated_patient_count: Optional[int] = Field(default=None, ge=0)
    referral_opportunity: Optional[bool] = None
    expected_referral_type: Optional[str] = Field(default=None, max_length=100)
    expected_referral_date: Optional[date] = None
    referral_status: Optional[str] = Field(default=None, max_length=50)
    cme_planned: Optional[bool] = None
    cme_topic: Optional[str] = Field(default=None, max_length=150)
    doctor_question: Optional[str] = None
    commercial_concern: Optional[str] = None
    competitor_intelligence: Optional[str] = None
    next_action: Optional[str] = None
    status: Optional[str] = None


class DcrResponse(DcrBase):
    id: int
    dcr_number: str
    user_id: int
    status: str
    followup_completed: bool = False
    created_at: Optional[datetime] = None

    # Enriched fields for presentation
    marketer_name: Optional[str] = None
    territory_name: Optional[str] = None
    hospital_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_specialty: Optional[str] = None
    visit_type_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
