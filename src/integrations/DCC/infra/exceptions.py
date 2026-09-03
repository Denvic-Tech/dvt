class DCCIntegrationError(Exception):
    pass


class DCCTransportError(DCCIntegrationError):
    pass


class DCCResponseValidationError(DCCIntegrationError):
    pass


class DCCUnexpectedResponseError(DCCIntegrationError):
    pass
