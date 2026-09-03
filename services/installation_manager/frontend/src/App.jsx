import { useCallback, useEffect, useState } from 'react'
import { getConfig, getState } from './api.js'
import InstallForm from './components/InstallForm.jsx'
import UpdateScreen from './components/UpdateScreen.jsx'
import ProgressView from './components/ProgressView.jsx'

// view: loading | update | install | progress
export default function App() {
  const [view, setView] = useState('loading')
  const [state, setState] = useState(null)
  const [config, setConfig] = useState(null)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    setError('')
    try {
      const [st, cfg] = await Promise.all([getState(), getConfig()])
      setState(st)
      setConfig(cfg)
      setView(st.installed || st.running ? 'update' : 'install')
    } catch (e) {
      setError(`Бэкенд сервиса недоступен: ${e.message}`)
      setView('install')
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const onJobStarted = useCallback(() => setView('progress'), [])

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <span className="logo">🚀</span>
          <div>
            <h1>DVT — установка и обновление</h1>
            <p className="subtitle">
              {state?.installed
                ? `Установлен: версия ${state.current_version || '—'} · ${state.lib_dir}`
                : state?.running
                  ? 'DVT запущен на этой машине'
                  : 'Продукт ещё не установлен на этой машине'}
            </p>
          </div>
        </div>
      </header>

      <main className="main">
        {view === 'loading' && <div className="card center">Загрузка…</div>}

        {view !== 'loading' && view !== 'progress' && (
          <>
            {state && !state.docker_available && (
              <div className="banner banner-error">
                ❌ Docker недоступен. Убедитесь, что Docker запущен на этой машине.
              </div>
            )}
            {error && <div className="banner banner-error">❌ {error}</div>}
          </>
        )}

        {view === 'update' && (
          <UpdateScreen
            state={state}
            config={config}
            onStarted={onJobStarted}
            onReinstall={() => setView('install')}
          />
        )}

        {view === 'install' && (
          <>
            {config?.is_update && (
              <div className="banner banner-info">
                ⚙️ Обнаружена существующая установка. Текущие значения подставлены,
                пустые секреты будут сохранены.{' '}
                <button className="link-btn" onClick={() => setView('update')}>
                  ← Вернуться к обновлению
                </button>
              </div>
            )}
            <InstallForm initialConfig={config} onStarted={onJobStarted} />
          </>
        )}

        {view === 'progress' && <ProgressView onBack={reload} />}
      </main>
    </div>
  )
}
