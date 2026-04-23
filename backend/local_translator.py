"""
local_translator.py

Offline translation via argostranslate.
Language packages are downloaded once, stored in the project directory,
and used offline thereafter without checking the internet.
"""

import os
import threading
import traceback

_lock = threading.Lock()
_ready: set[tuple[str, str]] = set()   # pairs already verified/installed

# Store packages in the project's models dir, not a temp location
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG_DIR = os.path.join(_BASE_DIR, "models", "argostranslate")

# Crucial: Point argostranslate to our project-specific directory
os.makedirs(_PKG_DIR, exist_ok=True)
os.environ["ARGOS_PACKAGES_DIR"] = _PKG_DIR
os.environ["ARGOS_DEVICE_DATA_DIR"] = _PKG_DIR


def _ensure_package(from_code: str, to_code: str) -> bool:
    key = (from_code, to_code)
    with _lock:
        if key in _ready:
            return True

    try:
        import argostranslate.package
        import argostranslate.translate

        # 1. First, check if already installed locally (Offline First)
        installed = argostranslate.translate.get_installed_languages()
        from_lang = next((l for l in installed if l.code == from_code), None)
        if from_lang:
            if any(t.to_lang.code == to_code for t in from_lang.translations_to):
                # Found it locally! No need for internet.
                with _lock:
                    _ready.add(key)
                return True

        # 2. Not found locally, attempt to update index and download (Once)
        print(f"[Translator] Package {from_code}->{to_code} not found locally.")
        print(f"[Translator] Updating package index from internet (one-time)...")
        
        try:
            argostranslate.package.update_package_index()
        except Exception as e:
            print(f"[Translator] Network error while updating index: {e}")
            return False

        available = argostranslate.package.get_available_packages()
        pkg = next(
            (p for p in available
             if p.from_code == from_code and p.to_code == to_code),
            None
        )
        
        if pkg is None:
            print(f"[Translator] No offline package for {from_code}->{to_code}")
            return False

        print(f"[Translator] Downloading {from_code}->{to_code} to {_PKG_DIR} ...")
        pkg_path = pkg.download()
        argostranslate.package.install_from_path(pkg_path)
        print(f"[Translator] Package {from_code}->{to_code} installed and cached.")
        
        with _lock:
            _ready.add(key)
        return True

    except Exception:
        traceback.print_exc()
        return False


def translate(text: str, from_code: str, to_code: str) -> str:
    """
    Translate text offline. Returns original text on failure.
    from_code / to_code are ISO 639-1 codes (e.g. 'tr', 'en').
    """
    if not text.strip() or from_code == to_code:
        return text

    if not _ensure_package(from_code, to_code):
        # Fallback: if codes are incompatible or download failed
        return text

    try:
        import argostranslate.translate
        return argostranslate.translate.translate(text, from_code, to_code)
    except Exception as e:
        print(f"[Translator] Error translating: {e}")
        return text


def translate_batch(texts: list[str], from_code: str, to_code: str) -> list[str]:
    """
    Translate multiple texts in a single model call for speed.
    Uses a unique separator to maintain segment boundaries.
    """
    if not texts:
        return []
    if from_code == to_code:
        return texts

    # Filter out empty/whitespace-only segments but keep indices to reconstruct
    valid_indices = []
    to_translate = []
    for i, t in enumerate(texts):
        if t.strip():
            valid_indices.append(i)
            to_translate.append(t.strip())

    if not to_translate:
        return texts

    if not _ensure_package(from_code, to_code):
        return texts

    # Use a separator that is unlikely to be modified or removed by the model
    # ArgosTranslate usually preserves " ||| " well.
    separator = " ||| "
    joined_text = separator.join(to_translate)

    try:
        import argostranslate.translate
        translated_blob = argostranslate.translate.translate(joined_text, from_code, to_code)
        
        # Split back and handle potential model inconsistencies in separator spacing
        translated_list = translated_blob.split("|||")
        translated_list = [t.strip() for t in translated_list]

        if len(translated_list) != len(to_translate):
            print(f"[Translator] Batch size mismatch: sent {len(to_translate)}, got {len(translated_list)}. Falling back to sequential.")
            # Fallback to sequential for this specific batch if model messed up the separators
            return [translate(t, from_code, to_code) for t in texts]

        # Reconstruct the original list with translated results at correct indices
        results = list(texts)
        for idx, trans in zip(valid_indices, translated_list):
            results[idx] = trans
        return results

    except Exception as e:
        print(f"[Translator] Batch translation error: {e}")
        return [translate(t, from_code, to_code) for t in texts]
