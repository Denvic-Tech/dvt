from typing import Optional, List, Union, Literal, Annotated
from datetime import datetime

from pydantic import BaseModel, Field


class S3Object(BaseModel):
    """Модель объекта в S3 (устаревшая, для обратной совместимости)."""
    key: str = Field(..., description="Ключ объекта в бакете")
    size: int = Field(..., description="Размер объекта в байтах", ge=0)
    last_modified: Optional[datetime] = Field(None, description="Дата последнего изменения")
    etag: Optional[str] = Field(None, description="ETag объекта")
    storage_class: Optional[str] = Field(None, description="Класс хранения (STANDARD, GLACIER и т.д.)")


class S3NodeBase(BaseModel):
    """Базовый класс для узлов S3 (папок и файлов)."""
    type: str = Field(..., description="Тип узла: folder или file")
    name: str = Field(..., description="Имя узла (последний сегмент пути)")
    path: str = Field(..., description="Полный путь (prefix/key)")

    class Config:
        discriminator = "type"


class S3File(S3NodeBase):
    """Модель файла в S3."""
    type: Literal["file"] = "file"
    size: int = Field(..., description="Размер файла в байтах", ge=0)
    last_modified: Optional[datetime] = Field(None, description="Дата последнего изменения")
    etag: Optional[str] = Field(None, description="ETag файла")
    storage_class: Optional[str] = Field(None, description="Класс хранения (STANDARD, GLACIER и т.д.)")


class S3Folder(S3NodeBase):
    """Модель папки в S3."""
    type: Literal["folder"] = "folder"


S3Node = Annotated[Union[S3File, S3Folder], Field(discriminator="type")]


class S3Bucket(BaseModel):
    """Модель бакета в S3."""
    name: str = Field(..., description="Имя бакета")
    creation_date: Optional[datetime] = Field(None, description="Дата создания бакета")
    nodes: List[S3Node] = Field(default_factory=list, description="Список узлов (папок и файлов) в бакете")
    total_size: int = Field(default=0, description="Общий размер всех файлов в байтах", ge=0)
    files_count: int = Field(default=0, description="Количество файлов", ge=0)
    folders_count: int = Field(default=0, description="Количество папок", ge=0)
