#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import shutil
from pathlib import Path

from pdf2image import convert_from_path

POPPLER_PATH = None


def convert_pdf_to_jpg(pdf_path: Path, output_folder: Path) -> bool:
    try:
        print(f"Converting '{pdf_path.name}'...")
        pdf_output_dir = output_folder / pdf_path.stem
        pdf_output_dir.mkdir(parents=True, exist_ok=True)
        images = convert_from_path(
            pdf_path=pdf_path,
            dpi=300,
            output_folder=pdf_output_dir,
            fmt="jpeg",
            thread_count=4,
            poppler_path=POPPLER_PATH,
        )
        converted_files = []
        for i, _image_path in enumerate(images):
            expected_jpg_name = f"{pdf_path.stem}_page_{i + 1}.jpeg"
            source_jpg_path = pdf_output_dir / expected_jpg_name
            if source_jpg_path.exists():
                final_jpg_path = pdf_output_dir / f"{pdf_path.stem}_page_{i + 1}.jpg"
                shutil.move(source_jpg_path, final_jpg_path)
                converted_files.append(final_jpg_path)
            else:
                print(
                    f"Warning: Expected file {source_jpg_path} not found after conversion."
                )
        print(
            f"Successfully converted '{pdf_path.name}' to {len(converted_files)} JPG files in '{pdf_output_dir}'."
        )
        return True
    except Exception as e:
        print(f"Error converting '{pdf_path.name}': {e}")
        if "pdf_output_dir" in locals() and pdf_output_dir.exists():
            try:
                shutil.rmtree(pdf_output_dir)
            except Exception as cleanup_e:
                print(f"Error during cleanup of '{pdf_output_dir}': {cleanup_e}")
        return False


def process_directory(start_dir: Path, output_base_dir: Path) -> None:
    print(f"Starting PDF to JPG conversion in directory: {start_dir}")
    print(f"Output will be saved in: {output_base_dir}")
    converted_count = 0
    failed_count = 0
    for item in start_dir.rglob("*"):
        if item.is_file() and item.suffix.lower() == ".pdf":
            if output_base_dir in item.parents:
                print(
                    f"Skipping PDF '{item.name}' as it's within the output directory."
                )
                continue
            if convert_pdf_to_jpg(item, output_base_dir):
                try:
                    item.unlink()
                    print(f"Removed original PDF: '{item.name}'")
                    converted_count += 1
                except OSError as e:
                    print(f"Error removing original PDF '{item.name}': {e}")
                    failed_count += 1
            else:
                failed_count += 1
    print("\n--- Conversion Summary ---")
    print(f"Successfully converted and removed: {converted_count} PDF files.")
    print(f"Failed to convert: {failed_count} PDF files.")
    print("------------------------")


if __name__ == "__main__":
    cwdectory = Path.cwd()
    output_directory = cwdectory / "output_jpgs"
    output_directory.mkdir(exist_ok=True)
    process_directory(cwdectory, output_directory)
    print("\nScript finished.")
    print(f"Converted JPG files are located in: {output_directory}")
