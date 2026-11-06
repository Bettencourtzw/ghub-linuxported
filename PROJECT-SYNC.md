# Project sync

- Canonical source: https://github.com/Bettencourtzw/ghub-linuxported
- Primary branch: `main`. Use scoped feature branches and reviewed pull requests.
- Local checkout: `/Users/bettencourt/Documents/ChatGPT/personal/ghub-linuxported`.
- Personal, non-client project; no Hours tracking.
- Linux desktop application; no hosted runtime is configured in this checkout.
- macOS is used for source edits, documentation previews and pure-Python tests.
- Linux runtime dependencies: Python 3.11+, PyGObject, GTK4 and libadwaita 1.7+.
  See `README.md` and `install.sh` for installation. No environment file is required.
- Sync through Git; keep device backups, dumps, credentials and caches out of commits.
- No GitHub Actions or hosting configuration is present. Do not add automatic CI
  or deploy hooks without authorization.
- Main updates require an explicit request. Installing or updating a running
  Linux instance requires separate authorization naming the machine.
- Local checks: `python3 -m unittest discover -s tests -v` and `git diff --check`.
- Hardware and native GTK verification require a Linux environment and suitable devices.
