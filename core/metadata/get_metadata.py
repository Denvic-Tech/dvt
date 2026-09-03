from typing import Any, Optional

import pandas as pd
import dask.dataframe as dd

from sqlalchemy import Engine
from kafka import KafkaProducer

from core.metadata.df_metadata import get_df_metadata
from core.metadata.db_metadata import load_db_metadata
from core.metadata.json_metadata import get_json_metadata
from core.metadata.kafka_metadata import load_kafka_metadata
from core.metadata.series_metadata import get_series_metadata
from core.types import Metadata


def get_metadata(obj: Any, fernet_key: Optional[str] = None) -> Metadata | None:
    """
    Возвращает метаданные для поддерживаемых типов объектов.

    :param obj: Объект, для которого нужно получить метаданные. Поддерживаются:
                - pandas.DataFrame
                - dask.dataframe.DataFrame
                - sqlalchemy.Engine
                - kafka.KafkaProducer
    :param fernet_key: Необязательный ключ для расшифровки пароля в DBMetadata
    """

    if isinstance(obj, (pd.DataFrame, dd.DataFrame)):
        return get_df_metadata(obj)

    if isinstance(obj, Engine):
        return load_db_metadata(obj, fernet_key=fernet_key)

    if isinstance(obj, KafkaProducer):
        return load_kafka_metadata(obj)

    if isinstance(obj, (pd.Series, dd.Series)):
        return get_series_metadata(obj)

    if isinstance(obj, (dict, list)):
        return get_json_metadata(obj)

    return None
