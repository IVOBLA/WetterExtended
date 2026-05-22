import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import Dashboard from './pages/Dashboard.jsx';
import MapView from './pages/MapView.jsx';
import Locations from './pages/Locations.jsx';
import Thresholds from './pages/Thresholds.jsx';
import Training from './pages/Training.jsx';
import Horizons from './pages/Horizons.jsx';
import Configuration from './pages/Configuration.jsx';
import Progress from './pages/Progress.jsx';
import Accuracy from './pages/Accuracy.jsx';
import Logs from './pages/Logs.jsx';
import AiSuggestions from './pages/AiSuggestions.jsx';
import Datensatz from './pages/Datensatz.jsx';
import LiveDaten from './pages/LiveDaten.jsx';
import MapFullscreen from './pages/MapFullscreen.jsx';
import Atmosphaere from './pages/Atmosphaere.jsx';
import CellFilters from './pages/CellFilters.jsx';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/"            element={<Dashboard />} />
        <Route path="/map"         element={<MapView />} />
        <Route path="/live"        element={<LiveDaten />} />
        <Route path="/data"        element={<Datensatz />} />
        <Route path="/atmosphaere" element={<Atmosphaere />} />
        <Route path="/locations"   element={<Locations />} />
        <Route path="/thresholds"  element={<Thresholds />} />
        <Route path="/horizons"    element={<Horizons />} />
        <Route path="/training"    element={<Training />} />
        <Route path="/config"      element={<Configuration />} />
        <Route path="/progress"    element={<Progress />} />
        <Route path="/accuracy"    element={<Accuracy />} />
        <Route path="/logs"        element={<Logs />} />
        <Route path="/ai-analysis"   element={<AiSuggestions />} />
        <Route path="/cell-filters"  element={<CellFilters />} />
        <Route path="*"              element={<Navigate to="/" replace />} />
      </Route>
      <Route path="/karte" element={<MapFullscreen />} />
    </Routes>
  )
}
