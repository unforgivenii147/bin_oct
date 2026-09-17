#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize, word_tokenize


class TextSummarizer:
    def __init__(self, language: str = "english") -> None:
        self.language = language
        self.stop_words = set(stopwords.words(language))

    def _preprocess_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _tokenize_sentences(self, text: str) -> list[str]:
        sentences = sent_tokenize(text)
        return [s.strip() for s in sentences if len(s.split()) > 2]

    def _calculate_word_frequencies(self, sentences: list[str]) -> dict[str, float]:
        word_freq = defaultdict(int)
        total_words = 0
        for sentence in sentences:
            words = word_tokenize(sentence.lower())
            for word in words:
                if word.isalnum() and word not in self.stop_words:
                    word_freq[word] += 1
                    total_words += 1
        if total_words > 0:
            for word in word_freq:
                word_freq[word] /= total_words
        return dict(word_freq)

    def _score_sentences(
        self, sentences: list[str], word_freq: dict[str, float]
    ) -> dict[int, float]:
        sentence_scores = {}
        for idx, sentence in enumerate(sentences):
            words = word_tokenize(sentence.lower())
            score = 0
            word_count = 0
            for word in words:
                if word.isalnum() and word in word_freq:
                    score += word_freq[word]
                    word_count += 1
            if word_count > 0:
                sentence_scores[idx] = score / word_count
            else:
                sentence_scores[idx] = 0
        return sentence_scores

    def _select_top_sentences(
        self, sentence_scores: dict[int, float], num_sentences: int
    ) -> list[int]:
        top_indices = sorted(
            sentence_scores.keys(), key=lambda x: sentence_scores[x], reverse=True
        )[:num_sentences]
        return sorted(top_indices)

    def summarize(self, text: str, ratio: float = 0.3) -> str:
        if not text or not isinstance(text, str):
            return ""
        if not 0 < ratio <= 1:
            raise ValueError("Ratio must be between 0 and 1")
        text = self._preprocess_text(text)
        sentences = self._tokenize_sentences(text)
        if len(sentences) <= 1:
            return text
        num_sentences = max(1, int(len(sentences) * ratio))
        word_freq = self._calculate_word_frequencies(sentences)
        sentence_scores = self._score_sentences(sentences, word_freq)
        selected_indices = self._select_top_sentences(sentence_scores, num_sentences)
        summary = " ".join([sentences[i] for i in selected_indices])
        return summary

    def summarize_by_count(self, text: str, num_sentences: int = 3) -> str:
        if not text or not isinstance(text, str):
            return ""
        if num_sentences < 1:
            raise ValueError("Number of sentences must be >= 1")
        text = self._preprocess_text(text)
        sentences = self._tokenize_sentences(text)
        if len(sentences) <= num_sentences:
            return text
        word_freq = self._calculate_word_frequencies(sentences)
        sentence_scores = self._score_sentences(sentences, word_freq)
        selected_indices = self._select_top_sentences(sentence_scores, num_sentences)
        summary = " ".join([sentences[i] for i in selected_indices])
        return summary

    def get_scores(self, text: str) -> dict[str, float]:
        text = self._preprocess_text(text)
        sentences = self._tokenize_sentences(text)
        word_freq = self._calculate_word_frequencies(sentences)
        scores = self._score_sentences(sentences, word_freq)
        return {sentences[idx]: score for idx, score in scores.items()}


if __name__ == "__main__":
    fn = Path(sys.argv[1])
    data = fn.read_text(encoding="utf8")
    summarizer = TextSummarizer(language="english")
    print("=== Summarize by Ratio (30%) ===")
    summary_ratio = summarizer.summarize(data, ratio=0.3)
    print(summary_ratio)
    print()
    print("=== Summarize by Count (3 sentences) ===")
    summary_count = summarizer.summarize_by_count(data, num_sentences=3)
    print(summary_count)
    print()
    print("=== Sentence Scores ===")
    scores = summarizer.get_scores(data)
    for sentence, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        print(f"Score: {score:.4f} | {sentence[:60]}...")
    print()
