import requests
import time
import random

# Server URL (FastAPI default port is 8000)
URL = "http://localhost:8000/api/products"

def run_factory_sim():
    print("🏭 Factory Simulator is running...")
    while True:
        # Simulate AI Detection
        status = random.choice(["Fresh", "Defective"])
        confidence = round(random.uniform(90.0, 99.9), 2)
        
        payload = {
            "status": status,
            "confidence": confidence
        }
        
        try:
            response = requests.post(URL, json=payload)
            if response.status_code == 200:
                print(f"✅ Sent to Backend: {status} ({confidence}%)")
            else:
                print(f"❌ Server Error: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Connection Error: {e}")
            
        time.sleep(5)

if __name__ == "__main__":
    run_factory_sim()