from httpx import BasicAuth


def build_dcc_auth(username: str, password: str) -> BasicAuth:
    return BasicAuth(username=username, password=password)
