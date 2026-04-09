import json, os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import BaseModel

import models, schemas
from database import engine, get_db, SessionLocal

MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.hivemq.com")

# Global Variable
active_session_id = None
current_operator_id = None

# ==========================================
# MQTT
# ==========================================
def on_mqtt_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        db = SessionLocal()
        tele = models.SensorData(
            session_id=active_session_id,
            temp=data['temp'],
            vibration=data['vib'],
            current=data['curr']
        )
        db.add(tele)
        db.commit()
        db.close()
    except Exception as e:
        print(f"MQTT Error: {e}")

mqtt_c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
mqtt_c.on_message = on_mqtt_message
# ==========================================
# FastAPI
# ==========================================
app = FastAPI(title="Smart Factory Cloud API")

@app.on_event("startup")
def startup_event():
    print("\n🚀 Starting Cloud Services...")
    models.Base.metadata.create_all(bind=engine)
    print("✅ Database Tables Verified.")

    # Restore session if server restarted
    db = SessionLocal()
    open_session = db.query(models.SystemSession).filter(
        models.SystemSession.end_time == None
    ).first()
    if open_session:
        active_session_id = open_session.id
        current_operator_id = open_session.operator_id
        print(f"🔄 Restored Session {active_session_id}")
    db.close()

    try:
        mqtt_c.connect(MQTT_BROKER, 1883)
        mqtt_c.loop_start()
        print("✅ MQTT Broker Connected.")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

@app.on_event("shutdown")
def shutdown_event():
    mqtt_c.loop_stop()
    print("🛑 Cloud Service Shutdown.")

# ==========================================
# Endpoints
# ==========================================
@app.get("/")
def home():
    return {"status": "Online"}

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "Operator"

@app.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    global current_operator_id
    user = db.query(models.User).filter(
        models.User.username == request.username,
        models.User.password_hash == request.password
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    current_operator_id = user.id
    return {"user_id": user.id, "username": user.username, "role": user.access_role}

@app.post("/create-user")
def create_user(request: CreateUserRequest, db: Session = Depends(get_db)):
    new_user = models.User(
        username=request.username,
        password_hash=request.password,
        access_role=request.role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# ==========================================
# User Edit Endpoints
# ==========================================

class EditPasswordRequest(BaseModel):
    new_password: str

class EditUsernameRequest(BaseModel):
    new_username: str

class EditRoleRequest(BaseModel):
    new_role: str

@app.put("/edit-password/{user_id}")
def edit_password(user_id: int, request: EditPasswordRequest, db: Session = Depends(get_db)):
    # Check if user is logged in
    if current_operator_id is None:
        raise HTTPException(status_code=401, detail="Please login first")

    # Check if user exists
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if user has permission to edit this account
    if current_operator_id != user_id and current_operator_id is not None:
        raise HTTPException(status_code=403, detail="You can only edit your own account")

    # Update password
    user.password_hash = request.new_password
    db.commit()

    print(f"🔑 Password updated for user {user_id}")
    return {"message": "Password updated successfully"}

@app.put("/edit-username/{user_id}")
def edit_username(user_id: int, request: EditUsernameRequest, db: Session = Depends(get_db)):
    # Check if user is logged in
    if current_operator_id is None:
        raise HTTPException(status_code=401, detail="Please login first")

    # Check if user exists
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if user has permission to edit this account
    if current_operator_id != user_id and current_operator_id is not None:
        raise HTTPException(status_code=403, detail="You can only edit your own account")

    # Check if new username already exists
    existing_user = db.query(models.User).filter(
        models.User.username == request.new_username,
        models.User.id != user_id
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Update username
    user.username = request.new_username
    db.commit()

    print(f"👤 Username updated for user {user_id}")
    return {"message": "Username updated successfully"}

@app.put("/edit-role/{user_id}")
def edit_role(user_id: int, request: EditRoleRequest, db: Session = Depends(get_db)):
    # Check if user is logged in
    if current_operator_id is None:
        raise HTTPException(status_code=401, detail="Please login first")

    # Check if user exists
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Only Admin can edit roles
    admin_user = db.query(models.User).filter(models.User.id == current_operator_id).first()
    if not admin_user or admin_user.access_role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admin can edit user roles")

    # Update role
    user.access_role = request.new_role
    db.commit()

    print(f"🎭 Role updated for user {user_id} to {request.new_role}")
    return {"message": "Role updated successfully"}

@app.post("/logout")
def logout():
    global current_operator_id, active_session_id
    if active_session_id is not None:
        db = SessionLocal()
        session = db.query(models.SystemSession).filter(
            models.SystemSession.id == active_session_id
        ).first()
        if session:
            session.end_time = datetime.now()
            db.commit()
        db.close()
        active_session_id = None
    print(f"👋 Operator {current_operator_id} Logged Out.")
    current_operator_id = None
    return {"message": "Logged out successfully"}

@app.post("/start-session")
def start_session(db: Session = Depends(get_db)):
    global active_session_id
    if current_operator_id is None:
        raise HTTPException(status_code=401, detail="Please login first")
    if active_session_id is not None:
        raise HTTPException(status_code=400, detail="A session is already running")
    new_s = models.SystemSession(operator_id=current_operator_id, start_time=datetime.now())
    db.add(new_s)
    db.commit()
    db.refresh(new_s)
    active_session_id = new_s.id
    print(f"🆕 Session {active_session_id} Started.")
    return {"message": "Session Started", "session_id": active_session_id}

@app.post("/stop-session")
def stop_session(db: Session = Depends(get_db)):
    global active_session_id
    if current_operator_id is None:
        raise HTTPException(status_code=401, detail="Please login first")
    if active_session_id is None:
        raise HTTPException(status_code=400, detail="No active session to stop")
    session = db.query(models.SystemSession).filter(
        models.SystemSession.id == active_session_id
    ).first()
    if session:
        session.end_time = datetime.now()
        db.commit()
    print(f"🏁 Session {active_session_id} Stopped.")
    active_session_id = None
    return {"message": "Session Stopped"}

# ==========================================
# GET Endpoints
# ==========================================

@app.get("/inspections")
def get_inspections(db: Session = Depends(get_db)):
    inspections = db.query(models.Inspection).all()
    return inspections

@app.get("/inspections/session/{session_id}")
def get_inspections_by_session(session_id: int, db: Session = Depends(get_db)):
    inspections = db.query(models.Inspection).filter(
        models.Inspection.session_id == session_id
    ).all()
    return inspections

@app.get("/telemetry")
def get_telemetry(db: Session = Depends(get_db)):
    telemetry = db.query(models.SensorData).all()
    return telemetry

@app.get("/telemetry/session/{session_id}")
def get_telemetry_by_session(session_id: int, db: Session = Depends(get_db)):
    telemetry = db.query(models.SensorData).filter(
        models.SensorData.session_id == session_id
    ).all()
    return telemetry

@app.get("/sessions")
def get_sessions(db: Session = Depends(get_db)):
    sessions = db.query(models.SystemSession).all()
    return sessions