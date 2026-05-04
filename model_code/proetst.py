from transformers import AutoImageProcessor, AutoModelForImageClassification
from PIL import Image
import cv2

# Load the model and preprocessor
print("Loading model...")
preprocessor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
model = AutoModelForImageClassification.from_pretrained("microsoft/resnet-50")
print("Model loaded!")

# Initialize the camera (0 for default camera, 1 for external camera)
cap = cv2.VideoCapture(0)  # Change to 1 if you have an external camera

if not cap.isOpened():
    print("Error: Could not open camera")
    exit()

print("Press 'c' to capture and classify, 'q' to quit")

while True:
    # Read frame from camera
    ret, frame = cap.read()
    
    if not ret:
        print("Failed to grab frame")
        break
    
    # Display the frame
    cv2.imshow('Camera Feed - Press C to classify, Q to quit', frame)
    
    # Wait for key press
    key = cv2.waitKey(1) & 0xFF
    
    # Capture and classify on 'c' key press
    if key == ord('c'):
        print("Classifying...")
        # Convert BGR (OpenCV format) to RGB (PIL format)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Convert to PIL Image
        image = Image.fromarray(rgb_frame)
        
        # Classify the image
        inputs = preprocessor(images=image, return_tensors="pt")
        outputs = model(**inputs)
        logits = outputs.logits
        
        # Get prediction
        predicted_class_idx = logits.argmax(-1).item()
        predicted_class = model.config.id2label[predicted_class_idx]
        
        print(f"Predicted class: {predicted_class}")
    
    # Quit on 'q' key press
    elif key == ord('q'):
        break

# Release camera and close windows
cap.release()
cv2.destroyAllWindows()