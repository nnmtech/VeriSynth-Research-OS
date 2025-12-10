"""
VeriSynthOS Memory Agent - Enterprise Edition Launcher
Loads the full-featured enterprise memory agent
"""

import importlib.util
import sys
from pathlib import Path

# Load the enterprise memory agent module
spec = importlib.util.spec_from_file_location(
    "memory_enterprise",
    Path(__file__).parent / "agents.memory.main.enterprise.py"
)

if spec and spec.loader:
    module = importlib.util.module_from_spec(spec)
    sys.modules["memory_enterprise"] = module
    spec.loader.exec_module(module)
    
    # Export the FastAPI app for uvicorn
    app = module.app
else:
    raise ImportError("Could not load enterprise memory agent")
