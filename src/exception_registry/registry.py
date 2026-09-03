from typing import TYPE_CHECKING, ClassVar, Dict, List, Optional

from src.exception_registry.exception_types import ExceptionType

if TYPE_CHECKING:
    from src.exception_registry.registered_exception import RegisteredException

class ExceptionRegistry:
    """
    Централизованный регистр ошибок
    """
    _instance: ClassVar[Optional['ExceptionRegistry']] = None
    _exceptions: Dict[int, 'RegisteredException'] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register_error(self, exc: 'RegisteredException') -> 'RegisteredException':
        """Зарегистрировать ошибку"""

        exception_hash = hash(exc)

        if exception_hash in self._exceptions:
            raise ValueError(f"Ошибка '{exc.name}' уже зарегистрирована")

        self._exceptions[exception_hash] = exc
        return exc

    def delete_error(self, name: str, code: str) -> bool:
        for k, v in self._exceptions.items():
            # Не обрабатываем HTTP_GENERATED Exceptions
            if v.code == code and v.name == name and v.type == ExceptionType.CUSTOM.value:
                self._exceptions.pop(k)
                return True
        else:
            return False

    def get_errors_by_filters(self, **filters) -> List['RegisteredException']:
        """
        Получить ошибки с фильтрацией по атрибутам ExceptionCode

        Args:
            **filters: Фильтры по атрибутам ExceptionCode (name, code, description, category)
        """
        res = self._exceptions.values()

        for attr_name, attr_value in filters.items():
            res = list(filter(lambda e: getattr(e, attr_name) == attr_value, res))
            # Если после фильтра res пустой, нет смысла дальше проверять
            if not res:
                return res
        return res

    @staticmethod
    def serialize_exceptions(errors: List['RegisteredException']) -> List | Dict:
        if len(errors) == 1:
            return errors[0].serialize()

        return [obj.serialize() for obj in errors]

    def list_serialized_errors(self) -> List:
        return [obj.serialize() for obj in self._exceptions.values()]

    def get_schemas(self):
        return [obj.response_model for obj in self._exceptions.values()]


ERROR_REGISTRY = ExceptionRegistry()
