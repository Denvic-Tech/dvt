export async function candidateRequest(path, { method = 'GET', data, key } = {}) {
  const headers = {}
  if (method === 'POST') {
    headers['Content-Type'] = 'application/json'
    headers['X-DVT-CSRF'] = '1'
  }
  if (key) headers['Idempotency-Key'] = key
  const response = await fetch('/api' + path, {
    method, headers, body: data === undefined ? undefined : JSON.stringify(data),
  })
  if (response.ok) return response.json()
  const body = await response.json().catch(() => ({}))
  const error = new Error(typeof body.detail === 'string' ? body.detail : 'HTTP ' + response.status)
  error.status = response.status
  error.detail = body.detail
  throw error
}
