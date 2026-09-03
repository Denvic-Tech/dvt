import { useEffect, useState } from 'react'
import { getSecrets, startInstall } from '../api.js'

const EMPTY = {
  version: 'latest',
  public_urls: ['http://localhost'],
  postgres_user: 'dvt-user',
  postgres_db: 'DVT',
  postgres_password: '',
  valkey_password: '',
  valkey_db: '0',
  grpc_token: '',
  fernet_key: '',
  ai_mcp_enabled: false,
  ai_mcp_internal_secret: '',
  external_port: '80',
  task_workers_count: 1,
}

function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

function SecretField({ label, value, onChange, placeholder, onGenerate }) {
  const [visible, setVisible] = useState(false)
  return (
    <Field label={label} hint={placeholder}>
      <div className="secret-row">
        <input
          type={visible ? 'text' : 'password'}
          className="input mono"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
        />
        <button type="button" className="btn btn-small" onClick={() => setVisible(!visible)}>
          {visible ? '🙈' : '👁'}
        </button>
        <button type="button" className="btn btn-small" onClick={onGenerate} title="Сгенерировать">
          🎲
        </button>
      </div>
    </Field>
  )
}

export default function InstallForm({ initialConfig, onStarted }) {
  const [form, setForm] = useState(EMPTY)
  const [libDir, setLibDir] = useState('/var/lib/dvt')
  const [isUpdate, setIsUpdate] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!initialConfig) return
    setIsUpdate(Boolean(initialConfig.is_update))
    setLibDir(initialConfig.lib_dir || '/var/lib/dvt')
    setForm((prev) => ({
      ...prev,
      version: initialConfig.version || prev.version,
      public_urls: initialConfig.public_urls?.length ? initialConfig.public_urls : prev.public_urls,
      postgres_user: initialConfig.postgres_user || prev.postgres_user,
      postgres_db: initialConfig.postgres_db || prev.postgres_db,
      valkey_db: initialConfig.valkey_db ?? prev.valkey_db,
      external_port: initialConfig.external_port || prev.external_port,
      task_workers_count: initialConfig.task_workers_count || prev.task_workers_count,
      ai_mcp_enabled: Boolean(initialConfig.ai_mcp_enabled),
    }))
  }, [initialConfig])

  const set = (key) => (value) => setForm((prev) => ({ ...prev, [key]: value }))

  async function generate(field) {
    const secrets = await getSecrets()
    set(field)(field === 'fernet_key' ? secrets.fernet_key : secrets.password)
  }

  function setUrl(index, value) {
    setForm((prev) => {
      const urls = [...prev.public_urls]
      urls[index] = value
      return { ...prev, public_urls: urls }
    })
  }

  const addUrl = () =>
    setForm((prev) => ({ ...prev, public_urls: [...prev.public_urls, ''] }))
  const removeUrl = (index) =>
    setForm((prev) => ({
      ...prev,
      public_urls: prev.public_urls.filter((_, i) => i !== index),
    }))

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await startInstall({
        ...form,
        public_urls: form.public_urls.map((u) => u.trim()).filter(Boolean),
        task_workers_count: Number(form.task_workers_count) || 1,
      })
      onStarted()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const secretHint = isUpdate
    ? 'Пусто — сохранится текущее значение'
    : 'Пусто — сгенерируется автоматически'

  return (
    <form className="form" onSubmit={handleSubmit}>
      {error && <div className="banner banner-error">❌ {error}</div>}

      <section className="card">
        <h2>⚙️ Основные параметры</h2>
        <div className="grid-2">
          <Field label="Каталог данных" hint="Задаётся при запуске установщика (--dir)">
            <input className="input mono" value={libDir} disabled />
          </Field>
          <Field label="Версия DVT (tag образов)">
            <input
              className="input mono"
              value={form.version}
              onChange={(e) => set('version')(e.target.value)}
            />
          </Field>
          <Field label="Внешний порт">
            <input
              className="input"
              type="number"
              min="1"
              max="65535"
              value={form.external_port}
              onChange={(e) => set('external_port')(e.target.value)}
            />
          </Field>
          <Field label="Количество task-worker'ов">
            <input
              className="input"
              type="number"
              min="1"
              max="64"
              value={form.task_workers_count}
              onChange={(e) => set('task_workers_count')(e.target.value)}
            />
          </Field>
        </div>
      </section>

      <section className="card">
        <h2>🌐 Публичные URL</h2>
        <p className="section-hint">
          Если хотя бы один URL использует https://, будут включены secure-cookie.
        </p>
        {form.public_urls.map((url, i) => (
          <div className="url-row" key={i}>
            <input
              className="input mono"
              value={url}
              onChange={(e) => setUrl(i, e.target.value)}
              placeholder="http://localhost"
            />
            {form.public_urls.length > 1 && (
              <button type="button" className="btn btn-small" onClick={() => removeUrl(i)}>
                ✕
              </button>
            )}
          </div>
        ))}
        <button type="button" className="btn btn-ghost" onClick={addUrl}>
          + Добавить URL
        </button>
      </section>

      <section className="card">
        <h2>🗄️ PostgreSQL</h2>
        <div className="grid-2">
          <Field label="Пользователь">
            <input
              className="input mono"
              value={form.postgres_user}
              onChange={(e) => set('postgres_user')(e.target.value)}
            />
          </Field>
          <Field label="База данных">
            <input
              className="input mono"
              value={form.postgres_db}
              onChange={(e) => set('postgres_db')(e.target.value)}
            />
          </Field>
        </div>
        <SecretField
          label="Пароль PostgreSQL"
          value={form.postgres_password}
          onChange={set('postgres_password')}
          placeholder={secretHint}
          onGenerate={() => generate('postgres_password')}
        />
      </section>

      <section className="card">
        <h2>🗄️ Valkey</h2>
        <Field label="Номер базы">
          <input
            className="input mono"
            value={form.valkey_db}
            onChange={(e) => set('valkey_db')(e.target.value)}
          />
        </Field>
        <SecretField
          label="Пароль Valkey"
          value={form.valkey_password}
          onChange={set('valkey_password')}
          placeholder={secretHint}
          onGenerate={() => generate('valkey_password')}
        />
      </section>

      <section className="card">
        <h2>🔐 Токены сервисов</h2>
        <SecretField
          label="Токен gRPC Forward Service"
          value={form.grpc_token}
          onChange={set('grpc_token')}
          placeholder={secretHint}
          onGenerate={() => generate('grpc_token')}
        />
        <SecretField
          label="Fernet-ключ"
          value={form.fernet_key}
          onChange={set('fernet_key')}
          placeholder={secretHint}
          onGenerate={() => generate('fernet_key')}
        />
      </section>

      <section className="card">
        <h2>🤖 AI MCP</h2>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={form.ai_mcp_enabled}
            onChange={(e) => set('ai_mcp_enabled')(e.target.checked)}
          />
          <span>Включить пользовательский AI MCP сервер</span>
        </label>
        <p className="section-hint">
          По умолчанию сервис выключен и его Docker-контейнер не запускается.
        </p>
        {form.ai_mcp_enabled && (
          <SecretField
            label="Внутренний секрет AI MCP"
            value={form.ai_mcp_internal_secret}
            onChange={set('ai_mcp_internal_secret')}
            placeholder={secretHint}
            onGenerate={() => generate('ai_mcp_internal_secret')}
          />
        )}
      </section>

      <div className="submit-row">
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Запуск…' : isUpdate ? '🚀 Переустановить DVT' : '🚀 Запустить DVT'}
        </button>
      </div>
    </form>
  )
}
