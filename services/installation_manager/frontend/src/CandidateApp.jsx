import { useCallback, useEffect, useState } from 'react'
import { candidateRequest } from './candidateApi.js'

const operationKey = 'dvt-candidate-operation'
const requestKey = 'dvt-candidate-request'

const stages = {
  admitted: 'Операция сохранена',
  preparing: 'Проверяется кандидат',
  prepared: 'Кандидат проверен',
  recovering: 'Исполнитель переключает мастер',
  resuming: 'Доступ подтверждён',
  recovery_required: 'Требуется продолжение операции',
  succeeded: 'Мастер заменён, доступ проверен',
  cancelled: 'Доступ к исходному мастеру восстановлен',
  failed: 'Переключение остановлено до замены мастера',
}

export default function CandidateApp() {
  const [code, setCode] = useState('')
  const [paired, setPaired] = useState(false)
  const [snapshot, setSnapshot] = useState(null)
  const [disconnected, setDisconnected] = useState(false)
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(false)

  const show = useCallback((result) => {
    if (!result) return
    sessionStorage.setItem(operationKey, result.operation.id)
    const submission = JSON.parse(sessionStorage.getItem(requestKey) ?? 'null')
    if (submission && submission.previous !== result.operation.id) {
      sessionStorage.removeItem(requestKey)
    }
    setSnapshot(result)
  }, [])

  useEffect(() => {
    let stopped = false
    let timer
    let interrupted = false

    async function poll() {
      try {
        const id = sessionStorage.getItem(operationKey)
        const submitting = sessionStorage.getItem(requestKey)
        let result
        if (submitting) {
          result = await candidateRequest('/operations/active')
          if (!result) [result] = await candidateRequest('/operations?limit=1')
        } else {
          result = id ? await candidateRequest('/operations/' + id) : null
          if (!result) result = await candidateRequest('/operations/active')
          if (!result) [result] = await candidateRequest('/operations?limit=1')
        }
        if (stopped) return
        show(result)
        setPaired(true)
        setDisconnected(false)
        if (interrupted) window.location.reload()
      } catch (error) {
        if (stopped) return
        if (error.status === 401) {
          setPaired(false)
        } else if (error.status === 404) {
          sessionStorage.removeItem(operationKey)
        } else {
          interrupted = true
          setDisconnected(true)
        }
      }
      if (!stopped) timer = setTimeout(poll, 1500)
    }

    poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [show, paired])

  async function pair(event) {
    event.preventDefault()
    setMessage('')
    setPending(true)
    try {
      await candidateRequest('/session', { method: 'POST', data: { code } })
      setPaired(true)
    } catch (error) {
      setMessage(error.message)
    } finally {
      setCode('')
      setPending(false)
    }
  }

  async function submit(resume) {
    setMessage('')
    setPending(true)
    try {
      if (resume) {
        show(await candidateRequest('/operations/' + snapshot.operation.id + '/resume', {
          method: 'POST', data: {},
        }))
        return
      }
      const release = await candidateRequest('/operations/candidate')
      const existing = JSON.parse(sessionStorage.getItem(requestKey) ?? 'null')
      const key = existing?.key ?? crypto.randomUUID()
      sessionStorage.setItem(requestKey, JSON.stringify({
        key, previous: existing?.previous ?? sessionStorage.getItem(operationKey),
      }))
      show(await candidateRequest('/operations', {
        method: 'POST', key, data: { kind: 'manager_recovery', release },
      }))
    } catch (error) {
      if (error.detail?.operation_id) {
        sessionStorage.setItem(operationKey, error.detail.operation_id)
      }
      setMessage(error.message)
    } finally {
      setPending(false)
    }
  }

  const operation = snapshot?.operation
  const canResume = snapshot?.actions.includes('resume')

  return (
    <main className="main">
      <section className="card">
        <h1>DVT — мастер установки</h1>
        {disconnected && <p role="status">Мастер перезапускается. Ожидаем восстановления связи.</p>}
        {!paired && !disconnected && (
          <form onSubmit={pair}>
            <label htmlFor="pairing-code">Одноразовый код из административного терминала</label>
            <input id="pairing-code" type="password" value={code} autoComplete="off"
              onChange={(event) => setCode(event.target.value)} required />
            <button disabled={pending} type="submit">Подключиться</button>
          </form>
        )}
        {paired && (
          <>
            {operation && (
              <dl>
                <dt>Операция</dt><dd>{operation.id}</dd>
                <dt>Статус</dt><dd aria-live="polite">{stages[operation.stage] ?? operation.stage}</dd>
              </dl>
            )}
            <button disabled={pending || disconnected} onClick={() => submit(canResume)}>
              {canResume ? 'Продолжить операцию' : 'Запустить проверку замены мастера'}
            </button>
          </>
        )}
        {message && <p role="alert">{message}</p>}
      </section>
    </main>
  )
}
