# fleche

[![docs](https://app.readthedocs.org/projects/fleche/badge/?version=latest)](https://fleche.readthedocs.io/en/latest/?badge=latest)





A persistent caching solution for arbitrary Python functions - like `lru_cache` on steroids.

> flèche is French for 'arrow' and also used in fencing as a fast attack.

## Features

- **Persistent Caching**: Cache function results across runs using various storage backends
- **Flexible Storage**: Choose from file-based, SQL, in-memory, or custom storage solutions
- **Intelligent Hashing**: Automatically generates cache keys from function arguments
- **Query Support**: Search and retrieve cached results with metadata filtering
- **Configurable**: Control what gets hashed (version, module, code, arguments)
- **Multiple Backends**: File (pickle, JSON), SQLAlchemy, Bagofholding, and more
- **Thread-Safe**: Safe for use in multi-threaded environments
- **Type-Aware**: Works seamlessly with NumPy, Pandas, and custom types

## Installation

### Basic Installation

```bash
pip install fleche
```

### With conda

`fleche` is available on [conda-forge](https://conda-forge.org/). Two packages are
published:

- **`fleche-base`** — the core library only (no optional dependencies)
- **`fleche`** — the full install, which also pulls in the optional dependencies

```bash
# Core library only
conda install -c conda-forge fleche-base

# Full install with all optional dependencies
conda install -c conda-forge fleche
```

### With Optional Dependencies

```bash
# For SQL storage
pip install fleche[sqlalchemy]

# For alternate serialization formats
pip install fleche[cloudpickle,dill]

# For Bagofholding storage
pip install fleche[bagofholding]

# For SshCache (sharing caches across machines over SSH) — requires cloudpickle
pip install fleche[ssh]

# For documentation
pip install fleche[docs]

# For development and testing
pip install fleche[tests]
```

## Quick Start

### Basic Usage

```python
from fleche import fleche

@fleche()
def expensive_function(x, y):
    """This function's results will be cached."""
    print(f"Computing for {x}, {y}...")
    return x + y

# First call computes the result
result = expensive_function(1, 2)  # prints "Computing for 1, 2..."

# Second call retrieves from cache
result = expensive_function(1, 2)  # no print - result from cache!

# Different arguments compute again
result = expensive_function(2, 3)  # prints "Computing for 2, 3..."
```

### Working with Cache Results

```python
@fleche()
def compute(x):
    return x ** 2

# Get the cache key (digest) for arguments
digest = compute.digest(5)

# Check if result is cached
if compute.contains(5):
    result = compute.load(5)
else:
    result = compute(5)

# Get Call object with metadata
call = compute.call(5)
```

## Configuration

### Decorator Options

```python
@fleche(
    version=1,           # Versioning for function changes
    hash_version=True,   # Include version in cache key
    hash_module=True,    # Include module name in cache key
    hash_code=False,     # Include function code in cache key
    require=None,        # Required argument for caching
    ignore=None,         # Arguments to ignore in cache key
    isolate=False,       # Isolate cache by working directory
)
def my_function(x):
    return x * 2
```

## Storage Backends

### In-Memory Storage (Default)
- Default when no `fleche.toml` configuration file is present
- Transient: data is lost when the process exits

### File Storage
- Stores cache in filesystem using pickle (or cloudpickle/dill)
- Persistent across runs
- XDG Base Directory Specification compliant when configured

### SQL Storage
- Requires `sqlalchemy`
- **Call storage only** — stores call records (function name, arguments, metadata) in a SQL database; a separate value backend (file or memory) is still required for results
- SQLite is the primary tested backend; any SQLAlchemy-supported database should work
- Enables efficient server-side filtering when querying cached calls

### SSH (remote) Cache
- **Requires `cloudpickle`** (`pip install fleche[ssh]`) — used as the wire protocol between client and remote server; not optional
- Forwards every cache operation over a persistent `ssh host python -m fleche remote --serve` subprocess
- Stack with a local cache to read-through to a shared remote one — see `fleche.remote.SshCache`

### In-Memory Storage
- For testing or temporary caching
- Loses data when process exits

### Custom Backends
Implement the `Storage` interface to create custom backends.

## Advanced Features

### Versioning

Track function versions to invalidate cache when implementation changes:

```python
@fleche(version=2)
def process_data(data):
    # Incrementing version invalidates all v1 cache entries
    return data * 2
```

### Ignoring Arguments

Skip certain arguments when generating cache keys:

```python
@fleche(ignore=['verbose', 'debug'])
def compute(x, y, verbose=False, debug=False):
    return x + y  # Cache key only uses x and y
```

### Querying Results

Find cached results matching specific criteria (only after issuing a corresponding call):

```python
@fleche()
def fetch_data(user_id, date):
    return get_data(user_id, date)

# Issue a call to cache the result
fetch_data(user_id=123, date='2024-01-01')

# Get all cached results
all_results = list(fetch_data.query())

# Get results matching specific arguments (None acts as wildcard)
results = list(fetch_data.query(user_id=123))

# Inspect a result
for call in fetch_data.query(user_id=123):
    print(call.arguments, call.result)
```

## Performance

Use the included benchmarks to evaluate performance:

```bash
python -m benchmarks.run_benchmarks
```

## Testing

Run the test suite:

```bash
pip install "fleche[tests]"
pytest tests/
```

## Contributing

Contributions are welcome! Please ensure tests pass and code follows the project style.

## License

BSD-3-Clause License - see LICENSE file for details.

## Resources

- **Documentation**: See `docs/` directory
- **Tests**: See `tests/` for usage examples
- **Benchmarks**: See `benchmarks/` for performance metrics
