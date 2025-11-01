# pandoc-tikz2svg-filter

A Pandoc filter that automatically converts TikZ and CircuitikZ diagrams into SVG files
for both Light and Dark mode display.

---

## Features
- Converts TikZ/CircuitikZ environments to SVG during Pandoc conversion  
- Automatically generates black/white versions for Light/Dark mode  
- Embeds SVGs using HTML blocks with CSS-based theme switching  
- Compatible with modern Markdown → HTML or PDF workflows  

---

## Installation

### Prerequisites
Install the following dependencies:

| Component | Purpose | Installation |
|------------|----------|---------------|
| Python 3 | runtime | [python.org](https://www.python.org) |
| Pandoc | conversion engine | [pandoc.org/installing.html](https://pandoc.org/installing.html) |
| LuaLaTeX | TikZ rendering | [TeX Live](https://tug.org/texlive/) |
| Poppler (pdftocairo) | PDF → SVG conversion | [Poppler for Windows/Linux/Mac](https://github.com/oschwartz10612/poppler-windows/releases/) |
| Panflute | Pandoc filter library | `pip install panflute` |

---

## Usage

Run Pandoc with the filter:

```bash
pandoc --katex input.tex -f latex+raw_tex \
  --filter tikz2svg.py -o output.md
