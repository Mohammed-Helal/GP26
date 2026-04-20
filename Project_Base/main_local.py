import os, cv2, torch, time
from datetime import datetime
from threading import Thread
from PIL import Image
from pymodbus.client import ModbusTcpClient

import models
from database import SessionLocal

# ==========================================
# Configurations
# ==========================================
PLC_IP = "192.168.1.200"
PLC_PORT = 502
MODEL_PATH = "Project_Base/banana_classifier_final"
OUTPUT_DIR = "banana_classifications"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Global Variables
active_session_id = None
plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)

# ==========================================
# Helper: Start Session in DB
# ==========================================
def start_session_in_db():
    """Create a new session in the database"""
    global active_session_id
    try:
        db = SessionLocal()
        # Check if there's already an open session
        open_session = db.query(models.SystemSession).filter(
            models.SystemSession.end_time == None
        ).first()
        if open_session:
            print(f"⚠️ Session already exists in DB: {open_session.id}")
            active_session_id = open_session.id
            db.close()
            return open_session.id

        # Create new session
        new_s = models.SystemSession(
            operator_id=1,
            start_time=datetime.now()
        )
        db.add(new_s)
        db.commit()
        db.refresh(new_s)
        active_session_id = new_s.id
        db.close()
        print(f"🆕 New Session Created in DB: {active_session_id}")
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
            print(f"🏁 Session {active_session_id} Closed in DB.")
        db.close()
        active_session_id = None
    except Exception as e:
        print(f"❌ DB Error while stopping session: {e}")

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
    previous_mw10_value = None
    last_db_check = time.time()
    take_photo = None

    print("📸 Camera Stream Started.")
    print("💡 Press 's' to simulate MW11=1 (Start Session)")
    print("💡 Press 'd' to simulate MW11=0 (Stop Session)")
    print("💡 Press 'q' to quit")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Cannot read from camera")
            break

        cv2.imshow("System - Live Feed", frame)
        key = cv2.waitKey(1) & 0xFF

        # ==========================================
        # Keyboard simulation for testing
        # ==========================================
        if key == ord('s'):
            plc_client.write_register(11, 1)
            print("🔑 Key 's' pressed → MW11 = 1")

        if key == ord('d'):
            plc_client.write_register(11, 0)
            print("🔑 Key 'd' pressed → MW11 = 0")

        if key == ord('v'):
            take_photo = 1
            print("take_photo")

        try:
            # ==========================================
            # Check DB every 0.5 seconds
            # ==========================================
            if time.time() - last_db_check >= 0.5:
                db = SessionLocal()
                open_session = db.query(models.SystemSession).filter(
                    models.SystemSession.end_time == None
                ).first()
                db.close()
                last_db_check = time.time()

                # New session detected in DB → start PLC
                if open_session and active_session_id != open_session.id:
                    active_session_id = open_session.id
                    plc_client.write_register(11, 1)
                    print(f"🆕 Session {active_session_id} detected in DB → MW11 = 1 → PLC Started")

                # Session ended in DB → stop PLC
                elif not open_session and active_session_id is not None:
                    active_session_id = None
                    plc_client.write_register(11, 0)
                    print("🏁 Session ended in DB → MW11 = 0 → PLC Stopped")

            # ==========================================
            # Read MW11 from PLC
            # ==========================================
            mw11_response = plc_client.read_holding_registers(11, count=1)
            if mw11_response and not mw11_response.isError():
                mw11_value = mw11_response.registers[0]
            else:
                print("PLC not connected")

            # MW11 = 1 and no active session → Start session
            if mw11_value == 1 and active_session_id is None:
                print("📡 MW11 = 1 detected → Starting Session...")
                start_session_in_db()

            # MW11 = 0 and session is active → Stop session
            elif mw11_value == 0 and active_session_id is not None:
                print("📡 MW11 = 0 detected → Stopping Session...")
                stop_session_in_db()

            # ==========================================
            # Read MW10 - Product Detection Trigger
            # ==========================================
            mw10_response = plc_client.read_holding_registers(10, count=1)
            if mw10_response and not mw10_response.isError():
                mw10_value = mw10_response.registers[0]
                print(f"MW10_Value = {mw10_value}")

                # Trigger when MW10 goes from 0 to 1
                if mw10_value == 1 and previous_mw10_value == 0 or take_photo is not None:
                    if active_session_id is None:
                        print("⚠️ MW10 triggered but no active session, skipping.")
                    else:
                        print("⚡ MW10 = 1 detected! Product detected, Classifying...")

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
                        print(f"🤖 AI Result: {label} | Confidence: {conf:.2f}%")

                        # Save image locally
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        img_path = os.path.join(OUTPUT_DIR, f"product_{ts}.jpg")
                        cv2.imwrite(img_path, frame)
                        print(f"🖼️ Image Saved: {img_path}")

                        # Save inspection to DB
                        db = SessionLocal()
                        new_insp = models.Inspection(
                            session_id=active_session_id,
                            status=label,
                            confidence=conf,
                            image_path=img_path
                        )
                        db.add(new_insp)
                        db.commit()
                        print(f"📊 Inspection Saved to DB! Session: {active_session_id} | Status: {label}")
                        db.close()
                        take_photo = None

                        # Send pass/reject command to PLC
                        if label.lower() == "fresh":
                            plc_client.write_register(0, 1)
                            print("✅ Command Sent to PLC: PASS")
                        else:
                            plc_client.write_register(1, 1)
                            print("❌ Command Sent to PLC: REJECT")

                previous_mw10_value = mw10_value

        except Exception as e:
            # Continue loop despite connection errors
            pass

        # 'q' key → quit
        if key == ord('q'):
            print("👋 Quitting...")
            break

        time.sleep(0.05)

    cap.release()
    cv2.destroyAllWindows()

# ==========================================
# Main
# ==========================================
if __name__ == "__main__":
    # Connect to PLC
    if plc_client.connect():
        print(f"✅ Connected to PLC at {PLC_IP}")
    else:
        print(f"❌ PLC Connection Failed at {PLC_IP} - Running without PLC")

    # Restore session if app was restarted
    db = SessionLocal()
    open_session = db.query(models.SystemSession).filter(
        models.SystemSession.end_time == None
    ).first()
    if open_session:
        active_session_id = open_session.id
        print(f"🔄 Restored Active Session from DB: {active_session_id}")
    else:
        print("ℹ️ No active session found in DB.")
    db.close()

    # Start AI Logic
    run_ai_logic()
