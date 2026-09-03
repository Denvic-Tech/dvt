# Exception Registry

Централизованная система управления исключениями для DVT. Обеспечивает единообразную обработку ошибок, автоматическую регистрацию, сериализацию и генерацию OpenAPI схем для FastAPI.

## Зачем нужно

### Проблемы, которые решает:

1. **Отсутствие единого формата ошибок** - каждое исключение возвращает данные в своем формате
2. **Сложность документирования API** - нет автоматической генерации схем ошибок для OpenAPI
3. **Дублирование кода** - повторяющаяся логика обработки исключений в хэндлерах
4. **Отсутствие централизованного реестра** - невозможно получить список всех возможных ошибок системы
5. **Несогласованная категоризация** - ошибки не группируются по модулям/сервисам

### Что предоставляет:

- ✅ Единый формат сериализации исключений (name, code, description, category, type)
- ✅ Автоматическую регистрацию исключений при объявлении класса
- ✅ Генерацию Pydantic моделей для FastAPI responses
- ✅ Централизованный реестр всех исключений системы
- ✅ Категоризацию по сервисам и модулям
- ✅ Поддержку как обычных Exception, так и HTTPException
- ✅ Интеграцию с FastAPI exception handlers

## Структура модуля

```
exception_registry/
├── __init__.py
├── registered_exception.py     # Базовые классы RegisteredException, RegisteredHTTPException
├── registry.py                 # ExceptionRegistry - синглтон-реестр
├── exception_types.py          # Енумы ExceptionCategory, ExceptionType
├── handlers.py                 # FastAPI exception handler
├── utils.py                    # Декораторы и утилиты
├── schema.py                   # Pydantic схемы
└── errors_list/                # Определения кастомных исключений
    └── gateway/
        ├── admin.py
        ├── exception_registry.py
        └── ...
```

## Базовое использование

### 1. Создание кастомного исключения

Самый простой способ - наследоваться от `RegisteredException`:

```python
from src.exception_registry.registered_exception import RegisteredException
from src.exception_registry.exception_types import ExceptionCategory


class UserNotFoundException(RegisteredException):
    name = "USER_NOT_FOUND"
    code = "USER_404"
    description = "Пользователь не найден"
    category = ExceptionCategory.SERVICE_GATEWAY_ADMIN.value
```

**Важно:**
- `name` - уникальное имя ошибки (обычно UPPER_SNAKE_CASE)
- `code` - код ошибки (например, "USER_404")
- `description` - человекочитаемое описание на русском
- `category` - категория из `ExceptionCategory` enum (для группировки)

Исключение **автоматически регистрируется** в `ERROR_REGISTRY` при определении класса благодаря `__init_subclass__`.

### 2. Рейз исключения

```python
# Без дополнительных данных
raise UserNotFoundException()

# С дополнительным описанием
raise UserNotFoundException(description="Пользователь с ID=123 не найден")
```

При инициализации можно передать `description`, который перезапишет дефолтное описание и сохранится в `exc_data`.

### 3. HTTP исключения

Для исключений, которые должны возвращать HTTP статус-коды, используйте `RegisteredHTTPException`:

```python
from src.exception_registry.registered_exception import RegisteredHTTPException
from src.exception_registry.exception_types import ExceptionCategory


class ProjectNotFoundHTTP(RegisteredHTTPException):
    name = "PROJECT_NOT_FOUND"
    code = "PROJECT_404"
    description = "Проект не найден"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value
```

Рейз с указанием статус-кода:

```python
# HTTP 404
raise ProjectNotFoundHTTP(
    status_code=404,
    detail="Проект с ID=456 не найден"
)

# HTTP 403
raise ProjectNotFoundHTTP(
    status_code=403,
    detail="Нет прав доступа к проекту"
)
```

`RegisteredHTTPException` наследуется от `fastapi.HTTPException`, поэтому поддерживает все его параметры (status_code, detail, headers).

## Продвинутое использование

### 1. Использование декораторов

Если у вас уже есть существующий класс исключения, можно обернуть его декоратором:

```python
from src.exception_registry.utils import register_custom_exception, register_http_exception
from src.exception_registry.exception_types import ExceptionCategory


# Для обычных исключений
@register_custom_exception(
    exc_name="DATABASE_CONNECTION_ERROR",
    exc_code="DB_500",
    exc_description="Ошибка подключения к базе данных",
    exc_category=ExceptionCategory.DB.value
)
class DatabaseConnectionError(Exception):
    pass


# Для HTTP исключений
@register_http_exception(
    exc_name="UNAUTHORIZED_ACCESS",
    exc_code="AUTH_401",
    exc_description="Неавторизованный доступ",
    exc_category=ExceptionCategory.SERVICE_GATEWAY_ADMIN.value
)
class UnauthorizedAccess(Exception):
    pass
```

Декораторы автоматически:
- Создают обертку вокруг класса (`RegisteredExceptionWrapper` / `RegisteredHTTPExceptionWrapper`)
- Регистрируют в глобальном namespace (для корректной работы с pickle в многопоточности)
- Обновляют `response_model`

### 2. Работа с реестром

```python
from src.exception_registry.registry import ERROR_REGISTRY


# Получить все ошибки определенной категории
gateway_errors = ERROR_REGISTRY.get_errors_by_filters(
    category=ExceptionCategory.SERVICE_GATEWAY_ADMIN.value
)

# Найти конкретную ошибку по коду
error = ERROR_REGISTRY.get_errors_by_filters(code="USER_404")

# Получить все зарегистрированные ошибки в виде списка
all_errors = ERROR_REGISTRY.list_serialized_errors()

# Получить все Pydantic модели для OpenAPI схем
schemas = ERROR_REGISTRY.get_schemas()

# Удалить ошибку из реестра (только для CUSTOM типа)
ERROR_REGISTRY.delete_error(name="USER_NOT_FOUND", code="USER_404")
```

### 3. Сериализация исключений

```python
# Сериализация одного исключения
class MyError(RegisteredException):
    name = "MY_ERROR"
    code = "ERR_001"
    description = "Моя ошибка"
    category = ExceptionCategory.UNKNOWN.value

error = MyError(description="Детальное описание")
serialized = error.serialize()

# Результат:
# {
#     'name': 'MY_ERROR',
#     'code': 'ERR_001',
#     'description': 'Моя ошибка',
#     'category': 'UNKNOWN',
#     'type': 'CUSTOM',
#     'exc_data': 'Детальное описание'
# }

# Сериализация списка исключений
errors = [MyError(), AnotherError()]
serialized_list = ERROR_REGISTRY.serialize_exceptions(errors)
```

### 4. Интеграция с FastAPI

В Gateway уже настроен глобальный exception handler:

```python
from fastapi import FastAPI
from src.exception_registry.handlers import exception_handler

app = FastAPI()

# Регистрация хэндлера для всех Exception
app.add_exception_handler(Exception, exception_handler)
```

Handler автоматически:
- Распознает `RegisteredException` и `RegisteredHTTPException`
- Сериализует их в единый формат
- Возвращает JSONResponse с правильным статус-кодом
- Обрабатывает незарегистрированные исключения, создавая временные `UnknownHTTPException`

### 5. Добавление метаданных к response model

Можно обновить Pydantic модель для OpenAPI документации:

```python
class MyError(RegisteredException):
    name = "MY_ERROR"
    code = "ERR_001"
    description = "Моя ошибка"
    category = ExceptionCategory.UNKNOWN.value

# Добавить дополнительные поля в модель
MyError.update_response_model(
    example="Пример значения",
    deprecated=True
)
```

## Категории исключений

Доступные категории в `ExceptionCategory`:

```python
class ExceptionCategory(Enum):
    # База данных
    DB = 'DATABASE'
    DATAFRAME = "DATAFRAME"

    # Gateway сервис
    SERVICE_GATEWAY_ADMIN = "GATEWAY_ADMIN"
    SERVICE_GATEWAY_EXCEPTION_REGISTRY = "GATEWAY_EXCEPTION_REGISTRY"
    SERVICE_GATEWAY_INTERNAL = "GATEWAY_INTERNAL"
    SERVICE_GATEWAY_PROJECT = "GATEWAY_PROJECT"
    SERVICE_GATEWAY_TASK = "GATEWAY_PROJECT"
    SERVICE_GATEWAY_PUBLIC = "GATEWAY_PUBLIC"
    SERVICE_GATEWAY_STORAGE = "GATEWAY_STORAGE"
    SERVICE_GATEWAY_UTILS = "GATEWAY_UTILS"
    SERVICE_GATEWAY_QUEUE = "GATEWAY_QUEUE"
    SERVICE_GATEWAY_WS = "GATEWAY_WS"

    # Task Worker
    SERVICE_TASK_WORKER_CACHE = "TASK_WORKER_CACHE"
    SERVICE_TASK_WORKER_TASKS = "TASK_WORKER_TASKS"

    # Другое
    WORKER_CLIENT = "WORKER_CLIENT"
    S3 = "S3"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "UNKNOWN"
```

## Типы исключений

```python
class ExceptionType(Enum):
    CUSTOM = 'CUSTOM'                 # Созданные разработчиком
    HTTP_GENERATED = 'HTTP_GENERATED' # Сгенерированные хэндлером автоматически
```

## Примеры из кодовой базы

### Пример 1: Обычное исключение

```python
# src/exception_registry/errors_list/gateway/admin.py

class UserNotFoundException(RegisteredException):
    name = "USER_NOT_FOUND"
    code = "USER_404"
    description = "Пользователь не найден"
    category = ExceptionCategory.SERVICE_GATEWAY_ADMIN.value


# Использование:
user = db.get_user(user_id)
if not user:
    raise UserNotFoundException(description=f"Пользователь {user_id} не найден")
```

### Пример 2: HTTP исключение

```python
# src/exception_registry/errors_list/gateway/exception_registry.py

class ExceptionRegistryNotFound(RegisteredHTTPException):
    name = 'REGISTRY_NOT_FOUND'
    code = 'EXCEPTION_404'
    description = 'Exception не найден'
    category = ExceptionCategory.SERVICE_GATEWAY_EXCEPTION_REGISTRY.value


# Использование:
if not exception_exists:
    raise ExceptionRegistryNotFound(
        status_code=404,
        detail="Исключение с кодом XYZ не найдено в реестре"
    )
```

### Пример 3: С декоратором

```python
from src.exception_registry.utils import register_http_exception


@register_http_exception(
    exc_name="VALIDATION_ERROR",
    exc_code="VALID_400",
    exc_description="Ошибка валидации входных данных",
    exc_category=ExceptionCategory.SERVICE_GATEWAY_UTILS.value
)
class ValidationError(ValueError):
    """Кастомная ошибка валидации"""
    pass


# Использование:
if not is_valid(data):
    raise ValidationError(
        status_code=400,
        detail={"field": "email", "error": "Некорректный email"}
    )
```

## Создание своих категорий

Если нужны новые категории, добавьте их в `exception_types.py`:

```python
class ExceptionCategory(Enum):
    # ... существующие категории ...

    # Новые категории
    SERVICE_MY_NEW_SERVICE = "MY_NEW_SERVICE"
    CACHE = "CACHE"
    EXTERNAL_API = "EXTERNAL_API"
```

## Лучшие практики

### ✅ DO:

1. **Используйте осмысленные имена и коды**
   ```python
   name = "USER_NOT_FOUND"  # ✅ Понятно
   code = "USER_404"        # ✅ Включает HTTP код
   ```

2. **Описания на русском языке**
   ```python
   description = "Пользователь не найден"  # ✅
   ```

3. **Группируйте исключения по модулям**
   ```
   errors_list/
   ├── gateway/
   │   ├── admin.py
   │   ├── projects.py
   │   └── tasks.py
   └── task_worker/
       └── cache.py
   ```

4. **Используйте правильную категорию**
   ```python
   category = ExceptionCategory.SERVICE_GATEWAY_ADMIN.value  # ✅ Специфичная
   ```

5. **Передавайте детали через description при рейзе**
   ```python
   raise UserNotFoundException(
       description=f"Пользователь с ID={user_id} не найден в базе"
   )  # ✅
   ```

### ❌ DON'T:

1. **Не используйте одинаковые name или code**
   ```python
   # ❌ Конфликт при регистрации
   class ErrorOne(RegisteredException):
       name = "ERROR"
       code = "ERR_001"

   class ErrorTwo(RegisteredException):
       name = "ERROR"  # ❌ Дубликат!
       code = "ERR_001"
   ```

2. **Не забывайте обязательные атрибуты**
   ```python
   class MyError(RegisteredException):
       name = "MY_ERROR"
       # ❌ Нет code, description, category - не зарегистрируется
   ```

3. **Не используйте UNKNOWN категорию без причины**
   ```python
   category = ExceptionCategory.UNKNOWN.value  # ❌ Всегда выбирайте конкретную
   ```

4. **Не создавайте исключения вне errors_list/**
   ```python
   # ❌ Плохо - в рандомном файле
   class SomeError(RegisteredException):
       ...

   # ✅ Хорошо - в dedicated модуле
   # src/exception_registry/errors_list/gateway/my_module.py
   ```

## Отладка

### Проверить, что исключение зарегистрировано:

```python
from src.exception_registry.registry import ERROR_REGISTRY
from src.exception_registry.utils import is_exception_in_registry

# Способ 1: Поиск в реестре
errors = ERROR_REGISTRY.get_errors_by_filters(name="USER_NOT_FOUND")
print(f"Найдено: {len(errors)} исключений")

# Способ 2: Проверка конкретного экземпляра
exc = UserNotFoundException()
is_registered = is_exception_in_registry(exc)
print(f"Зарегистрировано: {is_registered}")
```

### Получить все исключения:

```python
from src.exception_registry.registry import ERROR_REGISTRY

all_errors = ERROR_REGISTRY.list_serialized_errors()
for error in all_errors:
    print(f"{error['name']} ({error['code']}): {error['description']}")
```

### Логирование регистрации:

При импорте модуля с исключениями в логах появится:

```
DEBUG - Registration Exception - USER_NOT_FOUND with code USER_404
```

## Архитектурные детали

### Автоматическая регистрация

Использует хук `__init_subclass__`, который вызывается при создании любого подкласса:

```python
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)

    if (hasattr(cls, 'name') and
        hasattr(cls, 'code') and
        hasattr(cls, 'description')):

        ERROR_REGISTRY.register_error(cls)
```

### Singleton Registry

`ExceptionRegistry` реализован как синглтон через `__new__`:

```python
class ExceptionRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

### Хэширование

Исключения хэшируются по (name, code, description, category, exc_data) для уникальности в реестре.

### Pickle support

Декораторы регистрируют классы в глобальном namespace модуля для корректной работы pickle (нужно для loguru в многопоточном режиме).

## FAQ

**Q: Что делать, если исключение не регистрируется?**

A: Проверьте, что определены все обязательные атрибуты: `name`, `code`, `description`. Также убедитесь, что модуль с исключением импортируется при старте приложения.

**Q: Можно ли изменить description при рейзе?**

A: Да, передайте новое описание в конструктор: `raise MyError(description="Новое описание")`. Оно сохранится в `exc_data`.

**Q: В чем разница между RegisteredException и RegisteredHTTPException?**

A: `RegisteredHTTPException` наследуется от `fastapi.HTTPException` и имеет `status_code`, `detail`, `headers`. Используйте его для HTTP API. `RegisteredException` - базовый класс для любых исключений.

**Q: Как добавить новую категорию?**

A: Добавьте новое значение в enum `ExceptionCategory` в файле `exception_types.py`.

**Q: Можно ли использовать с другими фреймворками, не FastAPI?**

A: Да, но потребуется написать свой exception handler. Базовые классы и реестр не зависят от FastAPI.

## См. также

- `src/exception_registry/handlers.py` - реализация FastAPI handler
- `src/exception_registry/utils.py` - хелперы и декораторы
- `src/exception_registry/errors_list/` - примеры определений исключений