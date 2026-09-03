import json
from pathlib import Path
from typing import Any

from core.metadata import get_json_metadata
from core.types import FsCtx

from src.logger import logger
from src.node_dsl import IO, InputField, JSONOutputBaseNode, OutputField
from src.node_dsl.runtime.integrations.file_connection.mixin import FileConnectionInputMixin
from src.node_dsl.types import NodeMetadata
from src.nodes.extract.ftp_file import localized_ftp_file


class LoadJSON(FileConnectionInputMixin, JSONOutputBaseNode):
    TITLE = "Load JSON"
    EMOJI = "{ }"
    CATEGORY = "Extraction"

    path: str = InputField(
        description=(
            "Поддерживаются glob-паттерны, например:\n"
            "  'reports/01-01-*.json' — все файлы за 1 января\n"
            "  'reports/2025-*/data-*.json' — все файлы за 2025 год"
        )
    )
    encoding: str = InputField(
        default="utf-8",
        is_hidden=True,
    )

    output: IO.JSON = OutputField()

    def _read_json_document(self, ctx: FsCtx, path: str) -> Any:
        try:
            if ctx.protocol == "ftp":
                with (
                    localized_ftp_file(
                        path,
                        ctx.storage_options,
                        prefix="load-json-ftp-",
                        default_suffix=".json",
                    ) as temp_path,
                    Path(temp_path).open("rb") as file_obj,
                ):
                    payload = file_obj.read()
            else:
                with ctx.fs.open(path, "rb") as file_obj:
                    payload = file_obj.read()
        except FileNotFoundError:
            logger.error(f"JSON file not found at: {path}")
            raise
        except Exception as exc:
            logger.error(f"Failed to read JSON file {path}: {exc}")
            raise

        try:
            text = payload.decode(self.encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Failed to decode JSON file '{path}' with encoding '{self.encoding}': {exc}"
            ) from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in file '{path}': {exc}") from exc

    def _load_payload(self) -> Any:
        runtime = self._get_file_runtime(path=self.path)
        ctx = runtime.context
        logger.info(f"Loading JSON from {ctx.protocol.upper()}: {ctx.path}")

        files = runtime.list_files(
            required=True,
            subject="JSON file(s)",
            operation="listing JSON files",
        )
        logger.info(f"Found {len(files)} JSON file(s)")

        documents = []
        for path in files:
            with runtime.operation("reading JSON file", path=path):
                documents.append(self._read_json_document(ctx, path))
        if len(documents) == 1:
            return documents[0]
        return documents

    def process(self) -> None:
        self.output = self._load_payload()

    def infer_metadata(self) -> NodeMetadata:
        return {"output": get_json_metadata(self._load_payload())}
