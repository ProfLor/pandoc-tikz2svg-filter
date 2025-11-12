# -----------------------------------------------------------------------------
# tikz2svg.py
#
# Panflute filter to convert TikZ / CircuitikZ / picture LaTeX blocks into
# theme-aware SVG images (black / white variants) and emit MyST-compatible
# Markdown fragments suitable for dark/light presentation.
# Compiles TikZ with lualatex (PDF) and converts to SVG with pdftocairo.
# Generated files are stored under MEDIA_PATH.
# -----------------------------------------------------------------------------

## use the following if you want to have the output file name based on the input file name:
## $in = ".\working\Kapitel1_cleaned.tex"
## $out = [IO.Path]::ChangeExtension($in, ".md")
## pandoc --katex $in -f latex+raw_tex -t markdown --filter "..\pandoc-tikz2svg-filter\tikz2svg.py" -o $out

#!/usr/bin/env python3


# --- Standard imports and modules used by the filter ---
# panflute: manipulates the Pandoc AST
# hashlib: compute SHA1 hash for stable filenames
# tempfile: create temporary dirs for compilation artifacts
# subprocess: call lualatex and pdftocairo
# os: filesystem operations
# re: regex extraction of tikz environments
# sys: error reporting to stderr
import panflute as pf
import hashlib
import tempfile
import subprocess
import os
import re
import sys

# -----------------------------------------------------------------------------
# Configuration / constants
# - MEDIA_PATH: directory to place generated images (relative)
# - DOC_TEMPLATE: minimal standalone LaTeX wrapper used to compile TikZ code
# - STYLE_BLACK / STYLE_WHITE: small TikZ style adjustments to force
#   monochrome rendering suitable for theme-specific images
# -----------------------------------------------------------------------------
MEDIA_PATH = "media"

DOC_TEMPLATE = r"""
\documentclass[border=2pt]{standalone}
\usepackage{tikz}
\usepackage[siunitx, straight voltages, european]{circuitikz}
\usetikzlibrary{automata, positioning, arrows, circuits.ee.IEC}
\ctikzset{>=latex, tripoles/european not symbol=ieee circle}

%s
\begin{document}
%s
\end{document}
"""

STYLE_BLACK = r"\tikzset{every node/.style={text=black,fill=none},every path/.style={draw=black,fill=none}}"
STYLE_WHITE = r"\tikzset{every node/.style={text=white,fill=none},every path/.style={draw=white,fill=none}}"


# -----------------------------------------------------------------------------
# Utility helpers
# - sha1_hash: content-based stable id for filenames
# - sanitize_number: turn header number lists into underscore-separated strings
# -----------------------------------------------------------------------------
def sha1_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def sanitize_number(nums):
    return "0" if not nums else "_".join(str(n) for n in nums)


# -----------------------------------------------------------------------------
# TikZ extraction helper
# - extract_tikz: finds first tikz/circuitikz/picture environment inside a
#   string containing LaTeX code. Returns the full matched block or None.
# - This isolates the TikZ snippet to be wrapped and compiled.
# -----------------------------------------------------------------------------
def extract_tikz(raw: str):
    pattern = (
        r"\\begin\{(?P<env>tikzpicture|circuitikz|picture)\}.*?"
        r"\\end\{(?P=env)\}"
    )
    m = re.search(pattern, raw, re.S)
    return m.group(0) if m else None


# -----------------------------------------------------------------------------
# Compilation helper
# - compile_tikz_to_svg: create a temporary LaTeX file, run lualatex to produce
#   a PDF, then call pdftocairo to produce an SVG. Moves final SVG to target.
# - Behavior: suppress stdout to avoid polluting Pandoc; capture stderr and emit a
#   trimmed message to sys.stderr on errors (keeps Pandoc JSON clean).
# -----------------------------------------------------------------------------
def compile_tikz_to_svg(code: str, out_svg: str, style: str) -> bool:
    full_doc = DOC_TEMPLATE % (style, code)
    try:
        with tempfile.TemporaryDirectory(prefix="tikz_") as tmp:
            tex_path = os.path.join(tmp, "t.tex")
            pdf_path = os.path.join(tmp, "t.pdf")
            svg_path = os.path.join(tmp, "t.svg")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(full_doc)

            subprocess.run(
                ["lualatex", "-halt-on-error", "-interaction=nonstopmode",
                 "-output-directory", tmp, tex_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )

            subprocess.run(
                ["pdftocairo", "-svg", pdf_path, svg_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )

            os.replace(svg_path, out_svg)
        return True

    except subprocess.CalledProcessError as e:
        # On compile error show a truncated error to stderr (keeps pandoc output clean)
        msg = e.stderr.decode("utf-8", errors="ignore")[-400:]
        sys.stderr.write(f"[tikz2svg] compile error:\n{msg}\n")
        return False
    except Exception as e:
        sys.stderr.write(f"[tikz2svg] unexpected error: {e}\n")
        return False


# -----------------------------------------------------------------------------
# Helper to detect previously emitted dark/light raw blocks
# - _is_tikz_darklight_raw: checks RawBlock text for the class markers used in
#   generated MyST divs to avoid duplicating/splitting incorrectly.
# -----------------------------------------------------------------------------
def _is_tikz_darklight_raw(block):
    return (
        isinstance(block, pf.RawBlock)
        and block.format in ("html", "markdown", "gfm")
        and ("dark:hidden" in block.text or "hidden dark:block" in block.text)
    )


# -----------------------------------------------------------------------------
# Main filter action
# - tikz_filter: invoked for each AST element. Responsibilities:
#     * track Header elements to build numbering state for filenames
#     * process pf.Figure nodes containing Raw LaTeX TikZ blocks:
#         - extract tikz, generate images, emit MyST FOUR-colon figure directive
#     * process pf.Div with class "center" containing TikZ:
#         - extract tikz, generate images, emit two MyST ::: {div} blocks
#     * leave other elements unchanged
# - The function tries to be defensive: if extraction fails, it returns the
#   original element (or None where appropriate) to avoid breaking the AST.
# -----------------------------------------------------------------------------
def tikz_filter(elem, doc):

    # --- 1) Track header numbering for image filenames ---
    # Create and maintain doc.level1_number, doc.level2_number and image counters.
    if isinstance(elem, pf.Header):
        if not hasattr(doc, "level1_number"):
            doc.level1_number = []
            doc.level2_number = []
            doc.image_num_per_level2 = {}

        if elem.level == 1:
            # increment or init chapter counter
            if not doc.level1_number:
                doc.level1_number = [1]
            else:
                doc.level1_number[-1] += 1
            doc.level2_number = []
            doc.image_num_per_level2 = {}

        elif elem.level == 2:
            # increment or init section counter
            if not doc.level2_number:
                doc.level2_number = [1]
            else:
                doc.level2_number[-1] += 1
            # initialize per-section image counter map
            doc.image_num_per_level2[tuple(doc.level2_number)] = 0

        return elem

    # --- 2) Handle Figure nodes (LaTeX \begin{figure}) ---
    # Look for pf.Figure objects created by Pandoc from LaTeX figure environments.
    # If a RawBlock child contains tikz, extract, compile and replace with MyST.
    if isinstance(elem, pf.Figure):
        label = elem.identifier or ""
        # use pf.stringify for caption (keeps existing behavior)
        caption = pf.stringify(elem.caption) if elem.caption else ""

        # find tikz/circuitikz content inside figure
        tikz_raw = None
        for c in elem.content:
            if isinstance(c, pf.RawBlock) and any(k in c.text for k in ("tikzpicture","circuitikz","begin{picture}")):
                tikz_raw = c.text
                break
        if not tikz_raw:
            return elem

        tikz_code = extract_tikz(tikz_raw)
        if not tikz_code:
            return elem

        # ensure numbering state exists
        if not hasattr(doc, "level1_number"):
            doc.level1_number = []
            doc.level2_number = []
            doc.image_num_per_level2 = {}

        hl1 = sanitize_number(doc.level1_number)
        hl2 = sanitize_number(doc.level2_number)
        key = tuple(doc.level2_number)
        doc.image_num_per_level2.setdefault(key, 0)
        doc.image_num_per_level2[key] += 1
        img_num = doc.image_num_per_level2[key]

        os.makedirs(MEDIA_PATH, exist_ok=True)
        h = sha1_hash(tikz_code)
        base = f"{hl1}_{hl2}_{img_num}_{h}"
        black_svg = os.path.join(MEDIA_PATH, f"{base}_black.svg")
        white_svg = os.path.join(MEDIA_PATH, f"{base}_white.svg")

        # Compile if not already present
        if not os.path.exists(black_svg):
            compile_tikz_to_svg(tikz_code, black_svg, STYLE_BLACK)
        if not os.path.exists(white_svg):
            compile_tikz_to_svg(tikz_code, white_svg, STYLE_WHITE)

        # Use forward slashes in generated links (cross-platform)
        black_rel = black_svg.replace("\\", "/")
        white_rel = white_svg.replace("\\", "/")

        # Build the MyST block using explicit literal strings to avoid accidental brace/newline insertion.
        # Use :label: field (if present).
        label_field = f":label: {label}\n" if label else ""

        myst_lines = []
        myst_lines.append("::::{figure}")              # FOUR colons outer fence
        if label_field:
            myst_lines.append(label_field.rstrip())
        myst_lines.append(f":alt: {caption}")
        myst_lines.append("")  # blank line
        # dark image
        myst_lines.append(":::{div}")
        myst_lines.append(":class: dark:hidden")
        myst_lines.append(f"![]({black_rel})")
        myst_lines.append(":::")
        myst_lines.append("")  # blank line between divs
        # light image
        myst_lines.append(":::{div}")
        myst_lines.append(":class: hidden dark:block")
        myst_lines.append(f"![]({white_rel})")
        myst_lines.append(":::")
        myst_lines.append("")  # blank line before caption
        myst_lines.append(caption)
        myst_lines.append("::::")  # close outer figure with FOUR colons

        myst = "\n".join(myst_lines) + "\n"

        # Return as markdown raw block so Pandoc doesn't escape newlines as entities
        return [pf.RawBlock(myst, format="markdown")]

    # --- 3) Handle Div.center that contain TikZ/CircuitikZ ---
    # These are typically Pandoc Div blocks with class "center" created from LaTeX center environments.
    # The filter extracts the tikz code, compiles images and emits two MyST div blocks as siblings
    # so that they are not wrapped in a centering container.
    if isinstance(elem, pf.Div) and "center" in elem.classes:
        # look for RawBlock child with TikZ
        for child in elem.content:
            if isinstance(child, pf.RawBlock) and any(k in child.text for k in ("tikzpicture","circuitikz","begin{picture}")):
                tikz_code = extract_tikz(child.text)
                if not tikz_code:
                    return elem

                # numbering for standalone center images
                if not hasattr(doc, "level1_number"):
                    doc.level1_number = []
                    doc.level2_number = []
                    doc.image_num_per_level2 = {}

                hl1 = sanitize_number(doc.level1_number)
                hl2 = sanitize_number(doc.level2_number)
                key = tuple(doc.level2_number)
                doc.image_num_per_level2.setdefault(key, 0)
                doc.image_num_per_level2[key] += 1
                img_num = doc.image_num_per_level2[key]

                os.makedirs(MEDIA_PATH, exist_ok=True)
                h = sha1_hash(tikz_code)
                base = f"{hl1}_{hl2}_{img_num}_{h}"
                out_black = os.path.join(MEDIA_PATH, f"{base}_black.svg")
                out_white = os.path.join(MEDIA_PATH, f"{base}_white.svg")

                if not os.path.exists(out_black):
                    compile_tikz_to_svg(tikz_code, out_black, STYLE_BLACK)
                if not os.path.exists(out_white):
                    compile_tikz_to_svg(tikz_code, out_white, STYLE_WHITE)

                black_rel = out_black.replace("\\", "/")
                white_rel = out_white.replace("\\", "/")

                md_lines = []
                md_lines.append(":::{div}")
                md_lines.append(":class: dark:hidden")
                md_lines.append(f"![]({black_rel})")
                md_lines.append(":::")
                md_lines.append("")  # blank line
                md_lines.append(":::{div}")
                md_lines.append(":class: hidden dark:block")
                md_lines.append(f"![]({white_rel})")
                md_lines.append(":::")
                md_lines.append("")

                md = "\n".join(md_lines).strip() + "\n"
                return [pf.RawBlock(md, format="markdown")]

        return elem

    # --- default: no change ---
    return elem


# -----------------------------------------------------------------------------
# prepare and main
# - prepare: initialize doc-scoped counters before processing
# - main: run the panflute filter with tikz_filter action
# -----------------------------------------------------------------------------
def prepare(doc):
    doc.level1_number = []
    doc.level2_number = []
    doc.image_num_per_level2 = {}


def main(doc=None):
    pf.run_filter(tikz_filter, prepare=prepare, doc=doc)


if __name__ == "__main__":
    main()
