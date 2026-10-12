from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class TourPlan(Base):
    __tablename__ = "tour_plans"
    __table_args__ = (
        UniqueConstraint("id", "marketer_id", name="uq_tour_plan_id_marketer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(150), nullable=False)
    period_type = Column(String(20), nullable=False)
    period_start = Column(Date, nullable=False, index=True)
    period_end = Column(Date, nullable=False, index=True)
    marketer_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    territory_id = Column(Integer, ForeignKey("territories.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(20), default="Draft", nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    visits = relationship(
        "TourPlanVisit",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TourPlanVisit.planned_date, TourPlanVisit.sequence",
    )
    marketer = relationship("User", foreign_keys=[marketer_id])
    territory = relationship("Territory")
    audits = relationship("TourPlanAudit", cascade="all, delete-orphan")


class TourPlanVisit(Base):
    __tablename__ = "tour_plan_visits"
    __table_args__ = (
        UniqueConstraint("plan_id", "planned_date", "sequence", name="uq_plan_visit_sequence"),
        UniqueConstraint("plan_id", "planned_date", "doctor_id", name="uq_plan_visit_doctor_day"),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("tour_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    planned_date = Column(Date, nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=1)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False, index=True)
    visit_type_id = Column(Integer, ForeignKey("visit_types.id", ondelete="RESTRICT"), nullable=False)
    planned_products = Column(Text, nullable=True)
    planned_indication = Column(String(150), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(20), default="Planned", nullable=False)
    actual_dcr_id = Column(Integer, ForeignKey("fact_dcr.id", ondelete="SET NULL"), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plan = relationship("TourPlan", back_populates="visits")
    doctor = relationship("Doctor")
    visit_type = relationship("VisitType")
    actual_dcr = relationship("FactDCR", back_populates="tour_plan_visit")


class TourPlanAudit(Base):
    __tablename__ = "tour_plan_audits"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("tour_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(String(40), nullable=False)
    details = Column(Text, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    actor = relationship("User")


class TourPlanTemplate(Base):
    __tablename__ = "tour_plan_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    period_type = Column(String(20), nullable=False)
    territory_id = Column(Integer, ForeignKey("territories.id", ondelete="CASCADE"), nullable=False, index=True)
    visits_json = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    territory = relationship("Territory")


class TourPlanSetting(Base):
    __tablename__ = "tour_plan_settings"

    id = Column(Integer, primary_key=True)
    marketer_self_service = Column(Boolean, default=False, nullable=False)
    updated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TourPlanImport(Base):
    __tablename__ = "tour_plan_imports"

    id = Column(String(36), primary_key=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    metadata_json = Column(Text, nullable=False)
    rows_json = Column(Text, nullable=False)
    errors_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
