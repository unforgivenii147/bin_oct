#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import logging
import shutil
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path

from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(Path.home() / "face_detection.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
try:
    import cv2

    FACE_DETECTION_AVAILABLE = True
except ImportError:
    FACE_DETECTION_AVAILABLE = False
    print("❌ OpenCV not installed. Install with: pkg install opencv")
    sys.exit(1)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
MAX_DIMENSION = 640
CASCADE_DIR = "/data/data/com.termux/files/home/.local/share/opencv4/haarcascades/"
cascade_path = [
    "frontalface_default.xml",
    "frontalface_alt.xml",
    "frontalface_alt2.xml",
    "frontalface_alt_tree.xml",
]


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def create_face_detector(cascade_path):
    face_cascade = cv2.CascadeClassifier(CASCADE_DIR + cascade_path[0])
    if face_cascade.empty():
        logger.error("Failed to load cascade classifier")
        return None

    def detect_face(image_path: Path) -> bool:
        try:
            image = cv2.imread(str(image_path))
            if image is None:
                logger.warning(f"Cannot read image: {image_path.name}")
                return True
            h, w = image.shape[:2]
            max_dim = max(h, w)
            if max_dim > MAX_DIMENSION:
                scale = MAX_DIMENSION / max_dim
                new_w, new_h = int(w * scale), int(h * scale)
                image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30),
                flags=cv2.CASCADE_SCALE_IMAGE,
            )
            return len(faces) > 0
        except Exception as e:
            logger.error(f"Face detection error for {image_path.name}: {e}")
            return True

    return detect_face


def process_image_batch(args):
    image_path, current_dir, noface_dir, cascade_path = args
    detect_face = create_face_detector(cascade_path)
    if detect_face is None:
        return image_path, None, False, True
    try:
        if not image_path.exists():
            return image_path, None, False, True
        has_face = detect_face(image_path)
        if not has_face:
            try:
                relative_path = image_path.relative_to(current_dir)
            except ValueError:
                relative_path = image_path.name
            destination = noface_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(image_path), str(destination))
            return image_path, destination, True, has_face
        else:
            return image_path, None, False, has_face
    except Exception as e:
        logger.error(f"Error processing {image_path.name}: {e}")
        return image_path, None, False, True


def collect_images(directory: Path, exclude_dir: Path) -> list:
    images = []
    try:
        for path in directory.rglob("*"):
            if exclude_dir in path.parents or path.parent == exclude_dir:
                continue
            if path.is_file() and is_image_file(path):
                images.append(path)
    except Exception as e:
        logger.error(f"Error scanning directory: {e}")
    return images


def process_images(num_workers: int | None = None):
    current_dir = Path.cwd()
    noface_dir = Path("/sdcard/DCIM/noface")
    try:
        noface_dir.mkdir(exist_ok=True)
    except Exception as e:
        print(f"❌ ERROR: Cannot create directory {noface_dir}: {e}")
        return False
    print("\n🔍 Scanning for images...")
    images = collect_images(current_dir, noface_dir)
    if not images:
        print("⚠️ No images found!")
        return False
    print(f"📸 Found {len(images)} images")
    if num_workers is None:
        num_workers = min(cpu_count(), len(images), 4)
    num_workers = max(1, min(num_workers, 4))
    print(f"⚙️ Using {num_workers} worker processes\n")
    args_list = [(img, current_dir, noface_dir, cascade_path) for img in images]
    results = []
    start_time = time.time()
    if num_workers > 1:
        with Pool(processes=num_workers) as pool:
            for result in tqdm(
                pool.imap_unordered(process_image_batch, args_list),
                total=len(images),
                desc="Processing images",
                unit="img",
            ):
                results.append(result)
    else:
        for args in tqdm(args_list, desc="Processing images", unit="img"):
            results.append(process_image_batch(args))
    elapsed_time = time.time() - start_time
    total = len(results)
    moved = sum(1 for _, _, moved, _ in results if moved)
    noface_count = sum(1 for _, _, _, has_face in results if not has_face)
    has_face_count = total - noface_count
    print("\n" + "=" * 40)
    print("📊 SUMMARY")
    print("-" * 40)
    print(f"Total images:     {total}")
    print(f"With faces:       {has_face_count}")
    print(f"Without faces:    {noface_count}")
    print(f"Moved to noface: {moved}")
    print(f"Time elapsed:     {elapsed_time:.2f} seconds")
    print(f"Speed:            {total / elapsed_time:.1f} images/second")
    if moved > 0:
        print(f"\n📁 Moved to: {noface_dir}")
    print("-" * 40)
    return True


def main():
    print("🔍 Checking for Haar cascade file...")
    if not cascade_path:
        print("❌ Cascade file not found!")
        print("Install OpenCV with: pkg install opencv")
        sys.exit(1)
    print(f"✅ CASCADE FOUND: {cascade_path}")
    if not FACE_DETECTION_AVAILABLE:
        sys.exit(1)
    print("\n" + "=" * 40)
    print("📸 FACE DETECTION IMAGE ORGANIZER")
    print("-" * 40)
    print(f"Working directory: {Path.cwd()}")
    print("Images WITH faces → stay in place")
    print("Images WITHOUT faces → moved to 'noface/'")
    print("-" * 40)
    num_workers = None
    if len(sys.argv) > 1:
        try:
            num_workers = int(sys.argv[1])
            print(f"\n⚙️ Using {num_workers} workers (from command line)")
        except ValueError:
            print(f"\n⚠️ Invalid worker count: {sys.argv[1]}, using auto-detection")
    success = process_images(num_workers)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    raise SystemExit(main())
