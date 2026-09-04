import importlib
import sys


def _purge_transform_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src.nodes.transform" or module_name.startswith("src.nodes.transform."):
            sys.modules.pop(module_name, None)


def test_import_category_does_not_eager_import_nodes() -> None:
    _purge_transform_modules()

    importlib.import_module("src.nodes.transform")

    loaded = {
        name
        for name in sys.modules
        if name.startswith("src.nodes.transform.")
    }
    assert loaded == set()


def test_import_single_node_does_not_eager_import_category() -> None:
    _purge_transform_modules()

    module = importlib.import_module("src.nodes.transform.df_join")

    assert module.DataFrameJoin.__module__ == "src.nodes.transform.df_join.node"
    assert "src.nodes.transform.df_join.node" in sys.modules
    assert "src.nodes.transform.df_filter" not in sys.modules
    assert "src.nodes.transform.df_union" not in sys.modules
