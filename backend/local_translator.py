"""
local_translator.py

Offline translation via argostranslate.
Language packages are downloaded automatically on first use and cached.
"""

import os
import threading
import traceback

_lock = threading.Lock()
_ready: set[tuple[str, str]] = set()   # pairs already verified/installed

# Store packages in the project's models dir, not a temp location
_PKG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "argostranslate"
)
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

        os.makedirs(_PKG_DIR, exist_ok=True)

        # Check if already installed
        for lang in argostranslate.translate.get_installed_languages():
            if lang.code == from_code:
                for t in lang.translations_to:
                    if t.to_lang.code == to_code:
                        with _lock:
                            _ready.add(key)
                        return True

        # Not installed — download it
        print(f"[Translator] Fetching package index for {from_code}→{to_code} ...")
        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        pkg = next(
            (p for p in available
             if p.from_code == from_code and p.to_code == to_code),
            None
        )
        if pkg is None:
            print(f"[Translator] No offline package for {from_code}→{to_code}, "
                  "will use original text.")
            return False

        print(f"[Translator] Downloading {from_code}→{to_code} ...")
        pkg_path = pkg.download()
        argostranslate.package.install_from_path(pkg_path)
        print(f"[Translator] Package {from_code}→{to_code} installed.")
        with _lock:
            _ready.add(key)
        return True

    except Exception:
        traceback.print_exc()
        return False


def translate(text: str, from_code: str, to_code: str) -> str:
    """
    Translate text offline.  Returns original text on failure.
    from_code / to_code are ISO 639-1 two-letter codes (e.g. 'tr', 'en').
    """
    if not text.strip() or from_code == to_code:
        return text

    if not _ensure_package(from_code, to_code):
        return text

    try:
        import argostranslate.translate
        return argostranslate.translate.translate(text, from_code, to_code)
    except Exception as e:
        print(f"[Translator] Error translating: {e}")
        return text
