
import time
import sys
import os

# Add src to path to allow importing fleche
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from hypothesis import strategies as st
import pandas as pd
import numpy as np

def test_generation():
    print("Generating integer...")
    print(st.integers().example())

    print("Generating list of integers...")
    print(st.lists(st.integers(), min_size=5, max_size=5).example())

    print("Generating numpy array...")
    # hypothesis.extra.numpy might be needed
    try:
        from hypothesis.extra.numpy import arrays
        print(arrays(np.int32, (2, 2)).example())
    except ImportError:
        print("hypothesis.extra.numpy not available")

if __name__ == "__main__":
    test_generation()
