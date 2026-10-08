import sys
from pathlib import Path

# Ensure `backend/` is on sys.path so `import app.models.card` etc. resolve
# regardless of the directory pytest is invoked from.
BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
