from src.logger import logger
from src.node_dsl import JSONOutputBaseNode, InputField, OutputField, IO
from typing import Any, Dict, List


class ExpandJSON(JSONOutputBaseNode):
    TITLE = "Expand JSON"
    EMOJI = "🧩"
    CATEGORY = "JSON"

    json: IO.JSON = InputField(multiline=True)
    separator: str = InputField(default=".", description="Разделитель для ключей")
    max_depth: int = InputField(default=15, description="Максимальная глубина вложенности")
    max_array_size: int = InputField(default=100, description="Максимальный размер массива для размножения")
    max_total_rows: int = InputField(default=10000, description="Максимальное общее количество строк")
    output: IO.JSON = OutputField()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stats = {
            "depth": 0,
            "arrays_found": 0,
            "total_rows": 0,
            "warnings": []
        }

    def process(self):
        try:
            data = self.json
            if isinstance(data, dict):
                data = [data]

            final_result = []
            total_warnings = []

            for idx, entry in enumerate(data):
                logger.info(f"Processing entry {idx + 1}/{len(data)}")
                
                self.stats = {
                    "depth": 0,
                    "arrays_found": 0,
                    "total_rows": 0,
                    "warnings": []
                }
                
                expanded_entries = self.flatten_and_explode_optimized(entry)
                final_result.extend(expanded_entries)
                
                if self.stats.get("warnings"):
                    total_warnings.extend(self.stats["warnings"])
                
                logger.info(f"Entry {idx + 1}: generated {len(expanded_entries)} rows, "
                           f"found {self.stats.get('arrays_found', 0)} arrays")

            if final_result:
                all_keys = set()
                for row in final_result:
                    all_keys.update(row.keys())

                normalized_result = []
                for row in final_result:
                    normalized_row = {k: row.get(k, None) for k in sorted(list(all_keys))}
                    normalized_result.append(normalized_row)
                
                self.output = normalized_result
                logger.info(f"Total generated rows: {len(normalized_result)}")
                
                if total_warnings:
                    for warning in set(total_warnings):  # Уникальные предупреждения
                        logger.warning(f"ExpandJSON warning: {warning}")
            else:
                self.output = []
                logger.warning("No data generated")

        except Exception as e:
            logger.error(f"Error in ExpandJSON: {e}")
            raise

    def analyze_structure(self, data: Any, prefix: str = '', depth: int = 0) -> Dict:
        """
        Анализирует структуру JSON без создания комбинаций
        """
        if depth > self.max_depth:
            self.stats["warnings"].append(f"Превышена максимальная глубина на {prefix}")
            return {"type": "depth_limit", "path": prefix}
        
        structure = {
            "path": prefix,
            "type": type(data).__name__,
            "depth": depth,
            "has_arrays": False,
            "array_paths": [],
            "leaf_count": 0,
            "children": {}
        }
        
        if isinstance(data, dict):
            for key, value in data.items():
                new_prefix = f"{prefix}{self.separator}{key}" if prefix else key
                child_struct = self.analyze_structure(value, new_prefix, depth + 1)
                structure["children"][key] = child_struct
                structure["leaf_count"] += child_struct.get("leaf_count", 1)
                
                if child_struct.get("has_arrays"):
                    structure["has_arrays"] = True
                    structure["array_paths"].extend(child_struct.get("array_paths", []))
        
        elif isinstance(data, (list, tuple)):
            structure["has_arrays"] = True
            structure["array_paths"].append(prefix)
            structure["size"] = len(data)
            structure["leaf_count"] = len(data)
            
            if len(data) > self.max_array_size:
                self.stats["warnings"].append(
                    f"Массив {prefix} слишком большой: {len(data)} > {self.max_array_size}"
                )
            
            if data and len(data) > 0:
                first_item_struct = self.analyze_structure(data[0], prefix, depth + 1)
                structure["item_type"] = first_item_struct.get("type")
                structure["children"]["0"] = first_item_struct
        
        else:
            structure["leaf_count"] = 1
        
        return structure

    def flatten(self, data: Any, prefix: str = '') -> Dict:
        """
        Только уплощение без размножения
        """
        result = {}
        
        if isinstance(data, dict):
            for key, value in data.items():
                new_prefix = f"{prefix}{self.separator}{key}" if prefix else key
                if isinstance(value, (dict, list, tuple)):
                    result.update(self.flatten(value, new_prefix))
                else:
                    result[new_prefix] = value
        
        elif isinstance(data, (list, tuple)):
            if not data:
                result[prefix] = None
            elif len(data) == 1:
                if isinstance(data[0], (dict, list, tuple)):
                    result.update(self.flatten(data[0], prefix))
                else:
                    result[prefix] = data[0]
            else:
                all_simple = all(not isinstance(x, (dict, list, tuple)) for x in data)
                if all_simple:
                    result[prefix] = data
                else:
                    result[prefix + "[]"] = data
        
        else:
            result[prefix] = data
        
        return result

    def extract_arrays(self, flat_dict: Dict) -> Dict[str, List]:
        """
        Находит все массивы в уплощенной структуре
        """
        arrays = {}
        for key, value in flat_dict.items():
            if isinstance(value, (list, tuple)) and len(value) > 1:
                if len(value) <= self.max_array_size:
                    arrays[key] = value
                else:
                    self.stats["warnings"].append(
                        f"Массив {key} обрезан с {len(value)} до {self.max_array_size}"
                    )
                    arrays[key] = value[:self.max_array_size]
        return arrays

    def iter_cartesian_product(self, base_dict: Dict, arrays: Dict[str, List]):
        """
        Лениво создает декартово произведение только для массивов.
        Не материализует все комбинации сразу.
        """
        if not arrays:
            yield base_dict.copy()
            return

        array_keys = list(arrays.keys())
        array_values = list(arrays.values())
        indices = [0] * len(array_keys)

        while True:
            new_row = base_dict.copy()
            for i, key in enumerate(array_keys):
                new_row[key] = array_values[i][indices[i]]

            clean_row = {}
            for k, v in new_row.items():
                if k.endswith('[]'):
                    clean_row[k[:-2]] = v
                else:
                    clean_row[k] = v
            yield clean_row

            pos = len(array_keys) - 1
            while pos >= 0:
                indices[pos] += 1
                if indices[pos] < len(array_values[pos]):
                    break
                indices[pos] = 0
                pos -= 1

            if pos < 0:
                break

    def flatten_and_explode_optimized(self, data: Any) -> List[Dict]:
        """
        Оптимизированная версия: уплощает JSON и размножает строки по массивам
        """
        try:
            structure = self.analyze_structure(data)
            
            if structure.get("has_arrays"):
                array_paths = structure.get("array_paths", [])
                self.stats["arrays_found"] = len(array_paths)
                logger.debug(f"Found arrays at: {array_paths[:5]}")

            result = self._fully_expand_row(data, self.max_total_rows)
            self.stats["total_rows"] = len(result)

            return result
            
        except Exception as e:
            logger.error(f"Error in flatten_and_explode_optimized: {e}")
            return [self._safe_flatten(data)]

    def _fully_expand_row(self, row: Any, remaining_limit: int) -> List[Dict]:
        flat_dict = self.flatten(row)
        arrays = self.extract_arrays(flat_dict)

        if not arrays:
            return [self._clean_flat_dict(flat_dict)]

        if remaining_limit <= 0:
            return []

        expected_rows = 1
        for arr in arrays.values():
            expected_rows *= len(arr)

        if expected_rows > remaining_limit:
            self.stats["warnings"].append(
                f"Ожидается {expected_rows} строк, ограничено {remaining_limit}; "
                f"массивы сохранены без размножения"
            )
            preserved_row = self._clean_flat_dict(flat_dict)
            self.stats["total_rows"] = max(self.stats.get("total_rows", 0), 1)
            return [preserved_row]

        result = []
        for candidate in self.iter_cartesian_product(flat_dict, arrays):
            remaining_rows = remaining_limit - len(result)
            if remaining_rows <= 0:
                break

            expanded_candidate_rows = self._fully_expand_row(candidate, remaining_rows)
            result.extend(expanded_candidate_rows)

        return result

    def _clean_flat_dict(self, flat_dict: Dict) -> Dict:
        clean_dict = {}
        for key, value in flat_dict.items():
            if key.endswith("[]"):
                clean_dict[key[:-2]] = value
            else:
                clean_dict[key] = value
        return clean_dict

    def _safe_flatten(self, data: Any, prefix: str = '') -> Dict:
        result = {}
        stack = [(data, prefix)]
        
        while stack:
            current_data, current_prefix = stack.pop()
            
            if isinstance(current_data, dict):
                for key, value in current_data.items():
                    new_prefix = f"{current_prefix}{self.separator}{key}" if current_prefix else key
                    stack.append((value, new_prefix))
            
            elif isinstance(current_data, (list, tuple)):
                if len(current_data) == 1:
                    stack.append((current_data[0], current_prefix))
                elif len(current_data) > 1:
                    # Сохраняем как массив
                    result[current_prefix] = current_data
                else:
                    result[current_prefix] = None
            
            else:
                result[current_prefix] = current_data
        
        return result
