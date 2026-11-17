import assert from 'node:assert/strict'
import test from 'node:test'

import {
  candidateOperationKey, candidateRequestKey, confirmCandidateAdmission,
} from '../src/candidateApi.js'

const cancellation = '29f46867-1c2c-482a-8a50-9c17adfdcdaf'
const admitted = '36de68f2-4e51-4674-b344-f70717a47086'
const path = '/operator/operations'
const data = { kind: 'install', manifest_digest: 'sha256:' + 'a'.repeat(64) }

function session(previous = cancellation) {
  const values = new Map([[candidateOperationKey, previous]])
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

for (const stage of ['preparing', 'succeeded']) {
  test(`replays the same admission after losing 202 with an old history selection (${stage})`, async (t) => {
    const storage = session()
    const saved = JSON.stringify({ key: 'same-key', intent: JSON.stringify(data), previous: cancellation })
    storage.setItem(candidateRequestKey, saved)
    const operation = { ...data, id: admitted, stage }
    let calls = 0
    t.mock.method(globalThis, 'fetch', async (url, options) => {
      assert.equal(url, '/api' + path)
      assert.equal(options.method, 'POST')
      assert.equal(options.headers['Idempotency-Key'], 'same-key')
      assert.deepEqual(JSON.parse(options.body), data)
      if (++calls === 1) throw new TypeError('Lost response after commit')
      return Response.json(operation, { status: 202 })
    })

    await assert.rejects(confirmCandidateAdmission(path, storage), /Lost response/)
    assert.equal(storage.getItem(candidateOperationKey), cancellation)
    assert.equal(storage.getItem(candidateRequestKey), saved)
    assert.deepEqual(await confirmCandidateAdmission(path, storage), operation)
    assert.equal(storage.getItem(candidateOperationKey), admitted)
    assert.equal(storage.getItem(candidateRequestKey), null)
    assert.equal(calls, 2)
  })
}

test('keeps an exact history selection when there is no outstanding admission', async (t) => {
  const storage = session()
  t.mock.method(globalThis, 'fetch', () => assert.fail('Browsing history must not send POST'))
  assert.equal(await confirmCandidateAdmission(path, storage), null)
  assert.equal(storage.getItem(candidateOperationKey), cancellation)
})

test('an operation with another kind or digest cannot replace the selected one', async (t) => {
  const storage = session()
  storage.setItem(candidateRequestKey, JSON.stringify({ key: 'same-key', intent: JSON.stringify(data) }))
  t.mock.method(globalThis, 'fetch', async () => Response.json({
    ...data, id: admitted, kind: 'update', stage: 'preparing',
  }, { status: 202 }))
  await assert.rejects(confirmCandidateAdmission(path, storage), /другого намерения/)
  assert.equal(storage.getItem(candidateOperationKey), cancellation)
  assert.equal(storage.getItem(candidateRequestKey), null)
})
