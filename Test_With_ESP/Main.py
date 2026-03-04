import cv2
import json
import threading
import paho.mqtt.client as mqtt
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from contextlib import asynccontextmanager

# ============================================================
# 1. إعدادات MQTT
# ============================================================
MQTT_BROKER   = "localhost"   # ← عدّل لو IP البروكر مختلف
MQTT_PORT     = 1883
MQTT_USER     = ""            # ← أضف يوزر/باسورد لو ضبطت Mosquitto بأمان
MQTT_PASSWORD = ""

# Topics
TOPIC_SENSORS  = "factory/sensors"   # ESP يرسل  → هنا
TOPIC_COMMANDS = "factory/commands"  # السيرفر يرسل أوامر → ESP

# ============================================================
# 2. إعدادات قاعدة البيانات
# ============================================================
DATABASE_URL = "sqlite:///./production.db"
engine       = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()

class SensorRecord(Base):
    __tablename__ = "sensors"
    id          = Column(Integer, primary_key=True, index=True)
    temperature = Column(Float,  default=0.0)
    vibration   = Column(Float,  default=0.0)
    rpm         = Column(Float,  default=0.0)
    current     = Column(Float,  default=0.0)
    status      = Column(String, default="OK")
    timestamp   = Column(DateTime, default=datetime.now)

Base.metadata.create_all(bind=engine)

# ============================================================
# 3. MQTT Client (يعمل في Thread منفصل)
# ============================================================
mqtt_client   = mqtt.Client(client_id="factory_server")
latest_data   = {}   # آخر قراءة للعرض الفوري في الـ Dashboard

def save_to_db(data: dict):
    """حفظ البيانات القادمة من MQTT في SQLite"""
    db = SessionLocal()
    try:
        record = SensorRecord(
            temperature = data.get("temperature", 0.0),
            vibration   = data.get("vibration",   0.0),
            rpm         = data.get("rpm",          0.0),
            current     = data.get("current",      0.0),
            status      = data.get("status",       "OK"),
        )
        db.add(record)
        db.commit()
        print(f"💾 Saved: {data}")
    except Exception as e:
        print(f"❌ DB Error: {e}")
    finally:
        db.close()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ MQTT Connected to {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC_SENSORS)
        print(f"📡 Subscribed to '{TOPIC_SENSORS}'")
    else:
        print(f"❌ MQTT Connection failed. Code: {rc}")

def on_message(client, userdata, msg):
    global latest_data
    try:
        payload = json.loads(msg.payload.decode())
        print(f"📨 Received on '{msg.topic}': {payload}")
        latest_data = payload
        save_to_db(payload)
    except json.JSONDecodeError:
        print(f"⚠️ Invalid JSON: {msg.payload}")

def on_disconnect(client, userdata, rc):
    print(f"⚠️ MQTT Disconnected (rc={rc}). Reconnecting...")

mqtt_client.on_connect    = on_connect
mqtt_client.on_message    = on_message
mqtt_client.on_disconnect = on_disconnect

if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

def start_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"❌ MQTT Error: {e}")

# ============================================================
# 4. FastAPI App
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # تشغيل MQTT في Thread منفصل عند بدء السيرفر
    t = threading.Thread(target=start_mqtt, daemon=True)
    t.start()
    print("🚀 MQTT Thread started")
    yield
    mqtt_client.disconnect()

app = FastAPI(lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================
# 5. Video Streaming
# ============================================================
def gen_frames():
    camera = cv2.VideoCapture(0)
    while True:
        success, frame = camera.read()
        if not success:
            break
        cv2.rectangle(frame, (150, 100), (500, 400), (0, 255, 0), 2)
        cv2.putText(frame, "AI SCANNER", (160, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# ============================================================
# 6. API Endpoints
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Factory Monitor</title>
        <meta charset="utf-8">
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #1a1a1a; color: white; text-align: center; margin:0; padding:10px; }
            h1   { color: #4CAF50; }
            .main-container { display: flex; justify-content: space-around; flex-wrap: wrap; padding: 20px; gap: 20px; }
            .video-section  { background: #2d2d2d; padding: 15px; border-radius: 15px; border: 2px solid #4CAF50; }
            .data-section   { flex: 1; min-width: 320px; background: #2d2d2d; padding: 15px; border-radius: 15px; }
            .live-section   { background: #2d2d2d; padding: 15px; border-radius: 15px; width: 100%; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; color: white; }
            th, td { border: 1px solid #444; padding: 10px; }
            th { background-color: #4CAF50; }
            .ok      { color: #4eff4e; font-weight: bold; }
            .warning { color: #ffaa00; font-weight: bold; }
            .error   { color: #ff4e4e; font-weight: bold; }
            .sensor-card { display:inline-block; background:#3a3a3a; border-radius:10px; padding:15px 25px; margin:8px; min-width:140px; }
            .sensor-card span { display:block; font-size:28px; font-weight:bold; color:#4CAF50; }
            .sensor-card label { font-size:12px; color:#aaa; }
            .btn { padding:10px 20px; margin:5px; border:none; border-radius:8px; cursor:pointer; font-size:14px; font-weight:bold; }
            .btn-green  { background:#4CAF50; color:white; }
            .btn-red    { background:#f44336; color:white; }
            .btn-yellow { background:#ff9800; color:white; }
        </style>
    </head>
    <body>
        <h1>🏭 Industrial Quality Control - MQTT Dashboard</h1>

        <!-- Live Sensor Data -->
        <div class="live-section" style="margin-bottom:20px;">
            <h3>📡 Live Sensor Readings (from ESP8266)</h3>
            <div>
                <div class="sensor-card"><span id="temp">--</span><label>🌡️ Temperature °C</label></div>
                <div class="sensor-card"><span id="vib">--</span><label>📳 Vibration (g)</label></div>
                <div class="sensor-card"><span id="rpm">--</span><label>⚙️ RPM</label></div>
                <div class="sensor-card"><span id="cur">--</span><label>⚡ Current (A)</label></div>
                <div class="sensor-card"><span id="stat">--</span><label>🔍 Status</label></div>
            </div>
        </div>

        <!-- Commands Panel -->
        <div class="live-section" style="margin-bottom:20px;">
            <h3>🎮 Send Commands to ESP8266</h3>
            <button class="btn btn-green"  onclick="sendCmd('START')">▶️ START Motor</button>
            <button class="btn btn-red"    onclick="sendCmd('STOP')">⏹️ STOP Motor</button>
            <button class="btn btn-yellow" onclick="sendCmd('RESET')">🔄 RESET</button>
            <button class="btn" style="background:#2196F3;color:white;" onclick="sendCmd('STATUS')">📋 Get Status</button>
            <p id="cmdResult" style="color:#aaa; font-size:13px;"></p>
        </div>

        <div class="main-container">
            <div class="video-section">
                <h3>📷 Live Camera Feed</h3>
                <img src="/video_feed" width="560">
            </div>
            <div class="data-section">
                <h3>📊 Sensor Log (Last 10)</h3>
                <table id="logTable">
                    <thead>
                        <tr><th>#</th><th>Temp</th><th>Vib</th><th>RPM</th><th>Current</th><th>Status</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>

        <script>
            async function updateLive() {
                try {
                    const r = await fetch('/api/live');
                    const d = await r.json();
                    if (d.temperature !== undefined) {
                        document.getElementById('temp').textContent = d.temperature.toFixed(1);
                        document.getElementById('vib').textContent  = d.vibration.toFixed(3);
                        document.getElementById('rpm').textContent  = d.rpm.toFixed(0);
                        document.getElementById('cur').textContent  = d.current.toFixed(2);
                        document.getElementById('stat').textContent = d.status;
                    }
                } catch(e) {}
            }

            async function updateTable() {
                try {
                    const r = await fetch('/api/sensors');
                    const data = await r.json();
                    const tbody = document.querySelector('#logTable tbody');
                    tbody.innerHTML = '';
                    data.slice(0, 10).forEach(item => {
                        const cls = item.status === 'OK' ? 'ok' : (item.status === 'WARNING' ? 'warning' : 'error');
                        tbody.insertAdjacentHTML('beforeend', `<tr>
                            <td>${item.id}</td>
                            <td>${item.temperature}°C</td>
                            <td>${item.vibration}g</td>
                            <td>${item.rpm}</td>
                            <td>${item.current}A</td>
                            <td class="${cls}">${item.status}</td>
                        </tr>`);
                    });
                } catch(e) {}
            }

            async function sendCmd(cmd) {
                const r = await fetch('/api/command', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command: cmd})
                });
                const d = await r.json();
                document.getElementById('cmdResult').textContent = '✅ Sent: ' + cmd + ' → ' + d.topic;
            }

            setInterval(updateLive,  1000);
            setInterval(updateTable, 3000);
        </script>
    </body>
    </html>
    """

@app.get("/video_feed")
async def video_feed_endpoint():
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/live")
async def get_live():
    """أحدث قراءة استُقبلت من MQTT"""
    return latest_data if latest_data else {"message": "No data yet"}

@app.get("/api/sensors")
async def get_sensors(db: Session = Depends(get_db)):
    """جميع السجلات من الداتا بيز"""
    return db.query(SensorRecord).order_by(SensorRecord.timestamp.desc()).all()

class CommandModel(BaseModel):
    command: str   # مثل: "START", "STOP", "RESET"

@app.post("/api/command")
async def send_command(cmd: CommandModel):
    """إرسال أمر للـ ESP8266 عبر MQTT"""
    payload = json.dumps({"command": cmd.command, "timestamp": str(datetime.now())})
    mqtt_client.publish(TOPIC_COMMANDS, payload)
    print(f"📤 Command sent: {cmd.command} → {TOPIC_COMMANDS}")
    return {"status": "sent", "command": cmd.command, "topic": TOPIC_COMMANDS}

# ============================================================
# 7. تشغيل السيرفر
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# افتح المتصفح على: http://127.0.0.1:8000/
