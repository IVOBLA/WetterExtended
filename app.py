from flask import Flask, render_template
from flask import send_from_directory
import glob
import json
import folium
import os
from datetime import datetime


app = Flask(__name__)

@app.route('/')
def index():
    overlay_path = "data/overlay.png"
    object_files = sorted(glob.glob("train_data/objects/*.json"))

    m = folium.Map(location=[46.05, 14.51], zoom_start=7)

    radar_available = False

    # Prüfen ob Overlay vorhanden
    if os.path.exists(overlay_path):
        radar_available = True
        folium.raster_layers.ImageOverlay(
            image=overlay_path,
            bounds=[[44.67, 12.1], [47.42, 17.44]],
            opacity=0.7
        ).add_to(m)

    # Objekte (wenn vorhanden) laden und anzeigen
    if object_files:
        object_file = object_files[-1]
        with open(object_file) as f:
            objects = json.load(f)

        for obj in objects:
            if "lat" in obj and "lon" in obj:
                folium.CircleMarker(
                    location=[obj['lat'], obj['lon']],
                    radius=5,
                    color='red',
                    fill=True,
                    fill_color='red'
                ).add_to(m)

    # Karte speichern
    m.save("templates/map.html")

    if radar_available:
        return render_template("map.html", timestamp=datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
    else:
        return render_template("index.html", radar_available=radar_available)

@app.route('/data/<path:filename>')
def data_files(filename):
    return send_from_directory('data', filename)

if __name__ == '__main__':
    app.run(debug=True)
