import { useCallback, useEffect, useState } from 'react'
import { candidateRequest } from './candidateApi.js'

const operationKey = 'dvt-candidate-operation'
const requestKey = 'dvt-candidate-request'

const stages = {
  admitted: 'Операция сохранена',
  preparing: 'Проверяется кандидат',
  prepared: 'Кандидат проверен',
  maintenance: 'Окно обслуживания',
  backup: 'Подготовка копии',
  migrating: 'Миграция базы данных',
  applying: 'Применяется комплект',
  verifying: 'Проверяется готовность',
  recovering: 'Выполняется восстановление',
  resuming: 'Подтверждается доступ',
  recovery_required: 'Требуется продолжение операции',
  succeeded: 'Операция завершена',
  cancelled: 'Операция отменена',
  failed: 'Операция завершилась ошибкой',
}

const actionLabels = {
  resume: 'Продолжить операцию',
  cancel_preparation: 'Отменить подготовку',
  extend_maintenance: 'Продлить окно',
  defer_maintenance: 'Отложить обслуживание',
  recover_manager: 'Восстановить доступ к мастеру',
  return_to_source: 'Вернуть прежний комплект',
}

const terminalStages = new Set(['succeeded', 'cancelled', 'failed'])

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

  async function submit(action) {
    setMessage('')
    setPending(true)
    try {
      if (action) {
        const path = '/operations/' + snapshot.operation.id
        const endpoint = action === 'resume' ? path + '/resume' : path + '/actions/' + action
        show(await candidateRequest(endpoint, {
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
  const availableActions = snapshot?.actions.filter((action) => action in actionLabels) ?? []
  const canStart = !operation || terminalStages.has(operation.stage)

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
            {availableActions.map((action) => (
              <button key={action} disabled={pending || disconnected} onClick={() => submit(action)}>
                {actionLabels[action]}
              </button>
            ))}
            {canStart && (
              <button disabled={pending || disconnected} onClick={() => submit()}>
                Запустить проверку замены мастера
              </button>
            )}
            {operation && <a href={`/api/operations/${operation.id}/diagnostics`}>Диагностика</a>}
          </>
        )}
        {message && <p role="alert">{message}</p>}
      </section>
    </main>
  )
}
