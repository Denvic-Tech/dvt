import blake3


def _new_hasher():
    return blake3.blake3()
