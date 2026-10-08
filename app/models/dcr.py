from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean, ForeignKey, false, text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class FactDCR(Base):
    __tablename__ = "fact_dcr"

    id = Column(Integer, primary_key=True, index=True)
    dcr_number = Column(String(50), unique=True, index=True, nullable=False)
    report_date = Column(Date, nullable=False, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    territory_id = Column(Integer, ForeignKey("territories.id", ondelete="CASCADE"), nullable=False, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True)
    visit_type_id = Column(Integer, ForeignKey("visit_types.id", ondelete="CASCADE"), nullable=False, index=True)

    # Call & Product Details
    products_discussed = Column(Text, nullable=True)  # Comma-separated or product details
    samples_given = Column(Text, nullable=True)
    call_notes = Column(Text, nullable=True)
    doctor_feedback = Column(Text, nullable=True)
    next_followup_date = Column(Date, nullable=True)
    status = Column(String(20), default="Submitted", nullable=False, index=True)  # Submitted, Approved, Flagged
    primary_indication = Column(String(150), nullable=True)
    visit_outcome = Column(String(100), nullable=True)
    estimated_patient_count = Column(Integer, default=0, server_default=text("0"), nullable=False)
    followup_completed = Column(Boolean, default=False, server_default=false(), nullable=False)
    followup_completed_at = Column(DateTime(timezone=True), nullable=True)

    # Concord Referral & Marketing Intelligence
    referral_opportunity = Column(Boolean, default=False, server_default=false(), nullable=False)
    expected_referral_type = Column(String(100), nullable=True)
    expected_referral_date = Column(Date, nullable=True)
    referral_status = Column(String(50), default="Identified", nullable=True)
    cme_planned = Column(Boolean, default=False, server_default=false(), nullable=False)
    cme_topic = Column(String(150), nullable=True)
    doctor_question = Column(Text, nullable=True)
    commercial_concern = Column(Text, nullable=True)
    competitor_intelligence = Column(Text, nullable=True)
    next_action = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="dcrs")
    territory = relationship("Territory", back_populates="dcrs")
    hospital = relationship("Hospital", back_populates="dcrs")
    doctor = relationship("Doctor", back_populates="dcrs")
    visit_type = relationship("VisitType", back_populates="dcrs")

    def __repr__(self):
        return f"<FactDCR(dcr_number='{self.dcr_number}', date='{self.report_date}', doctor_id={self.doctor_id})>"
