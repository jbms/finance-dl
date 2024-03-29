"""Renames improperly-named OFX files generated by the finance_dl.ofx module"""
import argparse
import os

import bs4

from .ofx import get_ofx_date_range


def fix_name(path, dry_run):
    name = os.path.basename(path)
    d = os.path.dirname(path)
    date_format = '%Y%m%d'

    parts = name.split('-')
    if len(parts) != 4:
      print("Skipping %r" % name)
      return

    with open(path, 'rb') as f:
        date_range = get_ofx_date_range(f.read())
    new_parts = [
        date_range[0].strftime(date_format), date_range[1].strftime(date_format)
    ] + parts[2:]
    new_name = '-'.join(new_parts)
    if new_name != name:
        new_path = os.path.join(d, new_name)
        print('Rename %s -> %s' % (path, new_path))
        if not dry_run:
            os.rename(path, new_path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    for path in args.paths:
        fix_name(path, dry_run=args.dry_run)
