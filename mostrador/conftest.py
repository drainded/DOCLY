"""
conftest.py — raíz de mostrador/
=================================
Agrega engine/ y engine/document/ al sys.path para que los tests puedan
importar los módulos del motor con rutas cortas (ej. `from models import ...`).
"""

import sys
from pathlib import Path

# Permite: from models import DocumentMeta, ProcessingConfig
sys.path.insert(0, str(Path(__file__).parent / "engine" / "document"))

# Permite: from engine.document.models import ...  (por si algún test lo necesita)
sys.path.insert(0, str(Path(__file__).parent / "engine"))

# Permite: from engine.document.models import ...  desde la raíz del paquete
sys.path.insert(0, str(Path(__file__).parent))
