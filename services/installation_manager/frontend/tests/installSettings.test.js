import assert from 'node:assert/strict'
import test from 'node:test'
import { applicationOrigin } from '../src/installSettings.js'

test('normalizes an address using the application port', () => {
  assert.equal(applicationOrigin(' dvt.example.ru:8080 ', 80), 'http://dvt.example.ru')
  assert.equal(applicationOrigin('https://dvt.example.ru', 443), 'https://dvt.example.ru')
  assert.equal(applicationOrigin('2001:db8::1', 9090), 'http://[2001:db8::1]:9090')
})

test('rejects credentials, paths, query, fragment and unsupported protocols', () => {
  for (const input of ['http://', 'http://a@b', 'http://a/path', 'http://a?q=1', 'http://a#hash', 'ftp://a', 'http://a\\path']) {
    assert.throws(() => applicationOrigin(input, 80), Error, input)
  }
})
