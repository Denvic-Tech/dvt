import { useEffect, useRef, useState } from 'react'
import { candidateRequest } from './candidateApi.js'
import celebrate from './celebrate.js'
import { Icon } from './Wizard.jsx'

const stages = {
  admitted: 'Операция сохранена',
  preparing: 'Подготовка комплекта',
  prepared: 'Комплект проверен, можно применить',
  maintenance: 'Окно обслуживания',
  backup: 'Подготовка резервной копии',
  migrating: 'Миграция базы данных',
  applying: 'Применение комплекта',
  verifying: 'Проверка готовности',
  recovering: 'Восстановление',
  resuming: 'Подтверждение возобновления',
  recovery_required: 'Требуется восстановление',
  succeeded: 'Операция завершена',
  cancelled: 'Операция отменена',
  failed: 'Операция завершилась ошибкой',
}
const labels = {
  apply: 'Применить обновление',
  resume: 'Продолжить операцию',
  cancel_preparation: 'Отменить подготовку',
  extend_maintenance: 'Продлить ожидание задач',
  defer_maintenance: 'Отложить обслуживание',
  recover_manager: 'Восстановить доступ к мастеру',
  return_to_source: 'Вернуть прежний комплект',
  restore_start: 'Запустить восстановленный DVT',
}
const failures = {
  executor_unavailable: 'Не удалось запустить установку. Проверьте доступность Docker и повторите попытку.',
  distributor_unavailable: 'Distributor недоступен. Проверьте соединение с каталогом.',
  tls: 'Ошибка TLS. Проверьте доверенный CA, имя сервера и часы хоста.',
  registry_unavailable: 'Registry недоступен. Проверьте сеть и доступ к Registry.',
  disk_space: 'Недостаточно места. Освободите место и продолжите ту же операцию.',
  inodes: 'Недостаточно inode. Освободите ресурсы файловой системы.',
  incompatible_release: 'Релиз несовместим с рабочей версией. Проверьте путь перехода.',
  incompatible_schema: 'Схема базы не совпадает с ожидаемой. Откройте диагностику.',
  compose: 'Проверка Compose не пройдена. Откройте диагностику.',
  database_unavailable: 'База данных не ответила. Проверьте состояние PostgreSQL.',
  migration: 'Миграция завершилась ошибкой. Откройте диагностику.',
  gateway_unavailable: 'Gateway не подтвердил готовность. Откройте диагностику.',
  invalid_package: 'Комплект или его подпись не прошли проверку. Проверьте источник релиза.',
  profile_unhealthy: 'Сервис включённого профиля не подтвердил готовность.',
  backup: 'Не удалось проверить резервную копию. Откройте диагностику.',
  manager_unavailable: 'Мастер не подтвердил состояние журнала. Повторно откройте его защищённый адрес.',
  maintenance_drain_timeout: 'Активные задачи ещё выполняются. Продлите ожидание или отложите обслуживание.',
}
export const failureMessage = (code) => failures[code] ?? `Код причины: ${code}. Откройте диагностику.`
export const terminalStages = new Set(['succeeded', 'cancelled', 'failed'])
const needsConfirmation = new Set(['apply', 'return_to_source', 'restore_start'])
const gib = (bytes) => (bytes / 1024 ** 3).toFixed(2)

function OperationActions({ operation, disabled, act }) {
  const [confirmation, setConfirmation] = useState(null)
  const { plan } = operation
  if (!operation.actions?.length && !operation.failure) return null
  if (operation.kind === 'install' && ['admitted', 'preparing', 'prepared'].includes(operation.stage)
      && !operation.failure) return null
  return (
    <section className="wizard-card operator-form" aria-label="Действия">
      {operation.failure && <p role="alert">{failureMessage(operation.failure)}</p>}
      {plan && operation.kind !== 'install' && <details open={operation.stage === 'prepared'}>
        <summary>План операции</summary>
        <dl className="operator-facts">
          {plan.source_version && <><dt>Фактическая версия и схема</dt><dd>{plan.source_version} · {plan.source_revision}</dd></>}
          <dt>Целевая версия и схема</dt><dd>{plan.target_version} · {plan.target_revision}</dd>
          <dt>Манифест</dt><dd><code>{operation.manifest_digest}</code></dd>
          <dt>Добавить</dt><dd>{plan.add.join(', ') || '—'}</dd>
          <dt>Пересоздать</dt><dd>{plan.recreate.join(', ') || '—'}</dd>
          <dt>Убрать</dt><dd>{plan.retire.join(', ') || '—'}</dd>
          <dt>Образы с распаковкой, до</dt><dd>{gib(plan.pull_and_unpack_bytes)} ГиБ</dd>
          <dt>Резерв под данные</dt><dd>{gib(plan.data_reserve_bytes)} ГиБ</dd>
        </dl>
        {plan.source_version && (
          <p>Окно обслуживания включает ожидание задач до {plan.maintenance_drain_seconds} с,
            создание копии, миграцию и проверку готовности. Активные задачи завершаются.
            Непринятые корневые запуски отменяются. Плановые запуски в окне пропускаются,
            существующие повторы сохраняются.</p>
        )}
      </details>}
      <div className="operator-actions">
        {operation.actions.filter((action) => action in labels).map((action) => (
          <button className="btn btn-secondary" key={action} disabled={disabled} onClick={() => {
            if (needsConfirmation.has(action)) setConfirmation(action)
            else act(action, false)
          }}>{labels[action]}</button>
        ))}
      </div>
      {confirmation && operation.actions.includes(confirmation) && (
        <div className="banner banner-info" role="group" aria-label="Подтверждение действия">
          <p>{confirmation === 'apply'
            ? 'Начать окно обслуживания? DVT временно перестанет принимать новые запуски.'
            : 'Восстановление может потерять записи после создания резервной копии. Внешние изменения не откатываются.'}</p>
          <div className="operator-actions">
            <button className="btn btn-primary" disabled={disabled} onClick={() => {
              act(confirmation, true)
              setConfirmation(null)
            }}>Подтвердить действие</button>
            <button className="btn btn-secondary" onClick={() => setConfirmation(null)}>Назад</button>
          </div>
        </div>
      )}
      <a href={`/api/operator/operations/${operation.id}/diagnostics`} download={`dvt-${operation.id}.json`}>
        Скачать диагностику
      </a>
    </section>
  )
}

const installStages = [
  ['Подготовка', ['admitted']],
  ['Загрузка образов', ['preparing', 'prepared']],
  ['Настройка базы данных', ['migrating']],
  ['Запуск сервисов', ['applying']],
  ['Проверка доступности', ['verifying', 'resuming']],
]
const updateStages = [
  ['Подготовка', ['admitted', 'preparing', 'prepared']],
  ['Окно обслуживания', ['maintenance']],
  ['Резервная копия', ['backup']],
  ...installStages.slice(2),
]
const recoveryStages = [
  ['Подготовка', ['admitted', 'preparing', 'prepared']],
  ['Восстановление', ['recovering', 'recovery_required']],
  ['Проверка доступности', ['verifying', 'resuming']],
]
const operationDisplay = {
  install: { title: 'Установка DVT', success: 'DVT установлен', label: 'установки', rows: installStages },
  update: { title: 'Обновление DVT', success: 'DVT обновлён', label: 'обновления', rows: updateStages },
  manager_recovery: {
    title: 'Восстановление доступа к мастеру', success: 'Доступ к мастеру восстановлен',
    label: 'восстановления доступа', rows: recoveryStages,
  },
  restore: {
    title: 'Восстановление DVT', success: 'DVT восстановлен',
    label: 'восстановления', rows: recoveryStages,
  },
}
const stateLabels = { pending: 'В ожидании', active: 'Выполняется', done: 'Готово', failed: 'Ошибка' }
const timeFormat = new Intl.DateTimeFormat('ru-RU', { timeStyle: 'medium' })
const formatTime = (line) => line.at ? timeFormat.format(new Date(line.at)) : ''

function useOperationFeed(id) {
  const [entries, setEntries] = useState([])
  const [checkpoints, setCheckpoints] = useState([])
  useEffect(() => {
    if (!id) return
    let stopped = false
    let timer
    let eventCursor = 0
    let logCursor = 0
    async function poll() {
      const [events, logs] = await Promise.allSettled([
        candidateRequest(`/operations/${id}/events?after=${eventCursor}`),
        candidateRequest(`/operator/operations/${id}/log?after=${logCursor}&limit=100`),
      ])
      if (stopped) return
      if (events.status === 'fulfilled' && events.value.length) {
        eventCursor = events.value.at(-1).cursor
        setCheckpoints((previous) => [...previous, ...events.value.map((event) => event.checkpoint?.stage ?? event.stage).filter(Boolean)])
      }
      if (logs.status === 'fulfilled' && logs.value.lines.length) {
        logCursor = logs.value.next_cursor
        setEntries((previous) => [...previous, ...logs.value.lines])
      }
      const hasMore = logs.value?.lines.length === 100 || events.value?.length === 100
      timer = setTimeout(poll, hasMore ? 0 : 1000)
    }
    poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [id])
  return { entries, checkpoints }
}

function downloadLogs(text) {
  const link = document.createElement('a')
  const url = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain;charset=utf-8' }))
  link.href = url
  link.download = 'dvt-installation.log'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function copyLogs(text, button) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return true }
    catch { /* HTTP installations can use selection-based copying. */ }
  }
  const buffer = document.createElement('textarea')
  buffer.className = 'sr'
  buffer.value = text
  document.body.append(buffer)
  buffer.select()
  try { return document.execCommand('copy') }
  finally { buffer.remove(); button.focus() }
}

export default function CandidateOperation({ operation, disabled, act, settings, openSetup, onBack }) {
  const { entries, checkpoints } = useOperationFeed(operation.id)
  const following = useRef(true)
  const [copyStatus, setCopyStatus] = useState('')
  const terminal = useRef(null)
  const open = useRef(null)
  const heading = useRef(null)
  const celebrated = useRef(false)
  const copyTimer = useRef(null)
  const installation = operation.kind === 'install'
  const success = operation.stage === 'succeeded'
  const display = operationDisplay[operation.kind] ?? operationDisplay.update
  const title = success ? display.success : display.title
  const terminalMessage = ['failed', 'cancelled'].includes(operation.stage) ? stages[operation.stage] : ''
  const text = entries.map((line) => line.at ? `[${formatTime(line)}] ${line.message}` : line.message).join('\n')
  const setupPending = installation && success && !settings?.installed
  const canOpen = success && settings?.app_origin && !setupPending

  useEffect(() => { heading.current?.focus() }, [])
  useEffect(() => () => clearTimeout(copyTimer.current), [])
  useEffect(() => {
    if (following.current && terminal.current) terminal.current.scrollTop = terminal.current.scrollHeight
  }, [entries])
  useEffect(() => {
    if (canOpen && open.current && !celebrated.current) {
      celebrate(open.current)
      celebrated.current = true
    }
  }, [canOpen])

  async function copy(event) {
    const copied = await copyLogs(text, event.currentTarget).catch(() => false)
    setCopyStatus(copied ? 'copied' : 'error')
    clearTimeout(copyTimer.current)
    if (copied) copyTimer.current = setTimeout(() => setCopyStatus(''), 1800)
  }

  const { rows } = display
  const current = rows.findIndex(([, ids]) => ids.includes(operation.stage))
  const lastObserved = rows.findLastIndex(([, ids]) => ids.some((id) => checkpoints.includes(id)))
  const failed = ['failed', 'recovery_required'].includes(operation.stage)
  const recovering = ['recovering', 'recovery_required'].includes(operation.stage)
  return <>
    <div className="heading">
      <h1 tabIndex={-1} ref={heading}>{title}</h1>
      {canOpen && (settings.setup_required
        ? <button ref={open} id="open-dvt" className="primary" disabled={disabled} onClick={openSetup}>Открыть DVT</button>
        : <a ref={open} id="open-dvt" className="primary" href={settings.app_origin} target="_blank" rel="noopener noreferrer">Открыть DVT</a>)}
    </div>
    {terminalMessage && <p className="banner banner-info" role="status">{terminalMessage}</p>}
    <div className="columns">
      <section className="wizard-card">
        <div className="panel-head"><h2>Журнал {display.label}</h2>
          <div className="tools">
            <button type="button" className="icon-btn" aria-label="Скопировать логи"
              title="Скопировать логи" disabled={!entries.length} onClick={copy}><Icon name={copyStatus === 'copied' ? 'check' : 'copy'} /></button>
            <button type="button" className="icon-btn" aria-label="Скачать логи"
              title="Скачать логи" disabled={!entries.length} onClick={() => downloadLogs(text)}><Icon name="download" /></button>
          </div>
        </div>
        <div ref={terminal} className="terminal" role="log" aria-live="off" aria-label="Логи" tabIndex={0}
          onScroll={(event) => {
            const box = event.currentTarget
            following.current = box.scrollTop + box.clientHeight >= box.scrollHeight - 8
          }}>
          {!entries.length && <span>Ожидание вывода…</span>}
          {entries.map((line) => <div key={line.cursor} className="log-line">
            {line.at && <time dateTime={line.at}>{formatTime(line)}</time>}
            <span className={line.at ? '' : 'log-message'}>{line.message}</span>
          </div>)}
        </div>
        {copyStatus === 'error' && <p className="banner banner-error" role="alert">Не удалось скопировать логи.</p>}
        <span className="sr" role="status">{copyStatus === 'copied' ? 'Логи скопированы' : ''}</span>
      </section>
      <section className="wizard-card">
        <div className="panel-head"><h2>Этапы {display.label}</h2></div>
        <ol className="wizard-stages">
          {rows.map(([label], index) => {
            const status = success || index < (current >= 0 ? current : lastObserved) ? 'done'
              : failed && (current === index || (!recovering && index === Math.max(lastObserved, 0))) ? 'failed'
                : current === index || (!operation.id && index === 0) ? 'active' : 'pending'
            return <li className={`stage ${status}`} key={label}>
              <span className="mark" aria-hidden="true" /><div><strong>{label}</strong><small>{stateLabels[status]}</small></div>
            </li>
          })}
          {recovering && current < 0 && <li className={`stage ${failed ? 'failed' : 'active'}`}>
            <span className="mark" aria-hidden="true" /><div><strong>Восстановление</strong><small>{stages[operation.stage]}</small></div>
          </li>}
        </ol>
      </section>
    </div>
    {operation.id && <OperationActions operation={operation} disabled={disabled} act={act} />}
    {terminalStages.has(operation.stage) && !setupPending && !settings?.setup_required &&
      <div className="operator-actions"><button className="btn" onClick={onBack}>Назад</button></div>}
  </>
}
