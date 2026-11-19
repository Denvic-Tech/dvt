import { useEffect, useRef, useState } from 'react'
import { candidateRequest } from './candidateApi.js'
import { applicationOrigin, withHttpScheme } from './installSettings.js'
import { Icon } from './Wizard.jsx'

export default function CandidateReleaseForm({ settings, disabled, onSubmit, draft }) {
  const [catalog, setCatalog] = useState(null)
  const [version, setVersion] = useState(draft?.version ?? '')
  const [message, setMessage] = useState('')
  const install = !settings.installed
  const editable = Boolean(settings.install_dir_editable)
  const counter = useRef(0)
  const nextAddress = (value) => ({ value, id: counter.current++ })
  const [addresses, setAddresses] = useState(() =>
    (draft?.public_urls ?? (settings.public_urls?.length ? settings.public_urls : [settings.app_origin])).map(nextAddress))
  const focusId = useRef(null)
  const addressElements = useRef(new Map())
  useEffect(() => {
    if (focusId.current !== null) {
      addressElements.current.get(focusId.current)?.focus()
      focusId.current = null
    }
  }, [addresses])

  useEffect(() => {
    let active = true
    candidateRequest('/releases?channel=all').then((data) => {
      if (!active) return
      setCatalog(data)
      setVersion((current) => data.releases.some((row) => row.version === current)
        ? current : data.recommended_stable?.version ?? data.releases[0]?.version ?? '')
    }).catch(() => {
      if (active) setMessage('Каталог версий недоступен.')
    })
    return () => { active = false }
  }, [])

  const release = catalog?.releases.find((row) => row.version === version)
  const route = catalog?.paths?.[version] ?? []
  const selected = catalog?.first_steps?.[version]
    ?? catalog?.releases.find((row) => row.version === route[0])
  const available = selected ?? release
  const requiresIntermediate = route.length > 1

  function changeAddress(id, value) {
    setAddresses((rows) => rows.map((row) => row.id === id ? { ...row, value } : row))
  }

  function addAddress() {
    const row = nextAddress('http://')
    focusId.current = row.id
    setAddresses([...addresses, row])
  }

  function removeAddress(index) {
    const rows = addresses.filter((_, i) => i !== index)
    if (!rows.length) rows.push(nextAddress('http://'))
    focusId.current = rows[Math.min(index, rows.length - 1)].id
    setAddresses(rows)
  }

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
      const port = Number(fields.get('app_port'))
      data.app_port = port
      data.task_workers_count = Number(fields.get('workers'))
      data.ai_mcp_enabled = fields.has('ai_mcp')
    }
    if (install && editable) {
      const urls = []
      for (const { id, value } of addresses) {
        try { urls.push(applicationOrigin(value, data.app_port)) }
        catch {
          const input = addressElements.current.get(id)
          input.setCustomValidity('Введите адрес сервера, например http://dvt.example.ru.')
          input.reportValidity()
          return
        }
      }
      data.install_dir = fields.get('install_dir')
      data.public_urls = [...new Set(urls)]
    }
    onSubmit(data)
  }

  return <>
    <h1>{install ? 'Настройка установки' : 'Подготовка обновления'}</h1>
    {message && <p className="banner banner-error" role="alert">{message}</p>}
    {catalog?.catalog_error && !message && (
      <p className="banner banner-info" role="status">{catalog.releases.length
        ? 'Каталог версий недоступен. Показаны сохранённые версии.' : 'Каталог версий недоступен.'}</p>
    )}
    {catalog && !catalog.catalog_error && catalog.releases.length === 0 && <p role="status">Нет доступных версий.</p>}
    <form onSubmit={submit} className="wizard-card">
      {install && <div className="row address-row">
        <div className="caption">Адреса DVT<p className="hint" id="addr-hint">Укажите адрес сервера, например http://dvt.example.ru.</p></div>
        <div role="group" aria-label="Адреса DVT">
          <div id="addresses">
            {addresses.map(({ id, value }, index) => <div className="address" key={id}>
              <input value={value} type="text" inputMode="url" aria-label={`Адрес DVT ${index + 1}`}
                aria-describedby="addr-hint" placeholder="http://dvt.example.ru" required
                autoComplete="off" autoCapitalize="none" spellCheck={false} readOnly={!editable}
                ref={(input) => input ? addressElements.current.set(id, input) : addressElements.current.delete(id)}
                onChange={(event) => {
                  event.target.setCustomValidity('')
                  changeAddress(id, event.target.value)
                }}
                onBlur={() => { if (value.trim()) changeAddress(id, withHttpScheme(value.trim())) }} />
              {editable && <button className="icon-btn" type="button" aria-label="Удалить адрес" title="Удалить адрес"
                onClick={() => removeAddress(index)}><Icon name="cross" /></button>}
            </div>)}
          </div>
          {editable && <button type="button" className="add" onClick={addAddress}><Icon name="plus" />Добавить адрес</button>}
        </div>
      </div>}
      <div className="row">
        <label className="name" htmlFor="release-version">Версия DVT</label>
        <div className="select-wrap">
          <select id="release-version" value={version} disabled={!catalog?.releases.length}
            onChange={(event) => setVersion(event.target.value)}>
            {!catalog?.releases.length && <option value="">{catalog || message ? 'Нет доступных версий' : 'Загрузка…'}</option>}
            {catalog?.releases.map((row) => <option key={row.version} value={row.version}>
              {row.version}{row.version === catalog.recommended_stable?.version ? ' (рекомендуется)' : ''}
            </option>)}
          </select>
          <Icon name="chevron" />
        </div>
      </div>
      {requiresIntermediate && <div className="row"><span className="caption">Порядок обновления</span><span>{route.join(' → ')}</span></div>}
      {install && <>
        <div className="row">
          <label className="name" htmlFor="install-dir">Путь установки</label>
          <input id="install-dir" name="install_dir" defaultValue={draft?.install_dir ?? settings.install_dir ?? '/var/lib/dvt'}
            required pattern="/.*" title="Абсолютный путь, например /srv/dvt"
            autoComplete="off" autoCapitalize="none" spellCheck={false} readOnly={!editable} />
        </div>
        <div className="row">
          <label className="name" htmlFor="app-port">Порт приложения</label>
          <input id="app-port" type="number" name="app_port" min="1" max="65535" required defaultValue={draft?.app_port ?? settings.app_port ?? 80} />
        </div>
        <div className="row">
          <label className="name" htmlFor="workers">Число воркеров</label>
          <input id="workers" type="number" name="workers" min="1" required defaultValue={draft?.task_workers_count ?? 4} />
        </div>
        <div className="row switch-row">
          <label className="name" htmlFor="ai-mcp">Включить AI MCP</label>
          <span className="switch"><input id="ai-mcp" type="checkbox" name="ai_mcp" role="switch"
            defaultChecked={draft?.ai_mcp_enabled ?? false} /><span className="track" /></span>
        </div>
      </>}
      <footer className="actions"><button className="primary" type="submit"
        disabled={disabled || !available || (requiresIntermediate && !selected)}>
        {install ? 'Установить DVT' : 'Подготовить обновление'}
      </button></footer>
    </form>
  </>
}
