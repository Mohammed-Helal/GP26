/*
 * ============================================================
 *  ESP8266 — Factory Sensor Node
 *  يرسل: temperature, vibration, RPM, current draw
 *  يستقبل: أوامر من السيرفر (START, STOP, RESET...)
 *
 *  المكتبات المطلوبة (ثبّتها من Arduino Library Manager):
 *    - ESP8266WiFi      (مدمجة مع بورد ESP8266)
 *    - PubSubClient     (Nick O'Leary)
 *    - ArduinoJson      (Benoit Blanchon) v6+
 * ============================================================
 */

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ============================================================
// ⚙️ إعدادات — عدّلها حسب بيئتك
// ============================================================
const char* WIFI_SSID     = "YOUR_WIFI_NAME";       // ← اسم الشبكة
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";   // ← كلمة المرور

const char* MQTT_BROKER   = "192.168.1.XX";         // ← IP الـ Laptop (شغّل ipconfig/ifconfig)
const int   MQTT_PORT     = 1883;
const char* MQTT_USER     = "";                     // ← فارغ لو Mosquitto بدون مصادقة
const char* MQTT_PASSWORD = "";

const char* CLIENT_ID      = "esp8266_factory_01";
const char* TOPIC_SENSORS  = "factory/sensors";    // نشر البيانات
const char* TOPIC_COMMANDS = "factory/commands";   // استقبال الأوامر

// ============================================================
// 📌 Pins — عدّلها حسب توصيلاتك
// ============================================================
// مثال: MPU6050 للاهتزاز → I2C (D1=SCL, D2=SDA)
// مثال: ACS712 للتيار   → A0
// مثال: Encoder للـ RPM → D5

const int CURRENT_PIN   = A0;   // ACS712 أو مقاوم شنت
const int RPM_PIN       = D5;   // مدخل رقمي لـ Encoder
const int LED_STATUS    = LED_BUILTIN;

// ============================================================
// 🔧 متغيرات عامة
// ============================================================
WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);

bool    motorRunning    = false;
float   temperature     = 0.0;
float   vibration       = 0.0;
float   rpm_value       = 0.0;
float   current_value   = 0.0;

volatile unsigned long pulseCount = 0;
unsigned long lastRpmTime         = 0;
unsigned long lastPublishTime     = 0;
const unsigned long PUBLISH_INTERVAL = 3000; // ms — إرسال كل 3 ثوانٍ

// ============================================================
// 📡 MQTT: استقبال الأوامر من السيرفر
// ============================================================
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg = "";
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  Serial.println("📨 Command received: " + msg);

  // تحليل JSON
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, msg);
  if (err) { Serial.println("⚠️ JSON parse error"); return; }

  String command = doc["command"] | "";

  if (command == "START") {
    motorRunning = true;
    digitalWrite(LED_STATUS, LOW); // LED ON (active low)
    Serial.println("▶️ Motor STARTED");
  }
  else if (command == "STOP") {
    motorRunning = false;
    digitalWrite(LED_STATUS, HIGH);
    Serial.println("⏹️ Motor STOPPED");
  }
  else if (command == "RESET") {
    motorRunning = false;
    pulseCount   = 0;
    Serial.println("🔄 System RESET");
    ESP.restart();
  }
  else if (command == "STATUS") {
    // ردّ فوري بالحالة الحالية
    publishSensors();
  }
}

// ============================================================
// 📶 الاتصال بـ WiFi
// ============================================================
void connectWiFi() {
  Serial.print("🔌 Connecting to WiFi: ");
  Serial.print(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi Connected! IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n❌ WiFi Failed! Restarting...");
    delay(3000);
    ESP.restart();
  }
}

// ============================================================
// 🔗 الاتصال بـ MQTT Broker
// ============================================================
void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("🔗 Connecting to MQTT broker...");

    bool connected = (strlen(MQTT_USER) > 0)
      ? mqttClient.connect(CLIENT_ID, MQTT_USER, MQTT_PASSWORD)
      : mqttClient.connect(CLIENT_ID);

    if (connected) {
      Serial.println(" ✅ Connected!");
      mqttClient.subscribe(TOPIC_COMMANDS);
      Serial.println("📡 Subscribed to: " + String(TOPIC_COMMANDS));
    } else {
      Serial.print(" ❌ Failed (rc=");
      Serial.print(mqttClient.state());
      Serial.println("). Retry in 5s...");
      delay(5000);
    }
  }
}

// ============================================================
// 📊 قراءة السنسورات
// ============================================================
float readTemperature() {
  // ← بدّل هذا لقراءة حقيقية من DHT22 أو DS18B20 أو NTC
  // مثال DHT22:
  //   return dht.readTemperature();
  // حالياً: قيمة وهمية للاختبار
  return 20.0 + (float)(random(0, 100)) / 10.0; // 20.0 → 29.9
}

float readVibration() {
  // ← بدّل لقراءة MPU6050 أو ADXL345
  // مثال بسيط باستخدام analogRead لسنسور اهتزاز SW-420:
  //   return (digitalRead(VIBRATION_PIN) == HIGH) ? 1.0 : 0.0;
  return (float)(random(0, 50)) / 100.0; // 0.00 → 0.49 g
}

float readRPM() {
  // حساب RPM من pulse count
  unsigned long now    = millis();
  unsigned long dt     = now - lastRpmTime;
  unsigned long pulses = pulseCount;
  pulseCount   = 0;
  lastRpmTime  = now;

  // RPM = (pulses / pulses_per_rev) / (dt/60000)
  // افتراض: 1 pulse = 1 دورة كاملة
  float rpm = (dt > 0) ? (pulses * 60000.0 / dt) : 0.0;
  return rpm;
}

float readCurrent() {
  // ACS712 — 5A module: Sensitivity = 185 mV/A
  // VCC = 3.3V على ESP8266 → ADC range 0-1023 = 0-1V (بعض البوردات)
  // عدّل الحسابات حسب موديل ACS712 عندك
  int raw = analogRead(CURRENT_PIN);
  float voltage = (raw / 1023.0) * 3.3;       // جهد المدخل
  float current = (voltage - 1.65) / 0.185;   // ACS712-5A
  return abs(current);
}

// ============================================================
// 📤 نشر البيانات عبر MQTT
// ============================================================
void publishSensors() {
  temperature   = readTemperature();
  vibration     = readVibration();
  rpm_value     = readRPM();
  current_value = readCurrent();

  // تحديد الحالة تلقائياً
  String status = "OK";
  if (temperature > 80.0)  status = "WARNING";
  if (temperature > 100.0) status = "ERROR";
  if (vibration   > 0.4)   status = "WARNING";
  if (current_value > 4.5) status = "ERROR";

  // بناء JSON
  StaticJsonDocument<256> doc;
  doc["temperature"] = round(temperature * 10) / 10.0;
  doc["vibration"]   = round(vibration   * 1000) / 1000.0;
  doc["rpm"]         = round(rpm_value);
  doc["current"]     = round(current_value * 100) / 100.0;
  doc["status"]      = status;
  doc["device"]      = CLIENT_ID;

  char buffer[256];
  serializeJson(doc, buffer);

  bool ok = mqttClient.publish(TOPIC_SENSORS, buffer);
  Serial.println(ok ? "✅ Published: " + String(buffer)
                    : "❌ Publish failed");
}

// ============================================================
// Interrupt للـ RPM encoder
// ============================================================
ICACHE_RAM_ATTR void onEncoderPulse() {
  pulseCount++;
}

// ============================================================
// Setup & Loop
// ============================================================
void setup() {
  Serial.begin(115200);
  Serial.println("\n🚀 ESP8266 Factory Node Starting...");

  pinMode(LED_STATUS, OUTPUT);
  digitalWrite(LED_STATUS, HIGH); // LED OFF

  // Interrupt للـ RPM
  pinMode(RPM_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(RPM_PIN), onEncoderPulse, RISING);

  connectWiFi();

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMqttMessage);
  mqttClient.setKeepAlive(60);
  mqttClient.setBufferSize(512);

  connectMQTT();
  lastRpmTime = millis();

  Serial.println("✅ Setup complete. Publishing every " + String(PUBLISH_INTERVAL/1000) + "s");
}

void loop() {
  // إعادة الاتصال لو انقطع
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop(); // معالجة الرسائل الواردة (الأوامر)

  // نشر البيانات بشكل دوري
  unsigned long now = millis();
  if (now - lastPublishTime >= PUBLISH_INTERVAL) {
    lastPublishTime = now;
    publishSensors();
  }
}
