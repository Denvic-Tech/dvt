import { useCallback, useEffect, useRef, useState } from 'react'
import {
  candidateOperationKey as operationKey, candidateRequest, candidateRequestKey,
  confirmCandidateAdmission, syncCandidateInstance,
} from './candidateApi.js'
import CandidateOperation, { failureMessage, terminalStages } from './CandidateOperation.jsx'
import CandidateReleaseForm from './CandidateReleaseForm.jsx'
import { WizardHeader } from './Wizard.jsx'

const operations = '/operator/operations'

const fragment = new URLSearchParams(window.location.hash.slice(1))
const initialOperation = fragment.get('operation')
const pairingCode = fragment.get('pairing')
function clearPairingLink() {
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
}
const initialPairing = pairingCode && /^[\w-]{43}$/.test(pairingCode)
  ? candidateRequest('/session', { method: 'POST', data: { code: pairingCode } })
      .then(() => { clearPairingLink(); return '' }, (error) => error.message)
  : null

export default function CandidateApp() {
  const [code, setCode] = useState('')
  const [paired, setPaired] = useState(null)
  const [settings, setSettings] = useState(null)
  const [operation, setOperation] = useState(null)
  const [activeOperation, setActiveOperation] = useState(null)
  const [disconnected, setDisconnected] = useState(false)
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(false)
  const [starting, setStarting] = useState(() => Boolean(sessionStorage.getItem(candidateRequestKey)))
  const [draft, setDraft] = useState(() => {
    const saved = sessionStorage.getItem(candidateRequestKey)
    return saved ? JSON.parse(JSON.parse(saved).intent) : null
  })
  const dismissed = useRef(null)
  const admitting = useRef(false)
  const linkedOperation = useRef(/^[0-9a-f-]{36}$/.test(initialOperation) ? initialOperation : null)

  const show = useCallback((result) => {
    if (!result) return
    sessionStorage.setItem(operationKey, result.id)
    setOperation(result)
    setStarting(false)
  }, [])

  useEffect(() => {
    function followLink() {
      const params = new URLSearchParams(window.location.hash.slice(1))
      if (params.has('pairing') || params.has('operation')) window.location.reload()
    }
    window.addEventListener('hashchange', followLink)
    return () => window.removeEventListener('hashchange', followLink)
  }, [])

  useEffect(() => {
    let stopped = false
    let timer
    let uiVersion

    async function poll() {
      try {
        const info = await candidateRequest('/operator/settings')
        if (stopped) return
        if (syncCandidateInstance(info.instance_id)) {
          setSettings(null)
          setOperation(null)
          setActiveOperation(null)
          setStarting(false)
          setDraft(null)
          setMessage('')
        }
        if (linkedOperation.current) {
          sessionStorage.setItem(operationKey, linkedOperation.current)
          linkedOperation.current = null
          clearPairingLink()
        }
        const active = await candidateRequest(operations + '/active')
        let confirmed = null
        if (!stopped && !admitting.current && sessionStorage.getItem(candidateRequestKey)) {
          admitting.current = true
          try {
            confirmed = await confirmCandidateAdmission(operations)
            if (!stopped && confirmed) setMessage('')
          } catch (error) {
            if (error.status === 401) throw error
            if (!stopped) admissionError(error)
          } finally {
            admitting.current = false
          }
        }
        if (stopped) return
        const id = sessionStorage.getItem(operationKey)
        const selected = !confirmed && id && id !== active?.id
          ? await candidateRequest(operations + '/' + id).catch((error) => {
            if (error.status === 404) return null
            throw error
          })
          : null
        const result = confirmed ?? selected ?? active
          ?? (await candidateRequest(operations + '?limit=1'))[0]
        if (stopped) return
        if (sessionStorage.getItem(operationKey) === id && !sessionStorage.getItem(candidateRequestKey)) {
          if (result && (result.id !== dismissed.current || !terminalStages.has(result.stage))) {
            show(result)
          } else {
            sessionStorage.removeItem(operationKey)
            setOperation(null)
          }
        }
        setActiveOperation(active)
        setSettings(info)
        setPaired(true)
        setDisconnected(false)
        if (uiVersion && uiVersion !== info.ui_version) {
          window.location.reload()
          return
        }
        uiVersion = info.ui_version
      } catch (error) {
        if (stopped) return
        if (error.status === 401) {
          setSettings(null)
          setOperation(null)
          setActiveOperation(null)
          setPaired(false)
          setDisconnected(false)
        } else {
          setDisconnected(true)
        }
      }
      if (!stopped) timer = setTimeout(poll, 1600)
    }
    async function start() {
      const error = await initialPairing
      if (stopped) return
      if (error) setMessage(error)
      poll()
    }
    start()
    return () => { stopped = true; clearTimeout(timer) }
  }, [show, paired])

  async function run(callback) {
    setMessage('')
    setPending(true)
    try {
      await callback()
    } catch (error) {
      if (error.detail?.operation_id) {
        sessionStorage.setItem(operationKey, error.detail.operation_id)
      }
      setMessage(error.detail?.reason ? failureMessage(error.detail.reason) : error.message)
    } finally {
      setPending(false)
    }
  }

  function pair(event) {
    event.preventDefault()
    const data = { code }
    setCode('')
    run(async () => {
      await candidateRequest('/session', { method: 'POST', data })
      setPaired(true)
    })
  }

  function admissionError(error) {
    if (error.status === 503 && error.detail === 'Setup is switching to the installation directory') return
    if (!sessionStorage.getItem(candidateRequestKey)) setStarting(false)
    setMessage(error.detail?.reason ? failureMessage(error.detail.reason) : error.message)
  }

  async function submit(data) {
    if (admitting.current) return
    const intent = JSON.stringify(data)
    const key = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      (byte) => byte.toString(16).padStart(2, '0')).join('')
    sessionStorage.setItem(candidateRequestKey, JSON.stringify({ key, intent }))
    setMessage('')
    setDraft(data)
    setStarting(true)
    admitting.current = true
    try {
      show(await confirmCandidateAdmission(operations))
    } catch (error) {
      if (error.detail?.operation_id) sessionStorage.setItem(operationKey, error.detail.operation_id)
      admissionError(error)
    } finally {
      admitting.current = false
    }
  }

  function act(action, confirm) {
    run(async () => {
      show(await candidateRequest(`${operations}/${operation.id}/actions/${action}`, {
        method: 'POST', data: { confirm },
      }))
    })
  }

  function openSetup() {
    const tab = window.open('about:blank', '_blank')
    if (!tab) {
      setMessage('Разрешите открытие новой вкладки и повторите попытку.')
      return
    }
    tab.opener = null
    run(async () => {
      try {
        const operationId = settings.setup_operation_id
        const { code } = await candidateRequest(`/operator/setup/${operationId}/pairing`, {
          method: 'POST', data: {},
        })
        const target = new URL('/setup', settings.app_origin)
        target.hash = new URLSearchParams({ operation: operationId, pairing: code })
        tab.location.replace(target.href)
      } catch (error) {
        tab.close()
        throw error
      }
    })
  }

  function back() {
    dismissed.current = operation.id
    sessionStorage.removeItem(operationKey)
    setOperation(null)
    setDraft(null)
    setMessage('')
  }

  const disabled = pending || disconnected
  const visibleOperation = starting ? { kind: draft?.kind ?? 'install', stage: 'admitted' } : operation
  const progress = Boolean(visibleOperation) && (paired || starting)
  const docking = paired && activeOperation && !starting && activeOperation.id !== operation?.id

  return <>
    <WizardHeader />
    <main className={`wizard-main${progress ? ' wide' : ''}`}>
      {(disconnected || paired === null) && <p className="banner banner-info" role="status">Подключение к мастеру…</p>}
      {message && <p className="banner banner-error" role="alert">{message}</p>}
      {paired === false && !disconnected && (
        <form onSubmit={pair} className="wizard-card operator-form">
          <h2>Подключение к мастеру</h2>
          <label className="field" htmlFor="pairing-code">Одноразовый код из терминала
            <input id="pairing-code" type="password" value={code} autoComplete="off"
              onChange={(event) => setCode(event.target.value)} required />
          </label>
          <button className="primary" disabled={pending} type="submit">Подключиться</button>
        </form>
      )}

      {progress && <CandidateOperation key={visibleOperation.id ?? 'pending'} operation={visibleOperation}
        disabled={disabled} act={act} settings={settings} openSetup={openSetup} onBack={back} />}
      {docking && <div className="operator-actions">
        <button className="btn" onClick={() => show(activeOperation)}>Открыть активную операцию</button>
      </div>}
      {paired && settings && !progress && !activeOperation && !settings.setup_required && (
        <CandidateReleaseForm settings={settings} disabled={disabled} draft={draft} onSubmit={submit} />
      )}
    </main>
  </>
}
