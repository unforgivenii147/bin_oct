#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import random
import string
from pathlib import Path

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

AES_BLOCK_SIZE = 16


def random_key(length: int = 32) -> LiteralString:
    return "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


def encrypt_file(path, key) -> None:
    from os import urandom

    backend = default_backend()
    iv = urandom(AES_BLOCK_SIZE)
    cipher = Cipher(algorithms.AES(key.encode()), modes.CBC(iv), backend=backend)
    encryptor = cipher.encryptor()
    data = Path(path).read_bytes()
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data) + padder.finalize()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    Path(path).write_bytes(iv + encrypted_data)


def decrypt_file(path, key) -> None:
    backend = default_backend()
    raw = Path(path).read_bytes()
    iv = raw[:AES_BLOCK_SIZE]
    ciphertext = raw[AES_BLOCK_SIZE:]
    cipher = Cipher(algorithms.AES(key.encode()), modes.CBC(iv), backend=backend)
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded_data) + unpadder.finalize()
    Path(path).write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encrypt", action="store_true")
    parser.add_argument("--decrypt", action="store_true")
    parser.add_argument("--key", help="Encryption/decryption key")
    args = parser.parse_args()
    if args.encrypt:
        key = random_key()
        print(f"Encryption key: {key}")
        action = encrypt_file
    elif args.decrypt:
        if not args.key:
            print("Error: Decryption key is required.")
            return
        key = args.key
        action = decrypt_file
    else:
        print("Error: Specify either --encrypt or --decrypt.")
        return
    for path in Path.cwd().glob("*"):
        if path.is_file() and path.name != Path(__file__).name:
            print(f"Processing {path}...")
            action(path, key)


if __name__ == "__main__":
    raise SystemExit(main())
