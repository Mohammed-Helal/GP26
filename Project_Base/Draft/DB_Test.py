from database import engine

try:
    connection = engine.connect()
    print("✅ Connection Successful! Database is ready.")
    connection.close()
except Exception as e:
    print(f"❌ Connection Failed: {e}")