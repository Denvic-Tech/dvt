import { useState } from 'react'

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

export default function CandidateOperation({ operation, disabled, act }) {
  const [confirmation, setConfirmation] = useState(null)
  const { plan } = operation
  return (
    <section className="card operator-form" aria-label="Операция">
      <h2>{operation.kind === 'install' ? 'Установка' : 'Операция DVT'} {operation.version}</h2>
      <dl className="operator-facts">
        <dt>ID операции</dt><dd><code>{operation.id}</code></dd>
        <dt>Последняя подтверждённая стадия</dt><dd aria-live="polite">{stages[operation.stage] ?? operation.stage}</dd>
        {operation.failure && <><dt>Причина</dt><dd role="alert">{failureMessage(operation.failure)}</dd></>}
      </dl>
      {plan && <details open={operation.stage === 'prepared'}>
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
