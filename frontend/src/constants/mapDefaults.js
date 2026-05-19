/**
 * mapDefaults.js
 * Zentrale Konfiguration für alle Leaflet-Karten in WetterExtended.
 * Single Source of Truth — nie direkt in MapContainer hardcoden.
 *
 * Kärnten-Zentrum: Klagenfurt-Bereich (46.62°N / 14.31°E)
 *
 * Zoom-Referenz (OSM/Leaflet, Breitengrad ~46,7°):
 *   Zoom 6 → ~22° Längengrad sichtbar  (ganz Österreich + Nachbarländer)
 *   Zoom 7 → ~11° Längengrad sichtbar  (Kärnten + breiter Rand) ← MapView
 *   Zoom 8 → ~5,5° Längengrad sichtbar (Kärnten passt knapp mit Rand) ← Fullscreen
 *   Zoom 9 → ~2,75° Längengrad sichtbar (Kärnten 3° → passt NICHT mehr)
 *
 * Kärnten Ausdehnung: ca. 12,65°E–15,65°E (3° Breite), 46,37°N–47,12°N
 */

export const MAP_CENTER_KAERNTEN  = [46.62, 14.31]   // Klagenfurt-Bereich
export const MAP_ZOOM_DEFAULT     = 7                 // MapView (70vh) — ganz Kärnten + Rand
export const MAP_ZOOM_FULLSCREEN  = 8                 // MapFullscreen (100vh) — ganz Kärnten
export const MAP_ZOOM_MIN         = 6                 // Zoom-Untergrenze
export const MAP_ZOOM_MAX         = 14                // Zoom-Obergrenze

export const MAP_TILE_URL         = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
export const MAP_TILE_ATTRIBUTION = '© OpenStreetMap contributors'
