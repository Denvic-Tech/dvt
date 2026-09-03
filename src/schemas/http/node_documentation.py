from pydantic import BaseModel, Field


class PublishedNodeDocumentationSchema(BaseModel):
    node_name: str = Field(description="Имя ноды.")
    locale: str = Field(description="Фактически использованная локаль документации.")
    content: str = Field(description="Markdown-содержимое документации.")
