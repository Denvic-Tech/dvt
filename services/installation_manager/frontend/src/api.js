const BASE = '/api'

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* тело не JSON */ }
    throw new Error(detail)
  }
  return resp.json()
}

export const getState = () => request('/state')
export const getConfig = () => request('/config')
export const getSecrets = () => request('/secrets')
export const startInstall = (config) =>
  request('/install', { method: 'POST', body: JSON.stringify(config) })
export const startUpdate = (version, aiMcpEnabled, aiMcpInternalSecret) =>
  request('/update', {
    method: 'POST',
    body: JSON.stringify({
      version,
      ai_mcp_enabled: aiMcpEnabled,
      ai_mcp_internal_secret: aiMcpInternalSecret,
    }),
  })
export const getCurrentJob = (logOffset = 0) =>
  request(`/jobs/current?log_offset=${logOffset}`)
