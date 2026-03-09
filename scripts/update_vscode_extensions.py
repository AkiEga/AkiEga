#!/usr/bin/env python3
import base64
import os
import re
import subprocess
import sys
from datetime import date

import requests

OWNER = os.getenv('OWNER') or 'AkiEga'
TOKEN = os.getenv('GITHUB_TOKEN')

if not TOKEN:
    print('GITHUB_TOKEN must be provided via env vars', file=sys.stderr)
    sys.exit(1)

HEADERS = {
    'Authorization': f'token {TOKEN}',
    'Accept': 'application/vnd.github+json',
}


def list_repos(owner):
    repos = []
    url = f'https://api.github.com/users/{owner}/repos?per_page=100&type=owner'
    while url:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        repos.extend(r.json())
        m = re.search(r'<([^>]+)>; rel="next"', r.headers.get('Link', ''))
        url = m.group(1) if m else None
    return repos


def is_vscode_extension_repo(repo):
    """名前が vscode-extension で始まる、またはトピックに vscode-extension を含む"""
    name = repo.get('name', '')
    topics = repo.get('topics') or []
    return name.startswith('vscode-extension') or 'vscode-extension' in topics


def fetch_readme(owner, name):
    """リポジトリの README.md を文字列で返す。取得できなければ None。"""
    url = f'https://api.github.com/repos/{owner}/{name}/contents/README.md'
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get('encoding') == 'base64' and 'content' in data:
        try:
            return base64.b64decode(data['content']).decode('utf-8', errors='replace')
        except Exception:
            return None
    return None


def fetch_recent_commits(owner, name, count=5):
    """最近のコミットメッセージ一覧を返す。"""
    url = f'https://api.github.com/repos/{owner}/{name}/commits?per_page={count}'
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return []
    return [c['commit']['message'].split('\n')[0] for c in r.json()]


def generate_description_with_copilot(repo_name, readme, commits):
    """Copilot CLI を使って README + コミット履歴から1行の説明文を生成する。"""
    readme_excerpt = (readme or '')[:2000]
    commits_text = '\n'.join(f'- {c}' for c in commits) if commits else '(none)'

    prompt = (
        f"You are writing a GitHub profile README entry for a VS Code extension "
        f"called '{repo_name}'.\n"
        f"Based on the README and recent git log below, write ONE concise sentence "
        f"(max 120 characters) in English that describes what this extension does. "
        f"Output only the sentence with no extra text, quotes, or punctuation at the end.\n\n"
        f"=== README (excerpt) ===\n{readme_excerpt}\n\n"
        f"=== Recent commits ===\n{commits_text}"
    )

    try:
        result = subprocess.run(
            ['copilot', '-p', prompt],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            # 最初の1行だけ使う
            return result.stdout.strip().split('\n')[0].strip()
        print(f'  [warn] copilot -p failed for {repo_name}: {result.stderr.strip()}',
              file=sys.stderr)
    except FileNotFoundError:
        print('  [warn] copilot CLI not found; skipping description generation',
              file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f'  [warn] copilot -p timed out for {repo_name}', file=sys.stderr)
    return ''


def build_entries(owner):
    repos = list_repos(owner)
    entries = []
    for r in sorted(repos, key=lambda x: x['name']):
        if r.get('fork') or r.get('archived'):
            continue
        if not is_vscode_extension_repo(r):
            continue
        name = r['name']
        html_url = r['html_url']

        print(f'Processing: {name}')
        readme = fetch_readme(owner, name)
        commits = fetch_recent_commits(owner, name)
        desc = generate_description_with_copilot(name, readme, commits)

        # Copilot が失敗した場合は GitHub API の description にフォールバック
        if not desc:
            desc = (r.get('description') or '').strip()

        line = f'- [{name}]({html_url})'
        if desc:
            line += f' — {desc}'
        entries.append(line)
    return entries


def replace_section(readme_path, entries):
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    new_block = '#### VS Code Extensions\n'
    new_block += ('\n'.join(entries) if entries else '- (no repositories found)') + '\n'

    pattern = re.compile(r'#### VS Code Extensions\n.*?(?=\n#### |\Z)', re.S)
    if pattern.search(content):
        new_content = pattern.sub(new_block.rstrip('\n'), content)
    else:
        m = re.search(r'\n#### ', content)
        if m:
            new_content = content[:m.start()] + '\n' + new_block + content[m.start():]
        else:
            new_content = content.rstrip() + '\n\n' + new_block

    if new_content != content:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False


def git_setup():
    subprocess.check_call(['git', 'config', 'user.name', 'github-actions[bot]'])
    subprocess.check_call(['git', 'config', 'user.email',
                           '41898282+github-actions[bot]@users.noreply.github.com'])


def push_branch(branch, today):
    repo_full = os.getenv('GITHUB_REPOSITORY') or os.getenv('REPO') or ''
    remote_url = f'https://x-access-token:{TOKEN}@github.com/{repo_full}.git'
    subprocess.check_call(['git', 'remote', 'set-url', 'origin', remote_url])

    # 既存ブランチがあれば削除してから再作成
    existing = subprocess.run(
        ['git', 'ls-remote', '--heads', 'origin', branch],
        capture_output=True, text=True,
    )
    if existing.stdout.strip():
        print(f'Remote branch {branch} already exists — deleting before re-push')
        subprocess.check_call(['git', 'push', 'origin', f':{branch}'])

    subprocess.check_call(['git', 'checkout', '-b', branch])
    subprocess.check_call(['git', 'add', 'README.md'])
    subprocess.check_call(['git', 'commit', '-m',
                           f'Update VS Code Extensions list ({today})'])
    result = subprocess.run(
        ['git', 'push', 'origin', branch],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'git push failed:\n{result.stderr}', file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, 'git push')
    print(f'Pushed branch: {branch}')


def find_existing_pr(owner, repo, branch):
    """同じ head ブランチの open PR があれば URL を返す。なければ None。"""
    url = f'https://api.github.com/repos/{owner}/{repo}/pulls?state=open&head={owner}:{branch}'
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200 and r.json():
        return r.json()[0]['html_url']
    return None


def create_pr(branch, today):
    repo_full = os.getenv('GITHUB_REPOSITORY') or os.getenv('REPO') or ''
    parts = repo_full.split('/')
    if len(parts) != 2:
        print(f'Cannot parse repo "{repo_full}" for PR creation', file=sys.stderr)
        return
    owner, repo = parts

    existing_url = find_existing_pr(owner, repo, branch)
    if existing_url:
        print(f'Open PR already exists: {existing_url}')
        return

    url = f'https://api.github.com/repos/{owner}/{repo}/pulls'
    payload = {
        'title': f'Update VS Code Extensions section ({today})',
        'head': branch,
        'base': 'main',
        'body': (
            '## Automated update\n\n'
            'This PR was automatically created by the daily workflow.\n\n'
            '### Detection criteria\n'
            '- Repository name starts with `vscode-extension`, **or**\n'
            '- Repository topics contain `vscode-extension`\n'
        ),
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code == 201:
        print(f'PR created: {r.json()["html_url"]}')
    else:
        print(f'PR creation failed ({r.status_code}): {r.text}', file=sys.stderr)
        sys.exit(1)


def main():
    today = str(date.today())
    branch = f'update/vscode-extensions-{today}'

    readme_path = os.path.join(os.getcwd(), 'README.md')
    if not os.path.exists(readme_path):
        print('README.md not found in repository root', file=sys.stderr)
        sys.exit(1)

    print(f'Scanning repos for owner: {OWNER}')
    entries = build_entries(OWNER)
    print(f'Found {len(entries)} VS Code extension repo(s)')

    changed = replace_section(readme_path, entries)
    if not changed:
        print('No update required')
        return

    git_setup()
    push_branch(branch, today)
    create_pr(branch, today)


if __name__ == '__main__':
    main()
