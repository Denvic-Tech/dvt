from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_prod_builder_includes_extension_api_package() -> None:
    dockerfile = (PROJECT_ROOT / "docker" / "prod-builder.Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "COPY dvt_extension_api /app/dvt_extension_api" in dockerfile


def test_dev_builder_includes_extension_api_package_in_final_image() -> None:
    dockerfile = (PROJECT_ROOT / "docker" / "dev-builder.Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "COPY dvt_extension_api /app/dvt_extension_api" in dockerfile
    assert (
        "COPY --from=base-builder /app/dvt_extension_api /app/dvt_extension_api"
        in dockerfile
    )
