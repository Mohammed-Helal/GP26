# from fastapi import FastAPI, Depends
# from pydantic import BaseModel
# from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import sessionmaker, Session
# from datetime import datetime
# from fastapi.responses import StreamingResponse
# import cv2 # سنحتاجها فقط لو أردنا أن يقوم السيرفر بفتح الكاميرا بنفسه

# # 1. Database Configuration (SQLite)
# DATABASE_URL = "sqlite:///./production.db"
# engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# # 2. Database Model (Table Structure)
# class ProductRecord(Base):
#     __tablename__ = "products"
#     id = Column(Integer, primary_key=True, index=True)
#     status = Column(String)
#     confidence = Column(Float)
#     timestamp = Column(DateTime, default=datetime.now)

# # Create the database file
# Base.metadata.create_all(bind=engine)

# app = FastAPI()

# # Data Validation Model (Pydantic)
# class ProductCreate(BaseModel):
#     status: str
#     confidence: float

# # Dependency to get DB session
# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()

# # 3. API Endpoints
# @app.post("/api/products")
# async def receive_product(product: ProductCreate, db: Session = Depends(get_db)):
#     new_record = ProductRecord(status=product.status, confidence=product.confidence)
#     db.add(new_record)
#     db.commit()
#     db.refresh(new_record)
#     print(f"🚀 Received: {product.status} with {product.confidence}% confidence")
#     return {"message": "Data saved to SQLite", "id": new_record.id}

# @app.get("/api/products")
# async def get_products(db: Session = Depends(get_db)):
#     return db.query(ProductRecord).order_by(ProductRecord.timestamp.desc()).all()

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)



import cv2
import sqlite3
from fastapi import FastAPI, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime

# --- 1. إعدادات قاعدة البيانات (Database Configuration) ---
DATABASE_URL = "postgresql://postgres:123456@localhost:5432/Test_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# تعريف جدول المنتجات
class ProductRecord(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String)
    confidence = Column(Float)
    timestamp = Column(DateTime, default=datetime.now)

# إنشاء ملف الداتا بيز والجدول
Base.metadata.create_all(bind=engine)

# --- 2. إعدادات FastAPI و Pydantic ---
app = FastAPI()

class ProductCreate(BaseModel):
    status: str
    confidence: float

# وظيفة للحصول على جلسة الداتا بيز وقفلها تلقائياً
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 3. معالجة الفيديو (Video Streaming Logic) ---
def gen_frames():
    camera = cv2.VideoCapture(0) # فتح كاميرا لابتوب Dell (رقم 0)
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # رسم "مربع وهمي" يمثل منطقة فحص المنتج
            cv2.rectangle(frame, (150, 100), (500, 400), (0, 255, 0), 2)
            cv2.putText(frame, "AI SCANNER", (160, 90), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # تحويل الصورة إلى بايتات JPEG للبث
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            # بروتوكول البث المستمر
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# --- 4. العناوين (API Endpoints) ---

# صفحة الويب الرئيسية (Dashboard)
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Factory Monitor</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #1a1a1a; color: white; text-align: center; }
            .main-container { display: flex; justify-content: space-around; padding: 20px; }
            .video-section { background: #2d2d2d; padding: 15px; border-radius: 15px; border: 2px solid #4CAF50; }
            .data-section { width: 40%; background: #2d2d2d; padding: 15px; border-radius: 15px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; color: white; }
            th, td { border: 1px solid #444; padding: 10px; }
            th { background-color: #4CAF50; }
            .fresh { color: #4eff4e; font-weight: bold; }
            .defective { color: #ff4e4e; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>🏭 Industrial Quality Control</h1>
        <div class="main-container">
            <div class="video-section">
                <h3>Live Camera Feed</h3>
                <img src="/video_feed" width="600">
            </div>
            <div class="data-section">
                <h3>Production Log (Last 10 Items)</h3>
                <table id="logTable">
                    <thead>
                        <tr><th>ID</th><th>Status</th><th>Confidence</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
        <script>
            async function updateData() {
                const response = await fetch('/api/products');
                const data = await response.json();
                const tbody = document.querySelector('#logTable tbody');
                tbody.innerHTML = '';
                data.slice(0, 10).forEach(item => {
                    const row = `<tr>
                        <td>${item.id}</td>
                        <td class="${item.status.toLowerCase()}">${item.status}</td>
                        <td>${item.confidence}%</td>
                    </tr>`;
                    tbody.insertAdjacentHTML('beforeend', row);
                });
            }
            setInterval(updateData, 2000); // تحديث كل ثانيتين
        </script>
    </body>
    </html>
    """

# بث الفيديو
@app.get("/video_feed")
async def video_feed_endpoint():
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

# استقبال البيانات من بايثون أو الـ ESP
@app.post("/api/products")
async def add_product(item: ProductCreate, db: Session = Depends(get_db)):
    new_product = ProductRecord(status=item.status, confidence=item.confidence)
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return {"status": "success", "id": new_product.id}

# جلب البيانات لعرضها في الجدول
@app.get("/api/products")
async def get_all_products(db: Session = Depends(get_db)):
    return db.query(ProductRecord).order_by(ProductRecord.timestamp.desc()).all()

# تشغيل السيرفر
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# open that in Browser http://127.0.0.1:8000/