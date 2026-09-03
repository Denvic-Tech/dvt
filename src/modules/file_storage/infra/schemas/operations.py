from pydantic import BaseModel


class DeleteFolderIn(BaseModel):
    path: str


class DeleteFilesIn(BaseModel):
    paths: list[str]


class RenamePathIn(BaseModel):
    path: str
    new_name: str


class MovePathIn(BaseModel):
    path: str
    target_path: str = ""
