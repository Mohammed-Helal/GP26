import json, os, cv2, torch, time
from datetime import datetime
from threading import Thread
from PIL import Image
from pymodbus.client import ModbusTcpClient
import uvicorn
from fastapi import FastAPI
import requests

import models
from database import SessionLocal

# ==========================================
# Configurations
# ==========================================
PLC_IP = "192.168.1.200"
PLC_PORT = 502
MODEL_PATH = "banana_classifier_final"
OUTPUT_DIR = "banana_classifications"
CLOUD_API = "https://gp26-ckys.onrender.com"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Global Variables
active_session_id = None
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

# ==========================================
# Local FastAPI (PLC Commands)
# ==========================================
local_app = FastAPI(title="Local PLC API")

@local_app.post("/plc-start")
def plc_start(session_id: int):
    global active_session_id
    try:
        active_session_id = session_id
        plc_client.write_register(11, 1)
        print(f"✅ PLC Start Signal Sent. Session: {session_id}")
        return {"message": "PLC Start Signal Sent"}
    except Exception as e:
        print(f"❌ PLC Error: {e}")
        return {"error": str(e)}

@local_app.post("/plc-stop")
def plc_stop():
    global active_session_id
    try:
        active_session_id = None
        plc_client.write_register(12, 1)
        print("🏁 PLC Stop Signal Sent.")
        return {"message": "PLC Stop Signal Sent"}
    except Exception as e:
        print(f"❌ PLC Error: {e}")
        return {"error": str(e)}

@local_app.get("/status")
def status():
    return {
        "plc_connected": plc_client.is_socket_open(),
        "active_session": active_session_id
    }

# ==========================================
# AI Logic
# ==========================================
def run_ai_logic():
    global active_session_id
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

    cap = cv2.VideoCapture(0)
    previous_sensor_value = None

    print("📸 Camera Stream Started. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Cannot read from camera")
            break

        cv2.imshow("System - Live Feed", frame)
        key = cv2.waitKey(1) & 0xFF

        try:
            # Trigger on register 10
            response = plc_client.read_holding_registers(10, count=1)
            if not response.isError():
                current_sensor_value = response.registers[0]

                if (previous_sensor_value == 1 and current_sensor_value == 0) or (key == ord('a')):
                    if active_session_id is None:
                        print("⚠️ No active session, skipping.")
                    else:
                        print("⚡ Sensor Triggered! Classifying...")

                        # Process image
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(rgb_frame)
                        inputs = preprocessor(images=img, return_tensors="pt")

                        with torch.no_grad():
                            outputs = model(**inputs)

                        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
                        pred_idx = outputs.logits.argmax(-1).item()
                        label = model.config.id2label[pred_idx]
                        conf = probs[pred_idx].item() * 100

                        # Save image
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        img_path = os.path.join(OUTPUT_DIR, f"product_{ts}.jpg")
                        cv2.imwrite(img_path, frame)

                        # Save to DB
                        db = SessionLocal()
                        new_insp = models.Inspection(
                            session_id=active_session_id,
                            status=label,
                            confidence=conf,
                            image_path=img_path
                        )
                        db.add(new_insp)
                        db.commit()
                        print(f"📊 Result Saved! Status: {label} | Confidence: {conf:.2f}%")
                        db.close()

                        # Send command to PLC
                        if label.lower() == "fresh":
                            plc_client.write_register(0, 1)
                            print("✅ Command: PASS")
                        else:
                            plc_client.write_register(1, 1)
                            print("❌ Command: REJECT")

                previous_sensor_value = current_sensor_value

        except Exception as e:
            pass

        if key == ord('q'):
            break

        time.sleep(0.05)

    cap.release()
    cv2.destroyAllWindows()

# ==========================================
# Main
# ==========================================
if __name__ == "__main__":
    # Connect PLC
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
    else:
        print(f"❌ PLC Connection Failed at {PLC_IP}")

    # Start Local API in background thread
    Thread(
        target=lambda: uvicorn.run(local_app, host="0.0.0.0", port=8001),
        daemon=True
    ).start()
    print("✅ Local API Started on port 8001")

    # Start AI Logic
    run_ai_logic()