from src.exception_registry import RegisteredException


class ProjectTransferFlowError(RegisteredException):
    status_code = 400
    name = "PROJECT_TRANSFER_FLOW_ERROR"
    code = "PROJECT_TRANSFER_100"
    category = "PROJECT_TRANSFER"
    description = "Project transfer flow error"

    def __init__(self, description: str | None = None):
        super().__init__(description)
        Exception.__init__(self, description or self.description)


class ExportSelectionNotFoundError(ProjectTransferFlowError):
    status_code = 404
    name = "PROJECT_TRANSFER_SELECTION_NOT_FOUND"
    code = "PROJECT_TRANSFER_101"
    description = "None of the selected projects or folders is accessible"


class ImportTargetNotFoundError(ProjectTransferFlowError):
    status_code = 404
    name = "PROJECT_TRANSFER_TARGET_NOT_FOUND"
    code = "PROJECT_TRANSFER_102"
    description = "Import target folder or project was not found"
