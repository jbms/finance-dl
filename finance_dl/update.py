from typing import List, Optional
import argparse
import importlib
import subprocess
import concurrent.futures
import sys
import threading
import os
import time

config_prefix = 'CONFIG_'


def _format_duration(count) -> str:
    seconds_per_day = 24 * 60 * 60
    if count >= seconds_per_day:
        return '%d days' % (count // seconds_per_day)
    return '%d minutes' % (count // 60)


class App(object):
    def __init__(self, args):
        self.args = args
        self.config_module = importlib.import_module(args.config_module)
        self.log_dir = args.log_dir
        self._print_lock = threading.Lock()

    def print_message(self, message):
        with self._print_lock:
            print(message)

    def get_all_configs(self) -> List[str]:
        names = []
        for key in vars(self.config_module):
            if key.startswith(config_prefix):
                names.append(key[len(config_prefix):])
        return names

    def get_last_update_path(self, config_name: str) -> str:
        return os.path.join(self.log_dir, config_name + '.lastupdate')

    def get_log_path(self, config_name: str) -> str:
        return os.path.join(self.log_dir, config_name + '.txt')

    def get_last_update_time(self, config_name: str) -> Optional[float]:
        try:
            statinfo = os.stat(self.get_last_update_path(config_name))
            return statinfo.st_mtime
        except OSError:
            return None

    def command_status(self):
        cur_time = time.time()
        config_names = self.get_all_configs()
        max_name_len = max(len(x) for x in config_names)
        update_times = [(name, self.get_last_update_time(name))
                        for name in config_names]

        def get_time_sort_key(mtime: Optional[int]) -> float:
            if mtime is None:
                return float('-inf')
            return mtime

        update_times.sort(key=lambda x: get_time_sort_key(x[1]))
        for name, mtime in update_times:
            if mtime is not None:
                update_string = '%s (%s ago)' % (time.strftime(
                    '%c',
                    time.localtime(mtime)), _format_duration(cur_time - mtime))
            else:
                update_string = 'NEVER'
            print('%*s: %s' % (max_name_len, name, update_string))

    def run_config(self, config):
        self.print_message('%s: starting' % config)
        start_time = time.time()
        try:
            with open(self.get_log_path(config), 'wb') as f:
                subprocess.check_call([
                    sys.executable, '-m', 'finance_dl.cli', '--config-module',
                    self.args.config_module, '-c', config
                ], stdout=f, stderr=f)
            success = True
            with open(self.get_last_update_path(config), 'w') as f:
                pass
        except:
            success = False
        end_time = time.time()
        success_message = 'SUCCESS' if success else 'FAILED'
        self.print_message(
            '%s: %s in %d seconds' % (config, success_message,
                                      int(end_time - start_time)))

    def command_update(self):
        force = self.args.force
        cur_time = time.time()
        configs = self.args.config
        if self.args.all:
            configs = self.get_all_configs()
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=100) as executor:
            for config in configs:
                mtime = self.get_last_update_time(config)
                if not force and mtime is not None and (
                        cur_time - mtime) < 24 * 60 * 60:
                    print('%s: SKIPPING (updated %s ago)' %
                          (config, _format_duration(cur_time - mtime)))
                    continue
                executor.submit(self.run_config, config)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config-module', type=str, required=True,
                    help='Python module defining CONFIG_<name> functions.')
    ap.add_argument('--log-dir', type=str, required=True,
                    help='Directory containing log files.')

    subparsers = ap.add_subparsers(dest='command')

    ap_status = subparsers.add_parser('status', help='Show update status.')

    ap_update = subparsers.add_parser('update', help='Update configurations.')
    ap_update.add_argument('config', nargs='*', type=str, default=[],
                           help='Configuration to update')
    ap_update.add_argument(
        '-f', '--force', action='store_true',
        help='Force update even if the configuration has already run recently.'
    )
    ap_update.add_argument('-a', '--all', action='store_true',
                           help='Update all configurations.')

    args = ap.parse_args()

    app = App(args)

    if args.command:
        getattr(app, 'command_%s' % args.command)()
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
