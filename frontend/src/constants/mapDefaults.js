/**
 * mapDefaults.js
 * Zentrale Konfiguration für alle Leaflet-Karten in WetterExtended.
 * Single Source of Truth — nie direkt in MapContainer hardcoden.
 *
 * Kärnten-Zentrum: Klagenfurt-Bereich (46.62°N / 14.31°E)
 * Zoom 8 zeigt ganz Kärnten inkl. Randgebirge auf typischen Bildschirmen.
 * Zoom 9 für Fullscreen-Modus (mehr Detailtiefe bei größerer Fläche).
 */

export const MAP_CENTER_KAERNTEN = [46.62, 14.31]   // Klagenfurt-Bereich
export const MAP_ZOOM_DEFAULT    = 8                 // MapView (70vh)
export const MAP_ZOOM_FULLSCREEN = 9                 // MapFullscreen (100vh)
export const MAP_ZOOM_MIN        = 6                 // Zoom-Untergrenze
export const MAP_ZOOM_MAX        = 14                // Zoom-Obergrenze

export const MAP_TILE_URL        = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
export const MAP_TILE_ATTRIBUTION = '© OpenStreetMap contributors'
