#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import random
import string
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastwalk import walk_files

AES_BLOCK_SIZE = 128


def random_key(length: int = 32) -> str:
    return "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


def encrypt_file(path: Path, key: str) -> None:
    from os import urandom

    backend = default_backend()
    iv = urandom(16)
    cipher = Cipher(algorithms.AES(key.encode()), modes.CBC(iv), backend=backend)
    encryptor = cipher.encryptor()
    data = path.read_bytes()
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data) + padder.finalize()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    path.write_bytes(iv + encrypted_data)


def decrypt_file(path: Path, key: str) -> None:
    backend = default_backend()
    raw = path.read_bytes()
    iv = raw[:16]
    ciphertext = raw[16:]
    cipher = Cipher(algorithms.AES(key.encode()), modes.CBC(iv), backend=backend)
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded_data) + unpadder.finalize()
    path.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encrypt", action="store_true")
    parser.add_argument("--decrypt", action="store_true")
    parser.add_argument("--key", help="Encryption/decryption key")
    args = parser.parse_args()
    msg = "Please specify --encrypt or --decrypt with --key if decrypting"
    if args.encrypt:
        key = random_key()
        print(f"Encryption key: {key}")
        action = encrypt_file
        with Path("key").open("a", encoding="utf-8") as f:
            f.write("\n")
            f.write(key)
    elif args.decrypt:
        if not args.key:
            raise SystemExit(msg)
        key = args.key
        action = decrypt_file
    else:
        raise SystemExit(msg)
    for path_str in walk_files("."):
        path = Path(path_str)
        if path.is_file() and path.name != "key":
            action(path, key)


if __name__ == "__main__":
    raise SystemExit(main())
