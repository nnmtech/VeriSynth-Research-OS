#!/usr/bin/env python3
"""
Example: How to ingest local documents into VeriSynthOS Memory Agent

This shows how to use the /ingest endpoint to load local files or directories.
"""

import requests
import json
from pathlib import Path

# Memory agent URL
BASE_URL = "http://127.0.0.1:7000"

def ingest_file(filepath: str):
    """Ingest a single file"""
    url = f"{BASE_URL}/ingest"
    payload = {
        "local_path": filepath
    }
    
    response = requests.post(url, json=payload)
    print(f"Ingesting file: {filepath}")
    print(f"Response: {response.json()}\n")
    return response.json()

def ingest_directory(dirpath: str, recursive: bool = True):
    """Ingest all text files in a directory"""
    url = f"{BASE_URL}/ingest"
    payload = {
        "local_path": dirpath,
        "recursive": recursive
    }
    
    response = requests.post(url, json=payload)
    print(f"Ingesting directory: {dirpath} (recursive={recursive})")
    print(f"Response: {response.json()}\n")
    return response.json()

def check_health():
    """Check if the memory agent is running"""
    url = f"{BASE_URL}/health"
    try:
        response = requests.get(url)
        print("Health check:")
        print(json.dumps(response.json(), indent=2))
        print()
        return True
    except Exception as e:
        print(f"Error: Memory agent not running? {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("VeriSynthOS Memory Agent - Local Ingestion Example")
    print("=" * 60)
    print()
    
    # Check if server is running
    if not check_health():
        print("Please start the memory agent first:")
        print("  make dev")
        exit(1)
    
    # Example 1: Ingest a single file
    print("Example 1: Ingest a single file")
    print("-" * 40)
    ingest_file("/home/nmtech/VeriSynthOS/README.md")
    
    # Example 2: Ingest entire directory (non-recursive)
    print("Example 2: Ingest current directory (non-recursive)")
    print("-" * 40)
    ingest_directory("/home/nmtech/VeriSynthOS", recursive=False)
    
    # Example 3: Ingest directory recursively
    print("Example 3: Ingest directory recursively (commented out)")
    print("-" * 40)
    print("# Uncomment to ingest all Python files in the project:")
    print("# ingest_directory('/home/nmtech/VeriSynthOS', recursive=True)")
    print()
    
    print("=" * 60)
    print("Done! Your documents are now indexed.")
    print("Next steps:")
    print("  1. Implement the /search endpoint to query indexed documents")
    print("  2. Use MAKER voting for multi-agent verification")
    print("  3. Connect to orchestrator for RAG-powered research")
    print("=" * 60)
