class AgentConnectError(Exception):
    """Base error for agent connection codes."""


class ConnectCodeNotFoundError(AgentConnectError):
    pass


class ConnectCodeExpiredError(AgentConnectError):
    pass


class ConnectCodeRevokedError(AgentConnectError):
    pass


class ConnectCodeClaimLimitError(AgentConnectError):
    pass


class PublicUrlNotAllowedError(AgentConnectError):
    pass
