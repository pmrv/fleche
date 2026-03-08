import re

# Since the default run takes ~3 minutes (2m56s), we only have about 1 minute of leeway to reach 4 minutes!
# No wonder doubling `number` or `repeat` globally blew past 4 minutes!
# We must be very precise.
# We will ONLY increase the number of repetitions for `number=10` to `number=20` in `benchmark_digest.py` and `benchmark_integration.py`
# And maybe increase small_data from 100 to 200, and nested_data from 50 to 100 in `benchmark_storage.py`.

with open("benchmarks/benchmark_storage.py", "r") as f:
    content = f.read()
content = content.replace('small_data = [f"value_{i}" for i in range(100)]', 'small_data = [f"value_{i}" for i in range(200)]')
content = content.replace('nested_data = [st_nested_values.example() for _ in range(50)]', 'nested_data = [st_nested_values.example() for _ in range(100)]')
# Don't touch numpy arrays (large_data) or Sql calls_data, they are slow.
with open("benchmarks/benchmark_storage.py", "w") as f:
    f.write(content)

with open("benchmarks/benchmark_integration.py", "r") as f:
    content = f.read()
# Let's increase the number of repetitions in timeit for integration.
content = content.replace('number = 10', 'number = 20')
with open("benchmarks/benchmark_integration.py", "w") as f:
    f.write(content)

with open("benchmarks/benchmark_digest.py", "r") as f:
    content = f.read()
content = content.replace('number = 10', 'number = 20')
with open("benchmarks/benchmark_digest.py", "w") as f:
    f.write(content)
