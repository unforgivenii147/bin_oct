#!/data/data/com.termux/files/home/.local/bin/python
import os
import shutil
import sys

import mobi

# Get input file from command line argument
input_file = sys.argv[1]

# Extract the mobi file (returns tempdir and path to extracted content)
tempdir, path = mobi.extract(input_file)
print(f"Extracted to: {path}")

# path points to an .epub or .html file
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Determine output path beside the original .mobi file
base_name = os.path.splitext(os.path.basename(input_file))[0]
output_dir = os.path.dirname(os.path.abspath(input_file))
output_file = os.path.join(output_dir, base_name + ".html")

# If path is an .epub, we may need to handle images/css too.
# Copy the whole extracted directory contents and rename main file to .html
if path.lower().endswith(".epub"):
    # For epub, the content is typically in a folder with html files
    # Copy all extracted files to output_dir/<base_name>_files
    extracted_dir = os.path.dirname(path)
    files_dir = os.path.join(output_dir, base_name + "_files")

    if os.path.exists(files_dir):
        shutil.rmtree(files_dir)
    shutil.copytree(extracted_dir, files_dir)

    # Also save the main content as a single html file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
else:
    # It's already an html file - just write it out
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)

print(f"HTML saved to: {output_file}")

# Clean up temp directory
shutil.rmtree(tempdir, ignore_errors=True)
