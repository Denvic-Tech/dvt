<h1>Node DSL документация</h1>

---

# Базовый класс BaseNode
В данном модуле определены базовые классы BaseNode и расширенные базовые классы

---

## `BaseNode`

### Назначение
Базовый класс для всех нод ETL пайплайна.  
Использует **метакласс `BaseNodeMeta`** для автоматической конфигурации полей и метаданных.
Наследуется от `MetadataNodeMixin` и `ProgressNodeMixin`

#### `MetadataNodeMixin` - Миксин для нод, которые могут предоставлять метаданные
#### `ProgressNodeMixin` - Миксин для отслеживания прогресса ноды. Реализует методы отслеживания текущего шага ноды


### Основные атрибуты класса
#### --------- Атрибуты метаданных ---------
- `TITLE: ClassVar[str | None]` - заголовок ноды.  
- `CATEGORY: ClassVar[str]` - категория (по умолчанию `"Custom"`).  
- `TAGS: ClassVar[List[str]]` - список тегов.  
- `TYPE: ClassVar[enums.NodeType]` - тип ноды (`BASE` по умолчанию).  
- `OUTPUT_NODE: ClassVar[bool]` - является ли выходной нодой.  
- `DESCRIPTION: ClassVar[Optional[str]]` - описание.  
- `DEPRECATED: ClassVar[bool]` - устаревшая ли нода.  
- `EXPERIMENTAL: ClassVar[bool]` - экспериментальная ли нода.  
- `VISIBLE: ClassVar[bool]` - отображать ли в UI.  

#### --------- Атрибуты, определяемые в метаклассе ---------

- `_input_field_instances: Dict[str, InputField]` - словарь входных полей
- `_output_field_instances: Dict[str, OutputField]` - словарь выходных полей

#### --------- Атрибуты, определяемые при инициализации ---------

- `_user_id: str` - id пользователя
-  `_project_id: str` - id проекта
-  `_task_id: str` - id задачи
-  `_node_id: str` - id ноды
- `_process_start_cb: Optional[OnNodeProcessStartCallback]` - Callback на запуске ноды
- `_process_success_cb: Optional[OnNodeProcessSuccessCallback]` - Callback на завершении ноды
- `_progress_cb: Optional[OnNodeProgressStepCallback] = None` - Callback, который вызывается при выполнении ноды
### Основные методы
- `from_pipeline_processor` - фабричный метод для создания ноды на основе `PipelineProcessor`.
- `_set_inputs_outputs` - назначает значения по умолчанию для входов и `Ellipsis` для выходов.
- `process` - !!!!! **абстрактный метод** выполнения ноды (обязателен к реализации в наследниках).  
- `execute` - Выполняет ноду в следующей последовательности:
  - Если есть `Callback` `_process_start_cb`, то вызывает его
  - Потом вызывает хук `BEFORE_PROCESS`
  - **Выполняет метод ноды - `process`**
  - Вызывает хук `AFTER_PROCESS`
  - Если есть `Callback` `_process_success_cb`, то вызывает его

### Так же есть базовые классы, которые расширяют `BaseNode`:
* `SqlConnectionOutputBaseNode` - Класс нод, которые работают с `SQLAlchemy`. Имеет `Engine` в качестве выходного поля
* `KafkaConnectionOutputBaseNode` - Класс нод, которые работают с `Kafka`. Имеет `KafkaProducer` в качестве выходнного поля
* `InternalBaseNode` - Класс служебных нод
* `PrimitiveBaseNode` - Класс для примитивных нод
* `TestingBaseNode` - Класс нод для тестирования
* `DFOutputBaseNode` - Класс нод, которые имеют DataFrame в качестве выходного поля. Переопределяет метод `execute`. Вызывает `process`, чтобы получить на выходе Dask DataFrame и далее кэширует каждую партицию каждого выходного поля (`_output_field_instances`)

---

# Базовый метакласс BaseNodeMeta
В данном модуле определены базовые классы BaseNodeMeta и расширенные базовые классы

---

## `BaseNodeMeta`

### Назначение
Метакласс для `BaseNode`, выполняющий:
- обработку полей (`InputField`, `OutputField`),
- разрешение типов через `TypeResolver`,
- формирование метаданных ноды,
- установку значений по умолчанию.

### Основные методы
- `__new__`  
  - если создаётся сам `BaseNode`, возвращает класс без изменений,  
  - иначе вызывает `_process_fields()` и `_set_defaults()`.  

- `_process_fields`  
  - перебирает атрибуты класса,  
  - определяет поля, являющиеся экземплярами `FieldBase`,  
  - связывает их с `attr_name` и `field_name`,  
  - получает аннотации типов,  
  - через `TypeResolver` вычисляет `resolved_type`, `is_list_type`, `is_literal_type`, `options`, `schema`,  
  - собирает `input_fields` и `output_fields`,  
  - записывает их в `dct['_input_field_instances']` и `dct['_output_field_instances']`.  

- `_set_defaults`  
  - устанавливает в `dct` значения по умолчанию для входных полей (если они заданы в `InputField.default`).  

### Так же есть базовые классы, которые расширяют `BaseNodeMeta`:
* `ConnectionOutputNodeMeta` - При вызове `__new__` проверяет, что классы наследники реализуют поле `connection` типа `OutputField`, кроме базовых классов `SqlConnectionOutputBaseNode`, `KafkaConnectionOutputBaseNode`
* `DFOutputNodeMeta` - При вызове `__new__` проверяет, что классы наследники реализуют поле `connection` типа `OutputField`, кроме базового класса `DFOutputBaseNode`
* `InternalNodeMeta`,`PrimitiveNodeMeta`,`TestingNodeMeta` - При вызове `__new__` для базового класса возвращает сам класс, для наследников обрабатывает все поля, используя `__new__` из метакласса `BaseNodeMeta`

----

# Поля ввода/вывода ноды

В данном модуле определены базовые классы для декларативного описания **входных** и **выходных** полей ноды.  

---

## `FieldBase[T]`

Базовый класс для полей ввода/вывода.  

### Основные атрибуты
- `field_name: Optional[str]` - имя поля (передаётся при инициализации или заполняется через `__set_name__`).
- `description: Optional[str]` - описание поля.
- `attr_name: Optional[str]` - имя атрибута внутри Python-класса. Устанавливается автоматически при создании класса или метаклассом.
- `resolved_type: Optional[Union[node_typing.IO, List[node_typing.IO]]]` - вычисленный тип поля.
- `is_list_type: bool` - является ли тип списком.
  
### Методы
- `__set_name__(owner: Type, name: str)`  
  Автоматически вызывается при создании класса. Устанавливает имя атрибута (`attr_name`) и подставляет его в `field_name`, если оно не было задано явно.
  
- `validate_attrs()`  
  Проверяет, что у поля установлены `attr_name` и `resolved_type`.  
  Если поле не было объявлено как атрибут класса или не имеет типа, вызывает исключение.

---

## `InputField[T]`

Представляет **входное поле ноды**. Наследуется от `FieldBase`.

### Дополнительные параметры конструктора
- `default: Any` - значение по умолчанию. Если не задано (`...`), поле считается обязательным.  
- `optional: bool` - флаг опциональности (имеет приоритет над `default`).  
- `is_hidden: bool` - скрытое поле (например, для служебных данных).  
- `multiline: bool` - подсказка для UI (многострочный ввод).  
- `metadata_source_field: Optional[str]` - имя поля, которое выступает источником метаданных.  
- Ограничения и подсказки для UI:
  - `min_value`, `max_value` - границы для числовых значений.
  - `step` - шаг изменения.
  - `round_val` - округление.
  - `force_input: bool` - требовать соединение, не использовать виджет.
  - `widget: Optional[str]` - явный тип виджета (например, `"STRING"`, `"TEXTAREA"`).

### Внутренние атрибуты (переопределяются в MetaClass)
- `is_literal_type: bool` - является ли поле литеральным типом.  
- `options: Optional[List[str]]` - допустимые значения (например, для выбора из списка).  
- `schema: Optional[dict]` - схема для валидации или UI.

Реализует метод `get_definition`, который возвращает заполненную модель `InputDefinitionModel`


---

## `OutputField[T]`

Представляет **выходное поле ноды**. Наследуется от `FieldBase`.

### Дополнительные параметры конструктора
- `is_list: bool` - явно указать, что выход является списком (даже если тип не `List[T]`).  
- `tooltip: Optional[str]` - подсказка (tooltip) для UI.

Реализует метод `get_definition`, который возвращает заполненную модель `OutputDefinitionModel`

---

# Реестры нод, хуков, менеджера локализации
При импорте библиотеки `node_dsl` вызывается внутренний метод `init_nodes` из файла `_init_nodes.py`, который инициализирует и заполняет следующие сущности:
## `NODE_DEFINITIONS (registry/definitions.py)`
Реестр данных локализации нод. Используется в эндпоинтах `/nodes`. Для инициализации использует менеджер локализации `LocalizationManager`
## `HOOKS_REGISTRY (registry/hooks.py)`
Реестр хуков нод, хранит данные в следующем виде: `{<Имя класса ноды>: {<Стадия выполнения N>: {<Название метода класса>: [<HookEntry1>, ...]}}}`.

Метод `execute` базового класса `BaseNode` вызывает метод `run_async`, который использует данный реестр хуков
## `NODE_CLASSES (registry/nodes.py)` 
Глобальный реестр нод, ключ - название класса ноды, значение - сам класс. Используется при регистрации хуков нод в методе `_init_nodes.py`


