from transformers import AutoImageProcessor, AutoModelForImageClassification
from PIL import Image
import cv2
import torch
from pymodbus.client import ModbusTcpClient
import time
import sys
import os
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================
PLC_IP = '192.168.1.200'
PLC_PORT = 502
MODEL_PATH = r"banana_classifier_final"
CONFIDENCE_THRESHOLD = 0.5  # Minimum confidence to accept prediction

# Create output directory for captured images
OUTPUT_DIR = "banana_classifications"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def find_available_camera():
    """
    Scan for available camera ports and return the first working one.
    Returns the port number or None if no camera is found.
    """
    print("\n" + "="*60)
    print("CAMERA DETECTION")
    print("="*60)
    
    for i in range(5):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"✓ Camera found on port {i}")
                print(f"  Resolution: {width}x{height}")
                cap.release()
                return i
            cap.release()
        else:
            print(f"✗ No camera on port {i}")
    
    print("\n✗ ERROR: No camera found on any port (0-4)")
    print("  Please check if your camera is connected and enabled")
    return None


def load_model(model_path):
    """Load the model and preprocessor with error handling."""
    try:
        print("\n" + "="*60)
        print("MODEL LOADING")
        print("="*60)
        print(f"Loading model from: {model_path}")
        
        preprocessor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
        print("✓ Preprocessor loaded")
        
        model = AutoModelForImageClassification.from_pretrained(model_path)
        print("✓ Model loaded successfully")
        
        model = model.to('cpu')
        model.eval()
        print("✓ Model set to evaluation mode")
        
        classes = list(model.config.id2label.values())
        print(f"✓ Classes: {classes}")
        
        return preprocessor, model
    
    except Exception as e:
        print(f"\n✗ ERROR loading model: {e}")
        print(f"  Make sure '{model_path}' directory contains valid model files")
        return None, None


def connect_to_plc(ip, port):
    """Establish connection to PLC with error handling."""
    try:
        print("\n" + "="*60)
        print("PLC CONNECTION")
        print("="*60)
        print(f"Connecting to PLC at {ip}:{port}")
        
        client = ModbusTcpClient(ip, port=port)
        
        if client.connect():
            print(f"✓ Connected to PLC at {ip}:{port}")
            return client
        else:
            print(f"✗ Failed to connect to PLC at {ip}:{port}")
            print("  ✗ SENSOR TRIGGERING WILL NOT WORK")
            return None
    
    except Exception as e:
        print(f"✗ Error connecting to PLC: {e}")
        print("  ✗ SENSOR TRIGGERING WILL NOT WORK")
        return None


def read_sensor_value(client):
    """Read sensor value from PLC safely. Returns None if error."""
    if client is None:
        return None
    
    try:
        response = client.read_holding_registers(10, count=1)
        if not response.isError():
            return response.registers[0]
    except Exception as e:
        pass
    
    return None


def write_result_to_plc(client, result):
    """Write classification result to PLC safely."""
    if client is None:
        return
    
    try:
        if result == "fresh":
            client.write_register(0, 1)
            print("✓ Sent 'FRESH' signal to PLC")
        else:
            client.write_register(1, 1)
            print("✓ Sent 'ROTTEN' signal to PLC")
    except Exception as e:
        print(f"Warning: Could not write to PLC: {e}")


def classify_frame(frame, preprocessor, model):
    """Classify a single frame and return results."""
    try:
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb_frame)
        
        # Preprocess
        inputs = preprocessor(images=image, return_tensors="pt")
        
        # Inference
        with torch.no_grad():
            outputs = model(**inputs)
        
        # Get predictions
        probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        predicted_idx = outputs.logits.argmax(-1).item()
        predicted_class = model.config.id2label[predicted_idx]
        confidence = probs[predicted_idx].item() * 100
        
        # Get all class probabilities
        all_probs = {
            model.config.id2label[idx]: probs[idx].item() * 100
            for idx in range(len(model.config.id2label))
        }
        
        return {
            'class': predicted_class,
            'confidence': confidence,
            'all_probs': all_probs
        }
    
    except Exception as e:
        print(f"✗ Error during classification: {e}")
        return None


def save_classified_image(frame, result, classification_count):
    """
    Save classified image with timestamp and add text overlay.
    Returns the full path to the saved image.
    """
    try:
        # Create a copy to add text overlay
        frame_with_text = frame.copy()
        
        # Add text overlay
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.2
        thickness = 3
        color = (0, 255, 0) if result['class'] == 'fresh' else (0, 0, 255)
        
        cv2.putText(frame_with_text, f"Class: {result['class'].upper()}", 
                    (10, 60), font, font_scale, color, thickness)
        cv2.putText(frame_with_text, f"Confidence: {result['confidence']:.2f}%", 
                    (10, 130), font, font_scale, color, thickness)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"banana_{result['class']}_{timestamp}.jpg"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        # Save image
        cv2.imwrite(filepath, frame_with_text)
        
        return filepath
    
    except Exception as e:
        print(f"✗ Error saving image: {e}")
        return None


def display_image_result(frame, result, display_time=1):
    """
    Display the classified frame with results overlay.
    Automatically closes after display_time seconds (default 3 seconds).
    """
    try:
        frame_with_text = frame.copy()
        height, width = frame_with_text.shape[:2]
        
        # Add semi-transparent background for text readability
        overlay = frame_with_text.copy()
        cv2.rectangle(overlay, (0, 0), (width, 300), (0, 0, 0), -1)
        frame_with_text = cv2.addWeighted(overlay, 0.3, frame_with_text, 0.7, 0)
        
        # Add text overlay
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.2
        thickness = 3
        color = (0, 255, 0) if result['class'] == 'fresh' else (0, 0, 255)
        
        y_pos = 50
        
        # Add main result
        cv2.putText(frame_with_text, f"Result: {result['class'].upper()}", 
                    (20, y_pos), font, font_scale, color, thickness)
        
        # Add confidence
        y_pos += 60
        cv2.putText(frame_with_text, f"Confidence: {result['confidence']:.2f}%", 
                    (20, y_pos), font, 1.0, (255, 255, 255), 2)
        
        # Add all probabilities
        y_pos += 60
        cv2.putText(frame_with_text, "All Classes:", 
                    (20, y_pos), font, 1, (200, 200, 200), 2)
        
        for class_name, prob in result['all_probs'].items():
            y_pos += 40
            prob_text = f"{class_name}: {prob:.2f}%"
            cv2.putText(frame_with_text, prob_text, 
                        (40, y_pos), font, 0.9, (200, 200, 200), 2)
        
        # Display the frame
        cv2.imshow('Classification Result', frame_with_text)
        
        # Wait for display_time seconds (convert to milliseconds)
        # User can press any key to close early
        cv2.waitKey(display_time * 1000)
        cv2.destroyWindow('Classification Result')
        
    except Exception as e:
        print(f"Warning: Could not display image: {e}")


# ============================================================================
# MAIN PROGRAM
# ============================================================================

def main():
    print("\n" + "="*60)
    print("🍌 BANANA CLASSIFIER WITH SENSOR-TRIGGERED CAPTURE")
    print("="*60)
    
    # Step 1: Find camera
    camera_port = 1  # Change this if needed, or use find_available_camera()
    # Uncomment the next line to auto-detect camera:
    # camera_port = find_available_camera()
    
    if camera_port is None:
        print("\nExiting...")
        return
    
    # Step 2: Load model
    preprocessor, model = load_model(MODEL_PATH)
    if model is None:
        print("\nExiting...")
        return
    
    # Step 3: Connect to PLC (REQUIRED for sensor triggering)
    plc_client = connect_to_plc(PLC_IP, PLC_PORT)
    if plc_client is None:
        print("\n✗ ERROR: Cannot proceed without PLC connection!")
        print("  This program requires sensor input from the PLC")
        print("Exiting...")
        return
    
    # Step 4: Open camera
    print("\n" + "="*60)
    print("CAMERA INITIALIZATION")
    print("="*60)
    
    cap = cv2.VideoCapture(camera_port)
    
    if not cap.isOpened():
        print(f"✗ ERROR: Could not open camera on port {camera_port}")
        print("Exiting...")
        return
    
    print(f"✓ Camera opened on port {camera_port}")
    print(f"✓ Images will be saved to: {os.path.abspath(OUTPUT_DIR)}")
    
    # Step 5: Main loop
    print("\n" + "="*60)
    print("🍌 BANANA CLASSIFIER READY!")
    print("="*60)
    print("Mode: SENSOR-TRIGGERED (1→0 signal change)")
    print("Reading sensor from register 10...")
    print("\nWindows:")
    print("  - LIVE FEED: Continuous camera stream")
    print("  - RESULT: Shows for 3 seconds after classification")
    print("\nPress 'q' in LIVE FEED window to quit")
    print("="*60 + "\n")
    
    frame_count = 0
    classification_count = 0
    previous_sensor_value = None  # Track previous value to detect change
    debounce_time = None  # Track time to avoid multiple captures from bouncing signal
    debounce_delay = 0  # Seconds to ignore signal changes after capture
    
    try:
        while True:
            ret, frame = cap.read()
            
            if not ret:
                print("✗ Failed to grab frame from camera")
                break
            
            frame_count += 1
            
            # Display live camera feed
            cv2.imshow('LIVE FEED - Press Q to Quit', frame)
            
            # Check for manual quit
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("\n🛑 Shutting down...")
                break
            
            # Read sensor value from PLC
            current_sensor_value = read_sensor_value(plc_client)
            
            # Detect signal change from 1 to 0 (with debouncing)
            should_classify = False
            
            if current_sensor_value is not None:
                # Check if signal changed from 1 to 0
                if previous_sensor_value == 1 and current_sensor_value == 0:
                    # Check debounce timer
                    if debounce_time is None or (time.time() - debounce_time) > debounce_delay:
                        should_classify = True
                        debounce_time = time.time()
                        print(f"\n⚡ SENSOR TRIGGERED (1→0 transition)")
                
                previous_sensor_value = current_sensor_value
            
            if should_classify:
                print(f"\n{'='*60}")
                print(f"Classification #{classification_count + 1}")
                print(f"{'='*60}")
                
                result = classify_frame(frame, preprocessor, model)
                
                if result:
                    classification_count += 1
                    
                    # Display results in console
                    print(f"🍌 Result: {result['class'].upper()}")
                    print(f"📊 Confidence: {result['confidence']:.2f}%")
                    print(f"📋 All probabilities:")
                    for class_name, prob in result['all_probs'].items():
                        print(f"   • {class_name}: {prob:.2f}%")
                    
                    # Save image
                    image_path = save_classified_image(frame, result, classification_count)
                    if image_path:
                        print(f"💾 Image saved: {image_path}")
                    
                    # Send result to PLC
                    write_result_to_plc(plc_client, result['class'])
                    
                    print(f"{'='*60}")
                    
                    # Display result image for 3 seconds (non-blocking)
                    # This will show result and automatically close
                    display_image_result(frame, result, display_time=3)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Interrupted by user")
    
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
    
    finally:
        # Cleanup
        print("\nCleaning up...")
        cap.release()
        cv2.destroyAllWindows()
        
        if plc_client:
            plc_client.close()
            print("✓ PLC connection closed")
        
        print(f"✓ Program ended")
        print(f"  Total frames processed: {frame_count}")
        print(f"  Total classifications: {classification_count}")
        print(f"  Images saved to: {os.path.abspath(OUTPUT_DIR)}")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()