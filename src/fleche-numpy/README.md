# fleche-numpy

[fleche](https://github.com/pmrv/fleche) digest hooks for numpy: arrays (`np.ndarray` and its subclasses), `np.bool_` and `np.timedelta64`.

```bash
pip install fleche-numpy
```

Installing it is all it takes: fleche finds the hooks through its `fleche` entry point group.
Without it, fleche does not digest these values.
numpy number scalars (`np.float64`, `np.int32`, ...) need no hooks; fleche digests them itself.

With fleche-numpy installed, destructuring value stores take arrays of `dtype=object` apart element by element, like lists, and inline other arrays into their parent entry like scalars.
With the store's `remaining_size` set, an array counts its `nbytes` towards it.

How arrays are digested — dtype, shape and bytes, per field for structured dtypes, per element for object dtypes — is described in fleche's [numpy documentation](https://fleche.readthedocs.io/en/latest/digests/numpy.html).

This package lives in the fleche repository, under `src/fleche-numpy`, and is versioned and released independently of fleche itself.
