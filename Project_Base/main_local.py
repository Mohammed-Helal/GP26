import os, cv2, torch, time, json
from datetime import datetime
from threading import Thread
from PIL import Image
from pymodbus.client import ModbusTcpClient
import cloudinary
import cloudinary.uploader
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import models
from database import SessionLocal

# ==========================================
# System Configurations
# ==========================================
# Force OpenCV to use xcb (Fixes Wayland Lag on Linux)
os.environ["QT_QPA_PLATFORM"] = "xcb"
# Hide OpenCV font warnings
os.environ["OPENCV_LOG_LEVEL"] = "FATAL"

PLC_IP = "192.168.1.200"
PLC_PORT = 502
MODEL_PATH = "Project_Base/banana_classifier_final"
OUTPUT_DIR = "banana_classifications"

# MQTT Configuration
MQTT_BROKER = "192.168.1.100"  # Update with your MQTT broker IP
MQTT_PORT = 1883
MQTT_TOPIC = "factory/sensors"


if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ==========================================
# MQTT
# ==========================================
def on_mqtt_message(client, userdata, msg):
    global active_session_id
    try:
        data = json.loads(msg.payload.decode())
        
        if active_session_id is None:
            return

        db = SessionLocal()
        tele = models.SensorData(
            session_id=active_session_id,
            temp=data.get('temperature', 0.0),    
            vibration=data.get('vibration', 0.0),   
            current=data.get('current', 0.0)     
        )
        db.add(tele)
        db.commit()
        db.close()
    except json.JSONDecodeError:
        print("❌ MQTT Error: Received malformed JSON from ESP")
    except Exception as e:
        print(f"❌ MQTT Database Error: {e}")

# MQTT Setup
def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    print(f"✅ Connected to MQTT Broker!")
    client.subscribe(MQTT_TOPIC)
    print(f"📡 Subscribed to topic: {MQTT_TOPIC}")

mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

# ==========================================
# Cloudinary Configuration
# ==========================================
# TODO: Replace these with your actual Cloudinary credentials
cloudinary.config( 
  cloud_name = "helal", 
  api_key = "815319279227261", 
  api_secret = "8eV6XQ5jEe8U-YjxQgwkVuE23IM" 
)

# Global Variables for System State
active_session_id = None
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
current_operator_id = 21  # Update this dynamically based on the logged-in user
plc_connected = False

# Global Variables for Async DB Polling
db_session_active = False
db_active_id = None

# ==========================================
# Database Monitor Thread
# ==========================================
def db_monitor_thread():
    """
    Background thread to poll the database every 2 seconds.
    This prevents blocking the main camera loop and keeps the UI smooth.
    """
    global db_session_active, db_active_id
    while True:
        try:
            db = SessionLocal()
            open_session = db.query(models.SystemSession).filter(
                models.SystemSession.end_time == None
            ).first()
            
            if open_session:
                db_session_active = True
                db_active_id = open_session.id
            else:
                db_session_active = False
                db_active_id = None
            
            db.close()
        except Exception as e:
            print(f"⚠️ DB Monitor Error: {e}")
        
        time.sleep(2.0)

# ==========================================
# Camera Threading Class
# ==========================================
class CameraStream:
    """
    A class to run camera reading in a separate background thread.
    This prevents the AI and network delays from freezing the video feed.
    """
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False

    def start(self):
        Thread(target=self.update, daemon=True).start()
        return self

    def update(self):
        while True:
            if self.stopped:
                return
            (self.grabbed, self.frame) = self.stream.read()
            time.sleep(0.01)

    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True
        self.stream.release()

# ==========================================
# Helper: Start Session in DB
# ==========================================
def start_session_in_db(operator_id):
    """Create a new session in the database for a specific operator"""
    global active_session_id
    try:
        db = SessionLocal()
        open_session = db.query(models.SystemSession).filter(
            models.SystemSession.end_time == None
        ).first()
        
        if open_session:
            print(f"⚠️ Session already exists in DB: {open_session.id}")
            active_session_id = open_session.id
            db.close()
            return open_session.id

        new_s = models.SystemSession(
            operator_id=operator_id,
            start_time=datetime.now()
        )
        db.add(new_s)
        db.commit()
        db.refresh(new_s)
        active_session_id = new_s.id
        db.close()
        print(f"🆕 New Session Created in DB: Session ID {active_session_id} | Operator ID: {operator_id}")
        return active_session_id
    except Exception as e:
        print(f"❌ DB Error while starting session: {e}")
        return None

# ==========================================
# Helper: Stop Session in DB
# ==========================================
def stop_session_in_db():
    """Close the active session in the database"""
    global active_session_id
    if active_session_id is None:
        print("⚠️ No active session to stop.")
        return
    try:
        db = SessionLocal()
        session = db.query(models.SystemSession).filter(
            models.SystemSession.id == active_session_id
        ).first()
        
        if session:
            session.end_time = datetime.now()
            db.commit()
            print(f"🏁 Session {active_session_id} Closed in DB. (Operator ID: {session.operator_id})")
        db.close()
        active_session_id = None
    except Exception as e:
        print(f"❌ DB Error while stopping session: {e}")

# ==========================================
# AI Logic
# ==========================================
def run_ai_logic():
    global active_session_id, current_operator_id, plc_connected
    from transformers import AutoImageProcessor, AutoModelForImageClassification

    print("🔄 Loading AI Model...")
    try:
        preprocessor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
        model = AutoModelForImageClassification.from_pretrained(MODEL_PATH)
        model.eval()
        print("✅ AI Model Loaded Successfully.")
    except Exception as e:
        print(f"❌ Error Loading Model: {e}")
        return

    # Start the Background Database Monitor Thread
    print("🔍 Starting Database Monitor Thread...")
    Thread(target=db_monitor_thread, daemon=True).start()

    # Initialize and start the camera stream thread
    cam = CameraStream(0).start()
    take_photo = None

    print("📸 Camera Stream Started.")
    print("💡 Press 's' to simulate MW11=1 (Start Session)")
    print("💡 Press 'd' to simulate MW11=0 (Stop Session)")
    print("💡 Press 'v' to manually trigger inspection")
    print("💡 Press 'q' to quit")

    while True:
        # Fetch the latest frame from the background thread
        frame = cam.read()
        if frame is None:
            print("⚠️ Cannot read from camera")
            break

        cv2.imshow("System - Live Feed", frame)
        key = cv2.waitKey(1) & 0xFF

        # ==========================================
        # Keyboard Simulation (Testing Tools)
        # ==========================================
        if key == ord('s'):
            if plc_connected: 
                plc_client.write_register(11, 1)
            else:
                # SIMULATION MODE: Start session directly if no PLC
                if active_session_id is None:
                    print("🛠️ SIMULATION: Starting Session...")
                    start_session_in_db(current_operator_id)
            print("🔑 Key 's' pressed → MW11 = 1")

        if key == ord('d'):
            if plc_connected: 
                plc_client.write_register(11, 0)
            else:
                # SIMULATION MODE: Stop session directly if no PLC
                if active_session_id is not None:
                    print("🛠️ SIMULATION: Stopping Session...")
                    stop_session_in_db()
            print("🔑 Key 'd' pressed → MW11 = 0")

        if key == ord('v'):
            take_photo = 1
            print("📸 Manual photo capture triggered")

        try:
            # ==========================================
            # FAST Non-Blocking Database Check
            # ==========================================
            if db_session_active and active_session_id != db_active_id:
                active_session_id = db_active_id
                if plc_connected:
                    plc_client.write_register(11, 1)
                print(f"🆕 Session {active_session_id} detected via DB Monitor → MW11 = 1")

            elif not db_session_active and active_session_id is not None:
                active_session_id = None
                if plc_connected:
                    plc_client.write_register(11, 0)
                print("🏁 Session ended via DB Monitor → MW11 = 0")

            # ==========================================
            # Read from PLC (ONLY IF CONNECTED)
            # ==========================================
            if plc_connected:
                mw11_response = plc_client.read_holding_registers(11, count=1)
                if mw11_response and not mw11_response.isError():
                    mw11_value = mw11_response.registers[0]
                    
                    if mw11_value == 1 and active_session_id is None:
                        print("📡 MW11 = 1 detected → Starting Session...")
                        start_session_in_db(current_operator_id)
                    elif mw11_value == 0 and active_session_id is not None:
                        print("📡 MW11 = 0 detected → Stopping Session...")
                        stop_session_in_db()

                mw10_response = plc_client.read_holding_registers(10, count=1)
                if mw10_response and not mw10_response.isError():
                    mw10_value = mw10_response.registers[0]
            else:
                mw10_value = 0

            # ==========================================
            # AI Inference execution
            # ==========================================
            if (mw10_value == 1) or (take_photo is not None):
                if active_session_id is None:
                    print("⚠️ Trigger received but no active session. Skipping inspection.")
                    take_photo = None
                    if plc_connected: plc_client.write_register(10, 0)
                else:
                    print("⚡ Product detected! Running AI Classification...")

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb_frame)
                    inputs = preprocessor(images=img, return_tensors="pt")

                    with torch.no_grad():
                        outputs = model(**inputs)

                    probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
                    pred_idx = outputs.logits.argmax(-1).item()
                    label = model.config.id2label[pred_idx]
                    conf = probs[pred_idx].item() * 100
                    print(f"🤖 AI Result: {label} | Confidence: {conf:.2f}%")

                    # ==========================================
                    # Cloud Upload Logic (Only if confidence < 70)
                    # ==========================================
                    if conf < 100:
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        temp_local_path = os.path.join(OUTPUT_DIR, f"temp_low_conf_{ts}.jpg")
                        
                        # 1. Save image locally temporarily
                        cv2.imwrite(temp_local_path, frame)
                        print(f"☁️ Low confidence ({conf:.2f}%) detected. Uploading to Cloudinary...")
                        
                        try:
                            # 2. Upload to Cloudinary
                            response = cloudinary.uploader.upload(temp_local_path)
                            secure_url = response.get('secure_url')
                            
                            # 3. Save URL to Database
                            db = SessionLocal()
                            new_insp = models.Inspection(
                                session_id=active_session_id,
                                status=label,
                                confidence=conf,
                                image_path=secure_url # Save the online link
                            )
                            db.add(new_insp)
                            db.commit()
                            db.close()
                            print(f"📊 Saved to DB with Cloud Link: {secure_url}")
                            
                        except Exception as upload_err:
                            print(f"❌ Cloudinary Upload Failed: {upload_err}")
                            
                        finally:
                            # 4. Remove local temp file to save disk space
                            if os.path.exists(temp_local_path):
                                os.remove(temp_local_path)
                                print(f"🗑️ Cleaned up temporary file.")
                    else:
                        print(f"✅ High confidence ({conf:.2f}%), skipping upload.")

                    # Reset trigger flags
                    take_photo = None
                    if plc_connected:
                        plc_client.write_register(10, 0)

                    # Send PASS/REJECT command to PLC
                    if label.lower() == "fresh":
                        if plc_connected: plc_client.write_register(0, 1)
                        print("✅ Command Sent to PLC: PASS")
                    else:
                        if plc_connected: plc_client.write_register(1, 1)
                        print("❌ Command Sent to PLC: REJECT")

        except Exception as e:
            pass

        if key == ord('q'):
            print("👋 Quitting the application...")
            break

        time.sleep(0.01)

    cam.stop()
    cv2.destroyAllWindows()

# ==========================================
# Application Entry Point
# ==========================================
if __name__ == "__main__":
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
        plc_connected = True
    else:
        print(f"❌ PLC Connection Failed at {PLC_IP} - Running in Simulation Mode (No PLC)")
        plc_connected = False

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"✅ MQTT Client Started. Broker: {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")


    db = SessionLocal()
    open_session = db.query(models.SystemSession).filter(
        models.SystemSession.end_time == None
    ).first()
    
    if open_session:
        active_session_id = open_session.id
        db_session_active = True
        db_active_id = open_session.id
        print(f"🔄 Restored Active Session from DB: {active_session_id} (Operator ID: {open_session.operator_id})")
    else:
        print("ℹ️ No active session found in DB.")
    db.close()

    run_ai_logic()