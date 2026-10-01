from src.exception_registry import RegisteredException


class KafkaUnavailableError(RegisteredException):
    category = "KAFKA_UNAVAILABLE"


class KafkaSnapshotLostError(RegisteredException):
    category = "KAFKA_SNAPSHOT_LOST"


class KafkaDecodeError(RegisteredException):
    category = "KAFKA_DECODE_ERROR"


class KafkaCommitError(RegisteredException):
    category = "KAFKA_COMMIT_UNCERTAIN"
