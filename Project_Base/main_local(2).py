import os, cv2, time, json, pickle
from datetime import datetime
from threading import Thread
from PIL import Image
import numpy as np
import torch
import torchvision.models as models
import torchvision.transforms as transforms
from sklearn.metrics import pairwise_distances
from pymodbus.client import ModbusTcpClient
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import Database.models as db_models
from Database.base import SessionLocal

# ==========================================
# System Configurations
# ==========================================
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ["OPENCV_LOG_LEVEL"] = "FATAL"

PLC_IP = "192.168.1.200"
PLC_PORT = 502
PATCHCORE_PATH = r"Project_Base/CV_Models/patchcore.pkl"
FEWSHOT_PATH   = r"Project_Base/CV_Models/fewshot.pkl"
OUTPUT_DIR = "Project_Base/Images"

MQTT_BROKER = "192.168.1.238"
MQTT_PORT = 1883
MQTT_TOPIC = "factory/sensors"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ============================================================
# NEW FEATURE EXTRACTOR (PyTorch)
# ============================================================
class FeatureExtractor:
    def __init__(self):
        print("🔄 Loading ResNet50 Backbone...")
        self.model = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
        self.features = {}
        self.model.layer2.register_forward_hook(lambda m, i, o: self.features.update({'layer2': o}))
        self.model.layer3.register_forward_hook(lambda m, i, o: self.features.update({'layer3': o}))
        self.model.eval()
        
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def extract_features(self, frame_bgr):
        # Convert BGR to RGB and then to PIL
        img_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img_pil = Image.fromarray(img_rgb)
        img_tensor = self.transform(img_pil).unsqueeze(0)
        
        with torch.inference_mode():
            self.model(img_tensor)
        
        f2 = self.features['layer2'].mean(dim=[2, 3]).squeeze().numpy()
        f3 = self.features['layer3'].mean(dim=[2, 3]).squeeze().numpy()
        return np.concatenate([f2, f3])

# ==========================================
# MQTT & Database Utils
# ==========================================
def on_mqtt_message(client, userdata, msg):
    global active_session_id
    try:
        data = json.loads(msg.payload.decode())
        if active_session_id is None: return
        db = SessionLocal()
        tele = db_models.SensorData(
            session_id=active_session_id,
            temp=data.get('temperature', 0.0),    
            vibration=data.get('vibration', 0.0),   
            current=data.get('current', 0.0)     
        )
        db.add(tele)
        db.commit()
        db.close()
    except Exception as e: print(f"❌ MQTT Error: {e}")

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(MQTT_TOPIC)

mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

active_session_id = None
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
current_operator_id = 1
plc_connected = False
db_session_active = False
db_active_id = None

def db_monitor_thread():
    global db_session_active, db_active_id
    while True:
        try:
            db = SessionLocal()
            open_session = db.query(db_models.SystemSession).filter(db_models.SystemSession.end_time == None).first()
            if open_session:
                db_session_active = True
                db_active_id = open_session.id
            else:
                db_session_active = False
                db_active_id = None
            db.close()
        except Exception as e: print(f"⚠️ DB Monitor Error: {e}")
        time.sleep(2.0)

class CameraStream:
    def __init__(self):
        self.stream = cv2.VideoCapture(0)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
    def start(self):
        Thread(target=self.update, daemon=True).start()
        return self
    def update(self):
        while not self.stopped:
            (self.grabbed, self.frame) = self.stream.read()
            time.sleep(0.01)
    def read(self): return self.frame
    def stop(self):
        self.stopped = True
        self.stream.release()

def start_session_in_db(operator_id):
    global active_session_id
    db = SessionLocal()
    new_s = db_models.SystemSession(operator_id=operator_id, start_time=datetime.now())
    db.add(new_s)
    db.commit()
    db.refresh(new_s)
    active_session_id = new_s.id
    db.close()
    print(f"Session {active_session_id} started")
    return active_session_id

def stop_session_in_db():
    global active_session_id
    if active_session_id:
        db = SessionLocal()
        session = db.query(db_models.SystemSession).filter(db_models.SystemSession.id == active_session_id).first()
        if session:
            session.end_time = datetime.now()
            db.commit()
            print(f"Session {active_session_id} stoped")
        db.close()
        active_session_id = None

# ==========================================
# AI MAIN LOGIC
# ==========================================
def run_ai_logic():
    global active_session_id, current_operator_id, plc_connected

    # 1. Load Custom Models
    print("🔄 Initializing PatchCore & Few-Shot Models...")
    try:
        extractor = FeatureExtractor()
        with open(PATCHCORE_PATH, 'rb') as f:
            pc_data = pickle.load(f)
            memory_bank = pc_data['memory_bank']
            threshold = pc_data['threshold']
        
        with open(FEWSHOT_PATH, 'rb') as f:
            fs_data = pickle.load(f)
            class_features = fs_data['class_features']
            class_names = fs_data['class_names']
        print(f"✅ Models Loaded. Threshold: {threshold:.4f}")
    except Exception as e:
        print(f"❌ Error Loading Pickle Models: {e}")
        return

    Thread(target=db_monitor_thread, daemon=True).start()
    cam = CameraStream().start()
    take_photo = None

    while True:
        frame = cam.read()
        if frame is None: break

        # UI Overlay for status
        display_frame = frame.copy()
        status_text = "Session: Active" if active_session_id else "Session: IDLE"
        cv2.putText(display_frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow("Bottle Inspector", display_frame)
        
        key = cv2.waitKey(1) & 0xFF

        # Simulation Keys
        if key == ord('s'):
            if plc_connected: plc_client.write_register(11, 1)
            else: start_session_in_db(current_operator_id)
        if key == ord('d'):
            if plc_connected: plc_client.write_register(11, 0)
            else: stop_session_in_db()
        if key == ord('v'): take_photo = 1
        if key == ord('q'): break

        # Sync DB/PLC Session State
        if db_session_active and active_session_id != db_active_id:
            active_session_id = db_active_id
            if plc_connected: plc_client.write_register(11, 1)
        elif not db_session_active and active_session_id is not None:
            active_session_id = None
            if plc_connected: plc_client.write_register(11, 0)

        # Trigger logic
        mw10_value = 0
        if plc_connected:
            res = plc_client.read_holding_registers(address=10, count=1)
            if res and not res.isError(): mw10_value = res.registers[0]

        if (mw10_value == 1) or (take_photo is not None):
            if active_session_id is None:
                take_photo = None
            else:
                print("⚡ Triggered! Analyzing Bottle...")
                
                # --- INFERENCE STEP ---
                feat = extractor.extract_features(frame)
                
                # 1. Anomaly Detection (PatchCore)
                distances = pairwise_distances(feat.reshape(1, -1), memory_bank)
                score = float(distances.min())
                is_anomaly = score > threshold
                
                if not is_anomaly:
                    predicted_class = "Good"
                    status = "Accepted"
                    confidence = 100.0 # Standard for PatchCore OK
                else:
                    # 2. Defect Classification (Few-Shot)
                    min_dist = float('inf')
                    predicted_class = "Unknown"
                    for c_name, refs in class_features.items():
                        dists = pairwise_distances(feat.reshape(1, -1), refs)
                        d = dists.min()
                        if d < min_dist:
                            min_dist = d
                            predicted_class = c_name
                    status = "Defected"
                    confidence = 90.0 # Estimation
                
                print(f"📊 Result: {predicted_class} (Score: {score:.4f})")

                # Save to DB
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                img_path = os.path.join(OUTPUT_DIR, f"insp_{ts}.jpg")
                cv2.imwrite(img_path, frame)

                try:
                    db = SessionLocal()
                    new_insp = db_models.Inspection(
                        session_id=active_session_id,
                        status=status,
                        defect_category=predicted_class,
                        confidence=score, # Store raw score in confidence field
                        image_path=img_path
                    )
                    db.add(new_insp)
                    db.commit()
                    db.close()
                except Exception as e: print(f"❌ DB Log Error: {e}")

                # PLC Feedback
                if plc_connected:
                    if predicted_class == "Good": plc_client.write_register(0, 1) # Pass
                    else: plc_client.write_register(1, 1) # Reject
                    plc_client.write_register(10, 0) # Reset Trigger
                
                take_photo = None

    cam.stop()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
        plc_connected = True
    else:
        print(f"❌ PLC Connection Failed - Running in Simulation Mode")
        plc_connected = False

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"✅ MQTT Client Started. Broker: {MQTT_BROKER}")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

    db = SessionLocal()
    try:
        open_session = db.query(db_models.SystemSession).filter(
            db_models.SystemSession.end_time == None
        ).first()
        
        if open_session:
            active_session_id = open_session.id
            db_session_active = True
            db_active_id = open_session.id
            print(f"🔄 Restored Active Session: {active_session_id}")
        else:
            print("ℹ️ No active session found in DB.")
    except Exception as e:
        print(f"⚠️ Error checking DB for sessions: {e}")
    finally:
        db.close()

    run_ai_logic()