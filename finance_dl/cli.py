import argparse
import importlib
import logging
import json


def get_log_level(name):
    name = name.upper()
    numeric_level = getattr(logging, name, None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % name)
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config-module', type=str,
                    help='Python module defining CONFIG_<name> functions.')
    spec_group = ap.add_mutually_exclusive_group(required=True)
    spec_group.add_argument('--config', '-c', type=str,
                            help='Configuration name to use.')
    spec_group.add_argument('--spec', '-s', type=json.loads,
                            help='JSON configuration specification')
    ap.add_argument('--interactive', '-i', action='store_true', default=False,
                    help='Start interactive shell.')
    ap.add_argument(
        '--visible', action='store_true', help=
        'Run with a visible browser (if applicable).  Implied by --interactive.'
    )
    ap.add_argument('--log', type=get_log_level, default=logging.INFO,
                    help='Log level.')
    args = ap.parse_args()
    logging.basicConfig(
        level=args.log,
        format='%(asctime)s %(filename)s:%(lineno)d [%(levelname)s] %(message)s')

    if args.config_module:
        config_module = importlib.import_module(args.config_module)
    else:
        config_module = object()

    if args.config:
        key_prefix = 'CONFIG_'
        config_key = key_prefix + args.config
        if config_key is None:
            valid_keys = sorted(
                k for k in vars(config_module) if k.startswith(key_prefix))
            raise KeyError(
                'Invalid configuration key: %r.  Valid configuration keys: %r.'
                % (config_key, valid_keys))
        spec = getattr(config_module, config_key, None)()
    else:
        spec = args.spec
    module_name = spec.pop('module')
    module = importlib.import_module(module_name)

    headless = not args.visible
    if args.interactive:
        headless = False
    spec.setdefault('headless', headless)

    if args.interactive:

        def run_interactive_shell(**ns):
            import IPython
            user_ns = dict(vars(module), **ns)

            # Don't leave __name__ set, as that causes IPython to override the
            # real module's entry in sys.modules.
            user_ns.pop('__name__', None)
            IPython.terminal.ipapp.launch_new_instance(
                argv=[
                    '--no-banner',
                    '--no-autoindent',
                    '--InteractiveShellApp.exec_lines=["%load_ext autoreload", "%autoreload 2"]',
                ],
                user_ns=user_ns,
            )

        interactive_func = getattr(module, 'interactive', None)
        if interactive_func is not None:
            with interactive_func(**spec) as ns:
                run_interactive_shell(**ns)
        else:
            run_interactive_shell()
    else:
        module.run(**spec)


if __name__ == '__main__':
    main()
