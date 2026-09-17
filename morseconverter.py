#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MORSE_CODE_DICT = {
    "A": ".-",
    "B": "-...",
    "C": "-.-.",
    "D": "-..",
    "E": ".",
    "F": "..-.",
    "G": "--.",
    "H": "....",
    "I": "..",
    "J": ".---",
    "K": "-.-",
    "L": ".-..",
    "M": "--",
    "N": "-.",
    "O": "---",
    "P": ".--.",
    "Q": "--.-",
    "R": ".-.",
    "S": "...",
    "T": "-",
    "U": "..-",
    "V": "...-",
    "W": ".--",
    "X": "-..-",
    "Y": "-.--",
    "Z": "--..",
    "1": ".----",
    "2": "..---",
    "3": "...--",
    "4": "....-",
    "5": ".....",
    "6": "-....",
    "7": "--...",
    "8": "---..",
    "9": "----.",
    "0": "-----",
    " ": "/",
}
REVERSE_MORSE_DICT = {v: k for k, v in MORSE_CODE_DICT.items()}


def text_to_morse(text: str) -> str:
    morse = []
    for char in text.upper():
        if char in MORSE_CODE_DICT:
            morse.append(MORSE_CODE_DICT[char])
        else:
            morse.append(char)
    return " ".join(morse)


def morse_to_text(morse: str) -> str:
    text = []
    morse_chars = morse.split(" ")
    for code in morse_chars:
        if code in REVERSE_MORSE_DICT:
            text.append(REVERSE_MORSE_DICT[code])
        elif code:
            text.append(code)
    return "".join(text)


def encrypt_file(input_filename, output_filename) -> None:
    try:
        content = Path(input_filename).read_text(encoding="utf-8")
        morse_content = text_to_morse(content)
        Path(output_filename).write_text(morse_content, encoding="utf-8")
    except FileNotFoundError:
        sys.exit(1)
    except Exception:
        sys.exit(1)


def decrypt_file(input_filename, output_filename) -> None:
    try:
        morse_content = Path(input_filename).read_text(encoding="utf-8")
        text_content = morse_to_text(morse_content)
        Path(output_filename).write_text(text_content, encoding="utf-8")
    except FileNotFoundError:
        sys.exit(1)
    except Exception:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Morse Code Encryptor/Decryptor")
    parser.add_argument("input_file", help="Input file name")
    parser.add_argument("output_file", help="Output file name")
    parser.add_argument(
        "--encrypt", action="store_true", help="Encrypt text to Morse code"
    )
    parser.add_argument(
        "--decrypt", action="store_true", help="Decrypt Morse code to text"
    )
    args = parser.parse_args()
    if args.encrypt and args.decrypt:
        sys.exit(1)
    if not args.encrypt and not args.decrypt:
        sys.exit(1)
    if args.encrypt:
        encrypt_file(args.input_file, args.output_file)
    elif args.decrypt:
        decrypt_file(args.input_file, args.output_file)


if __name__ == "__main__":
    raise SystemExit(main())
