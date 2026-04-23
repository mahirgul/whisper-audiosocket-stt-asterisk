"""
download_languages.py

Pre-downloads common language packages for offline translation.
Focuses on Turkish (tr), English (en), and German (de).
"""

import os
import sys

# Add backend to path so we can import local_translator
sys.path.append(os.path.join(os.getcwd(), "backend"))
import local_translator

def download_packages():
    # Common pairs (ArgosTranslate translates through English)
    pairs = [
        ("tr", "en"),
        ("en", "tr"),
        ("de", "en"),
        ("en", "de"),
        ("tr", "de"),
        ("de", "tr")
    ]
    
    print("=== Stereo Transcribe Pro — Language Package Downloader ===\n")
    
    for from_code, to_code in pairs:
        print(f"--- Checking package: {from_code} -> {to_code} ---")
        success = local_translator._ensure_package(from_code, to_code)
        if success:
            print(f"DONE: {from_code} -> {to_code} is ready.\n")
        else:
            print(f"FAILED: Could not prepare {from_code} -> {to_code}.\n")

    print("============================================================")
    print("All requested packages are handled and stored in models/argostranslate")

if __name__ == "__main__":
    download_packages()
