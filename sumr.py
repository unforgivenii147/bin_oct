#!/data/data/com.termux/files/home/.local/bin/python
"""
summarizer.py — Unified text summarization CLI.

Combines three original scripts into one argparse-driven tool with a
pluggable "backend" concept.

Backends
--------
nltk         Frequency-based summarizer using NLTK (from `summa.py`).
             Supports ratio-based and count-based selection, plus a
             `scores` subcommand to dump per-sentence scores.
nltk-simple  Frequency-based summarizer with the simpler scoring of
             `sumr_nltk.py` (no frequency normalization; denominator
             counts every token).
sumy         Wraps the `sumy` library's LexRank / LSA / TextRank
             summarizers (from `sumr.py`).

Third-party packages (must be installed separately)
---------------------------------------------------
    pip install nltk sumy
    python -m nltk.downloader punkt stopwords

Original -> merged mapping
--------------------------
summa.py     -> summarizer.py summarize <file> -b nltk -r 0.3 --no-save
                summarizer.py summarize <file> -b nltk -c 3   --no-save
                summarizer.py scores    <file> -b nltk
sumr.py      -> summarizer.py summarize <file> -b sumy -c 5 -m lexrank
sumr_nltk.py -> summarizer.py summarize <file> -b nltk-simple -c 5

Usage examples
--------------
    python summarizer.py summarize article.txt -b nltk -r 0.3
    python summarizer.py summarize article.txt -b nltk -c 3 --no-save
    python summarizer.py summarize article.txt -b nltk-simple -c 5
    python summarizer.py summarize article.txt -b sumy -m textrank -c 5
    python summarizer.py scores    article.txt -n 10
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence


# ============================================================================
# Shared helpers
# ============================================================================

def read_text(path: Path) -> str:
    """Read a UTF-8 text file. Raises FileNotFoundError on missing input."""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """Write a UTF-8 text file (creating parents if needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def default_summary_path(input_path: Path) -> Path:
    """
    Derive the default output filename: <stem>_summary.txt (matches
    `sumr.py` / `sumr_nltk.py`).
    """
    return input_path.with_name(input_path.stem + "_summary.txt")


def preview(text: str, limit: int = 500) -> str:
    """Truncate long summaries for terminal display."""
    return text if len(text) <= limit else text[:limit] + "..."


# ============================================================================
# NLTK frequency-based summarizer
# ============================================================================

class NLTKFrequencySummarizer:
    """
    Frequency-based extractive summarizer using NLTK.

    Two variants are supported so both original behaviors remain reachable:

    * ``variant="summa"``  — mirrors `summa.py`:
        - word frequencies normalized by the total number of alnum,
          non-stopword tokens;
        - sentence score = sum(freq) / (#alnum non-stopword tokens).

    * ``variant="simple"`` — mirrors `sumr_nltk.py`:
        - raw (unnormalized) word counts;
        - sentence score = sum(freq) / (#all tokens, including
          punctuation and stopwords).
    """

    VARIANTS = ("summa", "simple")

    def __init__(self, language: str = "english", variant: str = "summa") -> None:
        if variant not in self.VARIANTS:
            raise ValueError(
                f"Unknown nltk variant {variant!r}; choose one of {self.VARIANTS}"
            )
        # Lazy import so `--help` works without nltk installed.
        from nltk.corpus import stopwords  # type: ignore

        self.language: str = language
        self.variant: str = variant
        self.stop_words = set(stopwords.words(language))

    # ---- public API --------------------------------------------------------

    def summarize_by_ratio(self, text: str, ratio: float = 0.3) -> str:
        """Keep the top ``ratio`` fraction of sentences (nltk/summa only)."""
        if not text or not isinstance(text, str):
            return ""
        if not 0 < ratio <= 1:
            raise ValueError("Ratio must be between 0 and 1")

        text = self._preprocess(text)
        sentences = self._tokenize_sentences(text)
        if len(sentences) <= 1:
            return text

        k = max(1, int(len(sentences) * ratio))
        freqs = self._word_frequencies(sentences)
        scores = self._score_sentences(sentences, freqs)
        top = self._select_top(scores, k)
        return " ".join(sentences[i] for i in top)

    def summarize_by_count(self, text: str, count: int = 3) -> str:
        """Keep the top ``count`` sentences, preserving original order."""
        if not text or not isinstance(text, str):
            return ""
        if count < 1:
            raise ValueError("Number of sentences must be >= 1")

        text = self._preprocess(text)
        sentences = self._tokenize_sentences(text)
        if len(sentences) <= count:
            return text

        freqs = self._word_frequencies(sentences)
        scores = self._score_sentences(sentences, freqs)
        top = self._select_top(scores, count)
        return " ".join(sentences[i] for i in top)

    def get_scores(self, text: str) -> Dict[str, float]:
        """Return a mapping {sentence -> score}, ordered by original text."""
        text = self._preprocess(text)
        sentences = self._tokenize_sentences(text)
        freqs = self._word_frequencies(sentences)
        scores = self._score_sentences(sentences, freqs)
        return {sentences[i]: s for i, s in scores.items()}

    # ---- internals ---------------------------------------------------------

    @staticmethod
    def _preprocess(text: str) -> str:
        """Collapse all whitespace into single spaces (summa.py behavior)."""
        return re.sub(r"\s+", " ", text).strip()

    def _tokenize_sentences(self, text: str) -> List[str]:
        """Sentence-tokenize and drop sentences with <= 2 words."""
        from nltk.tokenize import sent_tokenize  # type: ignore

        return [s.strip() for s in sent_tokenize(text) if len(s.split()) > 2]

    def _word_frequencies(self, sentences: Sequence[str]) -> Dict[str, float]:
        """
        Count alnum non-stopword tokens. If variant == "summa", normalize
        each count by the grand total (summa.py behavior).
        """
        from nltk.tokenize import word_tokenize  # type: ignore

        counter: Counter = Counter()
        total = 0
        for sentence in sentences:
            for token in word_tokenize(sentence.lower()):
                if token.isalnum() and token not in self.stop_words:
                    counter[token] += 1
                    total += 1

        if self.variant == "summa" and total > 0:
            for token in counter:
                counter[token] /= total
        return dict(counter)

    def _score_sentences(
        self,
        sentences: Sequence[str],
        freqs: Dict[str, float],
    ) -> Dict[int, float]:
        """
        Score each sentence using the variant-appropriate denominator.
        """
        from nltk.tokenize import word_tokenize  # type: ignore

        scores: Dict[int, float] = {}
        for i, sentence in enumerate(sentences):
            tokens = word_tokenize(sentence.lower())
            if self.variant == "simple":
                # sumr_nltk.py: numerator = sum over all tokens (non-freq
                # tokens contribute 0), denominator = len(all tokens).
                score = sum(freqs.get(t, 0) for t in tokens)
                n = len(tokens)
            else:
                # summa.py: restrict both numerator and denominator to
                # alnum non-stopword tokens.
                relevant = [t for t in tokens
                            if t.isalnum() and t not in self.stop_words]
                score = sum(freqs.get(t, 0) for t in relevant)
                n = len(relevant)
            scores[i] = score / n if n else 0.0
        return scores

    @staticmethod
    def _select_top(scores: Dict[int, float], k: int) -> List[int]:
        """Return the indices of the k highest-scoring sentences, in order."""
        top = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)[:k]
        return sorted(top)


# ============================================================================
# Sumy backend
# ============================================================================

def sumy_summarize(
    text: str,
    count: int = 5,
    method: str = "lexrank",
    language: str = "english",
) -> str:
    """
    Summarize ``text`` using the sumy library.

    Mirrors ``sumr.py`` but accepts text directly (no intermediate file),
    so we don't need to write/read a temp file for in-memory operation.
    """
    # Lazy imports — sumy is optional.
    from sumy.nlp.stemmers import Stemmer          # type: ignore
    from sumy.nlp.tokenizers import Tokenizer       # type: ignore
    from sumy.parsers.plaintext import PlaintextParser  # type: ignore
    from sumy.summarizers.lex_rank import LexRankSummarizer  # type: ignore
    from sumy.summarizers.lsa import LsaSummarizer  # type: ignore
    from sumy.summarizers.text_rank import TextRankSummarizer  # type: ignore
    from sumy.utils import get_stop_words           # type: ignore

    parser = PlaintextParser.from_string(text, Tokenizer(language))
    stemmer = Stemmer(language)

    if method == "lexrank":
        summarizer = LexRankSummarizer(stemmer)
    elif method == "lsa":
        summarizer = LsaSummarizer(stemmer)
    elif method == "textrank":
        summarizer = TextRankSummarizer(stemmer)
    else:
        raise ValueError(f"Unknown summarization method: {method}")

    summarizer.stop_words = get_stop_words(language)
    sentences = summarizer(parser.document, count)
    return " ".join(str(s) for s in sentences)


# ============================================================================
# Subcommand handlers
# ============================================================================

def cmd_summarize(args: argparse.Namespace) -> int:
    """Handle ``summarizer.py summarize ...``."""
    text = read_text(args.input)

    # --- dispatch on backend ------------------------------------------------
    if args.backend == "sumy":
        count = args.count if args.count is not None else 5
        summary = sumy_summarize(
            text, count=count, method=args.method, language=args.language,
        )

    elif args.backend == "nltk-simple":
        count = args.count if args.count is not None else 5
        summarizer = NLTKFrequencySummarizer(
            language=args.language, variant="simple",
        )
        summary = summarizer.summarize_by_count(text, count=count)

    else:  # "nltk"
        summarizer = NLTKFrequencySummarizer(
            language=args.language, variant="summa",
        )
        if args.ratio is not None:
            summary = summarizer.summarize_by_ratio(text, ratio=args.ratio)
        elif args.count is not None:
            summary = summarizer.summarize_by_count(text, count=args.count)
        else:
            # Default: summa.py's default ratio.
            summary = summarizer.summarize_by_ratio(text, ratio=0.3)

    # --- persistence --------------------------------------------------------
    if not args.no_save:
        out_path = args.output or default_summary_path(args.input)
        write_text(out_path, summary)
        if not args.quiet:
            print(f"Summary saved to '{out_path}'")

    # --- console output -----------------------------------------------------
    if not args.quiet:
        print()
        print(preview(summary))

    return 0


def cmd_scores(args: argparse.Namespace) -> int:
    """Handle ``summarizer.py scores ...`` (nltk backend only)."""
    text = read_text(args.input)
    summarizer = NLTKFrequencySummarizer(
        language=args.language, variant="summa",
    )
    scores = summarizer.get_scores(text)

    items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if args.top is not None:
        items = items[: args.top]

    for sentence, score in items:
        print(f"Score: {score:.4f} | {sentence[:60]}...")
    return 0


# ============================================================================
# Argument parser
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="summarizer.py",
        description="Unified text summarizer (NLTK / NLTK-simple / Sumy).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ---- summarize ---------------------------------------------------------
    p = sub.add_parser(
        "summarize",
        help="Produce a summary of a text file.",
        description="Summarize an input text file using the chosen backend.",
    )
    p.add_argument("input", type=Path, help="Input text file.")
    p.add_argument(
        "-b", "--backend",
        choices=("nltk", "nltk-simple", "sumy"),
        default="nltk",
        help="Summarization backend (default: nltk).",
    )
    p.add_argument(
        "-m", "--method",
        choices=("lexrank", "lsa", "textrank"),
        default="lexrank",
        help="Sumy algorithm (sumy backend only; default: lexrank).",
    )
    p.add_argument(
        "-c", "--count", type=int, default=None,
        help="Number of sentences to keep. Defaults: 3 for nltk, "
             "5 for nltk-simple and sumy.",
    )
    p.add_argument(
        "-r", "--ratio", type=float, default=None,
        help="Fraction of sentences to keep (nltk backend only). "
             "Overrides --count. Default for nltk: 0.3.",
    )
    p.add_argument(
        "-l", "--language", default="english",
        help="Language for stopwords/tokenization (default: english).",
    )
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output file (default: <input>_summary.txt).",
    )
    p.add_argument(
        "--no-save", action="store_true",
        help="Do not write the summary to disk; only print it "
             "(preserves summa.py's stdout-only behavior).",
    )
    p.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress the printed preview (still writes the output file).",
    )

    # ---- scores ------------------------------------------------------------
    q = sub.add_parser(
        "scores",
        help="Print per-sentence scores (nltk backend only).",
        description="Dump per-sentence scores, sorted descending.",
    )
    q.add_argument("input", type=Path, help="Input text file.")
    q.add_argument(
        "-b", "--backend", choices=("nltk",), default="nltk",
        help="Backend (only nltk supports scoring).",
    )
    q.add_argument(
        "-l", "--language", default="english",
        help="Language for stopwords/tokenization (default: english).",
    )
    q.add_argument(
        "-n", "--top", type=int, default=None,
        help="Only show the top N highest-scoring sentences.",
    )

    return parser


# ============================================================================
# Entry point
# ============================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a shell exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "summarize":
            return cmd_summarize(args)
        if args.command == "scores":
            return cmd_scores(args)
        parser.print_help()
        return 1
    except FileNotFoundError:
        print(f"Error: file '{args.input}' not found", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(
            f"Error: missing dependency ({exc}). "
            f"Install with: pip install nltk sumy",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 — surface any backend error
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
