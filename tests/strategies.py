from hypothesis import strategies as st
from dataclasses import make_dataclass
import string
import keyword
from fleche.call import Call


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
