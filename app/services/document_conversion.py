"""
document_conversion.py
──────────────────────
LibreOffice-based document conversion service.

Supported conversions (soffice headless):
  • DOCX / DOC / ODT / RTF  →  PDF
  • PDF / DOC / ODT / RTF   →  DOCX
  • Any supported format    →  TXT  (plain-text extract)

LibreOffice must be installed on the server.
  Linux  : apt install libreoffice
  macOS  : brew install --cask libreoffice
  Windows: Download from https://www.libreoffice.org/

The env var LIBREOFFICE_CMD overrides the default binary name.
"""

import os
import shutil
import subprocess
import tempfile
import logging

logger = logging.getLogger(__name__)

# ── Binary resolution ────────────────────────────────────────────────────────
def _libreoffice_cmd() -> str:
    """Return the LibreOffice executable to call."""
    env_cmd = os.environ.get("LIBREOFFICE_CMD", "")
    if env_cmd:
        return env_cmd

    # Common install locations
    candidates = [
        "soffice",                                  # Linux (in PATH)
        "libreoffice",                              # macOS Homebrew
        r"C:\Program Files\LibreOffice\program\soffice.exe",   # Windows default
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if shutil.which(c) or os.path.isfile(c):
            return c

    return "soffice"   # fall back; will raise FileNotFoundError if missing


def is_libreoffice_available() -> bool:
    """Return True if LibreOffice is detected on this machine."""
    cmd = _libreoffice_cmd()
    try:
        result = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return False


# ── Conversion ───────────────────────────────────────────────────────────────
ALLOWED_TARGETS = {"pdf", "docx", "txt", "odt", "rtf"}

EXTENSION_MAP = {
    "pdf":  "pdf",
    "docx": "docx:MS Word 2007 XML",   # explicit filter for reliable DOCX output
    "txt":  "txt:Text (encoded)",
    "odt":  "odt",
    "rtf":  "rtf",
}


def convert_document(source_path: str, target_format: str) -> str:
    """
    Convert *source_path* to *target_format* using LibreOffice headless mode.

    Returns the **path to the converted file** inside a temporary directory.
    The caller is responsible for cleaning up that directory when done:

        tmp_dir = os.path.dirname(output_path)
        # … use output_path …
        shutil.rmtree(tmp_dir, ignore_errors=True)

    Raises:
        ValueError        – unsupported target format
        FileNotFoundError – LibreOffice not found
        RuntimeError      – conversion process returned non-zero exit code
    """
    target_format = target_format.lower().lstrip(".")

    if target_format not in ALLOWED_TARGETS:
        raise ValueError(
            f"Unsupported target format '{target_format}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_TARGETS))}"
        )

    cmd = _libreoffice_cmd()
    tmp_dir = tempfile.mkdtemp(prefix="clause_conv_")

    try:
        filter_arg = EXTENSION_MAP.get(target_format, target_format)

        result = subprocess.run(
            [
                cmd,
                "--headless",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to", filter_arg,
                "--outdir", tmp_dir,
                source_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,          # 2-minute cap for large files
        )

        if result.returncode != 0:
            logger.error("LibreOffice stderr: %s", result.stderr)
            raise RuntimeError(
                f"LibreOffice conversion failed (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )

        # Find the output file — LO names it <basename>.<target_ext>
        base = os.path.splitext(os.path.basename(source_path))[0]
        out_ext = target_format  # e.g. "pdf", "docx", "txt"
        out_path = os.path.join(tmp_dir, f"{base}.{out_ext}")

        if not os.path.exists(out_path):
            # Sometimes LO writes the extension in upper-case or uses a
            # different casing — do a case-insensitive scan.
            for fname in os.listdir(tmp_dir):
                if fname.lower().startswith(base.lower()):
                    out_path = os.path.join(tmp_dir, fname)
                    break
            else:
                files_found = os.listdir(tmp_dir)
                raise RuntimeError(
                    f"Converted file not found in {tmp_dir}. "
                    f"Files present: {files_found}"
                )

        logger.info("Converted %s → %s", source_path, out_path)
        return out_path

    except Exception:
        # Clean up tmp dir on error
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
