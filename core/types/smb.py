from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class SMBNodeBase(BaseModel):
    """Базовый класс для узлов SMB (директорий и файлов)."""

    type: str = Field(..., description="Тип узла: folder или file")
    name: str = Field(..., description="Имя узла (название файла или папки)")
    path: str = Field(..., description="Полный путь к узлу внутри SMB share")

    class Config:
        discriminator = "type"


class SMBFile(SMBNodeBase):
    """Модель файла на SMB share."""

    type: Literal["file"] = "file"
    size: int = Field(..., description="Размер файла в байтах", ge=0)
    last_modified: Optional[datetime] = Field(None, description="Дата последнего изменения")
    permissions: Optional[str] = Field(None, description="Права доступа")


class SMBFolder(SMBNodeBase):
    """Модель папки на SMB share."""

    type: Literal["folder"] = "folder"
    permissions: Optional[str] = Field(None, description="Права доступа")


SMBNode = Annotated[Union[SMBFile, SMBFolder], Field(discriminator="type")]


class SMBDirectoryMetadata(BaseModel):
    """Модель метаданных текущей директории SMB share."""

    host: str = Field(..., description="Адрес хоста")
    share: str = Field(..., description="Имя SMB share")
    current_path: str = Field("/", description="Текущий путь просмотра")
    nodes: list[SMBNode] = Field(default_factory=list, description="Список файлов и папок в директории")

    total_size: int = Field(default=0, description="Общий размер файлов в текущей выборке", ge=0)
    files_count: int = Field(default=0, description="Количество файлов", ge=0)
    folders_count: int = Field(default=0, description="Количество папок", ge=0)
