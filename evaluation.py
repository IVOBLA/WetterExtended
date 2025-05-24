# evaluation.py

import numpy as np
import csv
import os
import debug_utils
from debug_utils import debug_log

def evaluate_prediction(forecast_list, actual_objects, timestamp):
    if not forecast_list or not actual_objects:
        debug_log("Keine Daten zur Bewertung vorhanden.")
        return 0, float('inf')

    total_error = 0
    matched = 0

    for f_obj in forecast_list:
        min_dist = float('inf')
        for a_obj in actual_objects:
            dist = np.hypot(f_obj["x"] - a_obj["x"], f_obj["y"] - a_obj["y"])
            if dist < min_dist:
                min_dist = dist

        if min_dist < 50:  # Treffer wenn Distanz < 50 Pixel
            total_error += min_dist
            matched += 1

    accuracy = (matched / len(forecast_list)) * 100 if forecast_list else 0
    avg_error = total_error / matched if matched else float('inf')

    debug_log(f"Trefferquote: {accuracy:.2f}% — Durchschnittsfehler: {avg_error:.2f} Pixel")

    os.makedirs("plots", exist_ok=True)

    with open("plots/evaluation_results.csv", "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([accuracy, avg_error, timestamp])
    
    return accuracy, avg_error

def plot_error_over_time():
    try:
        accuracies = []
        errors = []
        timestamps = []

        with open("plots/evaluation_results.csv", "r") as f:
            reader = csv.reader(f)
            for row in reader:
                accuracies.append(float(row[0]))
                errors.append(float(row[1]))
                timestamps.append(row[2])

        plt.figure(figsize=(12, 6))
        plt.plot(timestamps, errors, marker='o', linestyle='-', label='Ø Fehler (Pixel)')
        plt.xticks(rotation=45)
        plt.title("Durchschnittlicher Fehler über Zeit")
        plt.xlabel("Zeit")
        plt.ylabel("Fehler in Pixel")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig("plots/fehler_ueber_zeit.png")
        plt.close()

    except Exception as e:
        print(f"Fehler bei Fehler-Plot über Zeit: {e}")
        
import matplotlib.pyplot as plt

def plot_forecast_vs_reality(forecast, reality, timestamp):
    if not forecast or not reality:
        print("[SKIP] Keine Daten für Plot vorhanden.")
        return

    plt.figure(figsize=(10, 6))

    # Forecast-Positionen
    forecast_x = [f["x"] for f in forecast]
    forecast_y = [f["y"] for f in forecast]
    plt.scatter(forecast_x, forecast_y, color='blue', label='Vorhersage', marker='x')

    # Real-Positionen
    reality_x = [r["x"] for r in reality]
    reality_y = [r["y"] for r in reality]
    plt.scatter(reality_x, reality_y, color='green', label='Realität', marker='o')

    # Linien zwischen Forecast und Realität
    for f, r in zip(forecast, reality):
        plt.plot([f["x"], r["x"]], [f["y"], r["y"]], color='gray', linestyle='--', linewidth=0.8)

    plt.legend()
    plt.grid(True)
    plt.title("Vorhersage vs Realität")
    plt.xlabel("x-Pixel")
    plt.ylabel("y-Pixel")
    plt.tight_layout()

    os.makedirs("plots", exist_ok=True)
    plt.savefig(f"plots/forecast_vs_reality_{timestamp}.png")
    plt.close()
