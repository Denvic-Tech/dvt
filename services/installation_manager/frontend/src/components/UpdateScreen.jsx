import { useEffect, useState } from 'react'
import { startUpdate } from '../api.js'

export default function UpdateScreen({ state, config, onStarted, onReinstall }) {
  const [version, setVersion] = useState('latest')
  const [aiMcpEnabled, setAiMcpEnabled] = useState(false)
  const [aiMcpInternalSecret, setAiMcpInternalSecret] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setAiMcpEnabled(Boolean(config?.ai_mcp_enabled))
  }, [config])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await startUpdate(
        version.trim(),
        aiMcpEnabled,
        aiMcpInternalSecret.trim(),
      )
      onStarted()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit}>
      <section className="card">
        <h2>🔄 Обновление DVT</h2>
        <p className="section-hint">
          Текущая версия: <b>{state?.current_version || 'неизвестна'}</b>.
          Будут обновлены сервисы: {state?.target_services?.join(', ') || '—'}.
        </p>

        {error && <div className="banner banner-error">❌ {error}</div>}

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={aiMcpEnabled}
            onChange={(e) => setAiMcpEnabled(e.target.checked)}
          />
          <span>Включить пользовательский AI MCP сервер</span>
        </label>

        {aiMcpEnabled && (
          <label className="field">
            <span className="field-label">Внутренний секрет AI MCP</span>
            <input
              type="password"
              className="input mono"
              value={aiMcpInternalSecret}
              onChange={(e) => setAiMcpInternalSecret(e.target.value)}
              placeholder={
                config?.has_ai_mcp_internal_secret
                  ? 'Пусто — сохранится текущее значение'
                  : 'Пусто — сгенерируется автоматически'
              }
              autoComplete="off"
            />
          </label>
        )}

        <label className="field">
          <span className="field-label">Версия (tag образов) *</span>
          <input
            className="input mono"
            required
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </label>

        <div className="submit-row">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Запуск…' : '🔄 Обновить DVT'}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>⚙️ Переустановка и настройка</h2>
        <p className="section-hint">
          Изменение публичных URL, портов, паролей и других параметров с полным
          перезапуском стека.
        </p>
        <button type="button" className="btn" onClick={onReinstall}>
          Открыть полную настройку →
        </button>
      </section>
    </form>
  )
}
