"""Audio notification service for laptop speaker HMI feedback.

Plays synthetic sound or WAV file using system audio backends (paplay/aplay).
Non-blocking execution via background daemon threads.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parent
BEEP_SOUND_FILE = CURRENT_DIR / "beep_success.wav"


def _try_play(audio_path: str | Path) -> bool:
    target = str(audio_path)
    for player in ("pw-play", "paplay", "aplay"):
        if shutil.which(player):
            try:
                res = subprocess.run(
                    [player, target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                continue
    return False


def _play_worker(sound_type: str = "success") -> None:
    try:
        if sound_type == "success":
            if BEEP_SOUND_FILE.is_file() and _try_play(BEEP_SOUND_FILE):
                return
            # Fallback to system completion chime if available
            system_chimes = [
                "/usr/share/sounds/freedesktop/stereo/complete.oga",
                "/usr/share/sounds/gnome/default/alerts/glass.ogg",
                "/usr/share/sounds/sound-icons/prompt.wav",
            ]
            for chime in system_chimes:
                if os.path.exists(chime) and _try_play(chime):
                    return
        elif sound_type == "alert":
            # Warning beep for PAD rejection
            system_alerts = [
                "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
                "/usr/share/sounds/gnome/default/alerts/drip.ogg",
            ]
            for alert in system_alerts:
                if os.path.exists(alert) and _try_play(alert):
                    return
    except Exception as exc:
        logger.debug(f"Audio playback error: {exc}")


_last_sound_time = 0.0


def play_attendance_sound(cooldown: float = 2.0) -> None:
    """Trigger attendance success sound from computer speaker (non-blocking, rate-limited)."""
    global _last_sound_time
    import time
    now = time.monotonic()
    if now - _last_sound_time < cooldown:
        return
    _last_sound_time = now
    threading.Thread(target=_play_worker, args=("success",), daemon=True).start()


def play_warning_sound() -> None:
    """Trigger rejection/spoof warning sound from computer speaker (non-blocking)."""
    threading.Thread(target=_play_worker, args=("alert",), daemon=True).start()
