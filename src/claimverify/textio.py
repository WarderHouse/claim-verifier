"""Read manuscript and source files into plain text.

PDFs go through the poppler `pdftotext` binary (no Python PDF dependency).
Ligatures are normalized because pdftotext emits fi/fl/ff glyphs that break
token matching downstream, and text is NFC-normalized so composed and
decomposed accents key identically.
"""

from __future__ import annotations

import shutil
import subprocess
import unicodedata
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md"}

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "­": "",  # soft hyphen
}

_PDFTOTEXT_TIMEOUT = 120


class TextExtractionError(RuntimeError):
    pass


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    # Re-join words hyphenated across line breaks: "develop-\nment" -> "development"
    lines = text.split("\n")
    out: list[str] = []
    carry = ""
    for line in lines:
        line = carry + line
        carry = ""
        if line.rstrip().endswith("-") and not line.rstrip().endswith("--"):
            stripped = line.rstrip()
            carry = stripped[:-1]
            continue
        out.append(line)
    if carry:
        out.append(carry)
    return "\n".join(out)


def read_text(path: Path) -> str:
    """Return normalized plain text for a .pdf, .txt, or .md file."""
    if path.suffix.lower() in TEXT_SUFFIXES:
        return normalize(path.read_text(encoding="utf-8", errors="replace"))
    if path.suffix.lower() == ".pdf":
        binary = shutil.which("pdftotext")
        if binary is None:
            raise TextExtractionError(
                "pdftotext not found. Install poppler (brew install poppler / "
                "apt install poppler-utils), or supply .txt input."
            )
        try:
            proc = subprocess.run(
                [binary, "-enc", "UTF-8", str(path.resolve()), "-"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=_PDFTOTEXT_TIMEOUT,
                env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            )
        except subprocess.TimeoutExpired as e:
            raise TextExtractionError(
                f"pdftotext timed out after {_PDFTOTEXT_TIMEOUT}s on {path.name} "
                "(malformed PDF?)"
            ) from e
        if proc.returncode != 0:
            raise TextExtractionError(
                f"pdftotext failed on {path.name}: {proc.stderr.strip()}"
            )
        return normalize(proc.stdout)
    raise TextExtractionError(
        f"Unsupported file type: {path.name} (use .pdf, .txt, or .md)"
    )
