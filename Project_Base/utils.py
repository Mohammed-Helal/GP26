import os
import shutil

def move_to_confirmed_dataset(local_image_path, category):
    clean_path = local_image_path.replace("Project_Base/", "").lstrip("/")
    
    base_dir = "confirmed_dataset"
    target_dir = os.path.join(base_dir, category)
    os.makedirs(target_dir, exist_ok=True)
    
    file_name = os.path.basename(clean_path)
    target_path = os.path.join(target_dir, file_name)

    try:
        if os.path.exists(clean_path):
            shutil.move(clean_path, target_path)
            print(f"📦 Moved: {file_name} to {category}")
            return target_path
        else:
            print(f"❌ Not Found: {clean_path} (I am at: {os.getcwd()})")
            return None
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return None
    
def delete_inspection_image(image_path):
    """حذف الصورة من الهارد ديسك"""
    try:
        # تنظيف المسار زي ما عملنا في الـ move
        clean_path = image_path.replace("Project_Base/", "").lstrip("/")
        
        if os.path.exists(clean_path):
            os.remove(clean_path)
            print(f"🗑️ Successfully deleted: {clean_path}")
            return True
        else:
            print(f"⚠️ Cannot delete: File not found at {clean_path}")
            return False
    except Exception as e:
        print(f"❌ Error deleting file: {e}")
        return False