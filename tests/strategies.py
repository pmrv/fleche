from hypothesis import strategies as st
from dataclasses import make_dataclass
import collections
import string
import keyword
import numpy as np
from fleche.call import Call
from fleche import digest


@st.composite
def dataclasses(draw, field_types, frozen=None, clscache={}):
    if frozen is None:
        frozen = draw(st.booleans())
    fields = draw(
        st.dictionaries(
            st.text(string.ascii_letters, min_size=3, max_size=3).filter(
                # keywords as field names obviously break
                # somehow using mro as a field name causes the dataclass to pick up type.mro as a default value
                # this can then break dataclass creation if non-default fields follow
                lambda s: not keyword.iskeyword(s) and s != "mro"
            ),
            field_types,
            min_size=1,
            max_size=5,
        )
    )
    clsname = 'C' + digest.digest(fields)
    if clsname not in clscache:
        cls = clscache[clsname] = make_dataclass(
            clsname, [(k, type(v)) for k, v in fields.items()], frozen=frozen
        )
    else:
        cls = clscache[clsname]
    return cls(*fields)


@st.composite
def namedtuples(draw, field_types, clscache={}):
    fields = draw(
        st.dictionaries(
            st.text(string.ascii_letters, min_size=3, max_size=3).filter(
                lambda s: not keyword.iskeyword(s) and s != "mro"
            ),
            field_types,
            min_size=1,
            max_size=5,
        )
    )
    clsname = 'NT' + digest.digest(list(fields.keys()))
    if clsname not in clscache:
        cls = clscache[clsname] = collections.namedtuple(clsname, list(fields.keys()))
    else:
        cls = clscache[clsname]
    return cls(**fields)


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
    st.complex_numbers(allow_nan=False),
    st.text(),
    st.binary(),
    st.booleans(),
]
key_strategies.append(dataclasses(st.one_of(*key_strategies), frozen=True))
key_strategies.append(namedtuples(st.one_of(*key_strategies)))


# Base values include all key strategies plus indigestible types like Call
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
        dataclasses(children, frozen=True),
        namedtuples(children),
    ),
    max_leaves=10,
)

st_data = st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.text(),
    st.binary(),
    st.booleans(),
    st.lists(st.integers()),
    st.tuples(st.integers(), st.text()),
    st.dictionaries(st.text(), st.integers()),
    st.builds(np.array, st.lists(st.integers())),
)

st_hex = st.text(min_size=64, max_size=64, alphabet="0123456789abcdef")

st_digested_calls = st.builds(
    Call,
    name=st.text(string.ascii_letters, min_size=1, max_size=10),
    arguments=st.dictionaries(
        st.text(string.ascii_letters + string.digits + "_", min_size=1, max_size=5),
        st_hex,
        max_size=6,
    ),
    metadata=st.builds(dict),
    module=st.one_of(st.none(), st.text(string.ascii_letters, min_size=1, max_size=10)),
    version=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    result=st.one_of(st.none(), st_hex),
)
