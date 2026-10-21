import pytest

from src.modules.data_catalog.domain.policies import expression_dependencies

COLUMNS = ("amount", "qty", "unit price", "tax")


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("amount * qty", ("amount", "qty")),
        ("`unit price` * qty + tax", ("unit price", "qty", "tax")),
        ("amount > @threshold", ("amount",)),
        ("amount.fillna(0) + unknown_col", ("amount",)),
        ("1 + 2", ()),
    ],
)
def test_dependencies_are_input_columns_in_order_of_appearance(expression, expected):
    assert expression_dependencies(expression, COLUMNS) == (expected, False)


def test_unparseable_expression_is_reported_as_unknown():
    deps, failed = expression_dependencies("amount *", COLUMNS)
    assert deps == () and failed is True
