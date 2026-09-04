import posixpath as ppath


def clean_join(*parts: str) -> str:
    return "/".join(part.strip("/") for part in parts if part and part.strip("/"))


def normalize_relative_target_path(path: str, extension: str) -> str:
    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    raw_path = (path or "").strip().strip("/")
    if not raw_path:
        raise ValueError("path cannot be empty")

    parent_dir, file_name = ppath.split(raw_path)
    if not file_name:
        raise ValueError("path must include a file or dataset name")

    normalized_file_name = _normalize_file_name(file_name, normalized_extension)
    return ppath.join(parent_dir, normalized_file_name) if parent_dir else normalized_file_name


def _normalize_file_name(file_name: str, extension: str) -> str:
    candidate = file_name.strip().strip("/")
    if not candidate:
        raise ValueError("path must include a file or dataset name")

    stem = candidate
    lowered_extension = extension.lower()
    while stem.lower().endswith(lowered_extension):
        stem = stem[:-len(extension)]
        if not stem:
            raise ValueError(f"path cannot consist only of '{extension}'")

    return f"{stem}{extension}"
