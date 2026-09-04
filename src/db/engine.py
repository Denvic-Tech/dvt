import json

import pydantic.json
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

import config


def _custom_json_serializer(*args, **kwargs) -> str:
    """
    Encodes json in the same way that pydantic does.
    """
    return json.dumps(*args, default=pydantic.json.pydantic_encoder, **kwargs)


engine = create_sync_engine(
    url=config.POSTGRES.DATABASE_URL,
    echo=config.DEBUG.SQL_ECHO,
    json_serializer=_custom_json_serializer,
    connect_args={"prepare_threshold": None},
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
)

async_engine: AsyncEngine = create_async_engine(
    url=config.POSTGRES.DATABASE_URL,
    echo=config.DEBUG.SQL_ECHO,
    json_serializer=_custom_json_serializer,
    connect_args={"prepare_threshold": None},
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
)
