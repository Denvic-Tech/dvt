from pydantic import BaseModel


class BatchItem(BaseModel):
    key: str
    value: str