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


class CommandBase:
    def __init__(self, args):
        self.args = args
        self.config_module = importlib.import_module(args.config_module)
        self.log_dir = args.log_dir

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


class StatusCommand(CommandBase):
    def __init__(self, args):
        super().__init__(args)

    def __call__(self):
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


class Updater(CommandBase):
    def __init__(self, args):
        super().__init__(args)
        force = self.args.force
        cur_time = time.time()
        configs = self.args.config
        if self.args.all:
            configs = self.get_all_configs()
        configs_to_update = []
        for config in configs:
            mtime = self.get_last_update_time(config)
            if not force and mtime is not None and (
                    cur_time - mtime) < 24 * 60 * 60:
                print('%s: SKIPPING (updated %s ago)' %
                      (config, _format_duration(cur_time - mtime)))
                continue
            configs_to_update.append(config)
        self.configs_to_update = configs_to_update
        self._lock = threading.Lock()
        self.configs_completed = 0

    def print_message(self, config, start_time, message, completed=False):
        with self._lock:
            if completed:
                self.configs_completed += 1
            print('[%d/%d] %s [%.fs elapsed] %s' %
                  (self.configs_completed, len(self.configs_to_update), config,
                   time.time() - start_time, message.rstrip()))

    def run_config(self, config):
        start_time = time.time()
        self.print_message(config, start_time, 'starting')
        success = False
        termination_message = 'SUCCESS'
        try:
            with open(
                    self.get_log_path(config), 'w', encoding='utf-8',
                    newline='') as f:
                process = subprocess.Popen(
                    [
                        sys.executable, '-m', 'finance_dl.cli',
                        '--config-module', self.args.config_module, '-c', config
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    universal_newlines=True,
                )
                for line in process.stdout:
                    self.print_message(config, start_time, line.rstrip())
                    f.write(line)
                process.wait()
                if process.returncode == 0:
                    success = True
                    with open(
                            self.get_last_update_path(config),
                            'w',
                            encoding='utf-8',
                            newline='') as f:
                        pass
                else:
                    termination_message = 'FAILED with return code %d' % (process.returncode)

        except:
            termination_message = 'FAILED with exception'
        self.print_message(config, start_time, termination_message,
                           completed=True)

    def __call__(self):
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.args.parallelism) as executor:
            for config in self.configs_to_update:
                executor.submit(self.run_config, config)


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('--config-module', type=str, required=True,
                    help='Python module defining CONFIG_<name> functions.')
    ap.add_argument('--log-dir', type=str, required=True,
                    help='Directory containing log files.')

    subparsers = ap.add_subparsers(dest='command')
    subparsers.required = True

    ap_status = subparsers.add_parser(
        'status',
        help='Show update status.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap_status.set_defaults(command_class=StatusCommand)

    ap_update = subparsers.add_parser(
        'update',
        help='Update configurations.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap_update.add_argument('config', nargs='*', type=str, default=[],
                           help='Configuration to update')
    ap_update.add_argument(
        '-f', '--force', action='store_true',
        help='Force update even if the configuration has already run recently.'
    )
    ap_update.add_argument('-a', '--all', action='store_true',
                           help='Update all configurations.')
    ap_update.add_argument(
        '-p', '--parallelism', type=int, default=4,
        help='Maximum number of configurations to update in parallel.')
    ap_update.set_defaults(command_class=Updater)

    args = ap.parse_args()

    command = args.command_class(args)
    command()


if __name__ == '__main__':
    main()
