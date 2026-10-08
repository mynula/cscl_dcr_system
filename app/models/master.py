from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Territory(Base):
    __tablename__ = "territories"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    region = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    hospitals = relationship("Hospital", back_populates="territory", cascade="all, delete-orphan")
    doctors = relationship("Doctor", back_populates="territory", cascade="all, delete-orphan")
    users = relationship("User", back_populates="territory")
    dcrs = relationship("FactDCR", back_populates="territory")

    def __repr__(self):
        return f"<Territory(code='{self.code}', name='{self.name}')>"


class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=False, index=True)
    type = Column(String(50), default="General Hospital")  # Medical College, Diagnostic Center, Private Clinic
    address = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    territory_id = Column(Integer, ForeignKey("territories.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    territory = relationship("Territory", back_populates="hospitals")
    doctors = relationship("Doctor", back_populates="hospital")
    dcrs = relationship("FactDCR", back_populates="hospital")

    def __repr__(self):
        return f"<Hospital(name='{self.name}', territory_id={self.territory_id})>"


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    qualification = Column(String(100), nullable=True)
    specialty = Column(String(100), nullable=False, index=True)
    designation = Column(String(100), nullable=True)
    phone = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    chamber_address = Column(String(255), nullable=True)
    territory_id = Column(Integer, ForeignKey("territories.id", ondelete="CASCADE"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    territory = relationship("Territory", back_populates="doctors")
    hospital = relationship("Hospital", back_populates="doctors")
    dcrs = relationship("FactDCR", back_populates="doctor")

    def __repr__(self):
        return f"<Doctor(name='{self.name}', specialty='{self.specialty}')>"


class VisitType(Base):
    __tablename__ = "visit_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    dcrs = relationship("FactDCR", back_populates="visit_type")

    def __repr__(self):
        return f"<VisitType(name='{self.name}')>"
