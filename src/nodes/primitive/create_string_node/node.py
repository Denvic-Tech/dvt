from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class CreateStringNode(PrimitiveBaseNode):
    TITLE = "Create String"
    CATEGORY = "Primitive"
    DISABLED = True

    string: str = InputField(
        agent_description=(
            "Disabled legacy primitive. If maintaining an existing graph, supply the string to "
            "emit unchanged after normal input resolution; this node performs no parsing or "
            "formatting."
        ),
    )

    output: str = OutputField()

    def process(self):
        self.output = self.string
