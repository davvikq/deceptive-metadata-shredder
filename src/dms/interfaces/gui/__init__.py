"""PySide6 desktop GUI package for DMS."""
# Intentionally empty — do NOT eagerly import app.py here.
# Importing this package must not trigger PySide6 / Qt initialisation as a
# side-effect; that causes Python to load app.py as *both*
# 'dms.interfaces.gui.app' (package import) and '__main__' (when run with
# `python -m dms.interfaces.gui.app`), which produces:
#   RuntimeWarning: 'dms.interfaces.gui.app' found in sys.modules
# Use the 'dms-gui' console-script entry point instead of -m.

