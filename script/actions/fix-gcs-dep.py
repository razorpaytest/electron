#!/usr/bin/env python3
"""Reinstall a GCS dep from src/DEPS for the machine running this script.

The src cache is synced on Linux, so gclient picks each GCS object by
evaluating its DEPS condition against the Linux host (macOS checkouts
override host_os but not host_cpu). That is fine for tools the build runs as
executables, but not for libraries the build loads into its own processes,
which must match this machine exactly. This re-evaluates the conditions with
this machine's host_os and host_cpu and installs the object they select.
"""

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(SRC_DIR, 'third_party', 'depot_tools'))
import gclient_eval  # pylint: disable=wrong-import-position

GCS_URL = 'https://storage.googleapis.com'


def select_object(dep, variables):
  matches = [
      o for o in dep['objects']
      if gclient_eval.EvaluateCondition(o['condition'], variables)
  ]
  if len(matches) != 1:
    names = [o['object_name'] for o in matches]
    sys.exit(f'Expected one object for host_os={variables["host_os"]} '
             f'host_cpu={variables["host_cpu"]}, found {names}')
  return matches[0]


def download(bucket, obj, dest):
  url = f'{GCS_URL}/{bucket}/{obj["object_name"]}'
  sha256 = hashlib.sha256()
  with urllib.request.urlopen(url) as response, open(dest, 'wb') as f:
    while chunk := response.read(1 << 20):
      sha256.update(chunk)
      f.write(chunk)
  if sha256.hexdigest() != obj['sha256sum']:
    sys.exit(f'sha256 mismatch for {url}: expected {obj["sha256sum"]}, '
             f'got {sha256.hexdigest()}')


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('dep',
                      help='DEPS path, e.g. src/third_party/llvm-libclang')
  parser.add_argument('--host-os', required=True, choices=('linux', 'mac',
                                                           'win'))
  parser.add_argument('--host-cpu', required=True, choices=('arm64', 'x64'))
  args = parser.parse_args()

  deps_file = os.path.join(SRC_DIR, 'DEPS')
  with open(deps_file, encoding='utf-8') as f:
    local_scope = gclient_eval.Exec(f.read(), deps_file)
  dep = local_scope['deps'][args.dep]
  if dep.get('dep_type') != 'gcs':
    sys.exit(f'{args.dep} is not a GCS dep')

  variables = dict(local_scope.get('vars', {}),
                   host_os=args.host_os,
                   host_cpu=args.host_cpu)
  obj = select_object(dep, variables)

  # DEPS paths are relative to the gclient root, which is src/'s parent.
  install_dir = os.path.join(os.path.dirname(SRC_DIR), args.dep)
  with tempfile.TemporaryDirectory() as tmp:
    archive = os.path.join(tmp, os.path.basename(obj['object_name']))
    download(dep['bucket'], obj, archive)
    shutil.rmtree(install_dir, ignore_errors=True)
    os.makedirs(install_dir)
    with tarfile.open(archive) as tar:
      if hasattr(tarfile, 'data_filter'):
        tar.extractall(install_dir, filter='data')
      else:
        tar.extractall(install_dir)
  print(f'Installed {obj["object_name"]} into {install_dir}')


if __name__ == '__main__':
  main()
