import whisper
import os

def download_all():
    models = ["small", "medium", "large-v3"]
    model_dir = os.path.join(os.getcwd(), "models", "whisper")
    
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
        
    print(f"Models will be downloaded to '{model_dir}'...\n")
    
    for m in models:
        print(f"--- Downloading {m} model... ---")
        try:
            whisper.load_model(m, device="cpu", download_root=model_dir)
            print(f"SUCCESS: {m} is ready.\n")
        except Exception as e:
            print(f"ERROR: Could not download {m}! Error: {e}\n")

if __name__ == "__main__":
    download_all()
