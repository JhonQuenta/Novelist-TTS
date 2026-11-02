"""Check tracked publication files without displaying possible secrets."""
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DENIED_DIRS={'data','.venv','venv','env','__pycache__','work','outputs','runtime'}
DENIED_EXTENSIONS={'.epub','.pdf','.wav','.mp3','.m4a','.opus','.ogg','.flac','.mp4','.mkv',
    '.zip','.7z','.msix','.exe','.dll','.onnx','.gguf','.bin','.pem','.key','.pfx','.p12','.log','.pyc'}
RULES={
    'GitHub token':r'\bgh[pousr]_[A-Za-z0-9]{20,}\b',
    'GitHub fine-grained token':r'\bgithub_pat_[A-Za-z0-9_]{30,}\b',
    'AWS access key':r'\bAKIA[A-Z0-9]{16}\b',
    'OpenAI-style key':r'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b',
    'Private key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'Personal Windows path':r'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"\']+',
}

def main():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,stdout=subprocess.PIPE,check=True)
    files=[name for name in result.stdout.decode('utf-8').split('\0') if name]
    issues=[]
    for name in files:
        relative=Path(name)
        if any(part.lower() in DENIED_DIRS or part.lower().startswith('pruebas') for part in relative.parts) or relative.suffix.lower() in DENIED_EXTENSIONS or relative.name.startswith('.env'):
            issues.append((name,'excluded data or binary file'));continue
        path=ROOT/relative
        if path.is_symlink() or not path.is_file():issues.append((name,'non-regular file'));continue
        data=path.read_bytes()
        if len(data)>2_000_000 or b'\0' in data:issues.append((name,'binary or unexpectedly large file'));continue
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:issues.append((name,'non-UTF-8 file'));continue
        for label,pattern in RULES.items():
            if re.search(pattern,text):issues.append((name,label))
    if issues:
        for name,label in issues:print(f'{name}: {label}')
        print('Review these files before publishing. Matched values are not printed.')
        return 1
    print(f'Checked {len(files)} tracked source files: no excluded data or recognized secrets detected.')
    return 0

if __name__=='__main__':sys.exit(main())
