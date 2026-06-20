"""Hilfslogik zur Auswahl robuster Radar-Vorgängerframes."""

import os


def select_optflow_prev_radar_path(immediate_prev_path, last_valid_prev_path):
    """Wählt für Optical Flow den besten verfügbaren Vorgängerframe.

    Wenn der unmittelbare Vorgängerframe fehlt (z. B. durch Cleanup oder einen
    not_new-/Download-Skip), bleibt der letzte noch existierende gültige Frame
    als Vorgänger nutzbar, statt Optical Flow mit prev_radar_missing zu
    deaktivieren.
    """
    if immediate_prev_path and os.path.exists(immediate_prev_path):
        return immediate_prev_path
    if last_valid_prev_path and os.path.exists(last_valid_prev_path):
        return last_valid_prev_path
    return immediate_prev_path


def remember_valid_radar_path(current_path, last_valid_prev_path):
    """Merkt den aktuellen Frame nur dann als gültigen OF-Vorgänger, wenn er existiert."""
    if current_path and os.path.exists(current_path):
        return current_path
    return last_valid_prev_path
