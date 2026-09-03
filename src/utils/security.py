from cryptography.fernet import Fernet

import config

cipher = Fernet(config.SECURITY.FERNET_KEY)


def fernet_decrypt(value: str) -> str:
    decrypted_value = cipher.decrypt(value.encode()).decode()
    return decrypted_value
