from typing import Any


def getattr_deep(obj: Any, attr: str, default: Any = None) -> Any:
    """Get a nested attribute from an object using dot notation.

    Args:
        obj (Any): The object to get the attribute from.
        attr (str): The attribute to get, in dot notation.
        default (Any, optional): The default value to return if the attribute is not found. Defaults to None.

    Returns:
        Any: The value of the nested attribute, or the default value if not found.
    """
    if isinstance(obj, dict):
        _getattr = lambda _obj, _key: _obj[_key]
    else:
        _getattr = getattr

    try:
        for key in attr.split('.'):
            obj = _getattr(obj, key)
        return obj
    except (AttributeError, KeyError, TypeError):
        return default
