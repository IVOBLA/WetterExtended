# model_training.py

import os
import json
import glob
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from math import sin, cos, pi, atan2
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense
from tensorflow.keras.losses import MeanSquaredError
from tensorflow.keras.optimizers import Adam
from sklearn.model_selection import train_test_split
from tensorflow.keras.callbacks import EarlyStopping

from geo_utils import pixel_to_geo
from weather_api import get_weather_data
from debug_utils import debug_log 
from utils import find_nearest_station, calculate_velocity

sequence_length = 3
num_features = 22

def train_or_load_model():
    model_path = "weather_lstm_model.keras"

    if os.path.exists(model_path):
        debug_log("Lade bestehendes Modell...")
        model = load_model(model_path, compile=False)
        model.compile(loss=MeanSquaredError(), optimizer=Adam(learning_rate=0.001))
        return model

    debug_log("Erstelle neues LSTM Modell...")
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(sequence_length, num_features)),
        LSTM(64),
        Dense(32, activation="relu"),
        Dense(16, activation="relu"),
        Dense(2)
    ])
    model.compile(loss=MeanSquaredError(), optimizer=Adam(learning_rate=0.001))
    return model


def train_with_historical_and_live_data(model, live_objects, timestamp=None, stations=[]):
    X_train, y_train = [], []
    new_ids, matched_ids = 0, 0

    object_files = sorted(glob.glob("train_data/objects/*.json"))
    weather_files = sorted(glob.glob("train_data/weather/*.json"))

    for i in range(sequence_length, len(object_files)):
        try:
            ts_now = os.path.splitext(os.path.basename(object_files[i]))[0]
            if not ts_now:
                continue
            with open(object_files[i]) as f_now, open(weather_files[i]) as wf:
                now_objs = json.load(f_now)
                weather = json.load(wf)
            with open(object_files[i - 1]) as f_prev:
                prev_objs = json.load(f_prev)

            for obj in now_objs:
                match = next((o for o in prev_objs if o["id"] == obj["id"]), None)
                if not match:
                    new_ids += 1
                    continue
                matched_ids += 1

                vx, vy = calculate_velocity(obj["id"], object_files)
                delta_angle = atan2(vy, vx)
                station = find_nearest_station(*pixel_to_geo(obj["x"], obj["y"]), weather)
                weather_vals = [station.get(k, 0) for k in ["RR", "DD", "FF", "FFX", "GLOW", "P", "RF", "TL", "TP"]] if station else [0] * 9
                hour_angle = 2 * pi * (datetime.strptime(ts_now, "%Y-%m-%d_%H-%M-%S").hour * 60 + datetime.strptime(ts_now, "%Y-%m-%d_%H-%M-%S").minute) / (24 * 60)

                sequence = []
                for j in range(i - sequence_length, i):
                    with open(object_files[j]) as f_hist:
                        hist_objs = json.load(f_hist)
                    hist_match = next((h for h in hist_objs if h["id"] == obj["id"]), None)
                    if not hist_match:
                        break

                    inp = [
                        hist_match["x"], hist_match["y"],
                        hist_match["vx"], hist_match["vy"],
                        hist_match["size"], hist_match["area"], hist_match["eccentricity"],
                        hist_match.get("core_ratio", 0), hist_match.get("intensity_trend", 0)
                    ] + weather_vals + [
                        sin(hour_angle), cos(hour_angle),
                        cos(delta_angle), sin(delta_angle)
                    ]
                    if len(inp) == num_features:
                        sequence.append(inp)

                if len(sequence) == sequence_length:
                    X_train.append(sequence)
                    y_train.append([obj["x"] + 10 * vx, obj["y"] + 10 * vy])
        except Exception as e:
            debug_log(f"Fehler bei Trainingsdaten: {e}")

    for obj in live_objects:
        sequence = []
        for j in range(-sequence_length, 0):
            idx = j + len(object_files)
            if idx < 0:
                continue
            with open(object_files[idx]) as f_hist:
                hist_objs = json.load(f_hist)
            hist_match = next((h for h in hist_objs if h["id"] == obj["id"]), None)
            if not hist_match:
                break

            vx_hist = obj["vx"]
            vy_hist = obj["vy"]
            delta_hist = atan2(vy_hist, vx_hist)
            station = find_nearest_station(*pixel_to_geo(hist_match["x"], hist_match["y"]), stations)
            weather_vals = [station.get(k, 0) for k in ["RR", "DD", "FF", "FFX", "GLOW", "P", "RF", "TL", "TP"]] if station else [0] * 9

            try:
                hour_angle = 2 * pi * (
                    datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S").hour * 60 +
                    datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S").minute
                ) / (24 * 60)
            except Exception:
                hour_angle = 0

            inp = [
                hist_match["x"], hist_match["y"],
                vx_hist, vy_hist,
                hist_match["size"], hist_match["area"], hist_match["eccentricity"],
                hist_match.get("core_ratio", 0), hist_match.get("intensity_trend", 0)
            ] + weather_vals + [
                sin(hour_angle), cos(hour_angle),
                cos(delta_hist), sin(delta_hist)
            ]

            if len(inp) == num_features:
                sequence.append(inp)

        if len(sequence) == sequence_length:
            X_train.append(sequence)
            y_train.append([obj["x"] + 10 * obj["vx"], obj["y"] + 10 * obj["vy"]])

    if not X_train:
        debug_log("Keine Trainingsdaten vorhanden.")
        debug_log(f"[DEBUG] Anzahl Objektdateien: {len(object_files)}")
        debug_log(f"[DEBUG] Anzahl Live-Objekte: {len(live_objects)}")
        debug_log(f"[DEBUG] Gesammelt: X_train={len(X_train)}, y_train={len(y_train)}")
        return None

    X_train = np.array(X_train)
    y_train = np.array(y_train)

    debug_log(f"Starte Training auf {len(X_train)} Samples (neu: {new_ids}, wiedererkannt: {matched_ids})...")

    X_train, X_val, y_train, y_val = train_test_split(X_train, y_train, test_size=0.2, random_state=42)
    early_stop = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)

    history = model.fit(X_train, y_train,
                    validation_data=(X_val, y_val),
                    epochs=100,
                    batch_size=32,
                    callbacks=[early_stop],
                    verbose=1)
    model.save("weather_lstm_model.keras")
    debug_log("Modell gespeichert.")
    print(f"[INFO] Finaler Trainingsfehler (MSE): {history.history['loss'][-1]:.6f}")

    # Lernkurve
    plt.figure(figsize=(8, 4))
    plt.plot(history.history['loss'], label="Train Loss")
    plt.plot(history.history['val_loss'], label="Validation Loss")
    plt.title("Lernkurve (MSE)")
    plt.xlabel("Epoche")
    plt.ylabel("Loss")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig("train_data/loss_curve.png")
    debug_log("Lernkurve gespeichert: train_data/loss_curve.png")

    with open("train_data/train_stats.txt", "w") as f:
        f.write(f"Trainings-Samples: {len(X_train)}\n")
        f.write(f"Wiedererkannt: {matched_ids}\n")
        f.write(f"Neue Objekte: {new_ids}\n")
    debug_log("Trainingsstatistik gespeichert.")

    return model, history  # <- HIER HINZUFÜGEN