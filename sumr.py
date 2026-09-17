#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import os
import sys

from sumy.nlp.stemmers import Stemmer
from sumy.nlp.tokenizers import Tokenizer
from sumy.parsers.plaintext import PlaintextParser
from sumy.summarizers.lex_rank import LexRankSummarizer
from sumy.summarizers.lsa import LsaSummarizer
from sumy.summarizers.text_rank import TextRankSummarizer
from sumy.utils import get_stop_words


def summarize_file(input_file, sentences_count=5, method="lexrank", language="english"):
    parser = PlaintextParser.from_file(input_file, Tokenizer(language))
    if method == "lexrank":
        summarizer = LexRankSummarizer(Stemmer(language))
    elif method == "lsa":
        summarizer = LsaSummarizer(Stemmer(language))
    elif method == "textrank":
        summarizer = TextRankSummarizer(Stemmer(language))
    else:
        raise ValueError(f"Unknown summarization method: {method}")
    summarizer.stop_words = get_stop_words(language)
    summary = summarizer(parser.document, sentences_count)
    return " ".join([str(sentence) for sentence in summary])


def main():
    if len(sys.argv) < 2:
        print("Usage: python summarize.py <input_file> [sentences_count] [method]")
        print("Methods: lexrank (default), lsa, textrank")
        sys.exit(1)
    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found")
        sys.exit(1)
    sentences_count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    method = sys.argv[3] if len(sys.argv) > 3 else "lexrank"
    base_name = os.path.splitext(input_file)[0]
    output_file = f"{base_name}_summary.txt"
    try:
        print(f"Summarizing '{input_file}' using {method} method...")
        summary = summarize_file(input_file, sentences_count, method)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"Summary saved to '{output_file}'")
        print(f"\nSummary preview ({sentences_count} sentences):")
        print("-" * 40)
        print(summary[:500] + "..." if len(summary) > 500 else summary)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
