# debug_utils.py

import cv2
import os
import utils
from utils import log

from config import DEBUG_MODE  # Ein-/Ausschalten über config.py

def save_debug_image(path, image, message=None):
    if DEBUG_MODE:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cv2.imwrite(path, image)
        if message:
            debug_log(f"[DEBUG] {message}: {path}")

def debug_log(message):
    if DEBUG_MODE:
        log(f"[DEBUG] {message}")
