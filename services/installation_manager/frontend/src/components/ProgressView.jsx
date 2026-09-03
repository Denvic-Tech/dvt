import { useEffect, useRef, useState } from 'react'
import { getCurrentJob } from '../api.js'

const STATUS_ICON = {
  pending: '○',
  running: '◌',
  ok: '✅',
  failed: '❌',
}

const KIND_TITLE = {
  install: 'Установка DVT',
  update: 'Обновление DVT',
}

export default function ProgressView({ onBack }) {
  const [status, setStatus] = useState(null)
  const [logLines, setLogLines] = useState([])
  const [pollError, setPollError] = useState('')
  const logOffsetRef = useRef(0)
  const logBoxRef = useRef(null)

  useEffect(() => {
    let stopped = false
    let timer = null

    async function poll() {
      try {
        const snap = await getCurrentJob(logOffsetRef.current)
        if (stopped) return
        setPollError('')
        setStatus(snap)
        if (snap.log.length > 0) {
          logOffsetRef.current = snap.log_total
          setLogLines((prev) => [...prev, ...snap.log])
        }
        if (snap.state === 'running') {
          timer = setTimeout(poll, 1500)
        }
      } catch (e) {
        if (stopped) return
        setPollError(e.message)
        timer = setTimeout(poll, 3000)
      }
    }

    poll()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    const box = logBoxRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [logLines])

  const state = status?.state
  const kindTitle = KIND_TITLE[status?.kind] || 'Выполнение'

  return (
    <div className="progress-view">
      <section className="card">
        <h2>
          {state === 'succeeded' && `✅ ${kindTitle}: успешно`}
          {state === 'failed' && `❌ ${kindTitle}: ошибка`}
          {(!state || state === 'running') && `⚙️ ${kindTitle}…`}
          {status?.version && <span className="version-chip">{status.version}</span>}
        </h2>

        {pollError && (
          <div className="banner banner-error">Потеряна связь с бэкендом: {pollError}</div>
        )}

        <ul className="steps">
          {status?.steps.map((step) => (
            <li key={step.id} className={`step step-${step.status}`}>
              <span className="step-icon">{STATUS_ICON[step.status]}</span>
              <span className="step-title">{step.title}</span>
              {step.detail && step.status !== 'pending' && (
                <span className="step-detail">{step.detail}</span>
              )}
            </li>
          ))}
        </ul>

        {state === 'failed' && status?.error && (
          <div className="banner banner-error">{status.error}</div>
        )}

        {state === 'succeeded' && (
          <div className="banner banner-success">
            Готово. Продукт доступен по настроенным публичным URL.
          </div>
        )}

        {state && state !== 'running' && (
          <div className="submit-row">
            <button className="btn btn-primary" onClick={onBack}>
              ← Вернуться
            </button>
          </div>
        )}
      </section>

      <section className="card">
        <h2>📋 Журнал</h2>
        <pre className="log-box" ref={logBoxRef}>
          {logLines.join('\n') || 'Ожидание вывода…'}
        </pre>
      </section>
    </div>
  )
}
