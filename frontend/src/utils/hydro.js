const EMPTY_FEATURE_COLLECTION = Object.freeze({ type: 'FeatureCollection', features: Object.freeze([]) })

function isFiniteCoordinate(value) {
  return Number.isFinite(Number(value))
}

function isValidPosition(position) {
  return Array.isArray(position) && position.length >= 2 && isFiniteCoordinate(position[0]) && isFiniteCoordinate(position[1])
}

function isValidLinearRing(ring) {
  return Array.isArray(ring) && ring.length >= 3 && ring.every(isValidPosition)
}

function isValidHydroGeometry(geometry) {
  if (!geometry || typeof geometry !== 'object') return false
  if (geometry.type === 'Point') return isValidPosition(geometry.coordinates)
  if (geometry.type === 'Polygon') return Array.isArray(geometry.coordinates) && isValidLinearRing(geometry.coordinates[0])
  if (geometry.type === 'MultiPolygon') {
    return Array.isArray(geometry.coordinates) && geometry.coordinates.some(poly => Array.isArray(poly) && isValidLinearRing(poly[0]))
  }
  return false
}

function normalizeFeature(feature) {
  if (!feature || typeof feature !== 'object' || feature.type !== 'Feature') return null
  if (!isValidHydroGeometry(feature.geometry)) return null
  return {
    ...feature,
    properties: feature.properties && typeof feature.properties === 'object' ? feature.properties : {},
  }
}

export function safeHydroFeatures(response) {
  const fc = response?.data || response
  if (!fc || fc.type !== 'FeatureCollection' || !Array.isArray(fc.features)) return []
  return fc.features.map(normalizeFeature).filter(Boolean)
}

export function hydroFeatureCollection(response) {
  const features = safeHydroFeatures(response)
  return features.length > 0 ? { type: 'FeatureCollection', features } : { ...EMPTY_FEATURE_COLLECTION, features: [] }
}

export function hasValidHydroImpactLine(impact) {
  return impact?.relation === 'upstream_catchment_hit'
    && isFiniteCoordinate(impact.cell_lat)
    && isFiniteCoordinate(impact.cell_lon)
    && isFiniteCoordinate(impact.station_lat)
    && isFiniteCoordinate(impact.station_lon)
}


export function hydroFloodRows(response) {
  const rows = response?.data?.stations || response?.stations || []
  return Array.isArray(rows) ? rows : []
}
