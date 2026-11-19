import logo from './denvic.svg'

export function WizardHeader() {
  return <header className="wizard-header"><div className="bar">
    <span className="brand"><img alt="" src={logo} />
      <span className="wordmark"><span>Denvic</span><strong>Visual Transformer</strong></span>
    </span>
    <span className="context">Мастер установки</span>
  </div></header>
}

const artwork = {
  plus: <path d="M12 5v14M5 12h14" />,
  cross: <path d="m6 6 12 12M6 18 18 6" />,
  chevron: <path d="m6 9 6 6 6-6" />,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2" /><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></>,
  download: <path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4" />,
  check: <path d="m4 12 5 5L20 6" />,
}

export function Icon({ name }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{artwork[name]}</svg>
}
