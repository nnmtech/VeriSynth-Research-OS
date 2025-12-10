#!/usr/bin/env python3
"""Wrapper script to run the memory agent with proper module loading."""
import importlib.util
import sys

# Load the memory agent module from the file with dots in the name
spec = importlib.util.spec_from_file_location("memory_main", "agents.memory.main.py")
module = importlib.util.module_from_spec(spec)
sys.modules["memory_main"] = module
spec.loader.exec_module(module)

# Export the app for uvicorn
app = module.app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7000, reload=False)
