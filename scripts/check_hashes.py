import hashlib
import sys
from pathlib import Path

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
print('Scanning folder:', folder)
if not folder.exists():
    print('Folder does not exist:', folder)
    sys.exit(1)

hash_map = {}
errors = []
for p in folder.iterdir():
    if p.is_file():
        try:
            h = hashlib.sha256()
            with p.open('rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    h.update(chunk)
            digest = h.hexdigest()
            hash_map.setdefault(digest, []).append(p)
        except Exception as e:
            errors.append((p, str(e)))

print('\nDuplicate groups (by SHA256):')
found = 0
for h, items in hash_map.items():
    if len(items) > 1:
        found += 1
        print(f'Hash: {h}  Count: {len(items)}')
        for it in items:
            print('  -', it)

if found == 0:
    print('No duplicate file contents found (by SHA256).')

if errors:
    print('\nErrors:')
    for p, e in errors:
        print(p, e)

print('\nAll scanned files:')
for h, items in hash_map.items():
    for it in items:
        print(h[:8], it)
print('\nDone.')
