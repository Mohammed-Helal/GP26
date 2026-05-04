import requests
import time
import random

# Server URL (Check the port number from your terminal when running dotnet run)
URL = "http://localhost:5206/api/products" 

def start_simulator():
    print("🚀 Factory Simulator Started...")
    
    while True:
        # Generate random test data
        status_options = ["Fresh", "Defective"]
        current_status = random.choice(status_options)
        accuracy = round(random.uniform(88.0, 99.9), 2)

        # JSON Payload matching the C# Model
        payload = {
            "Status": current_status,
            "Confidence": accuracy
        }

        try:
            # Send HTTP POST request
            response = requests.post(URL, json=payload)
            
            if response.status_code == 200:
                print(f"✅ Success: {current_status} ({accuracy}%)")
                print(f"💬 Server Response: {response.json()}")
            else:
                print(f"❌ Failed: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"⚠️ Connection Error: {e}")

        # Wait 5 seconds for the next simulated product
        time.sleep(5)

if __name__ == "__main__":
    start_simulator()