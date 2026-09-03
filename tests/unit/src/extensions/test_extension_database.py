from src.extensions.database import extension_schema_name


def test_extension_schema_name_is_deterministic_safe_and_collision_resistant() -> None:
    assert extension_schema_name("bitrix24-connector") == extension_schema_name(
        "bitrix24-connector"
    )
    assert extension_schema_name("bitrix24-connector").startswith("dvt_ext_")
    assert extension_schema_name("foo-bar") != extension_schema_name("foo_bar")
    assert extension_schema_name("Foo") != extension_schema_name("foo")
    assert len(extension_schema_name("x" * 200)) <= 63
