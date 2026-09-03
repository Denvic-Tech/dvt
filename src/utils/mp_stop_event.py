from multiprocessing.synchronize import Event as MpEvent


class MPStopEvent:
    """Адаптер под интерфейс asyncio.Event, который использует multiprocessing.Event."""

    def __init__(self, mp_event: MpEvent):
        self._ev = mp_event

    def is_set(self) -> bool:
        return self._ev.is_set()

    def set(self) -> None:
        self._ev.set()
