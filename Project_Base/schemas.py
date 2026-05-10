from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

# --- 1. Schemas for(Telemetry) ---
class SensorDataBase(BaseModel):
    temp: float
    vibration: float
    current: float

class SensorDataCreate(SensorDataBase):
    session_id: Optional[int] = None 

class SensorDataResponse(SensorDataBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

# --- 2. Schemas for check (Inspections) ---
class InspectionBase(BaseModel):
    status: str
    defect_category: Optional[str] = None
    confidence: float
    image_path: str
    is_confirmed: bool = False

class InspectionCreate(InspectionBase):
    session_id: Optional[int] = None

class InspectionResponse(InspectionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# --- 3. Schemas for(Sessions) ---
class SystemSessionBase(BaseModel):
    operator_id: int

class SystemSessionCreate(SystemSessionBase):
    pass

class SystemSessionResponse(SystemSessionBase):
    id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    inspections: List[InspectionResponse] = []

    class Config:
        from_attributes = True

# --- 4. Schemas للمستخدمين (Users) ---
class UserBase(BaseModel):
    username: str
    access_role: str # Admin, Operator, Viewer

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int

    class Config:
        from_attributes = True