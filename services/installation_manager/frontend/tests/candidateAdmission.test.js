import assert from 'node:assert/strict'
import test from 'node:test'

import {
  candidateOperationKey, candidateRequestKey, confirmCandidateAdmission, syncCandidateInstance,
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

test('discards the previous installation’s selection and pending admission before replay', async (t) => {
  const storage = session()
  syncCandidateInstance('previous', storage)
  storage.setItem(candidateOperationKey, cancellation)
  const saved = JSON.stringify({ key: 'same-key', intent: JSON.stringify(data) })
  storage.setItem(candidateRequestKey, saved)

  assert.equal(syncCandidateInstance('previous', storage), false)
  assert.equal(storage.getItem(candidateOperationKey), cancellation)
  assert.equal(storage.getItem(candidateRequestKey), saved)

  t.mock.method(globalThis, 'fetch', () => assert.fail('A fresh instance must not replay the request'))
  assert.equal(syncCandidateInstance('fresh', storage), true)
  assert.equal(await confirmCandidateAdmission(path, storage), null)
  assert.equal(storage.getItem(candidateOperationKey), null)
})

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


test('keeps the first-install settings and key while the wizard restarts', async (t) => {
  const storage = session()
  const settings = { ...data, app_port: 80, install_dir: '/srv/dvt', public_urls: ['http://dvt.example.ru'] }
  const saved = JSON.stringify({ key: 'same-key', intent: JSON.stringify(settings) })
  storage.setItem(candidateRequestKey, saved)
  let calls = 0
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api' + path)
    assert.equal(options.headers['Idempotency-Key'], 'same-key')
    assert.deepEqual(JSON.parse(options.body), settings)
    if (++calls === 1) return Response.json({ detail: 'Setup is switching to the installation directory' }, { status: 503 })
    return Response.json({ ...settings, id: admitted, stage: 'admitted' }, { status: 202 })
  })
  await assert.rejects(confirmCandidateAdmission(path, storage), { status: 503 })
  assert.equal(storage.getItem(candidateRequestKey), saved)
  assert.equal((await confirmCandidateAdmission(path, storage)).id, admitted)
  assert.equal(storage.getItem(candidateRequestKey), null)
})

test('ends an invalid install intent so the operator can correct the directory', async (t) => {
  const storage = session()
  storage.setItem(candidateRequestKey, JSON.stringify({ key: 'same-key', intent: JSON.stringify(data) }))
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'Invalid path' }, { status: 422 }))
  await assert.rejects(confirmCandidateAdmission(path, storage), { status: 422 })
  assert.equal(storage.getItem(candidateRequestKey), null)
  assert.equal(storage.getItem(candidateOperationKey), cancellation)
})
