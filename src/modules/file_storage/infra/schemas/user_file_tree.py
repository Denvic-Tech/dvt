from pydantic import BaseModel

from core.types import FTPNode, S3Node


class UserFileTreeSchema(BaseModel):
    path: str
    nodes: list[S3Node | FTPNode]
    is_truncated: bool
    next_token: str | None = None
