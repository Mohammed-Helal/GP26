"""
Simu.py — محاكي ESP8266 عبر MQTT
يرسل بيانات سنسور وهمية (temperature, vibration, rpm, current)
ويستقبل الأوامر من السيرفر — كل ذلك عبر Mosquitto

تثبيت: pip install paho-mqtt
"""

import json
import time
import random
import threading
import paho.mqtt.client as mqtt

# ============================================================
# إعدادات
# ============================================================
MQTT_BROKER   = "localhost"
MQTT_PORT     = 1883
MQTT_USER     = ""
MQTT_PASSWORD = ""

TOPIC_SENSORS  = "factory/sensors"
TOPIC_COMMANDS = "factory/commands"
CLIENT_ID      = "esp8266_simulator"
PUBLISH_INTERVAL = 3  # ثوانٍ

# ============================================================
# استقبال الأوامر
# ============================================================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connected to MQTT broker {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(TOPIC_COMMANDS)
        print(f"📡 Listening for commands on '{TOPIC_COMMANDS}'\n")
    else:
        print(f"❌ Connection failed. Code: {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        command = payload.get("command", "")
        print(f"\n🎮 Command received: {command}")

        if command == "START":
            print("   ▶️  Motor STARTED (simulated)")
        elif command == "STOP":
            print("   ⏹️  Motor STOPPED (simulated)")
        elif command == "RESET":
            print("   🔄 System RESET (simulated)")
        elif command == "STATUS":
            print("   📋 Sending status immediately...")
            publish_once(client)
    except Exception as e:
        print(f"⚠️ Error handling command: {e}")

def on_disconnect(client, userdata, rc):
    print(f"⚠️ Disconnected (rc={rc})")

# ============================================================
# توليد بيانات وهمية واقعية
# ============================================================
def generate_sensor_data():
    temperature   = round(random.uniform(25.0, 95.0), 1)
    vibration     = round(random.uniform(0.001, 0.500), 3)
    rpm           = round(random.uniform(800, 3500))
    current_draw  = round(random.uniform(0.5, 5.0), 2)

    # حساب الحالة تلقائياً
    status = "OK"
    if temperature > 80 or current_draw > 4.5:
        status = "ERROR"
    elif temperature > 65 or vibration > 0.35:
        status = "WARNING"

    return {
        "temperature" : temperature,
        "vibration"   : vibration,
        "rpm"         : rpm,
        "current"     : current_draw,
        "status"      : status,
        "device"      : CLIENT_ID
    }

def publish_once(client):
    data    = generate_sensor_data()
    payload = json.dumps(data)
    result  = client.publish(TOPIC_SENSORS, payload)

    status_icon = {"OK": "🟢", "WARNING": "🟡", "ERROR": "🔴"}.get(data["status"], "⚪")
    print(
        f"{status_icon} Published → "
        f"Temp: {data['temperature']}°C | "
        f"Vib: {data['vibration']}g | "
        f"RPM: {data['rpm']} | "
        f"Current: {data['current']}A | "
        f"Status: {data['status']}"
    )
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        print(f"   ❌ Publish failed (rc={result.rc})")

# ============================================================
# Main
# ============================================================
def run_simulator():
    client = mqtt.Client(client_id=CLIENT_ID)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    print("🏭 ESP8266 MQTT Simulator Starting...")
    print(f"   Broker : {MQTT_BROKER}:{MQTT_PORT}")
    print(f"   Publish: every {PUBLISH_INTERVAL}s → {TOPIC_SENSORS}")
    print(f"   Listen : {TOPIC_COMMANDS}\n")

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"❌ Cannot connect to broker: {e}")
        print("💡 Make sure Mosquitto is running:")
        print("   Windows: net start mosquitto")
        print("   Linux:   sudo systemctl start mosquitto")
        return

    # تشغيل loop في Thread منفصل (لاستقبال الأوامر)
    client.loop_start()

    try:
        while True:
            publish_once(client)
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        print("\n👋 Simulator stopped.")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    run_simulator()
