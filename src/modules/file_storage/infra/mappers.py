from __future__ import annotations

from core.types import FTPFile, FTPFolder, S3File, S3Folder

from ..domain.entities import PresignedUpload, StorageFolderNode, StorageTree
from ..domain.types import StorageBackendKind

from .schemas.transfer import PresignedPostOut
from .schemas.user_file_tree import UserFileTreeSchema


def storage_tree_to_http_schema(tree: StorageTree) -> UserFileTreeSchema:
    nodes = []
    for node in tree.nodes:
        if isinstance(node, StorageFolderNode):
            if tree.backend_kind == StorageBackendKind.S3:
                nodes.append(S3Folder(name=node.name, path=node.path))
            else:
                nodes.append(FTPFolder(name=node.name, path=node.path, permissions=node.permissions))
            continue

        if tree.backend_kind == StorageBackendKind.S3:
            nodes.append(
                S3File(
                    name=node.name,
                    path=node.path,
                    size=node.size,
                    last_modified=node.last_modified,
                    etag=node.etag,
                    storage_class=node.storage_class,
                )
            )
        else:
            nodes.append(
                FTPFile(
                    name=node.name,
                    path=node.path,
                    size=node.size,
                    last_modified=node.last_modified,
                    permissions=node.permissions,
                )
            )

    return UserFileTreeSchema(
        path=tree.path,
        nodes=nodes,
        is_truncated=tree.is_truncated,
        next_token=tree.next_token,
    )


def presigned_upload_to_http_schema(payload: PresignedUpload) -> PresignedPostOut:
    return PresignedPostOut(url=payload.url, fields=payload.fields)
