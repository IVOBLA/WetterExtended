import folium
import json

# JSON-Datei laden (z. B. deine Beispieldatei)
with open("train_data/objects/2025-04-14_23-26-12.json", "r") as f:
    data = json.load(f)

# Zentrum der Karte bestimmen
avg_lat = sum(obj["lat"] for obj in data) / len(data)
avg_lon = sum(obj["lon"] for obj in data) / len(data)

# Karte erstellen
m = folium.Map(location=[avg_lat, avg_lon], zoom_start=8, tiles="cartodbpositron")

# Zellen und Richtungspfeile einzeichnen
for obj in data:
    lat, lon = obj["lat"], obj["lon"]
    vx, vy = obj["lstm_vx"], obj["lstm_vy"]
    folium.CircleMarker(
        location=[lat, lon],
        radius=max(3, obj["area"] ** 0.5 / 10),
        color="blue",
        fill=True,
        fill_opacity=0.6,
        popup=f"ID: {obj['id']} | Area: {obj['area']:.1f}"
    ).add_to(m)

    # Bewegungspfeil (LSTM)
    end_lat = lat + vy * 0.01
    end_lon = lon + vx * 0.01
    folium.PolyLine([[lat, lon], [end_lat, end_lon]], color="red", weight=2).add_to(m)

# Karte speichern und anzeigen
m.save("cell_map.html")
print("✔ Karte gespeichert als 'cell_map.html'")
