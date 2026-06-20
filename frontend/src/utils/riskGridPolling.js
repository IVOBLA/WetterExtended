const DEFAULT_INITIAL_BACKOFF_MS = 1000
const DEFAULT_MAX_BACKOFF_MS = 30000

export function nextRiskGridBackoffMs(previousMs, {
  initialMs = DEFAULT_INITIAL_BACKOFF_MS,
  maxMs = DEFAULT_MAX_BACKOFF_MS,
} = {}) {
  if (!Number.isFinite(previousMs) || previousMs <= 0) return initialMs
  return Math.min(previousMs * 2, maxMs)
}

export function riskGridErrorSignature(error) {
  const message = String(error?.message || error || 'Unbekannter Risk-Grid-Fehler')
  if (/Failed to fetch|NetworkError|ECONNREFUSED|ERR_CONNECTION_REFUSED|connection refused/i.test(message)) {
    return 'connection-refused'
  }
  return message
}

export function logRiskGridErrorOnce(error, state, logger = console.error) {
  const signature = riskGridErrorSignature(error)
  if (state.lastLoggedRiskGridError !== signature) {
    logger('Risk grid failed', error)
    state.lastLoggedRiskGridError = signature
    return true
  }
  return false
}

export async function waitForFlaskHealth({
  fetchImpl = fetch,
  healthUrl = '/api/health',
  state,
  signal,
  logger = console.error,
} = {}) {
  const response = await fetchImpl(healthUrl, {
    method: 'GET',
    cache: 'no-store',
    signal,
  })
  if (!response?.ok) {
    throw new Error(`${healthUrl}: ${response?.status || 'nicht erreichbar'}`)
  }
  if (state) state.lastLoggedRiskGridError = null
  return true
}

export async function loadRiskGridAfterHealth({
  apiClient,
  state,
  onSuccess,
  onError,
  fetchImpl = fetch,
  healthUrl = '/api/health',
  riskUrl = '/api/risk_grid',
  logger = console.error,
} = {}) {
  try {
    await waitForFlaskHealth({ fetchImpl, healthUrl, state, logger })
    const data = await apiClient.get(riskUrl)
    if (state) {
      state.riskGridBackoffMs = 0
      state.lastLoggedRiskGridError = null
    }
    onSuccess?.(data)
    return { ok: true, data }
  } catch (error) {
    if (state) {
      logRiskGridErrorOnce(error, state, logger)
      state.riskGridBackoffMs = nextRiskGridBackoffMs(state.riskGridBackoffMs)
    } else {
      logger('Risk grid failed', error)
    }
    onError?.(error)
    return { ok: false, error }
  }
}

export function nextRiskGridDelayMs(state, defaultDelayMs = 60000) {
  return state?.riskGridBackoffMs > 0 ? state.riskGridBackoffMs : defaultDelayMs
}
