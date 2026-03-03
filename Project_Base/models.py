# models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

# 1. Users Table (Access Control)
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    access_role = Column(String(20)) # Admin, Operator, Viewer

# 2. Sessions Table (Production Shifts)
class SystemSession(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(DateTime, default=datetime.now)
    end_time = Column(DateTime, nullable=True) 
    operator_id = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    inspections = relationship("Inspection", back_populates="session")
    telemetry_data = relationship("SensorData", back_populates="session")

# 3. Inspections Table (Vision Model Results)
class Inspection(Base):
    __tablename__ = "inspections"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id")) 
    status = Column(String(20)) # "Good" or "Defected"
    defect_category = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    image_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("SystemSession", back_populates="inspections")

# 4. Telemetry Table (ESP Sensor Data)
class SensorData(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    temp = Column(Float, nullable=True)
    vibration = Column(Float, nullable=True)
    current = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.now)

    session = relationship("SystemSession", back_populates="telemetry_data")