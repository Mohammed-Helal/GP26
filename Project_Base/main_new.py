import json, os, cv2, torch, time
from datetime import datetime
from threading import Thread
from PIL import Image
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

# متغيرات عالمية لإدارة الحالة
active_session_id = None 
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

# ==========================================
# 2. منطق الـ AI والـ PLC (الخلفية)
# ==========================================

def run_ai_logic():
    """هذه الدالة تعمل في Thread منفصل لمراقبة الحساس، عرض الكاميرا، وتشغيل الذكاء الاصطناعي"""
    global active_session_id
    from transformers import AutoImageProcessor, AutoModelForImageClassification
    
    print("🔄 Loading AI Model...")
    try:
        # تحميل معالج الصور والموديل
        preprocessor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
        model = AutoModelForImageClassification.from_pretrained(MODEL_PATH)
        model.eval()
        print("✅ AI Model Loaded Successfully.")
    except Exception as e:
        print(f"❌ Error Loading Model: {e}")
        return

    # فتح الكاميرا (تأكد من الرقم 0 أو 1 حسب جهازك)
    cap = cv2.VideoCapture(0) 
    previous_sensor_value = None

    print("📸 Camera Stream Started. Press 'q' on the image window to stop viewing.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Cannot read from camera")
            break

        # --- عرض البث المباشر للعملية ---
        cv2.imshow("System - Live Feed", frame)
        
        try:
            # قراءة الحساس من ريجستر 10 في الـ PLC (الزناد / Trigger)
            response = plc_client.read_holding_registers(10, count=1)
            if not response.isError():
                current_sensor_value = response.registers[0]
                
                # اكتشاف النبضة (الانتقال من 1 إلى 0)
                if previous_sensor_value == 1 and current_sensor_value == 0:
                    print("⚡ Sensor Triggered! Classifying...")
                    
                    # معالجة الصورة وتحليلها
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb_frame)
                    inputs = preprocessor(images=img, return_tensors="pt")
                    
                    with torch.no_grad():
                        outputs = model(**inputs)
                    
                    # استخراج النتائج
                    probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
                    pred_idx = outputs.logits.argmax(-1).item()
                    label = model.config.id2label[pred_idx]
                    conf = probs[pred_idx].item() * 100

                    # حفظ الصورة في المجلد المخصص
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    img_name = f"product_{ts}.jpg"
                    img_path = os.path.join(OUTPUT_DIR, img_name)
                    cv2.imwrite(img_path, frame)

                    # تسجيل البيانات في قاعدة البيانات
                    db = SessionLocal()
                    new_insp = models.Inspection(
                        session_id=active_session_id,
                        status=label,
                        confidence=conf,
                        image_path=img_path
                    )
                    db.add(new_insp)
                    db.commit()
                    db.close()
                    
                    print(f"📊 Result: {label} | Confidence: {conf:.2f}%")

                    # إرسال الأوامر للـ PLC (سجل 0 للسليم، سجل 1 للتالف)
                    if label.lower() == "fresh":
                        plc_client.write_register(0, 1)
                        print("✅ Command: PASS")
                    else:
                        plc_client.write_register(1, 1)
                        print("❌ Command: REJECT")

                previous_sensor_value = current_sensor_value
        except Exception as e:
            # استمرار الحلقة رغم أخطاء الاتصال العابرة
            pass

        # إغلاق النافذة عند الضغط على q
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        
        time.sleep(0.05) 

    cap.release()
    cv2.destroyAllWindows()

# ==========================================
# 3. MQTT
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
# 4. FastAPI App & Events
# ==========================================

app = FastAPI(title="Smart Factory Core API")

@app.on_event("startup")
def startup_event():
    """تشغيل كل المكونات عند بدء السيرفر"""
    print("\n🚀 Starting System Services...")
    
    # 1. إنشاء الجداول
    models.Base.metadata.create_all(bind=engine)
    print("✅ Database Tables Verified.")

    # 2. الاتصال بالـ PLC
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
    else:
        print(f"❌ PLC Connection Failed at {PLC_IP}")

    # 3. الاتصال بالـ MQTT
    try:
        mqtt_c.connect(MQTT_BROKER, 1883)
        mqtt_c.loop_start()
        print("✅ MQTT Broker Connected.")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

    # 4. تشغيل الـ AI في الخلفية
    Thread(target=run_ai_logic, daemon=True).start()
    print("✅ AI Logic Thread Started.")

@app.on_event("shutdown")
def shutdown_event():
    mqtt_c.loop_stop()
    plc_client.close()
    print("🛑 System Shutdown Complete.")

# ==========================================
# 5. Endpoints
# ==========================================

@app.get("/")
def home():
    return {"status": "Online", "plc": plc_client.is_socket_open()}

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

@app.post("/stop-session")
def stop_session(db: Session = Depends(get_db)):
    global active_session_id
    session = db.query(models.SystemSession).filter(models.SystemSession.id == active_session_id).first()
    if session:
        session.end_time = datetime.now()
        db.commit()
    print(f"🏁 Session {active_session_id} Stopped.")
    active_session_id = None
    return {"message": "Session Stopped"}