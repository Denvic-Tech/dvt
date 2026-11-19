import { useEffect, useState } from 'react'
import { candidateRequest } from './candidateApi.js'

export default function CandidateReleaseForm({ settings, disabled, onSubmit }) {
  const [catalog, setCatalog] = useState(null)
  const [version, setVersion] = useState('')
  const [message, setMessage] = useState('')
  const install = !settings.installed

  useEffect(() => {
    let active = true
    candidateRequest('/releases?channel=all').then((data) => {
      if (!active) return
      setCatalog(data)
      setVersion(data.recommended_stable?.version ?? data.releases[0]?.version ?? '')
    }).catch((error) => {
      if (active) setMessage(error.message)
    })
    return () => { active = false }
  }, [])

  const release = catalog?.releases.find((row) => row.version === version)
  const route = catalog?.paths?.[version] ?? []
  const selected = catalog?.first_steps?.[version]
    ?? catalog?.releases.find((row) => row.version === route[0])
  const available = selected ?? release
  const requiresIntermediate = route.length > 1

  function submit(event) {
    event.preventDefault()
    if (!available) return
    const fields = new FormData(event.currentTarget)
    const data = {
      kind: install ? 'install' : 'update',
      version: available.version,
      manifest_digest: available.manifest_digest,
      confirm_rc: available.channel === 'rc',
    }
    if (install) {
      data.app_port = Number(fields.get('app_port'))
      data.task_workers_count = Number(fields.get('workers'))
      data.ai_mcp_enabled = fields.has('ai_mcp')
    }
    onSubmit(data)
  }

  return (
    <form onSubmit={submit} className="operator-form">
      <h2>{install ? 'Установка DVT' : 'Подготовка обновления'}</h2>
      {install ? (
        <label className="field">Адрес DVT
          <input value={settings.app_origin} readOnly />
        </label>
      ) : catalog?.source && (
        <p>Работает DVT {catalog.source.version}, схема базы {catalog.source.revision}.</p>
      )}
      {catalog?.catalog_fetched_at && (
        <p className="section-hint">Каталог от {new Date(catalog.catalog_fetched_at).toLocaleString()}</p>
      )}
      {catalog?.catalog_error && (
        <p role="status">{catalog.catalog_fetched_at
          ? 'Каталог недоступен. Показаны сохранённые данные.'
          : 'Каталог недоступен. Подходящих сохранённых данных нет.'} ({catalog.catalog_error})</p>
      )}
      {catalog?.source_error && <p role="alert">Рабочая версия или схема базы не подтверждена.</p>}
      {catalog && !catalog.trust_configured && <p role="alert">Доверие к подписям релизов не настроено.</p>}
      {message && <p role="alert">{message}</p>}
      {catalog && catalog.releases.length === 0 && <p>Нет применимых релизов.</p>}
      {catalog?.releases.length > 0 && (
        <label className="field">Версия DVT
          <select value={version} onChange={(event) => setVersion(event.target.value)}>
            {catalog.releases.map((row) => (
              <option key={row.version} value={row.version}>
                {row.version}{row.version === catalog.recommended_stable?.version ? ' (рекомендуется)' : ''}
              </option>
            ))}
          </select>
        </label>
      )}
      {requiresIntermediate && (
        <p>Нужен переход через {route.join(' → ')}. Сначала подготовьте версию {route[0]}.</p>
      )}
      {install && <details>
        <summary>Дополнительные настройки</summary>
        <label className="field">Порт приложения
          <input type="number" name="app_port" min="1" max="65535" required defaultValue={settings.app_port} />
          <small>Оставьте предложенный порт, если внешний прокси не перенаправляет запросы.</small>
        </label>
        <label className="field">Число воркеров
          <input type="number" name="workers" min="1" required defaultValue="1" />
        </label>
        <label className="checkbox-row">
          <input type="checkbox" name="ai_mcp" />
          Включить AI MCP
        </label>
      </details>}
      <button className="btn btn-primary" type="submit"
        disabled={disabled || !available || (requiresIntermediate && !selected)}>
        {install ? 'Установить DVT' : 'Подготовить обновление'}
      </button>
    </form>
  )
}
