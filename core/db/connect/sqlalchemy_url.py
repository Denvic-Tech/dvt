from typing import Optional

from sqlalchemy import URL


def has_oracle_service_name(url: URL) -> bool:
    return url.get_backend_name().lower().startswith("oracle") and "service_name" in url.query


def with_database(url: URL, database_name: str | None) -> URL:
    if not database_name:
        return url

    if has_oracle_service_name(url):
        return url

    return url.set(database=database_name)


def split_backend_and_driver(url: URL) -> tuple[str, Optional[str]]:  # TODO: вынести в shared/предметную область
    backend = url.get_backend_name().lower()
    if "+" in url.drivername:
        _, driver = url.drivername.split("+", 1)
        return backend, driver.lower()
    return backend, None
