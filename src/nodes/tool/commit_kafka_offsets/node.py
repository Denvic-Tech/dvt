from dataclasses import asdict

from pydantic import BaseModel

from src.logger import logger
from src.modules.kafka_consumption.domain.exceptions import KafkaInputError
from src.modules.kafka_consumption.facade import (
    CommitKafkaOffsets as CommitOffsetsUseCase,
    build_kafka_gateway,
)
from src.modules.kafka_consumption.infra.mappers import offsets_from_json
from src.node_dsl import IO, InputField, KafkaConnectionRecord, SignalOutputBaseNode
from src.node_dsl.variables import UnresolvedValue, VariableOutput
from src.node_dsl.variables.system_variables import build_system_variable_type_map


class KafkaCommitVariables(BaseModel):
    kafka_commit_result: dict
    kafka_partitions_committed: int


class CommitKafkaOffsets(SignalOutputBaseNode):
    TITLE = "Commit Kafka Offsets"
    CATEGORY = "Tools"
    ICON_KEY = "kafka-connection"
    DESCRIPTION = (
        "Explicitly acknowledge the entire Kafka read batch after every required destination "
        "signals success. Use an exclusive group: check-then-commit is not atomic. "
        "At-least-once processing can repeat writes after failures."
    )
    OUTPUT_NODE = True
    CACHABLE = False
    REQUIRES_FRESH_EXECUTION = True
    EXPERIMENTAL = False
    DISABLED = False
    AUTO_ACTIVATE_SIGNAL_OUTPUTS = False
    SYSTEM_VARIABLES_MODEL = KafkaCommitVariables

    connection: KafkaConnectionRecord = InputField(
        description="Kafka connection",
        agent_description=(
            "Connect an accessible Kafka Connection with group commit permissions. "
            "The JSON connection_id is diagnostic; another connection to the same cluster is allowed."
        ),
    )
    offsets: IO.JSON = InputField(
        description="Kafka offsets",
        agent_description=(
            "Use the resolved kafka_offsets JSON from input_variables, normally after connecting "
            "all destination success signals to signal_in. Unresolved input never computes data. "
            "Saved JSON can be committed independently; next_offset is the next message position."
        ),
    )

    def _init_variables(self):
        self.signal_out = False
        self.output_variables = dict(self.output_variables or {})
        for name, var_type in build_system_variable_type_map(self.SYSTEM_VARIABLES_MODEL).items():
            self.output_variables[name] = VariableOutput(
                name=name, type=var_type, var_type="system",
                value=UnresolvedValue(reason="Kafka commit has not completed", declared_type=var_type),
            )
        self.__dict__.pop("_resolved_metadata", None)

    def _gateway(self):
        return build_kafka_gateway(
            properties=self.connection.properties,
            secrets=self.connection.secrets,
            check_cancelled=self.cancellation.raise_if_requested,
        )

    def process(self):
        self._init_variables()
        self.cancellation.raise_if_requested()
        if isinstance(self.offsets, UnresolvedValue):
            raise KafkaInputError("Kafka offsets are unresolved; finish the read and destination first")
        offsets = offsets_from_json(self.offsets)
        result = CommitOffsetsUseCase(self._gateway(), self.cancellation.raise_if_requested).execute(
            offsets
        )
        self.emit_system_variables(KafkaCommitVariables(
            kafka_commit_result={"partitions": [asdict(part) for part in result.partitions]},
            kafka_partitions_committed=result.partitions_committed,
        ))
        self.signal_out = True
        logger.info(
            "Kafka commit topic={} group={} read_id={}: {}",
            offsets.topic, offsets.group_id, offsets.read_id, asdict(result),
        )

    def process_metadata(self):
        self._init_variables()
