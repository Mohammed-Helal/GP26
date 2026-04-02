import json, os, cv2, torch, time
from datetime import datetime
from threading import Thread
from PIL import Image
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# import files
import models, schemas
from database import engine, get_db, SessionLocal

# ==========================================
# (Configurations)
# ==========================================
PLC_IP = "192.168.1.200" 
PLC_PORT = 502
MODEL_PATH = "banana_classifier_final"
MQTT_BROKER = "127.0.0.1"
OUTPUT_DIR = "banana_classifications"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Global Variable
active_session_id = None 
current_operator_id = None
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

# ==========================================
# PLC and AI
# ==========================================

def run_ai_logic():
    global active_session_id
    from transformers import AutoImageProcessor, AutoModelForImageClassification
    
    print("🔄 Loading AI Model...")
    try:
        # download model
        preprocessor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
        model = AutoModelForImageClassification.from_pretrained(MODEL_PATH)
        model.eval()
        print("✅ AI Model Loaded Successfully.")
    except Exception as e:
        print(f"❌ Error Loading Model: {e}")
        return

    # Open Cam
    cap = cv2.VideoCapture(0) 
    previous_sensor_value = None

    print("📸 Camera Stream Started. Press 'q' on the image window to stop viewing.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Cannot read from camera")
            break

        # Live stream 
        cv2.imshow("System - Live Feed", frame)

        key = cv2.waitKey(1) & 0xFF     

        try:
            # ==========================================
            # Start session 
            # ==========================================
            start_response = plc_client.read_holding_registers(11, count=1)
            if not start_response.isError():
                start_value = start_response.registers[0]
                if start_value == 1 and active_session_id is None and current_operator_id is None:
                    db = SessionLocal()
                    new_s = models.SystemSession(
                        operator_id= current_operator_id,  
                        start_time= datetime.now()
                    )
                    db.add(new_s)
                    db.commit()
                    db.refresh(new_s)
                    active_session_id = new_s.id
                    db.close()
                    print(f"🆕 Auto Session Started: {active_session_id}")

            # ==========================================
            # Start session 
            # ==========================================
            stop_response = plc_client.read_holding_registers(12, count=1)
            if not stop_response.isError():
                stop_value = stop_response.registers[0]
                if stop_value == 1 and active_session_id is not None:  # not None مش None
                    db = SessionLocal()
                    session = db.query(models.SystemSession).filter(
                        models.SystemSession.id == active_session_id
                    ).first()
                    if session:
                        session.end_time = datetime.now()
                        db.commit()
                    db.close()
                    print(f"🏁 Session {active_session_id} Stopped.")
                    active_session_id = None



            # Trigger on register(10)
            response = plc_client.read_holding_registers(10, count=1)
            if not response.isError():
                current_sensor_value = response.registers[0]
                
                # (0 ---> 1)
                if (previous_sensor_value == 1 and current_sensor_value == 0) or (key == ord('a')):
                    print("⚡ Sensor Triggered! Classifying...")
                    
                    # processing and analyze the photo
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
                    print(f"📊 Result Saved! ID: {new_insp.id} | Status: {label}")
                    db.close()
                    
                    # print(f"📊 Result: {label} | Confidence: {conf:.2f}%")

                    # إرسال الأوامر للـ PLC (سجل 0 للسليم، سجل 1 للتالف)
                    if label.lower() == "fresh":
                        plc_client.write_register(0, 1)
                        print("✅ Command: PASS")
                    else:
                        plc_client.write_register(1, 1)
                        print("❌ Command: REJECT")

                previous_sensor_value = current_sensor_value

        except Exception as e:
            # loop continue 
            pass

        # (q) to exit from the cam 
        if key == ord('q'):
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
    """run Everything in the server"""
    print("\n🚀 Starting System Services...")
    
    # 1. Create tables
    models.Base.metadata.create_all(bind=engine)
    print("✅ Database Tables Verified.")

    # 2. PLC comunication
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
    else:
        print(f"❌ PLC Connection Failed at {PLC_IP}")

    # 3. MQTT communication
    try:
        mqtt_c.connect(MQTT_BROKER, 1883)
        mqtt_c.loop_start()
        print("✅ MQTT Broker Connected.")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

    # 4.run ai model on the background
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

@app.post("/create-user")
def create_user(username: str, password: str, role: str = "Operator", db: Session = Depends(get_db)):
    new_user = models.User(
        username=username,
        password_hash=password,
        access_role=role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/login")
def login(username: str, password: str, db: Session = Depends(get_db)):
    global current_operator_id    
    user = db.query(models.User).filter(
        models.User.username == username,
        models.User.password_hash == password
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Wrong username or password")  # ✅

    current_operator_id = user.id
    return {"user_id": user.id, "username": user.username, "role": user.access_role}

@app.post("/logout")
def logout():
    global current_operator_id, active_session_id
    
    # لو في session شغالة، وقّفها الأول
    if active_session_id is not None:
        db = SessionLocal()
        session = db.query(models.SystemSession).filter(
            models.SystemSession.id == active_session_id
        ).first()
        if session:
            session.end_time = datetime.now()
            db.commit()
        db.close()
        print(f"🏁 Session {active_session_id} Stopped.")
        active_session_id = None
    
    print(f"👋 Operator {current_operator_id} Logged Out.")
    current_operator_id = None
    
    return {"message": "Logged out successfully"}

@app.post("/start-session")
def start_session(operator_id: int, db: Session = Depends(get_db)):
    global active_session_id

    if current_operator_id is None:
        raise HTTPException(status_code=401, detail="Please login first")
    
    if operator_id != current_operator_id:
        raise HTTPException(status_code=403, detail="Operator ID does not match logged in user")
    
    user = db.query(models.User).filter(models.User.id == operator_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Operator not found")
    
    # Sure no sessions work
    if active_session_id is not None:
        raise HTTPException(status_code=400, detail="A session is already running")
    
    new_s = models.SystemSession(operator_id=operator_id, start_time=datetime.now())
    db.add(new_s)
    db.commit()
    db.refresh(new_s)
    active_session_id = new_s.id

    try:
        plc_client.write_register(11, 1)  # register 11 = start
        print(f"✅ PLC Start Signal Sent.")
    except Exception as e:
        print(f"⚠️ PLC Signal Failed: {e}")


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

    try:
        plc_client.write_register(12, 1)  # register 11 = start
        print(f"✅ PLC Start Signal Sent.")
    except Exception as e:
        print(f"⚠️ PLC Signal Failed: {e}")  
    
    print(f"🏁 Session {active_session_id} Stopped.")
    active_session_id = None
    return {"message": "Session Stopped"}







