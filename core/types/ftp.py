from typing import Optional, List, Union, Literal, Annotated
from datetime import datetime
from pydantic import BaseModel, Field


class FTPNodeBase(BaseModel):
    """Базовый класс для узлов FTP (директорий и файлов)."""
    type: str = Field(..., description="Тип узла: folder или file")
    name: str = Field(..., description="Имя узла (название файла или папки)")
    path: str = Field(..., description="Полный путь к узлу")

    class Config:
        discriminator = "type"


class FTPFile(FTPNodeBase):
    """Модель файла на FTP сервере."""
    type: Literal["file"] = "file"
    size: int = Field(..., description="Размер файла в байтах", ge=0)
    last_modified: Optional[datetime] = Field(None, description="Дата последнего изменения")
    permissions: Optional[str] = Field(None, description="Права доступа (например, 644 или -rw-r--r--)")


class FTPFolder(FTPNodeBase):
    """Модель папки на FTP сервере."""
    type: Literal["folder"] = "folder"
    permissions: Optional[str] = Field(None, description="Права доступа (например, 755 или drwxr-xr-x)")


# Объединенный тип для списков
FTPNode = Annotated[Union[FTPFile, FTPFolder], Field(discriminator="type")]


class FTPDirectoryMetadata(BaseModel):
    """
    Модель метаданных текущей директории или всего подключения.
    """
    host: str = Field(..., description="Адрес хоста")
    current_path: str = Field("/", description="Текущий путь просмотра")
    nodes: List[FTPNode] = Field(default_factory=list, description="Список файлов и папок в директории")

    total_size: int = Field(default=0, description="Общий размер файлов в текущей выборке", ge=0)
    files_count: int = Field(default=0, description="Количество файлов", ge=0)
    folders_count: int = Field(default=0, description="Количество папок", ge=0)