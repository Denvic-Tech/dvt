from pydantic import BaseModel, Field


class CommonResponse(BaseModel):
    success: bool = Field(description="Успешно ли выполнено")
    message: str = Field(description="Сообщение")


class ErrorResponse(BaseModel):
    code: str = Field(description="Код ошибки")
    detail: str = Field(description="Описание ошибки")
