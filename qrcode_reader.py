#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys

from PIL import Image
from pyzbar.pyzbar import decode


def read_qr_code(image_path):
    try:
        img = Image.open(image_path)
        decoded_objects = decode(img)
        if not decoded_objects:
            print("No QR code found in the image.")
            return []
        print(f"Found {len(decoded_objects)} QR code(s):\n")
        results = []
        for i, obj in enumerate(decoded_objects, 1):
            data = obj.data.decode("utf-8")
            rect = obj.rect
            print(f"QR Code {i}:")
            print(f"  Data: {data}")
            print(f"  Type: {obj.type}")
            print(
                f"  Position: (left={rect.left}, top={rect.top}, width={rect.width}, height={rect.height})"
            )
            print()
            results.append(data)
        return results
    except FileNotFoundError:
        print(f"Error: Image file '{image_path}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing image: {e}")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python qr_reader.py <image_path>")
        print("Example: python qr_reader.py qrcode.png")
        sys.exit(1)
    img_path = sys.argv[1]
    print(f"Reading QR code from: {img_path}\n")
    results = read_qr_code(img_path)
    if results:
        print("First QR code data only:")
        print(results[0])


if __name__ == "__main__":
    raise SystemExit(main())
