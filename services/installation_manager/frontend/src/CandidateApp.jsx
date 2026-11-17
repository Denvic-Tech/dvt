import { useCallback, useEffect, useRef, useState } from 'react'
import {
  candidateOperationKey as operationKey, candidateRequest, candidateRequestKey, confirmCandidateAdmission,
} from './candidateApi.js'
import CandidateOperation, { failureMessage, terminalStages } from './CandidateOperation.jsx'
import CandidateReleaseForm from './CandidateReleaseForm.jsx'

const operations = '/operator/operations'

const initialOperation = new URLSearchParams(window.location.hash.slice(1)).get('operation')
if (initialOperation && /^[0-9a-f-]{36}$/.test(initialOperation)) {
  sessionStorage.setItem(operationKey, initialOperation)
  window.history.replaceState(null, '', window.location.pathname)
}

export default function CandidateApp() {
  const [code, setCode] = useState('')
  const [paired, setPaired] = useState(false)
  const [settings, setSettings] = useState(null)
  const [operation, setOperation] = useState(null)
  const [items, setItems] = useState([])
  const [activeOperation, setActiveOperation] = useState(null)
  const [disconnected, setDisconnected] = useState(false)
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(false)
  const admitting = useRef(false)

  const show = useCallback((result) => {
    if (!result) return
    sessionStorage.setItem(operationKey, result.id)
    setOperation(result)
  }, [])

  useEffect(() => {
    let stopped = false
    let timer
    let uiVersion
    let interrupted = false

    async function poll() {
      try {
        const info = await candidateRequest('/operator/settings')
        const active = await candidateRequest(operations + '/active')
        const history = await candidateRequest(operations)
        let confirmed = null
        if (!stopped && !admitting.current && sessionStorage.getItem(candidateRequestKey)) {
          admitting.current = true
          try {
            confirmed = await confirmCandidateAdmission(operations)
            if (!stopped && confirmed) setMessage('')
          } catch (error) {
            if (error.status === 401) throw error
            if (!stopped) setMessage(error.detail?.reason ? failureMessage(error.detail.reason) : error.message)
          } finally {
            admitting.current = false
          }
        }
        const id = sessionStorage.getItem(operationKey)
        const selected = history.find((entry) => entry.id === id)
        let result = confirmed ?? selected ?? active ?? history[0]
        if (!confirmed && !selected && id && id !== active?.id) {
          result = await candidateRequest(operations + '/' + id).catch((error) => {
            if (error.status === 404) return active ?? history[0]
            throw error
          })
        }
        if (stopped) return
        show(result)
        setItems(history)
        setActiveOperation(active)
        setSettings(info)
        setPaired(true)
        setDisconnected(false)
        if (interrupted || (uiVersion && uiVersion !== info.ui_version)) {
          window.location.reload()
          return
        }
        uiVersion = info.ui_version
      } catch (error) {
        if (stopped) return
        if (error.status === 401) {
          setPaired(false)
          setDisconnected(false)
        } else {
          interrupted = true
          setDisconnected(true)
        }
      }
      if (!stopped) timer = setTimeout(poll, 1600)
    }
    poll()
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

  function submit(data) {
    run(async () => {
      const intent = JSON.stringify(data)
      if (admitting.current) return
      const saved = JSON.parse(sessionStorage.getItem(candidateRequestKey) ?? 'null')
      const key = saved?.intent === intent ? saved.key : crypto.randomUUID()
      sessionStorage.setItem(candidateRequestKey, JSON.stringify({ key, intent }))
      admitting.current = true
      try {
        show(await confirmCandidateAdmission(operations))
      } finally {
        admitting.current = false
      }
    })
  }

  function act(action, confirm) {
    run(async () => {
      show(await candidateRequest(`${operations}/${operation.id}/actions/${action}`, {
        method: 'POST', data: { confirm },
      }))
    })
  }

  function openSetup() {
    run(async () => {
      const operationId = settings.setup_operation_id
      const { code } = await candidateRequest(`/operator/setup/${operationId}/pairing`, {
        method: 'POST', data: {},
      })
      const target = new URL('/setup', settings.app_origin)
      target.hash = new URLSearchParams({ operation: operationId, pairing: code })
      window.location.assign(target)
    })
  }

  const disabled = pending || disconnected
  const finished = !operation || terminalStages.has(operation.stage)
  const needsSetup = settings?.setup_required && settings.setup_operation_id

  return (
    <main className="main">
      <section className="card operator-form">
        <h1>DVT — мастер установки</h1>
        {disconnected && <p className="banner banner-info" role="status">Мастер перезапускается. Сохраняем последнюю подтверждённую стадию.</p>}
        {!paired && !disconnected && (
          <form onSubmit={pair} className="operator-form">
            <p>Мастер доступен по защищённому соединению.</p>
            <label className="field" htmlFor="pairing-code">Одноразовый код из административного терминала
              <input id="pairing-code" type="password" value={code} autoComplete="off"
                onChange={(event) => setCode(event.target.value)} required />
            </label>
            <button className="btn btn-primary" disabled={pending} type="submit">Подключиться</button>
          </form>
        )}
        {paired && settings && (
          <>
            <p>{needsSetup ? 'DVT готов к первичной настройке'
              : activeOperation?.failure || activeOperation?.stage === 'recovery_required'
                ? 'Требуется продолжить операцию'
                : activeOperation || !finished ? 'Операция выполняется'
                  : settings.installed ? 'DVT готов к работе' : 'Мастер готов'}</p>
            {needsSetup && <button className="btn btn-primary" disabled={disabled}
              onClick={openSetup}>Настроить первого администратора</button>}
            {settings.installed && finished && !activeOperation && !settings.setup_required && (
              <a href={settings.app_origin}>Открыть DVT</a>
            )}
          </>
        )}
        {message && <p className="banner banner-error" role="alert">{message}</p>}
      </section>
      {paired && operation && <CandidateOperation key={operation.id} operation={operation}
        disabled={disabled} act={act} />}
      {paired && activeOperation && activeOperation.id !== operation?.id && (
        <section className="card">
          <button className="btn btn-secondary" onClick={() => show(activeOperation)}>Открыть активную операцию</button>
        </section>
      )}
      {paired && settings && finished && !activeOperation && !settings.setup_required && (
        <section className="card">
          <CandidateReleaseForm settings={settings} disabled={disabled} onSubmit={submit} />
        </section>
      )}
      {paired && items.length > 0 && <section className="card operator-form">
        <h2>История операций</h2>
        <ul className="operator-history">
          {items.map((entry) => <li key={entry.id}>
            <button className="btn btn-secondary" disabled={entry.id === operation?.id}
              onClick={() => show(entry)}>{entry.version} · {entry.id}</button>
          </li>)}
        </ul>
      </section>}
    </main>
  )
}
