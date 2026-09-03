def get_image_tag(image: str) -> str | None:
    """
    Возвращает явно указанный тег Docker image.

    Примеры:
        postgres:15.3-alpine -> "15.3-alpine"
        localhost:5000/dvt/ui:1.2.3 -> "1.2.3"
        localhost:5000/dvt/ui -> None
        postgres -> None
        nginx@sha256:abc -> None
        nginx:1.25@sha256:abc -> "1.25"
    """
    image = image.strip()

    if not image:
        return None

    # Убираем digest-часть, если она есть: image:tag@sha256:...
    image_without_digest = image.split("@", 1)[0]

    # Важно: двоеточие в localhost:5000 — это не тег.
    # Поэтому проверяем только последний path segment после последнего "/".
    last_part = image_without_digest.rsplit("/", 1)[-1]

    if ":" not in last_part:
        return None

    _, tag = last_part.rsplit(":", 1)

    return tag or None
