import os, cv2, torch, time
from datetime import datetime
from PIL import Image
from pymodbus.client import ModbusTcpClient
import requests  # ← بيتكلم مع الـ Cloud API

import models
from database import SessionLocal

PLC_IP = "192.168.1.200"
PLC_PORT = 502
MODEL_PATH = "banana_classifier_final"
OUTPUT_DIR = "banana_classifications"
CLOUD_API = "http://localhost:8000"  # ← غيّره لـ Render URL لما ترفع

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

active_session_id = None
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

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

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        cv2.imshow("System - Live Feed", frame)
        key = cv2.waitKey(1) & 0xFF

        try:
            # Start session from PLC
            start_response = plc_client.read_holding_registers(11, count=1)
            if not start_response.isError():
                if start_response.registers[0] == 1 and active_session_id is None:
                    res = requests.post(f"{CLOUD_API}/start-session")
                    if res.status_code == 200:
                        active_session_id = res.json()["session_id"]
                        print(f"🆕 Session Started: {active_session_id}")

            # Stop session from PLC
            stop_response = plc_client.read_holding_registers(12, count=1)
            if not stop_response.isError():
                if stop_response.registers[0] == 1 and active_session_id is not None:
                    requests.post(f"{CLOUD_API}/stop-session")
                    active_session_id = None
                    print("🏁 Session Stopped.")

            # Trigger
            response = plc_client.read_holding_registers(10, count=1)
            if not response.isError():
                current_sensor_value = response.registers[0]
                if (previous_sensor_value == 1 and current_sensor_value == 0) or (key == ord('a')):
                    if active_session_id is None:
                        print("⚠️ No active session, skipping.")
                    else:
                        print("⚡ Classifying...")
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(rgb_frame)
                        inputs = preprocessor(images=img, return_tensors="pt")
                        with torch.no_grad():
                            outputs = model(**inputs)
                        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
                        pred_idx = outputs.logits.argmax(-1).item()
                        label = model.config.id2label[pred_idx]
                        conf = probs[pred_idx].item() * 100

                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        img_path = os.path.join(OUTPUT_DIR, f"product_{ts}.jpg")
                        cv2.imwrite(img_path, frame)

                        # حفظ في الداتا بيز مباشرة
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
                        print(f"📊 {label} | {conf:.2f}%")

                        if label.lower() == "fresh":
                            plc_client.write_register(0, 1)
                        else:
                            plc_client.write_register(1, 1)

                previous_sensor_value = current_sensor_value

        except Exception as e:
            pass

        if key == ord('q'):
            break

        time.sleep(0.05)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
    else:
        print(f"❌ PLC Connection Failed")
    run_ai_logic()