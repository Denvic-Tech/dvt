import pandas as pd
import pytest
from dask import dataframe as dd

from src.nodes.transform import DataFrameUnion

class TestDataFrameUnion:
    @pytest.mark.asyncio
    def test_dataframe_union_empty_columns(self):
        """Тест проверяет, что объединение не создает пустых столбцов"""

        # Создаем тестовые данные
        df1_data = {
            'FIRST_NAME': ['John', 'Jane'],
            'LAST_NAME': ['Doe', 'Smith'],
            'AGE': [25, 30],
            'CITY': ['NY', 'LA']
        }

        df2_data = {
            'FIRST_NAME': ['Bob', 'Alice'],
            'LAST_NAME': ['Brown', 'White'],
            'AGE': [35, 28],
            'COUNTRY': ['USA', 'UK']  # Умышленно другой столбец
        }

        # Создаем Dask DataFrames
        df1 = dd.from_pandas(pd.DataFrame(df1_data), npartitions=1)
        df2 = dd.from_pandas(pd.DataFrame(df2_data), npartitions=1)

        # Создаем объект класса
        union_node = DataFrameUnion(user_id="user",
                                    project_id="project",
                                    task_id="task",
                                    node_id="node-union",
                                    df1=df1,
                                    df2=df2,
                                    column_mapping={
                                        'FIRST_NAME': 'FIRST_NAME',
                                        'LAST_NAME': 'LAST_NAME'
                                    })

        union_node.process()
        result = union_node.output.compute()

        # Проверяем, что нет пустых столбцов
        assert 'FIRST_NAME' in result.columns
        assert 'LAST_NAME' in result.columns
        assert 'AGE' in result.columns
        assert result['FIRST_NAME'].isna().sum() == 0, "В FIRST_NAME есть пустые значения"
        assert result['LAST_NAME'].isna().sum() == 0, "В LAST_NAME есть пустые значения"

        # Проверяем, что данные сохранились
        assert len(result) == 4
        assert 'John' in result['FIRST_NAME'].values
        assert 'Bob' in result['FIRST_NAME'].values

        # Тест 2: Маппинг с дополнительными несуществующими колонками
        union_node.column_mapping = {
            'FIRST_NAME': 'FIRST_NAME',
            'LAST_NAME': 'LAST_NAME',
            'NON_EXISTENT': 'SOME_COLUMN'  # Несуществующая колонка
        }

        union_node.process()
        result = union_node.output.compute()

        # Проверяем, что не появились колонки из несуществующего маппинга
        assert 'NON_EXISTENT' not in result.columns
        assert 'SOME_COLUMN' not in result.columns

        # Тест 3: Маппинг с переименованием
        df2_renamed = dd.from_pandas(pd.DataFrame({
            'name': ['Bob', 'Alice'],  # Другие имена колонок
            'surname': ['Brown', 'White'],
            'age': [35, 28]
        }), npartitions=1)

        union_node.df2 = df2_renamed
        union_node.column_mapping = {
            'FIRST_NAME': 'name',
            'LAST_NAME': 'surname',
            'AGE': 'age'
        }

        union_node.process()
        result = union_node.output.compute()

        # Проверяем корректность маппинга
        assert 'FIRST_NAME' in result.columns
        assert 'LAST_NAME' in result.columns
        assert 'AGE' in result.columns
        assert result['FIRST_NAME'].isna().sum() == 0
        assert result['LAST_NAME'].isna().sum() == 0
        assert result['AGE'].isna().sum() == 0

        # Тест 4: Проверка с пустыми строками в маппинге
        union_node.column_mapping = {
            'FIRST_NAME': 'FIRST_NAME',
            'LAST_NAME': 'LAST_NAME',
            '': 'AGE',  # Пустая строка слева
            'CITY': ''  # Пустая строка справа
        }

        union_node.df1 = df1
        union_node.df2 = df2

        union_node.process()
        result = union_node.output.compute()

        # Проверяем, что пустые строки игнорируются
        assert '' not in result.columns
        assert len([col for col in result.columns if col.strip() == '']) == 0


    @pytest.mark.asyncio
    def test_dataframe_union_with_indexes(self):
        """Тест с индексами"""

        # Создаем DataFrame с индексом
        df1 = pd.DataFrame({
            'FIRST_NAME': ['John', 'Jane'],
            'LAST_NAME': ['Doe', 'Smith'],
            'VALUE': [1, 2]
        }).set_index('FIRST_NAME')

        df2 = pd.DataFrame({
            'FIRST_NAME': ['Bob', 'Alice'],
            'LAST_NAME': ['Brown', 'White'],
            'VALUE': [3, 4]
        }).set_index('FIRST_NAME')

        ddf1 = dd.from_pandas(df1, npartitions=1)
        ddf2 = dd.from_pandas(df2, npartitions=1)

        union_node = DataFrameUnion(user_id="user",
                                    project_id="project",
                                    task_id="task",
                                    node_id="node-union",
                                    df1=ddf1,
                                    df2=ddf2,
                                    column_mapping={
                                        'FIRST_NAME': 'FIRST_NAME',
                                        'LAST_NAME': 'LAST_NAME',
                                        'VALUE': 'VALUE'
                                    })
        union_node.process()
        result = union_node.output.compute()

        # Проверяем, что индекс сброшен и стал колонкой
        assert 'FIRST_NAME' in result.columns
        assert 'index' not in result.columns
        assert result['FIRST_NAME'].isna().sum() == 0


    @pytest.mark.asyncio
    def test_dataframe_union_different_columns(self):
        """Тест с полностью разными колонками"""

        df1 = dd.from_pandas(pd.DataFrame({
            'A': [1, 2],
            'B': [3, 4]
        }), npartitions=1)

        df2 = dd.from_pandas(pd.DataFrame({
            'C': [5, 6],
            'D': [7, 8]
        }), npartitions=1)

        union_node = DataFrameUnion(user_id="user",
                                    project_id="project",
                                    task_id="task",
                                    node_id="node-union",
                                    df1=df1, df2=df2,
                                    column_mapping={})

        union_node.process()
        result = union_node.output.compute()

        # Проверяем, что все колонки сохранились
        assert set(result.columns) == {'A', 'B', 'C', 'D'}
        # Проверяем, что есть NaN в несопоставленных колонках
        assert result['C'].isna().sum() == 2  # В df1 нет колонки C
        assert result['D'].isna().sum() == 2  # В df1 нет колонки D
        assert result['A'].isna().sum() == 2  # В df2 нет колонки A
        assert result['B'].isna().sum() == 2  # В df2 нет колонки B


    @pytest.mark.asyncio
    async def test_column_mapping_simple_rename(self):
        """Тест простого переименования колонок через маппинг"""
        # Создаем DataFrame с разными именами колонок
        df1 = dd.from_pandas(pd.DataFrame({
            'product': ['apple', 'banana'],
            'cost': [10, 20],
            'quantity': [5, 3]
        }), npartitions=1)

        df2 = dd.from_pandas(pd.DataFrame({
            'item': ['orange', 'grape'],
            'price': [15, 25],
            'amount': [7, 4]
        }), npartitions=1)

        # Маппинг: из df2 в имена как в df1
        column_mapping = {
            'product': 'item',  # df1.product <-> df2.item
            'cost': 'price',  # df1.cost <-> df2.price
            'quantity': 'amount'  # df1.quantity <-> df2.amount
        }

        union_node = DataFrameUnion(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-union",
            df1=df1,
            df2=df2,
            column_mapping=column_mapping
        )

        union_node.process()
        result = union_node.output.compute()

        # Проверяем, что все колонки из df1 присутствуют
        assert set(result.columns) == {'product', 'cost', 'quantity'}

        # Проверяем, что данные из df2 правильно перенесены
        assert result['product'].tolist() == ['apple', 'banana', 'orange', 'grape']
        assert result['cost'].tolist() == [10, 20, 15, 25]
        assert result['quantity'].tolist() == [5, 3, 7, 4]

        # Нет NaN значений
        assert result.isna().sum().sum() == 0

    @pytest.mark.asyncio
    async def test_column_mapping_with_different_dtypes(self):
        """Тест маппинга колонок с разными типами данных"""
        df1 = dd.from_pandas(pd.DataFrame({
            'id': pd.Series([1, 2], dtype='int32'),
            'price': pd.Series([10.5, 20.3], dtype='float32'),
            'active': pd.Series([True, False], dtype='bool')
        }), npartitions=1)

        df2 = dd.from_pandas(pd.DataFrame({
            'id': pd.Series(['3', '4'], dtype='string'),  # string вместо int
            'price': pd.Series([30, 40], dtype='int64'),  # int вместо float
            'active': pd.Series([1, 0], dtype='int32')  # int вместо bool
        }), npartitions=1)

        column_mapping = {
            'id': 'id',
            'price': 'price',
            'active': 'active'
        }

        union_node = DataFrameUnion(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-union",
            df1=df1,
            df2=df2,
            column_mapping=column_mapping
        )

        union_node.process()
        result = union_node.output.compute()

        # Проверяем наличие всех колонок
        assert set(result.columns) == {'id', 'price', 'active'}

        # Проверяем, что данные объединились (хотя типы могут быть приведены)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_column_mapping_with_trailing_whitespace(self):
        """
        Тест проверяет маппинг колонок, когда в именах колонок есть пробелы
        (в начале, в конце, или с обеих сторон).
        """

        # Создаем df1 с нормальными именами колонок
        df1 = pd.DataFrame({
            'Сумма': [100.50, 200.75, 300.25],
            'Цена': [10.5, 20.3, 30.1],
            'Количество': [5.0, 10.0, 15.0],
            'Номенклатура': ['Товар А', 'Товар Б', 'Товар В']
        })

        # Создаем df2 с колонками, содержащими пробелы
        df2 = pd.DataFrame({
            'Стоимость ': [400, 500, 600],  # Пробел в конце!
            ' Цена': [40, 50, 60],  # Пробел в начале
            ' Количество ': [20, 25, 30],  # Пробелы с обеих сторон
            'Номенклатура': ['Товар Г', 'Товар Д', 'Товар Е']
        })

        # Конвертируем в Dask DataFrames
        ddf1 = dd.from_pandas(df1, npartitions=1)
        ddf2 = dd.from_pandas(df2, npartitions=1)

        # Маппинг, который пользователь указывает в UI
        # Пользователь думает, что колонки называются без пробелов
        column_mapping = {
            'Сумма': 'Стоимость ',  # В df2 на самом деле 'Стоимость ' (с пробелом)
            'Цена': ' Цена',  # В df2 на самом деле ' Цена' (с пробелом в начале)
            'Количество': ' Количество '  # В df2 на самом деле ' Количество ' (с пробелами)
            # Номенклатура уже совпадает по имени
        }

        union_node = DataFrameUnion(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-union",
            df1=ddf1,
            df2=ddf2,
            column_mapping=column_mapping
        )

        union_node.process()
        result = union_node.output.compute()


        # 1. Проверяем, что все колонки из df1 присутствуют
        assert 'Сумма' in result.columns
        assert 'Цена' in result.columns
        assert 'Количество' in result.columns
        assert 'Номенклатура' in result.columns

        # 2. Проверяем, что НЕТ колонок с пробелами
        assert 'Стоимость ' not in result.columns
        assert ' Цена' not in result.columns
        assert ' Количество ' not in result.columns

        # 3. Проверяем, что данные правильно смаппились
        # Сумма: первые 3 значения из df1, следующие 3 из df2 (из 'Стоимость ')
        expected_sum = [100.50, 200.75, 300.25, 400.0, 500.0, 600.0]
        assert result['Сумма'].tolist() == pytest.approx(expected_sum, rel=1e-2)

        # Цена: первые 3 из df1, следующие 3 из df2 (из ' Цена')
        expected_price = [10.5, 20.3, 30.1, 40.0, 50.0, 60.0]
        assert result['Цена'].tolist() == pytest.approx(expected_price, rel=1e-2)

        # Количество: первые 3 из df1, следующие 3 из df2 (из ' Количество ')
        expected_quantity = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
        assert result['Количество'].tolist() == pytest.approx(expected_quantity, rel=1e-2)

        # Номенклатура
        expected_nomenclature = ['Товар А', 'Товар Б', 'Товар В', 'Товар Г', 'Товар Д', 'Товар Е']
        assert result['Номенклатура'].tolist() == expected_nomenclature

        # 4. Проверяем, что нет NaN значений в смаппированных колонках
        assert result['Сумма'].isna().sum() == 0, "В колонке 'Сумма' есть NaN значения"
        assert result['Цена'].isna().sum() == 0, "В колонке 'Цена' есть NaN значения"
        assert result['Количество'].isna().sum() == 0, "В колонке 'Количество' есть NaN значения"
        assert result['Номенклатура'].isna().sum() == 0, "В колонке 'Номенклатура' есть NaN значения"

        # 5. Проверяем размер результата
        assert len(result) == 6, f"Ожидалось 6 строк, получено {len(result)}"

        # Сумма должна быть float (из df1 float, из df2 int -> float)
        assert result['Сумма'].dtype in ['float64', 'float32', 'float']

        # 7. Дополнительная проверка: убедимся, что пробелы действительно были проблемой
        # Проверим исходные данные
        assert 'Стоимость ' in df2.columns
        assert 'Стоимость' not in df2.columns
        assert df2['Стоимость '].tolist() == [400, 500, 600]

    @pytest.mark.asyncio
    def test_dataframe_union_index_name_collision_does_not_crash(self):
        """
        Регрессия для ошибки:
        pandas.errors.InvalidIndexError: Reindexing only valid with uniquely valued Index objects

        Воспроизводится, когда после reset_index() появляются дубли имен колонок
        (например, индекс имеет имя, которое уже существует как колонка: set_index(drop=False)).
        """
        pdf1 = pd.DataFrame({"id": [1, 2], "v": [10, 20]}).set_index("id", drop=False)
        pdf2 = pd.DataFrame({"id": [3], "v": [30]}).set_index("id", drop=False)

        ddf1 = dd.from_pandas(pdf1, npartitions=1)
        ddf2 = dd.from_pandas(pdf2, npartitions=1)

        union_node = DataFrameUnion(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-union",
            df1=ddf1,
            df2=ddf2,
            column_mapping={},
        )

        union_node.process()
        result = union_node.output.compute()

        assert len(result) == 3
        assert result.columns.is_unique is True
        assert "id" in result.columns
        assert "__index__id" in result.columns

    @pytest.mark.asyncio
    def test_dataframe_union_column_mapping_collision_raises_value_error(self):
        """
        Если column_mapping приводит к дублям имен колонок после rename, лучше падать с понятной
        ошибкой, чем внутри dd.concat/pd.concat.
        """
        df1 = dd.from_pandas(pd.DataFrame({"A": [1]}), npartitions=1)
        df2 = dd.from_pandas(pd.DataFrame({"A": [2], "B": [3]}), npartitions=1)

        union_node = DataFrameUnion(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-union",
            df1=df1,
            df2=df2,
            column_mapping={"A": "B"},  # Переименует B -> A и получит две колонки A
        )

        with pytest.raises(ValueError, match=r"дублиру"):
            union_node.process()

