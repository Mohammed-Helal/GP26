from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

# --- 1. Schemas للمستشعرات (Telemetry) ---
class SensorDataBase(BaseModel):
    temp: float
    vibration: float
    current: float

class SensorDataCreate(SensorDataBase):
    session_id: Optional[int] = None # بيتبعت من الـ ESP أو بيتححدد في السيرفر

class SensorDataResponse(SensorDataBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

# --- 2. Schemas لفحص المنتجات (Inspections) ---
class InspectionBase(BaseModel):
    status: str
    defect_category: Optional[str] = None
    confidence: float
    image_path: str

class InspectionCreate(InspectionBase):
    session_id: Optional[int] = None

class InspectionResponse(InspectionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# --- 3. Schemas للعمليات (Sessions) ---
class SystemSessionBase(BaseModel):
    operator_id: int

class SystemSessionCreate(SystemSessionBase):
    pass

class SystemSessionResponse(SystemSessionBase):
    id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    # ده بيخلينا نسحب كل الفحوصات اللي تمت في الجلسة دي بمرة واحدة
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