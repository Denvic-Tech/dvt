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

const candidateInstanceKey = 'dvt-candidate-instance'
export const candidateOperationKey = 'dvt-candidate-operation'
export const candidateRequestKey = 'dvt-candidate-request'

export function syncCandidateInstance(instanceId, storage = sessionStorage) {
  if (storage.getItem(candidateInstanceKey) === instanceId) return false
  storage.removeItem(candidateOperationKey)
  storage.removeItem(candidateRequestKey)
  storage.setItem(candidateInstanceKey, instanceId)
  return true
}

export async function confirmCandidateAdmission(path, storage = sessionStorage) {
  const saved = storage.getItem(candidateRequestKey)
  if (!saved) return null
  const { key, intent } = JSON.parse(saved)
  const data = JSON.parse(intent)
  let result
  try {
    result = await candidateRequest(path, { method: 'POST', key, data })
  } catch (error) {
    // Only a definitive rejection ends an outstanding intent. A lost response
    // is resolved by replaying the exact admission key and request.
    if (error.status >= 400 && error.status < 500 && error.status !== 401
      && storage.getItem(candidateRequestKey) === saved) {
      storage.removeItem(candidateRequestKey)
    }
    throw error
  }
  if (storage.getItem(candidateRequestKey) !== saved) return null
  storage.removeItem(candidateRequestKey)
  if (!result?.id || result.kind !== data.kind || result.manifest_digest !== data.manifest_digest) {
    throw new Error('Мастер вернул операцию для другого намерения')
  }
  storage.setItem(candidateOperationKey, result.id)
  return result
}
