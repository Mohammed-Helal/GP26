# main.py
import json
from contextlib import asynccontextmanager # استيراد المكتبة الجديدة للـ lifespan
from fastapi import FastAPI, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pyModbusTCP.client import ModbusClient
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion # استيراد لتحديد إصدار MQTT
from datetime import datetime

# Import our custom modules
import models
import schemas
from database import engine, get_db, SessionLocal

# --- PLC Modbus Configuration ---
PLC_IP = "192.168.1.10" 
PLC_PORT = 502
plc_client = ModbusClient(host=PLC_IP, port=PLC_PORT, auto_open=True, auto_close=True)

def trigger_plc_reject():
    try:
        is_successful = plc_client.write_single_register(0, 1)
        if is_successful:
            print("Successfully sent reject command to PLC.")
        else:
            print("Failed to send command to PLC.")
    except Exception as e:
        print(f"Modbus communication error: {e}")

# ==========================================
# --- MQTT Configuration & Logic ---
# ==========================================
MQTT_BROKER = "127.0.0.1" 
MQTT_PORT = 1883
MQTT_TOPIC = "factory/sensors/esp32"

# ملاحظة: تم إضافة properties و reason_code لتتوافق مع الإصدار الثاني من MQTT
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to MQTT Broker with result code {reason_code}")
    client.subscribe(MQTT_TOPIC)

def on_mqtt_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        payload_dict = json.loads(payload_str)
        
        sensor_data = schemas.SensorDataCreate(**payload_dict)
        
        db = SessionLocal()
        try:
            db_sensor_data = models.SensorData(
                session_id=sensor_data.session_id,
                temp=sensor_data.temp,
                vibration=sensor_data.vibration,
                current=sensor_data.current
            )
            db.add(db_sensor_data)
            db.commit()
            print(f"Saved MQTT data to DB: Temp={sensor_data.temp}, Vib={sensor_data.vibration}")
        finally:
            db.close()
            
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

# استخدام الإصدار الثاني الحديث من MQTT
mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

# ==========================================
# --- FastAPI Lifespan (الطريقة الحديثة بديلة on_event) ---
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. ما يكتب هنا يعمل عند تشغيل السيرفر (Startup)
    models.Base.metadata.create_all(bind=engine)
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start() 
        print("MQTT Client Started.")
    except Exception as e:
        print(f"Failed to connect to MQTT Broker: {e}")
    
    yield # هذه الكلمة تعني: السيرفر يعمل الآن وجاهز لاستقبال الطلبات
    
    # 2. ما يكتب هنا يعمل عند إيقاف السيرفر (Shutdown)
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    print("MQTT Client Stopped gracefully.")

# ربط الـ lifespan بتطبيق FastAPI
app = FastAPI(title="Smart Factory Core API with MQTT", lifespan=lifespan)

# ==========================================
# --- HTTP Endpoints ---
# ==========================================

@app.get("/")
def read_root():
    return {"status": "API and MQTT Subscriber are running successfully"}

active_session_id = None
@app.post("/start-session")
def start_session(operator_id: int, db: Session = Depends(get_db)):
    global active_session_id
    new_s = models.SystemSession(operator_id=operator_id, start_time=datetime.now())
    db.add(new_s)
    db.commit()
    db.refresh(new_s)
    active_session_id = new_s.id
    print(f"🆕 Session {active_session_id} Started.")
    return {"message": "Session Started", "session_id": active_session_id}

@app.post("/create-user")
def create_user(username: str, password: str, role: str = "Operator", db: Session = Depends(get_db)):
    new_user = models.User(
        username=username,
        password_hash=password,  # في الـ production هتعمل hashing طبعاً
        access_role=role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/api/v1/inspections/result", response_model=schemas.InspectionResponse)
def add_inspection_result(
    inspection: schemas.InspectionCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    db_inspection = models.Inspection(
        session_id=inspection.session_id,
        status=inspection.status,
        defect_category=inspection.defect_category,
        confidence=inspection.confidence,
        image_path=inspection.image_path
    )
    
    db.add(db_inspection)
    db.commit()
    db.refresh(db_inspection)

    if inspection.status.lower() == "defected":
        background_tasks.add_task(trigger_plc_reject)

    return db_inspection