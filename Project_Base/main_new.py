import json, os, cv2, torch, time
from datetime import datetime
from threading import Thread
from PIL import Image
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# استيراد ملفاتك الخاصة
import models, schemas
from database import engine, get_db, SessionLocal

# ==========================================
# 1. الإعدادات (Configurations)
# ==========================================
PLC_IP = "192.168.1.200" 
PLC_PORT = 502
MODEL_PATH = "banana_classifier_final"
MQTT_BROKER = "127.0.0.1"
OUTPUT_DIR = "banana_classifications"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# متغيرات عالمية (Global) لإدارة الحالة
active_session_id = None 
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

# ==========================================
# 2. منطق الـ AI والـ PLC (الخلفية)
# ==========================================

def run_ai_logic():
    """هذه الدالة تعمل في Thread منفصل لمراقبة السنسور والذكاء الاصطناعي"""
    global active_session_id
    from transformers import AutoImageProcessor, AutoModelForImageClassification
    
    # تحميل الموديل مرة واحدة عند البداية
    preprocessor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
    model = AutoModelForImageClassification.from_pretrained(MODEL_PATH)
    model.eval()
    
    cap = cv2.VideoCapture(1) # الكاميرا
    previous_sensor_value = None

    while True:
        ret, frame = cap.read()
        if not ret: continue

        # قراءة السنسور من ريجستر 10 في الـ PLC
        try:
            response = plc_client.read_holding_registers(10, count=1)
            current_sensor_value = response.registers[0] if not response.isError() else None
            
            # اكتشاف نبضة السنسور (من 1 لـ 0)
            if previous_sensor_value == 1 and current_sensor_value == 0:
                print("⚡ Sensor Triggered! Classifying...")
                
                # تصنيف الصورة
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb_frame)
                inputs = preprocessor(images=img, return_tensors="pt")
                with torch.no_grad():
                    outputs = model(**inputs)
                
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
                pred_idx = outputs.logits.argmax(-1).item()
                label = model.config.id2label[pred_idx]
                conf = probs[pred_idx].item() * 100

                # حفظ الصورة
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                img_path = os.path.join(OUTPUT_DIR, f"prod_{ts}.jpg")
                cv2.imwrite(img_path, frame)

                # تسجيل في الداتا بيز (PostgreSQL)
                db = SessionLocal()
                new_insp = models.Inspection(
                    session_id=active_session_id, # ربطها بالعملية الحالية
                    status=label,
                    confidence=conf,
                    image_path=img_path
                )
                db.add(new_insp)
                db.commit()
                db.close()

                # إرسال أمر للـ PLC بناءً على النتيجة
                if label == "fresh":
                    plc_client.write_register(0, 1) # سليم
                else:
                    plc_client.write_register(1, 1) # تالف (Reject)

            previous_sensor_value = current_sensor_value
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(0.1)

# ==========================================
# 3. MQTT (Telemetry من الـ ESP)
# ==========================================

def on_mqtt_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        db = SessionLocal()
        # تسجيل الحساسات مربوطة بالـ Session الحالية
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
# 4. FastAPI Lifespan & Endpoints
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # تشغيل الجداول
    models.Base.metadata.create_all(bind=engine)
    # تشغيل الـ PLC و MQTT
    plc_client.connect()
    mqtt_c.connect(MQTT_BROKER, 1883)
    mqtt_c.loop_start()
    # تشغيل الـ AI في الخلفية
    Thread(target=run_ai_logic, daemon=True).start()
    yield
    mqtt_c.loop_stop()
    plc_client.close()

app = FastAPI(lifespan=lifespan)

@app.post("/start-session")
def start_session(operator_id: int, db: Session = Depends(get_db)):
    global active_session_id
    new_s = models.SystemSession(operator_id=operator_id, start_time=datetime.now())
    db.add(new_s)
    db.commit()
    db.refresh(new_s)
    active_session_id = new_s.id
    return {"message": "Session Started", "session_id": active_session_id}

@app.post("/stop-session")
def stop_session(db: Session = Depends(get_db)):
    global active_session_id
    session = db.query(models.SystemSession).filter(models.SystemSession.id == active_session_id).first()
    if session:
        session.end_time = datetime.now()
        db.commit()
    active_session_id = None
    return {"message": "Session Stopped"}