from hypothesis import strategies as st
import string
import keyword
from dataclasses import make_dataclass
from fleche.call import Call

try:
    import numpy as np
except ImportError:
    np = None

# Copied and adapted from tests/unit/digest/test_digest.py


@st.composite
def dataclasses(draw, field_types, frozen=None):
    if frozen is None:
        frozen = draw(st.booleans())
    fields = draw(
        st.dictionaries(
            st.text(string.ascii_letters, min_size=3, max_size=3).filter(
                lambda s: not keyword.iskeyword(s)
            ),
            field_types,
            min_size=1,
            max_size=5,
        )
    )
    clsname = draw(st.text(string.ascii_letters, min_size=3, max_size=3))
    cls = make_dataclass(
        clsname, [(k, type(v)) for k, v in fields.items()], frozen=frozen
    )
    return cls(*fields)


def calls(value_types):
    """Generate random Call objects using st.builds."""
    return st.builds(
        Call,
        name=st.text(string.ascii_letters, min_size=1, max_size=10),
        arguments=st.dictionaries(
            st.text(string.ascii_letters, min_size=1, max_size=5),
            value_types,
            max_size=6,
        ),
        module=st.one_of(
            st.none(), st.text(string.ascii_letters, min_size=1, max_size=10)
        ),
        version=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    )


key_strategies = [
    st.none(),
    st.integers(),
    st.floats(allow_nan=False),
    st.text(),
    st.binary(),
    st.booleans(),
]
key_strategies.append(dataclasses(st.one_of(*key_strategies), frozen=True))

# Base values include all key strategies plus unhashable types like Call
value_strategies = key_strategies.copy()
value_strategies.append(calls(st.one_of(*key_strategies)))


st_base_values = st.one_of(*value_strategies)
st_key_values = st.one_of(*key_strategies)  # Only hashable values for dict keys


st_nested_values = st.recursive(
    st_base_values,
    lambda children: st.one_of(
        (st_l := st.lists(children, max_size=6)),
        st.composite(lambda draw: tuple(draw(st_l)))(),
        st.dictionaries(st_key_values, children, max_size=6),  # Use only hashable keys
        dataclasses(children),
    ),
    max_leaves=10,
)


def generate_examples(strategy, count=100):
    """Generate a list of examples from a strategy."""
    examples = []
    for _ in range(count):
        examples.append(strategy.example())
    return examples


# Backend-safe strategies: restrict to types that every value-storage backend
# (stdlib pickle, cloudpickle, dill, H5Bag) can round-trip.
# Excluded from key_strategies above:
#   - st.binary(): H5Bag cannot store raw byte strings
#   - st.text() with full unicode: surrogates/null bytes break HDF5 strings
#   - dataclasses via make_dataclass: not importable by stdlib pickle
#   - calls: memoization metadata, not stored values
_backend_safe_leaf_strategies = [
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(
        alphabet=string.ascii_letters + string.digits + string.punctuation + " ",
        max_size=50,
    ),
]

st_backend_safe_base = st.one_of(*_backend_safe_leaf_strategies)


def st_backend_safe_nested(max_depth=3, max_size=6):
    """Hypothesis strategy for nested values serializable by every storage backend.

    Leaf types — None, bool, int, finite float, printable-ASCII text — are
    accepted by stdlib pickle, cloudpickle, dill, and H5Bag.  Containers are
    restricted to lists and str-keyed dicts.

    Parameters
    ----------
    max_depth : int
        Controls nesting depth via ``max_leaves = max_depth * max_size``.
    max_size : int
        Maximum items per list or dict.
    """
    return st.recursive(
        st_backend_safe_base,
        lambda children: st.one_of(
            st.lists(children, max_size=max_size),
            st.dictionaries(
                st.text(
                    alphabet=string.ascii_letters + string.digits,
                    min_size=1,
                    max_size=10,
                ),
                children,
                max_size=max_size,
            ),
        ),
        max_leaves=max_depth * max_size,
    )
