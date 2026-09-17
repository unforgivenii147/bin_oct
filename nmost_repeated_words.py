#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

try:
    import nltk
    from nltk.corpus import stopwords
    from nltk.tokenize import word_tokenize

    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    print("Warning: NLTK not installed. Install with: pip install nltk")
    print("Falling back to regex-based tokenization...\n")


def split_compound_words(text: str) -> str:
    return re.sub(r"[-_]", " ", text)


def tokenize_with_nltk(text: str) -> list[str]:
    text = split_compound_words(text)
    tokens = word_tokenize(text.lower())
    tokens = [token for token in tokens if token.isalnum()]
    return tokens


def tokenize_with_regex(text: str) -> list[str]:
    text = split_compound_words(text)
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return tokens


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 word_frequency.py <input_file> <n>")
        sys.exit(1)
    input_file = Path(sys.argv[1])
    try:
        n = int(sys.argv[2])
        if n <= 0:
            print("Error: n must be a positive integer")
            sys.exit(1)
    except ValueError:
        print("Error: n must be a valid integer")
        sys.exit(1)
    if not input_file.exists():
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)
    content = input_file.read_text(encoding="utf-8", errors="ignore")
    if NLTK_AVAILABLE:
        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            print("Downloading NLTK punkt tokenizer data...")
            nltk.download("punkt", quiet=True)
        words = tokenize_with_nltk(content)
    else:
        words = tokenize_with_regex(content)
    if NLTK_AVAILABLE:
        try:
            nltk.data.find("corpora/stopwords")
        except LookupError:
            nltk.download("stopwords", quiet=True)
        stop_words = set(stopwords.words("english"))
        words = [word for word in words if word not in stop_words]
    word_counts = Counter(words)
    top_words = word_counts.most_common(n)
    print(f"\nTop {n} most frequent words in '{input_file}':")
    print("-" * 40)
    print(f"{'Rank':<6} {'Word':<25} {'Count':<8} {'Frequency %'}")
    print("-" * 40)
    total_words = len(words)
    for i, (word, count) in enumerate(top_words, 1):
        percentage = (count / total_words * 40) if total_words > 0 else 0
        print(f"{i:<6} {word:<25} {count:<8} {percentage:.2f}%")
    print("-" * 40)
    print(f"Total unique words: {len(word_counts)}")
    print(f"Total words: {total_words}")
    if NLTK_AVAILABLE:
        print(f"Tokenizer: NLTK")
    else:
        print(f"Tokenizer: Regex (fallback)")


if __name__ == "__main__":
    main()
