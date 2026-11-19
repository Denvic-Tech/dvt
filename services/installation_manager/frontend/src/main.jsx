import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import CandidateApp from './CandidateApp.jsx'
import './styles.css'
import './wizard.css'

function Entry() {
  const [mode, setMode] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/operations/active')
      .then(response => response.status === 404 ? 'legacy' : 'candidate')
      .catch(() => sessionStorage.getItem('dvt-candidate-operation') ? 'candidate' : 'legacy')
      .then(value => { if (!cancelled) setMode(value) })
    return () => { cancelled = true }
  }, [])

  if (!mode) return <p role="status">Подключение к мастеру…</p>
  return mode === 'candidate' ? <CandidateApp /> : <App />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Entry />
  </React.StrictMode>
)
