from PIL import Image
import cv2
import numpy as np
import tensorflow as tf
from tensorflow.keras.applications.efficientnet import preprocess_input

# ============================================================
# CONFIGURATION
# ============================================================

MODEL_PATH  = r"Project_Base/bottle_model.h5"  
CLASS_NAMES = ['Broken', 'Good', 'Label', 'Scratch']  

# ============================================================
# LOAD MODEL
# ============================================================

print("Loading model...")
model = tf.keras.models.load_model(MODEL_PATH)
print("✅ Model loaded successfully!")
print(f"✅ Classes: {CLASS_NAMES}")

# ============================================================
# CAMERA SETUP
# ============================================================

cap = cv2.VideoCapture(1)

if not cap.isOpened():
    print("Error: Could not open camera")
    exit()

print("\n🍾 Bottle Classifier Ready!")
print("Press 'c' to capture and classify")
print("Press 'q' to quit")
print("=" * 50)

while True:
    ret, frame = cap.read()

    if not ret:
        print("Failed to grab frame")
        break

    cv2.imshow('Bottle Classifier - Press C to classify, Q to quit', frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('c'):
        print("\n🔍 Classifying...")

        # Preprocess
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (224, 224))
        img = np.expand_dims(img, axis=0)
        img = preprocess_input(img)

        # Predict
        predictions = model.predict(img, verbose=0)[0]
        predicted_idx   = np.argmax(predictions)
        predicted_class = CLASS_NAMES[predicted_idx]
        confidence      = predictions[predicted_idx] * 100

        # Print results
        print("=" * 50)
        print(f"🍾 Result: {predicted_class.upper()}")
        print(f"📊 Confidence: {confidence:.2f}%")
        print("📊 Details:")
        for i, class_name in enumerate(CLASS_NAMES):
            print(f"   {class_name}: {predictions[i]*100:.2f}%")
        print("=" * 50)

    elif key == ord('q'):
        print("\n👋 Closing...")
        break

cap.release()
cv2.destroyAllWindows()
print("✅ Done!")