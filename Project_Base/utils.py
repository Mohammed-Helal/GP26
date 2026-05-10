import os
import shutil

def move_to_confirmed_dataset(local_image_path, category):
    base_dir = "confirmed_dataset"
    target_dir = os.path.join(base_dir, category)
    
    os.makedirs(target_dir, exist_ok=True)
    
    file_name = os.path.basename(local_image_path)
    target_path = os.path.join(target_dir, file_name)
    
    try:
        if os.path.exists(local_image_path):
            shutil.move(local_image_path, target_path)
            print(f"📦 Moved: {file_name} -> {category}")
            return target_path
        else:
            print(f"❌ Error: File not found at {local_image_path}")
            return None
    except Exception as e:
        print(f"⚠️ Move failed: {e}")
        return None