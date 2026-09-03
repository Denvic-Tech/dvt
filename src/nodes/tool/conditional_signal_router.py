from src.node_dsl import IO, InputField, OutputField, SignalOutputBaseNode


class ConditionalSignalRouter(SignalOutputBaseNode):
    TITLE = "Conditional Signal Router"
    EMOJI = "🔀"
    CATEGORY = "Tool"
    CACHABLE = False
    AUTO_ACTIVATE_SIGNAL_OUTPUTS = False
    DISABLED_OUTPUTS = frozenset({"signal_out"})

    input_variables: dict[str, IO.VARIABLE] = InputField(
        default={},
        description="Input variables",
        allow_multiple_connections=True,
        force_handle_visible=True,
    )
    condition: IO.BOOLEAN = InputField(
        description="Boolean condition that selects the outgoing signal branch.",
        expression_policy="default",
    )

    then_signal: IO.SIGNAL = OutputField(
        description="Execution signal output for the 'IF' branch.",
        force_handle_visible=True,
    )
    else_signal: IO.SIGNAL = OutputField(
        description="Execution signal output for the 'ELSE' branch.",
        force_handle_visible=True,
    )

    def process(self) -> None:
        condition_result = bool(self.condition)
        self.then_signal = condition_result
        self.else_signal = not condition_result

    async def process_metadata(self) -> None:
        # Metadata-only mode must keep both branches reachable so downstream
        # metadata collection is not gated by runtime-only conditions.
        self.then_signal = True
        self.else_signal = True
