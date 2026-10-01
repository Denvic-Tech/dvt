from src.exception_registry import RegisteredException


class KafkaInputError(RegisteredException):
    category = "KAFKA_INPUT_ERROR"


class KafkaPositionError(RegisteredException):
    category = "KAFKA_POSITION_ERROR"


class KafkaMessageTooLargeError(RegisteredException):
    category = "KAFKA_MESSAGE_TOO_LARGE"
