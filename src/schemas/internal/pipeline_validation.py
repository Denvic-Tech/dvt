from typing import List
from typing import Dict
from typing import Optional

from pydantic import BaseModel, Field


class PipelineValidationErrorInfo(BaseModel):
    message: str = Field(..., description="Сообщение об ошибке")
    details: Optional[str] = Field(None, description="Дополнительная информация об ошибке")


class PipelineValidationNodeErrorInfo(BaseModel):
    message: str = Field(..., description="Сообщение об ошибке")
    node_name: str = Field(..., description="Имя ноды, в которой произошла ошибка")
    details: Optional[str] = Field(None, description="Дополнительная информация об ошибке")


class PipelineValidationResult(BaseModel):
    is_valid: bool = Field(..., description="Признак валидности пайплайна")
    error_info: Optional[PipelineValidationErrorInfo] = Field(
        None,
        description="Информация об ошибке валидации (если is_valid = False)"
    )
    target_nodes: List[str] = Field(default_factory=list, description="Список ID узлов для выполнения")
    node_errors: Dict[str, PipelineValidationNodeErrorInfo] = Field(
        default_factory=dict,
        description="Ошибок для конкретных узлов ({node_id: PipelineValidationNodeErrorInfo})"
    )
