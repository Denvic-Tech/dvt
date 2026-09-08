from src.node_dsl import PrimitiveBaseNode, InputField, OutputField


class CreateStringNode(PrimitiveBaseNode):
    TITLE = "Create String"
    CATEGORY = "Primitive"
    DISABLED = True

    string: str = InputField()

    output: str = OutputField()

    def process(self):
        self.output = self.string
