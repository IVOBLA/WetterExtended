#!/bin/bash

echo "📦 Wetterprojekt Setup (Raspberry Pi)"
echo "🔄 Arbeitsverzeichnis: $(pwd)"

# 1. Systempakete aktualisieren
sudo apt update
sudo apt install -y python3-pip python3-venv unzip libatlas-base-dev libopenjp2-7-dev libtiff5 libjpeg-dev libfreetype6-dev

# 2. Virtuelle Umgebung anlegen
python3 -m venv venv
source venv/bin/activate

# 3. pip aktualisieren und Abhängigkeiten installieren
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Installation abgeschlossen."
echo "➡️  Starte dein Projekt mit:"
echo "source venv/bin/activate && python3 main.py"
