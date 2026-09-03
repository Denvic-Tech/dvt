import traceback
from typing import Optional, Callable, Coroutine, Any

from src.logger import logger
from src.schemas.event import ProgressEvent, EventBase

SendMessageCallback = Callable[[EventBase, Optional[str], Optional[str]], Coroutine[Any, Any, None]]


class ProgressBar:
    """
    Класс для управления и отображения прогресса выполнения конкретного узла.
    """

    def __init__(
            self,
            total: int,
            task_id: str,
            node_id: str,
            client_id: Optional[str],
            send_message_callback: Optional[SendMessageCallback]
    ):
        """
        Инициализирует прогресс-бар для узла.
        Args:
            total: Общее количество шагов/элементов.
            task_id: ID задачи.
            node_id: ID узла.
            client_id: ID клиента для отправки сообщений.
            send_message_callback: Callback для отправки WebSocket сообщений.
        """
        if total <= 0:
            logger.warning(
                f"Progress bar for node {node_id} initialized with non-positive total value ({total}). Setting to 1.")
            total = 1
        self.total = total
        self.current = 0
        self.task_id = task_id
        self.node_id = node_id
        self.client_id = client_id
        self.send_message_callback = send_message_callback
        self._last_sent_value = -1  # Чтобы не отправлять одинаковые значения подряд

        # Отправляем начальное состояние (0%)
        self._send_update()

    async def _send_update(self, force: bool = False):
        """Отправляет сообщение о прогрессе через callback, если значение изменилось."""
        if not self.send_message_callback:
            logger.warning("send_message_callback is not configured in ProgressBar. Skipping progress update.")
            return

        if not self.client_id:
            logger.warning("user_id is not configured in ProgressBar. Skipping progress update.")
            return

        # Отправляем только если значение изменилось или если это принудительная отправка
        if self.current != self._last_sent_value or force:
            progress_message = ProgressEvent(
                value=self.current,
                max=self.total,
                task_id=self.task_id,
                node_id=self.node_id
            )
            try:
                await self.send_message_callback(progress_message, self.client_id)
                self._last_sent_value = self.current
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error in progress bar hook for node ID={self.node_id}: {e}")

    async def update_absolute(self, value: int, total: Optional[int] = None):
        """Обновляет прогресс-бар до абсолютного значения."""
        if total is not None:
            if total <= 0:
                logger.warning(
                    f"Progress bar total for node ID={self.node_id} updated to non-positive value ({total}). "
                    f"Setting to 1.")
                total = 1
            self.total = total
        self.current = max(0, min(value, self.total))
        await self._send_update()

    async def update(self, value_increment: int):
        """Увеличивает прогресс на указанное значение."""
        await self.update_absolute(self.current + value_increment)

    async def finish(self):
        """Устанавливает прогресс в 100% и отправляет финальное сообщение."""
        await self.update_absolute(self.total)
        # Гарантированно отправляем 100%
        await self._send_update(force=True)

    # --- Итератор для удобства использования в циклах ---
    def __aiter__(self):
        self._iter_index = 0
        # Отправляем 0% при начале итерации (неблокирующе)
        # asyncio.create_task(self.update_absolute(0)) # Убрано, т.к. итератор может использоваться в синхронном коде узла
        return self

    async def __anext__(self):
        if self._iter_index < self.total:
            # Обновляем перед возвратом значения
            await self.update_absolute(self._iter_index + 1)
            current_iter_index = self._iter_index
            self._iter_index += 1
            return current_iter_index
        else:
            # Гарантируем отправку 100% при завершении итерации
            await self.finish()
            raise StopAsyncIteration

    def __len__(self):
        return self.total


class ProgressBarManager:
    """
    Управляет созданием и отображением общего прогресса выполнения пайплайна.
    """
    PROGRESS_BAR_ENABLED: bool = True  # Глобальный флаг

    def __init__(
            self,
            task_id: str,
            user_id: Optional[str],
            project_id: Optional[str],
            send_message_callback: Optional[SendMessageCallback]
    ):
        self.total_steps: Optional[int] = None
        self.current_step = 0
        self.task_id = task_id
        self.user_id = user_id
        self.project_id = project_id
        self.send_message_callback = send_message_callback
        self._last_sent_value = -1

        logger.debug(f"ProgressBarManager initialized.")

    @classmethod
    def set_enabled(cls, enabled: bool):
        """Включает или отключает глобальный прогресс-бар."""
        cls.PROGRESS_BAR_ENABLED = enabled
        logger.info(f"Progress bar {'enabled' if enabled else 'disabled'}.")

    async def _send_update(self, force: bool = False):
        """Отправляет общее сообщение о прогрессе."""
        if not self.PROGRESS_BAR_ENABLED:
            return

        if not self.send_message_callback:
            return

        if not self.user_id:
            logger.warning("user_id is not set in ProgressBarManager. Skipping progress update.")
            return

        if self.current_step != self._last_sent_value or force:
            progress_message = ProgressEvent(
                value=self.current_step,
                max=self.total_steps,
                task_id=self.task_id,
                node_id=None  # Общий прогресс, без конкретного узла
            )
            try:
                await self.send_message_callback(progress_message, user_id=self.user_id, project_id=self.project_id)
                self._last_sent_value = self.current_step
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error sending overall progress update for task ID={self.task_id}: {e}")

    async def start(self, total_steps: int):
        """Устанавливает прогресс в 0% и отправляет начальное сообщение."""
        if total_steps <= 0:
            logger.warning(
                f"ProgressBarManager for task {self.task_id} initialized with non-positive total steps ({total_steps}). Setting to 1.")
            total_steps = 1

        self.total_steps = total_steps
        self.current_step = 0
        await self._send_update()

    async def update_step(self):
        """Увеличивает текущий шаг выполнения и отправляет обновление."""
        if self.current_step < self.total_steps:
            self.current_step += 1
            await self._send_update()
        else:
            logger.warning(f"Attempted to update progress beyond total steps for task ID={self.task_id}.")

    async def finish(self):
        """Устанавливает прогресс в 100% и отправляет финальное сообщение."""
        self.current_step = self.total_steps
        await self._send_update(force=True)  # Гарантированно отправляем 100%

    def get_node_progress_bar(self, node_id: str, node_total: int) -> ProgressBar:
        """
        Создает и возвращает ProgressBar для конкретного узла.
        Этот прогресс-бар будет отправлять свои обновления независимо.
        """
        return ProgressBar(
            total=node_total,
            task_id=self.task_id,
            node_id=node_id,
            client_id=self.user_id,
            send_message_callback=self.send_message_callback
        )
