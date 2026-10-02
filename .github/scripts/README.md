# scripts

<!-- docgen:begin id=.github/scripts:overview scope=.github/scripts hash=003bd5bc0997 -->
This module provides a Python script for automatically fixing common formatting issues in Markdown files. It applies a series of transformations to improve consistency and adherence to style guidelines, using both `markdownlint` for linting and custom functions for specific fixes. The script is designed to be run from the command line and can process individual files, directories, or glob patterns.

The core functionality includes functions that target specific Markdown formatting problems such as improper image syntax, incorrect ordered list numbering, angle bracket handling, broken link formatting, and inconsistent blank line usage. Each function operates on a single file, modifying its content in place to apply the necessary corrections. The module also handles recursive directory traversal and supports excluding certain directories from processing.

The main entry point processes a list of target files and applies all the defined fixes in sequence to each file. It integrates with `markdownlint` for automated linting and fixing, while also applying custom transformations that are not covered by the linter. The script supports command-line arguments for specifying targets and excluding directories, making it flexible for use in different project structures.
<!-- docgen:end id=.github/scripts:overview -->

<!-- docgen:begin id=.github/scripts:reference scope=.github/scripts hash=003bd5bc0997 -->
## Reference

### `mkdownfix.py`

- **`run_markdownlint`** (function)
- **`fix_images`** (function)
- **`renumber_ordered_lists`** (function)
- **`wrap_angle_brackets_in_backticks`** (function)
- **`fix_markdown_links`** (function)
- **`collapse_blank_lines`** (function)
- **`fix_multiline_link_blocks`** (function)
- **`ensure_title_heading`** (function)
- **`ensure_heading_hierarchy`** (function)
- **`ensure_blank_lines_around_fences`** (function)
- **`ensure_blank_lines_around_lists`** (function): Ensure there's at least one blank line before lists and between text and lists.
- **`get_markdown_files`** (function)
- **`main`** (function)
<!-- docgen:end id=.github/scripts:reference -->
