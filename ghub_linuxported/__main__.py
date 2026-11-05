import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        from .cli import main as cli
        return cli(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "tray":
        from .tray.main import main as tray
        sys.argv = sys.argv[:1] + sys.argv[2:]
        return tray()
    from .ui.app import main as gui
    return gui()


if __name__ == "__main__":
    sys.exit(main())
