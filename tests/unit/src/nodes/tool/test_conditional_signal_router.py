from src.nodes.tool.conditional_signal_router import ConditionalSignalRouter


def _build_node(*, condition: bool) -> ConditionalSignalRouter:
    return ConditionalSignalRouter(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-router-1",
        condition=condition,
    )


def test_conditional_signal_router_routes_then_branch() -> None:
    node = _build_node(condition=True)

    node.process()

    assert node.then_signal is True
    assert node.else_signal is False


def test_conditional_signal_router_routes_else_branch() -> None:
    node = _build_node(condition=False)

    node.process()

    assert node.then_signal is False
    assert node.else_signal is True
