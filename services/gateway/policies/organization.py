from services.gateway.exceptions import organization as org_exc


def normalize_organization_inn(inn: str | None) -> str | None:
    if inn is None:
        return None

    normalized = inn.strip()
    if not normalized:
        return None

    if not normalized.isdigit():
        raise org_exc.OrganizationInvalidINNHTTPError()

    return normalized
