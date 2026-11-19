import { useEffect, useState } from 'react'
import { candidateRequest } from './candidateApi.js'

export default function CandidateReleaseForm({ settings, disabled, onSubmit }) {
  const pinnedVersion = settings.initial_release_version
  const [channel, setChannel] = useState(pinnedVersion?.includes('-rc') ? 'rc' : 'stable')
  const [catalog, setCatalog] = useState(null)
  const [version, setVersion] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [message, setMessage] = useState('')
  const install = !settings.installed

  useEffect(() => {
    let active = true
    candidateRequest('/releases?channel=' + channel).then((data) => {
      if (!active) return
      setCatalog(data)
      setVersion(data.recommended_stable?.version ?? data.releases[0]?.version ?? '')
    }).catch((error) => {
      if (active) setMessage(error.message)
    })
    return () => { active = false }
  }, [channel])

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
      confirm_rc: channel === 'rc' && confirmed,
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
      <label className="field">Канал релиза
        <select value={channel} disabled={Boolean(pinnedVersion)} onChange={(event) => {
          setCatalog(null)
          setMessage('')
          setConfirmed(false)
          setChannel(event.target.value)
        }}>
          <option value="stable">Стабильные релизы</option>
          <option value="rc">Предварительные релизы (RC)</option>
        </select>
      </label>
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
          <select value={version} onChange={(event) => {
            setVersion(event.target.value)
            setConfirmed(false)
          }}>
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
      {channel === 'rc' && (
        <label className="checkbox-row">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          Подтверждаю выбор предварительного релиза
        </label>
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
        disabled={disabled || !available || (requiresIntermediate && !selected) || (channel === 'rc' && !confirmed)}>
        {install ? 'Установить DVT' : 'Подготовить обновление'}
      </button>
    </form>
  )
}
