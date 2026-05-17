#include <ModbusRTUSlave.h>

/* * Hardware Connections:
 * RS485 Module (MAX485): RO -> RX, DI -> TX, DE & RE -> Pin 3
 * Proximity Sensor: Pin 4 (Input)
 * Relay/Mechanism: Pin 5 (Output)
 */

const int dePin = 3;       // Driver Enable pin for RS485 communication
const int sensorPin = 4;   // Sensor to detect glass bottle arrival
const int actuatorPin = 5; // Relay to trigger sorting mechanism

// Holding Registers Array
// index 0: Sensor Status -> PLC reads this (0 = No bottle, 1 = Bottle detected)
// index 1: Sorting Decision -> PLC writes to this (0 = Keep, 1 = Reject)
uint16_t holdingRegisters[2] = {0, 0};

// Initialize Modbus object on the default Hardware Serial
ModbusRTUSlave modbus(Serial);

void setup() {
  pinMode(dePin, OUTPUT);
  pinMode(sensorPin, INPUT);
  pinMode(actuatorPin, OUTPUT);

  // Industrial Standard Config: 19200 Baud, Even Parity (8E1)
  // This must match your Schneider PLC Serial Port settings exactly
  Serial.begin(19200, SERIAL_8E1);
  
  // Link the array to Modbus Holding Registers
  modbus.configureHoldingRegisters(holdingRegisters, 2);
  
  // Start as Slave with ID: 1
  modbus.begin(1, 19200);
}

void loop() {
  // --- STEP 1: Update Sensor Data for PLC ---
  // If the local sensor sees a bottle, we set Register 0 to 1
  if (digitalRead(sensorPin) == HIGH) {
    holdingRegisters[100] = 1; 
  } else {
    holdingRegisters[100] = 0;
  }

  // --- STEP 2: Communication Handling ---
  // Put MAX485 in Receive Mode to listen for PLC requests
  digitalWrite(dePin, LOW); 
  
  // Process incoming Modbus requests (Read/Write)
  modbus.poll();

  // --- STEP 3: Execute Sorting Decision from PLC ---
  // If the PLC (via YOLO analysis) wrote '1' to Register 1:
  if (holdingRegisters[1] == 1) {
    digitalWrite(actuatorPin, HIGH); // Activate Relay/Mechanism
    delay(500);                      // Duration of the mechanical movement
    digitalWrite(actuatorPin, LOW);  // Reset Mechanism
    
    // Clear the register so we don't trigger again for the same bottle
    holdingRegisters[1] = 0;         
  }
}