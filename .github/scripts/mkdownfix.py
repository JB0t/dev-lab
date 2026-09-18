#!/usr/bin/env python3

import sys
import os
import glob
import subprocess
import re
import argparse
import fnmatch

def run_markdownlint(md_file):
    try:
        result = subprocess.run(
            ['markdownlint', md_file, '--fix'],
            check=True,
            capture_output=True,
            text=True
        )
        if result.stdout:
            print(f"markdownlint output for {md_file}:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        # Filter out MD013/line-length warnings from stderr
        filtered_stderr = []
        for line in (e.stderr or '').splitlines():
            if "MD013/line-length" not in line:
                filtered_stderr.append(line)
        if filtered_stderr or (e.stdout and e.stdout.strip()):
            print(f"Warning: markdownlint failed for {md_file} (exit code {e.returncode})")
            if e.stdout and e.stdout.strip():
                print(f"stdout:\n{e.stdout}")
            if filtered_stderr:
                print("stderr:")
                for line in filtered_stderr:
                    print(line)

def fix_images(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    # Replace ![](url) with ![image](url)
    content = re.sub(r'!\[\]\(([^)]+)\)', r'![image](\1)', content)
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(content)

def renumber_ordered_lists(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    stack = []  # Stack of (indent, number)
    for line in lines:
        m = re.match(r'^(\s*)(\d+)\.\s+(.*)', line)
        if m:
            indent = len(m.group(1))
            # Find the stack level for this indent
            while stack and stack[-1][0] > indent:
                stack.pop()
            if stack and stack[-1][0] == indent:
                num = stack[-1][1] + 1
                stack[-1] = (indent, num)
            else:
                num = 1
                stack.append((indent, num))
            new_line = f"{' ' * indent}{num}. {m.group(3)}\n"
            new_lines.append(new_line)
        else:
            stack = []
            new_lines.append(line)

    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

def wrap_angle_brackets_in_backticks(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    in_code_block = False
    new_lines = []
    # Regex: match <...> but not if inside a code span (backticks)
    angle_bracket_pattern = re.compile(r'(<[^ >][^<>]*?>)')

    for line in lines:
        # Toggle code block state
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue
        if not in_code_block:
            # Only wrap if not already inside backticks
            def repl(m):
                match = m.group(1)
                # If already wrapped in backticks, skip
                if re.search(r'`<[^<>]+>`', line):
                    return match
                return f'`{match}`'
            # Replace all <...> not in code spans
            # To avoid code spans, split by backticks and only process even indices
            parts = re.split(r'(`[^`]*`)', line)
            for i in range(0, len(parts), 2):
                parts[i] = angle_bracket_pattern.sub(repl, parts[i])
            line = ''.join(parts)
        new_lines.append(line)

    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

def fix_markdown_links(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove newlines inside link definitions
    # e.g. [text
    # ](url) => [text](url)
    content = re.sub(r'\[([^\]]+)\]\s*\(\s*<?([^)>\s]+)>?\s*\)', r'[\1](\2)', content, flags=re.MULTILINE)

    # Remove angle brackets from URLs in links: [text](<url>) => [text](url)
    content = re.sub(r'\[([^\]]+)\]\(<([^)]+)>\)', r'[\1](\2)', content)

    # If link text is a URL, replace with [github.com](url) or [link](url)
    def link_text_repl(match):
        text = match.group(1)
        url = match.group(2)
        # If text is a URL, use 'github.com' or 'link'
        if text.startswith('http'):
            # Try to extract domain
            domain = re.sub(r'^https?://([^/]+)/?.*', r'\1', text)
            if domain:
                return f'[{domain}]({url})'
            else:
                return f'[link]({url})'
        return f'[{text}]({url})'
    content = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', link_text_repl, content)

    # Remove duplicate links: [url](url) => [link](url)
    def dedup_link_text(match):
        url = match.group(1)
        domain = re.sub(r'^https?://([^/]+)/?.*', r'\1', url)
        return f'[{domain}]({url})'
    content = re.sub(r'\[(https?://[^\]]+)\]\((https?://[^\)]+)\)', dedup_link_text, content)

    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(content)

def collapse_blank_lines(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    # Collapse 3+ blank lines to 2
    content = re.sub(r'\n{3,}', '\n\n', content)
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(content)

def fix_multiline_link_blocks(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    while i < len(lines):
        # Look for a block starting with optional whitespace + '['
        if re.match(r'^\s*\[\s*$', lines[i]):
            # Save indentation
            indent = re.match(r'^(\s*)', lines[i]).group(1)
            # Try to match the next lines for the block pattern
            # Allow blank lines between elements
            j = i + 1
            # Skip blank lines
            while j < len(lines) and lines[j].strip() == '':
                j += 1
            if j < len(lines) and re.match(r'^\s*github\.com\s*$', lines[j]):
                j += 1
                while j < len(lines) and lines[j].strip() == '':
                    j += 1
                if j < len(lines) and re.match(r'^\s*`?<https?://[^>]+>`?\s*$', lines[j]):
                    url_line = lines[j].strip()
                    url = re.sub(r'[<>`]', '', re.search(r'<(https?://[^>]+)>', url_line).group(0))
                    j += 1
                    while j < len(lines) and lines[j].strip() == '':
                        j += 1
                    if j < len(lines) and re.match(r'^\s*\]\(`?<https?://[^>]+>`?\)\s*$', lines[j]):
                        # All parts matched, write the fixed link
                        new_lines.append(f'{indent}[github.com]({url})\n')
                        i = j + 1
                        continue
        # If not matched, just copy the line
        new_lines.append(lines[i])
        i += 1

    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

def ensure_title_heading(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Check if any line is a level-1 heading
    has_title = any(line.strip().startswith("# ") for line in lines)
    if has_title:
        return

    # Prettify filename: remove extension, replace _ and - with space, capitalize words
    base = os.path.basename(md_file)
    name = os.path.splitext(base)[0]
    pretty = name.replace("_", " ").replace("-", " ").strip().capitalize()
    # Optionally, capitalize each word:
    pretty = " ".join(word.capitalize() for word in pretty.split())

    # Insert title at the top
    lines = [f"# {pretty}\n\n"] + lines
    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def ensure_heading_hierarchy(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    title_found = False
    new_lines = []
    in_code_block = False
    for line in lines:
        stripped = line.strip()
        # Toggle code block state
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue
        if not in_code_block and stripped.startswith("# "):
            if not title_found:
                title_found = True
                new_lines.append(line)
            else:
                # Convert to level 2 heading
                new_lines.append(line.replace("# ", "## ", 1))
        else:
            new_lines.append(line)

    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

def ensure_blank_lines_around_fences(md_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Check if this line starts a code block
        if stripped.startswith("```"):
            # Check if previous line is not blank (and exists)
            if i > 0 and lines[i-1].strip() != "":
                new_lines.append("\n")
            
            new_lines.append(line)
            i += 1
            
            # Find the closing fence
            while i < len(lines):
                current_line = lines[i]
                new_lines.append(current_line)
                if current_line.strip().startswith("```"):
                    # This is the closing fence
                    # Check if next line is not blank (and exists)
                    if i + 1 < len(lines) and lines[i + 1].strip() != "":
                        new_lines.append("\n")
                    break
                i += 1
        else:
            new_lines.append(line)
        
        i += 1

    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

def ensure_blank_lines_around_lists(md_file):
    """Ensure there's at least one blank line before lists and between text and lists."""
    with open(md_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    in_code_block = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Toggle code block state
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue
            
        # Skip processing inside code blocks
        if in_code_block:
            new_lines.append(line)
            continue
        
        # Check if current line is a list item
        is_list_item = bool(re.match(r'^\s*[-*+]\s+', line) or re.match(r'^\s*\d+\.\s+', line))
        
        # Check if current line is a heading
        is_heading = stripped.startswith('#')
        
        if is_list_item or is_heading:
            # Check if previous line exists and is not blank
            if (i > 0 and 
                lines[i-1].strip() != "" and 
                not re.match(r'^\s*[-*+]\s+', lines[i-1]) and  # Previous line is not a list item
                not re.match(r'^\s*\d+\.\s+', lines[i-1]) and  # Previous line is not a numbered list item
                not lines[i-1].strip().startswith('#')):  # Previous line is not a heading
                
                # Add blank line before list or heading
                new_lines.append("\n")
        
        new_lines.append(line)
        
        # If current line is text (not list, not heading, not blank) and next line is a list or heading
        if (not is_list_item and not is_heading and stripped != "" and
            i + 1 < len(lines)):
            
            next_line = lines[i + 1]
            next_stripped = next_line.strip()
            next_is_list = bool(re.match(r'^\s*[-*+]\s+', next_line) or re.match(r'^\s*\d+\.\s+', next_line))
            next_is_heading = next_stripped.startswith('#')
            
            if (next_is_list or next_is_heading) and next_stripped != "":
                # Add blank line after text before list or heading
                new_lines.append("\n")

    with open(md_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

def get_markdown_files(target, exclude_dirs=None):
    exclude_dirs = exclude_dirs or []
    
    def should_exclude_dir(dir_path):
        """Check if directory should be excluded based on patterns."""
        dir_name = os.path.basename(dir_path)
        for pattern in exclude_dirs:
            if fnmatch.fnmatch(dir_name, pattern) or fnmatch.fnmatch(dir_path, pattern):
                return True
        return False
    
    if os.path.isdir(target):
        # Recursively find all .md files, excluding specified directories
        files = []
        for dp, dn, filenames in os.walk(target):
            # Filter out excluded directories from dn (modifies the walk)
            dn[:] = [d for d in dn if not should_exclude_dir(os.path.join(dp, d))]
            
            # Skip if current directory should be excluded
            if should_exclude_dir(dp):
                continue
                
            for f in filenames:
                if f.lower().endswith('.md'):
                    files.append(os.path.join(dp, f))
        return files
    elif '*' in target or '?' in target or '[' in target:
        # Glob pattern
        return glob.glob(target, recursive=True)
    elif os.path.isfile(target):
        return [target]
    else:
        return []

def main():
    parser = argparse.ArgumentParser(description='Fix common markdown issues using markdownlint and custom fixes.')
    parser.add_argument('targets', nargs='*', help='Files, directories, or glob patterns to process. If none specified, processes *.md in current directory.')
    parser.add_argument('--exclude-dirs', action='append', help='Directory patterns to exclude (can be used multiple times). Supports wildcards.')
    
    args = parser.parse_args()
    
    if not args.targets:
        # No argument: process all .md files in current directory (non-recursive)
        files = glob.glob('*.md')
    else:
        files = []
        for target in args.targets:
            files.extend(get_markdown_files(target, args.exclude_dirs))
    files = list(set(files))  # Remove duplicates

    if not files:
        print("No markdown files found to process.")
        sys.exit(1)

    if args.exclude_dirs:
        print(f"Excluding directories matching: {', '.join(args.exclude_dirs)}")

    for f in files:
        print(f"Processing {f}")
        run_markdownlint(f)
        fix_images(f)
        renumber_ordered_lists(f)
        wrap_angle_brackets_in_backticks(f)
        fix_markdown_links(f)
        collapse_blank_lines(f)
        fix_multiline_link_blocks(f)
        ensure_title_heading(f)
        ensure_heading_hierarchy(f)
        ensure_blank_lines_around_fences(f)
        ensure_blank_lines_around_lists(f)

    print("All markdownlint issues should now be fixed in processed files.")

if __name__ == '__main__':
    main()