from core.security import derive_legacy_auth_secret


def test_derive_legacy_auth_secret_is_stable_and_purpose_separated() -> None:
    master_secret = "Y8RFpaIxSaAFNsB352tpLXl5znUw5anEKIZgclOezak="

    access_secret = derive_legacy_auth_secret(master_secret, "JWT_ACCESS_TOKEN_SECRET_KEY")
    refresh_secret = derive_legacy_auth_secret(master_secret, "JWT_REFRESH_TOKEN_SECRET_KEY")

    assert access_secret == derive_legacy_auth_secret(
        master_secret,
        "JWT_ACCESS_TOKEN_SECRET_KEY",
    )
    assert access_secret != refresh_secret
    assert len(access_secret) >= 32


def test_derive_legacy_auth_secret_rejects_empty_inputs() -> None:
    for master_secret, secret_name in (
        ("", "JWT_ACCESS_TOKEN_SECRET_KEY"),
        ("master", ""),
    ):
        try:
            derive_legacy_auth_secret(master_secret, secret_name)
        except ValueError:
            pass
        else:
            raise AssertionError("empty derivation input must be rejected")
