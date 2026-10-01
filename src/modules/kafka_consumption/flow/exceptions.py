from src.exception_registry import RegisteredException


class KafkaConsumptionFlowError(RegisteredException):
    """Use named flow exceptions instead of raising RegisteredException directly."""

    category = "KAFKA_CONSUMPTION_FLOW_ERROR"
