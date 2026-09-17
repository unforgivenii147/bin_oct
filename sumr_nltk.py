#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import sys
from collections import Counter

from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize, word_tokenize


def summarize_nltk(text, num_sentences=5):
    sentences = sent_tokenize(text)
    words = word_tokenize(text.lower())
    stop_words = set(stopwords.words("english"))
    word_freq = Counter([w for w in words if w.isalnum() and w not in stop_words])
    sentence_scores = {}
    for i, sent in enumerate(sentences):
        sent_words = word_tokenize(sent.lower())
        score = sum(word_freq.get(w, 0) for w in sent_words if w.isalnum())
        sentence_scores[i] = score / max(1, len(sent_words))
    top_indices = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[
        :num_sentences
    ]
    summary = " ".join([sentences[i] for i in sorted(top_indices)])
    return summary


with open(sys.argv[1], "r") as f:
    text = f.read()
summary = summarize_nltk(text, 5)
with open(sys.argv[1].replace(".txt", "_summary.txt"), "w") as f:
    f.write(summary)
