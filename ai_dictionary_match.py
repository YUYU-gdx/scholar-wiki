#!/usr/bin/env python
"""AI Dictionary Matcher."""

import re
import shutil
import time
from collections import Counter
from pathlib import Path

SOURCE = Path(r"D:\Code\kn_gragh\outputs\full data\full data\organized_by_title\markdown")
TARGET = Path(r"D:\Code\kn_gragh\outputs\ai_matched")

TERM_DEFS = [
    # Core AI
    ("artificial intelligence", "substr", None),
    ("machine learning", "substr", None),
    ("deep learning", "substr", None),
    ("neural network", "substr", None),
    ("generative ai", "substr", None),
    ("genai", "substr", None),
    ("AGI", "regex", r"\bagi\b"),
    ("artificial general intelligence", "substr", None),
    ("AI-driven", "substr", None),
    ("AI-powered", "substr", None),

    # Models
    ("large language model", "substr", None),
    ("LLM", "regex", r"\bllm\b"),
    ("GPT", "regex", r"\bgpt\b"),
    ("ChatGPT", "substr", None),
    ("BERT", "regex", r"\bbert\b"),
    ("transformer model", "substr", None),
    ("diffusion model", "substr", None),
    ("GAN", "regex", r"\bgan\b"),
    ("generative adversarial network", "substr", None),
    ("VAE", "regex", r"\bvae\b"),
    ("variational autoencoder", "substr", None),
    ("autoencoder", "substr", None),
    ("CNN", "regex", r"\bcnn\b"),
    ("convolutional neural network", "substr", None),
    ("RNN", "regex", r"\brnn\b"),
    ("recurrent neural network", "substr", None),
    ("LSTM", "regex", r"\blstm\b"),
    ("long short-term memory", "substr", None),
    ("GRU", "regex", r"\bgru\b"),
    ("gated recurrent unit", "substr", None),
    ("attention mechanism", "substr", None),
    ("encoder-decoder", "substr", None),
    ("seq2seq", "substr", None),
    ("sequence-to-sequence", "substr", None),

    # Learning
    ("supervised learning", "substr", None),
    ("unsupervised learning", "substr", None),
    ("semi-supervised learning", "substr", None),
    ("self-supervised learning", "substr", None),
    ("reinforcement learning", "substr", None),
    ("transfer learning", "substr", None),
    ("few-shot learning", "substr", None),
    ("zero-shot learning", "substr", None),
    ("federated learning", "substr", None),
    ("active learning", "substr", None),
    ("curriculum learning", "substr", None),
    ("contrastive learning", "substr", None),

    # NLP
    ("natural language processing", "substr", None),
    ("NLP", "regex", r"\bnlp\b"),
    ("text generation", "substr", None),
    ("sentiment analysis", "substr", None),
    ("named entity recognition", "substr", None),
    ("tokenization", "substr", None),
    ("word embedding", "substr", None),
    ("word2vec", "substr", None),
    ("speech recognition", "substr", None),
    ("machine translation", "substr", None),
    ("text mining", "substr", None),

    # CV
    ("computer vision", "substr", None),
    ("image recognition", "substr", None),
    ("object detection", "substr", None),
    ("image segmentation", "substr", None),
    ("image generation", "substr", None),
    ("facial recognition", "substr", None),

    # Emerging
    ("prompt engineering", "substr", None),
    ("RAG", "regex", r"\brag\b"),
    ("retrieval-augmented generation", "substr", None),
    ("fine-tuning", "substr", None),
    ("RLHF", "substr", None),
    ("reinforcement learning from human feedback", "substr", None),
    ("chain-of-thought", "substr", None),
    ("foundation model", "substr", None),
    ("multimodal", "substr", None),
    ("AI agent", "substr", None),
    ("autonomous agent", "substr", None),
    ("intelligent agent", "substr", None),
    ("copilot", "substr", None),
    ("stable diffusion", "substr", None),
    ("Hugging Face", "substr", None),
    ("OpenAI", "substr", None),
    ("LangChain", "substr", None),
    ("LlamaIndex", "substr", None),
    ("vector database", "substr", None),
    ("vector embedding", "substr", None),
    ("semantic search", "substr", None),

    # Data
    ("predictive modeling", "substr", None),
    ("data mining", "substr", None),
    ("big data", "substr", None),
]


def prepare():
    substrs = {}
    regexes = []
    for label, ptype, regex_pat in TERM_DEFS:
        if ptype == "regex":
            pat = regex_pat if regex_pat else re.escape(label)
            regexes.append((re.compile(pat, re.IGNORECASE), label))
        else:
            substrs[label] = label.lower()
    return substrs, regexes


def file_matches(filepath, substrs, regexes):
    try:
        text = filepath.read_text(encoding="utf-8").lower()
    except UnicodeDecodeError:
        try:
            text = filepath.read_text(encoding="gbk").lower()
        except Exception:
            return False, []
    matched = []
    for label, ss in substrs.items():
        if ss in text:
            matched.append(label)
    for compiled, label in regexes:
        if compiled.search(text):
            matched.append(label)
    return len(matched) > 0, matched


def main():
    print("=" * 60)
    print("AI Dictionary Matcher")
    print(f"Source: {SOURCE}")
    print(f"Target: {TARGET}")
    print(f"Terms: {len(TERM_DEFS)}")
    print("=" * 60)

    if not SOURCE.exists():
        print(f"ERROR: {SOURCE}")
        return

    TARGET.mkdir(parents=True, exist_ok=True)
    substrs, regexes = prepare()
    md_files = sorted(SOURCE.glob("*.md"))
    total = len(md_files)
    print(f"\nScanning {total} files...\n")

    matched_count = 0
    term_counter = Counter()
    existing = set()
    start = time.time()

    for i, fpath in enumerate(md_files, 1):
        if i % 300 == 0 or i == total:
            print(f"  {i}/{total} ({time.time()-start:.1f}s)")
        ok, hits = file_matches(fpath, substrs, regexes)
        if ok:
            matched_count += 1
            for h in hits:
                term_counter[h] += 1
            name = fpath.name
            if name in existing:
                stem, sfx = fpath.stem, fpath.suffix
                n = 1
                while f"{stem}_dup{n}{sfx}" in existing:
                    n += 1
                name = f"{stem}_dup{n}{sfx}"
            existing.add(name)
            shutil.copy2(fpath, TARGET / name)

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Scanned  : {total}")
    print(f"  Matched  : {matched_count}")
    print(f"  Miss     : {total - matched_count}")
    print(f"  Time     : {elapsed:.1f}s")
    print(f"  Output   : {TARGET}")
    if term_counter:
        print(f"\n  Top terms ({len(term_counter)} unique):")
        for term, count in term_counter.most_common(25):
            print(f"    [{count:4d}] {term}")
    print("\nDone.")

if __name__ == "__main__":
    main()