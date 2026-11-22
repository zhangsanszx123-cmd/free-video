#!/usr/bin/env python3
"""Print the linux/amd64 config digest from a Docker-save archive, without extraction."""
import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import PurePosixPath


def normalized(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe image archive member')
    return str(path)


def config_digest(source):
    configs = {}
    manifests = None
    with tarfile.open(fileobj=source, mode='r|*') as archive:
        for member in archive:
            if not member.isfile() or member.size > 8 * 1024 * 1024:
                continue
            name = normalized(member.name)
            content = archive.extractfile(member).read()
            try:
                document = json.loads(content)
            except (ValueError, UnicodeError):
                continue
            if name == 'manifest.json':
                if manifests is not None or not isinstance(document, list):
                    raise ValueError('Invalid Docker-save manifest')
                manifests = document
            elif isinstance(document, dict) and document.get('architecture') == 'amd64' and document.get('os') == 'linux' and isinstance(document.get('rootfs'), dict) and document['rootfs'].get('type') == 'layers':
                configs[name] = hashlib.sha256(content).hexdigest()
    if not manifests:
        raise ValueError('Docker-save manifest is missing')
    candidates = set()
    for manifest in manifests:
        if not isinstance(manifest, dict) or not isinstance(manifest.get('Config'), str):
            raise ValueError('Invalid config member in Docker-save manifest')
        digest = configs.get(normalized(manifest['Config']))
        if digest:
            candidates.add(digest)
    if len(candidates) != 1:
        raise ValueError('Expected one linux/amd64 image configuration')
    return 'sha256:' + candidates.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', help='Docker-save tar/tar.gz file, or - for stdin')
    args = parser.parse_args()
    try:
        if args.archive == '-':
            digest = config_digest(sys.stdin.buffer)
        else:
            with open(args.archive, 'rb') as source:
                digest = config_digest(source)
        print(digest)
    except (OSError, ValueError, tarfile.TarError):
        print('Cannot verify the canonical linux/amd64 image config digest', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
