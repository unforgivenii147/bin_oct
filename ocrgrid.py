#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image


def pil_to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def cv_to_pil(img: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def to_grayscale(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def rescale(img: np.ndarray, scale: float = 2.0) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.resize(
        img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
    )


def deskew(img: np.ndarray) -> np.ndarray:
    gray = to_grayscale(img)
    coords = np.column_stack(np.where(gray > 0))
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    h, w = img.shape[:2]
    center = w // 2, h // 2
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def rotate(img: np.ndarray, angle: int) -> np.ndarray:
    h, w = img.shape[:2]
    center = w // 2, h // 2
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC)


def run_tesseract(img: Image.Image, psm: int, oem: int, dpi: int) -> dict[str, str]:
    config = f"--psm {psm} --oem {oem} -c user_defined_dpi={dpi}"
    text = pytesseract.image_to_string(img, config=config)
    return {"psm": psm, "oem": oem, "dpi": dpi, "config": config, "text": text}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fname", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=Path("ocr_output"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    base_img = Image.open(args.fname).convert("RGB")
    cv_img = pil_to_cv(base_img)
    image_variants: dict[str, Image.Image] = {
        "original": base_img,
        "grayscale": cv_to_pil(to_grayscale(cv_img)),
        "rescaled": cv_to_pil(rescale(cv_img)),
        "deskewed": cv_to_pil(deskew(cv_img)),
        "rotated_90": cv_to_pil(rotate(cv_img, 90)),
    }
    psm_values = [3, 4, 6, 11]
    oem_values = [1, 3]
    dpi_values = [150, 300]
    report_index: list[dict] = []
    for variant_name, img in image_variants.items():
        variant_dir = args.out / variant_name
        variant_dir.mkdir(exist_ok=True)
        for psm in psm_values:
            for oem in oem_values:
                for dpi in dpi_values:
                    result = run_tesseract(img, psm, oem, dpi)
                    tag = f"psm{psm}_oem{oem}_dpi{dpi}"
                    txt_path = variant_dir / f"{tag}.txt"
                    meta_path = variant_dir / f"{tag}.json"
                    txt_path.write_text(result["text"], encoding="utf-8")
                    meta_path.write_text(
                        json.dumps(
                            {
                                "image_variant": variant_name,
                                "source_file": str(args.fname),
                                "tesseract": result,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    report_index.append(
                        {
                            "variant": variant_name,
                            "psm": psm,
                            "oem": oem,
                            "dpi": dpi,
                            "text_file": str(txt_path),
                        }
                    )
    (args.out / "index.json").write_text(
        json.dumps(report_index, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
