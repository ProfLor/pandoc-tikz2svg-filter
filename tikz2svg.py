#! python

#version 2.0 automatically generating black and white images and prepending level 1 and 2 header to the file name for better sorting.
#Version 2.1 switching from pdf2svg to pdftocairo for better compatibility and quality.
#Version 2.2 automatically wrapping images in MyST div directives for dark/light mode support.
#Version 2.3 emit HTML for dark/light blocks and ensure they are not inside a <div class="center"> wrapper
#         by splitting any such wrapper so the dark/light blocks become siblings (not centered).
#Version 2.4 handle TikZ code inside figure environments and other nested structures.
#Install the following dependencies:
#Python 3 (from https://www.python.org/downloads/ or via Anaconda https://www.anaconda.com/products/distribution)
#python --version
#Pandoc (from https://pandoc.org/installing.html or via conda install -c conda-forge pandoc)
#pandoc --version
#lualatex (from TeX Live)
#lualatex -v
#pdftocairo (from poppler-utils)
#pdftocairo -v
#panflute (Python library for Pandoc filters) pip install panflute
#pip show panflute
#Do not forget to check the PATH environment variable if you have issues with finding lualatex or pdftocairo.
#

## use the following if you want to have the output file name based on the input file name:
## $in = ".\working\Kapitel1_cleaned.tex"
## $out = [IO.Path]::ChangeExtension($in, ".md")
## pandoc --katex $in -f latex+raw_tex --filter "..\pandoc-tikz2svg-filter\tikz2svg.py" -o $out


import panflute as pf
import hashlib
import tempfile
import subprocess
import os
import re

# TikZ settings for black and white versions:
CUSTOM_TIKZSET_BLACK = r"""
\tikzset{
  every node/.style={
    text=black,
    fill=none,
  },
  every path/.style={
    draw=black,
    fill=none,
  }
}
"""

CUSTOM_TIKZSET_WHITE = r"""
\tikzset{
  every node/.style={
    text=white,
    fill=none,
  },
  every path/.style={
    draw=white,
    fill=none,
  }
}
"""

DOC_TEMPLATE = r"""
\documentclass[border=2pt]{standalone}
\usepackage{tikz}
\usepackage[siunitx, straight voltages, european]{circuitikz}
\usetikzlibrary{automata, positioning, arrows}
\ctikzset{>=latex, tripoles/european not symbol=ieee circle}

%s

\begin{document}
%s
\end{document}
"""

EXTENSION_FOR = {
    'html': 'svg',
    'html4': 'svg',
    'html5': 'svg',
    'latex': 'pdf',
    'beamer': 'pdf'
}

MEDIA_PATH = "media"

def sha1_hash(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()

def tex2image(latex_code, filetype, outpath, preamble_code):
    full_doc = DOC_TEMPLATE % (preamble_code, latex_code)
    with tempfile.TemporaryDirectory(prefix="panflute_tikz_") as tmpdir:
        tex_file = os.path.join(tmpdir, "temp.tex")
        pdf_file = os.path.join(tmpdir, "temp.pdf")
        svg_file = os.path.join(tmpdir, "temp.svg")
        with open(tex_file, 'w', encoding='utf-8') as f:
            f.write(full_doc)
        try:
            subprocess.run(
                ['lualatex', '-halt-on-error', '-interaction=nonstopmode',
                 '-output-directory', tmpdir, tex_file],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        except subprocess.CalledProcessError as e:
            pf.debug("LaTeX Compile Error:\n" + e.stderr.decode('utf-8'))
            return False

        if filetype == 'pdf':
            if not os.path.exists(pdf_file):
                pf.debug("PDF was not created: " + pdf_file)
                return False
            os.replace(pdf_file, outpath)
        else:
            if not os.path.exists(pdf_file):
                pf.debug("PDF was not created: " + pdf_file)
                return False
            try:
                subprocess.run(
                    ['pdftocairo', '-svg', '-f', '1', '-l', '1', pdf_file, svg_file],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            except subprocess.CalledProcessError as e:
                pf.debug("pdftocairo Error:\n" + e.stderr.decode('utf-8'))
                return False
            if not os.path.exists(svg_file):
                pf.debug("SVG was not created: " + svg_file)
                return False
            os.replace(svg_file, outpath)
        return True

def sanitize_number(num):
    """
    Convert list of numbers like [1,2,3] into underscore separated string '1_2_3'.
    For empty or None, return '0'.
    """
    if not num:
        return '0'
    return '_'.join(str(n) for n in num)

def _is_tikz_darklight_raw(block):
    return (
        isinstance(block, pf.RawBlock)
        and block.format in ('html', 'markdown', 'gfm')
        and ('dark:hidden' in block.text or 'hidden dark:block' in block.text)
        and '<div' in block.text
    )

def extract_tikz_from_text(text):
    """Extract TikZ environments from LaTeX text"""
    tikz_patterns = [
        r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}',
        r'\\begin\{circuitikz\}.*?\\end\{circuitikz\}',
        r'\\begin\{picture\}.*?\\end\{picture\}'
    ]
    
    for pattern in tikz_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(0)
    return None

def process_tikz_code(tikz_code, doc):
    """Process TikZ code and return dark/light mode blocks"""
    filetype = EXTENSION_FOR.get(doc.format, 'svg')

    # Compose filename parts from header numbering
    if not hasattr(doc, "level1_number"):
        doc.level1_number, doc.level2_number = [], []
        doc.image_num_per_level2 = {}
    hl1 = sanitize_number(doc.level1_number)
    hl2 = sanitize_number(doc.level2_number)

    current_level2_num = tuple(doc.level2_number)
    if current_level2_num not in doc.image_num_per_level2:
        doc.image_num_per_level2[current_level2_num] = 0
    doc.image_num_per_level2[current_level2_num] += 1
    img_num = doc.image_num_per_level2[current_level2_num]

    # Generate hash of code
    hashcode = sha1_hash(tikz_code)
    outdir = MEDIA_PATH
    os.makedirs(outdir, exist_ok=True)

    # Compose base filename
    basefname = f"{hl1}_{hl2}_{img_num}_{hashcode}"

    # Generate black image
    fname_black = f"{basefname}_black.{filetype}"
    outpath_black = os.path.join(outdir, fname_black)
    if not os.path.exists(outpath_black):
        if not tex2image(tikz_code, filetype, outpath_black, CUSTOM_TIKZSET_BLACK):
            pf.debug("Black image conversion failed.")
            return None

    # Generate white image
    fname_white = f"{basefname}_white.{filetype}"
    outpath_white = os.path.join(outdir, fname_white)
    if not os.path.exists(outpath_white):
        if not tex2image(tikz_code, filetype, outpath_white, CUSTOM_TIKZSET_WHITE):
            pf.debug("White image conversion failed.")
            return None

    # Use relative URLs (no leading slash)
    img_path_black = os.path.join(outdir, fname_black).replace('\\', '/')
    img_path_white = os.path.join(outdir, fname_white).replace('\\', '/')

    # Emit raw HTML blocks (work inside/outside HTML), with Tailwind classes.
    light_html = f'<div class="dark:hidden">\n  <img src="{img_path_black}" alt="" />\n</div>\n'
    dark_html  = f'<div class="hidden dark:block">\n  <img src="{img_path_white}" alt="" />\n</div>\n'

    light_mode_block = pf.RawBlock(light_html, format='html')
    dark_mode_block  = pf.RawBlock(dark_html,  format='html')

    return [light_mode_block, dark_mode_block]

def tikz_filter(elem, doc):
    # Split <div class="center"> so our dark/light blocks are not wrapped
    if isinstance(elem, pf.Div) and ('center' in elem.classes):
        chunks = []
        buf = []
        for b in elem.content:
            if _is_tikz_darklight_raw(b):
                if buf:
                    chunks.append(pf.Div(*buf, classes=['center']))
                    buf = []
                chunks.append(b)
            else:
                buf.append(b)
        if buf:
            chunks.append(pf.Div(*buf, classes=['center']))
        # If we actually split, return list; else keep original
        if len(chunks) == 1 and isinstance(chunks[0], pf.Div) and chunks[0].attributes == elem.attributes and chunks[0].content == elem.content:
            return elem
        return chunks

    # Handle direct TikZ raw blocks
    if isinstance(elem, pf.RawBlock) and elem.format == 'latex':
        code = elem.text.lstrip()
        if any(code.startswith(start) for start in ['\\begin{tikzpicture}', '\\begin{circuitikz}', '\\begin{picture}']):
            return process_tikz_code(elem.text, doc)

    # Handle TikZ code inside figure environments or other raw blocks
    if isinstance(elem, pf.RawBlock) and elem.format == 'latex':
        tikz_code = extract_tikz_from_text(elem.text)
        if tikz_code:
            return process_tikz_code(tikz_code, doc)

    if isinstance(elem, pf.Header):
        # Track numbering up to level 2
        level = elem.level
        if not hasattr(doc, "level1_number"):
            doc.level1_number, doc.level2_number = [], []
            doc.image_num_per_level2 = {}
        if level == 1:
            if doc.level1_number:
                doc.level1_number[-1] += 1
            else:
                doc.level1_number = [1]
            doc.level2_number = []
            doc.image_num_per_level2 = {}
        elif level == 2:
            if len(doc.level2_number) == 0:
                doc.level2_number = [1]
            else:
                doc.level2_number[-1] += 1
            doc.image_num_per_level2[tuple(doc.level2_number)] = 0
        return elem

    return elem

def prepare(doc):
    doc.level1_number = []
    doc.level2_number = []
    doc.image_num_per_level2 = {}

def main(doc=None):
    return pf.run_filter(tikz_filter, prepare=prepare, doc=doc)

if __name__ == "__main__":
    main()