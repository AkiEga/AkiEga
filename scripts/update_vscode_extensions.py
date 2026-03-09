#!/usr/bin/env python3
import os
import re
import sys
import subprocess
from argparse import ArgumentParser

def read_copilot_file(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        lines = [l.rstrip() for l in f if l.strip()]
    # Filter to lines that look like markdown list items
    return [l for l in lines if l.startswith('- ')]

def replace_section(readme_path, entries):
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    heading = '#### VS Code Extensions'
    new_block = heading + '\n\n'
    if entries:
        new_block += '\n'.join(entries) + '\n'
    else:
        new_block += '- (no detected extensions)\n'

    pattern = re.compile(r'(#### VS Code Extensions\s*\n)(.*?)(?=\n#### |\Z)', re.S)
    if pattern.search(content):
        new_content = pattern.sub(new_block, content)
    else:
        # fallback: append before first "#### Embedded Systems / Hardware" or at end
        m = re.search(r'#### Embedded Systems / Hardware', content)
        if m:
            idx = m.start()
            new_content = content[:idx] + new_block + '\n' + content[idx:]
        else:
            new_content = content + '\n' + new_block

    if new_content != content:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

def git_commit_and_push(repo_full_name):
    try:
        subprocess.check_call(['git', 'add', 'README.md'])
        diff = subprocess.check_output(['git', 'diff', '--staged', '--name-only']).decode().strip()
        if not diff:
            print('No changes to commit')
            return
        subprocess.check_call(['git', 'config', 'user.name', 'github-actions[bot]'])
        subprocess.check_call(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'])
        subprocess.check_call(['git', 'commit', '-m', 'Update VS Code Extensions list (automated by Copilot CLI)'])
        remote = os.getenv('GITHUB_REPOSITORY') or repo_full_name
        token = os.getenv('GITHUB_TOKEN')
        if token:
            remote_url = f'https://x-access-token:{token}@github.com/{remote}.git'
            subprocess.check_call(['git', 'remote', 'set-url', 'origin', remote_url])
        subprocess.check_call(['git', 'push', 'origin', 'HEAD:main'])
        print('Pushed changes to main')
    except subprocess.CalledProcessError as e:
        print('Git operation failed:', e, file=sys.stderr)
        raise

def main():
    p = ArgumentParser()
    p.add_argument('--input', help='Copilot output markdown file', default=None)
    args = p.parse_args()

    readme_path = os.path.join(os.getcwd(), 'README.md')
    if not os.path.exists(readme_path):
        print('README.md not found in repository root', file=sys.stderr)
        sys.exit(1)

    entries = []
    if args.input:
        entries = read_copilot_file(args.input)

    if not entries:
        print('No entries from Copilot output; nothing to update')
        return

    changed = replace_section(readme_path, entries)
    if changed:
        print('README.md updated, committing...')
        repo_full = os.getenv('REPO') or os.getenv('GITHUB_REPOSITORY') or ''
        git_commit_and_push(repo_full)
    else:
        print('No update required')

if __name__ == '__main__':
    main()
