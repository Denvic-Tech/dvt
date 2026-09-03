from pydantic import BaseModel, Field


class PresignedPostOut(BaseModel):
    url: str
    fields: dict[str, str]


class ProxyUploadOut(BaseModel):
    filename: str = Field(description="Uploaded file name")
    path: str = Field(description="Normalized parent path")
