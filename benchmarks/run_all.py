"""Convenience script to run the complete benchmark suite from CLI."""

import asyncio
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.evaluate import run_all_benchmarks

if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
