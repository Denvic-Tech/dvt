from src.exception_registry import RegisteredException


class ProjectTransferDomainError(RegisteredException):
    status_code = 400
    name = "PROJECT_TRANSFER_DOMAIN_ERROR"
    code = "PROJECT_TRANSFER_001"
    category = "PROJECT_TRANSFER"
    description = "Project transfer domain error"

    def __init__(self, description: str | None = None):
        super().__init__(description)
        Exception.__init__(self, description or self.description)


class EmptyExportSelectionError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_EMPTY_SELECTION"
    code = "PROJECT_TRANSFER_002"
    description = "Nothing selected for export"


class SecretsPassphraseRequiredError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_PASSPHRASE_REQUIRED"
    code = "PROJECT_TRANSFER_003"
    description = "A passphrase is required to protect exported secrets"


class WeakPassphraseError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_WEAK_PASSPHRASE"
    code = "PROJECT_TRANSFER_004"
    description = "Passphrase is too short"


class InvalidPassphraseError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_INVALID_PASSPHRASE"
    code = "PROJECT_TRANSFER_005"
    description = "Bundle secrets cannot be decrypted with this passphrase"


class UnsupportedBundleFormatError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_UNSUPPORTED_FORMAT"
    code = "PROJECT_TRANSFER_006"
    description = "Bundle format version is not supported"


class InvalidBundleError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_INVALID_BUNDLE"
    code = "PROJECT_TRANSFER_007"
    description = "Bundle is malformed"


class BundleTooLargeError(ProjectTransferDomainError):
    status_code = 413
    name = "PROJECT_TRANSFER_BUNDLE_TOO_LARGE"
    code = "PROJECT_TRANSFER_008"
    description = "Bundle exceeds the allowed size"


class InvalidImportTargetError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_INVALID_TARGET"
    code = "PROJECT_TRANSFER_009"
    description = "Import target is invalid for this bundle"


class FolderDepthExceededError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_FOLDER_DEPTH_EXCEEDED"
    code = "PROJECT_TRANSFER_010"
    description = "Importing the bundle would exceed the maximum project folder depth"


class InvalidConnectionDecisionError(ProjectTransferDomainError):
    status_code = 400
    name = "PROJECT_TRANSFER_INVALID_CONNECTION_DECISION"
    code = "PROJECT_TRANSFER_011"
    description = "Connection decision is incomplete or refers to an unknown connection"
