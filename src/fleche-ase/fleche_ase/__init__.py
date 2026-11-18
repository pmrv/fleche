"""fleche digest hooks for ASE objects.

Importing this package is all that is needed: :data:`digest_hooks` is published through
fleche's ``fleche`` entry point, so ``Atoms``, its constraints, ``Calculator``, ``VibrationsData``
and the ``ase.thermochemistry`` classes are digestible arguments of any cached function.

:data:`destructurers`, under the entry point ``destructure``, makes an ``Atoms``
without a live calculator a leaf of a destructuring store: inlined into its
parent like an ``int``.  A structure carrying a calculator stays a separate
entry, since the calculator is pickled with it.

A calculator this module cannot identify raises ``Indigestible`` rather than sharing a key
with another one; :func:`register_calculator` is how a project teaches it one.
"""

import hashlib
import os
import time
import weakref
from pathlib import Path

import numpy

from ase import Atoms
from ase.calculators.calculator import Calculator
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixConstraint
from ase.thermochemistry import AbstractMode, BaseThermoChem
from ase.vibrations import VibrationsData
from fleche.digest import Indigestible, digest, Digest

__all__ = ["atoms_digest", "calculator_digest", "constraint_digest", "vibrations_digest",
           "thermo_mode_digest", "thermochemistry_digest",
           "file_fingerprint", "register_calculator",
           "digest_hooks", "destructurers", "PARAMETER_FREE"]

#: Calculator class names for which an empty ``todict()`` is a complete identity rather than
#: a missing one. Names, not classes, so that nothing here imports a calculator backend.
#: Extend it through :func:`register_calculator` with ``extractor=None``.
PARAMETER_FREE = {"EMT", "LennardJones", "MorsePotential", "TIP3P", "TIP4P"}

_EXTRACTORS = {}
_FINGERPRINTS = {}
_MODEL_DIGEST = weakref.WeakKeyDictionary()
_BLOCK = 1 << 20
#: How deep :func:`_saved_model_tensors` follows TF's restore graph. GRACE's deepest tensor
#: sits at 3; the bound is there so a cyclic or pathological graph cannot hang a digest.
_TRACKABLE_DEPTH = 8
#: An mtime younger than this is not trusted to have settled.
_RACE_WINDOW_NS = 2_000_000_000


def _hash_file(path, m):
    """Feed a file's bytes into a hash, a megabyte at a time.

    Args:
        path: The file to read.
        m: A :mod:`hashlib` hash object, updated in place.
    """
    with open(path, "rb") as fh:
        while chunk := fh.read(_BLOCK):
            m.update(chunk)


def file_fingerprint(path, max_files: int = 20000) -> str:
    """SHA-256 of a file's bytes, or of a directory's ``(relative path, bytes)`` listing.

    A directory's own name is not part of the hash; the names of the files inside it are.
    Results are memoised on ``(realpath, size, mtime_ns)`` -- for a directory, on the file
    count, the summed size and the newest mtime -- so fingerprinting the same model twice
    costs one ``stat`` per file rather than a reread. A hash is memoised only once its mtime
    is older than two seconds: mtime granularity runs to a whole second on some NFS mounts,
    so a same-size rewrite inside one tick would leave the memo key unchanged and hand back
    the previous content's hash. Git skips its "racily clean" index entries for the same
    reason.

    Args:
        path: An existing file or directory. Symlinks are followed, so a link is hashed as
            its target's content; inside a directory, a broken link and anything that is
            neither a file nor a directory are skipped. An empty subdirectory leaves no
            trace either, so two trees differing only by one hash alike -- the one place
            this is coarser than the tree digest on fleche's ``temppath`` branch.
        max_files: Upper bound on the number of files under a directory.

    Returns:
        The hash, as 64 hexadecimal characters.

    Raises:
        FileNotFoundError: *path* does not exist.
        ValueError: *path* is neither a file nor a directory, or holds more than
            *max_files* files.
        OSError: the content cannot be read.

    On a digest path these become ``Indigestible`` instead -- see :func:`_path_identity` --
    so that an unreadable file makes fleche run the call uncached rather than fail it.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"cannot fingerprint {p}: does not exist")

    if p.is_file():
        st = p.stat()
        key, newest = (str(p), st.st_size, st.st_mtime_ns), st.st_mtime_ns

        def compute():
            m = hashlib.sha256()
            _hash_file(p, m)
            return m.hexdigest()
    elif p.is_dir():
        files = sorted(f for f in p.rglob("*") if f.is_file())
        if len(files) > max_files:
            raise ValueError(f"cannot fingerprint {p}: {len(files)} files exceeds "
                             f"max_files={max_files}")
        stats = [f.stat() for f in files]
        newest = max((s.st_mtime_ns for s in stats), default=0)
        key = (str(p), len(files), sum(s.st_size for s in stats), newest)

        def compute():
            m = hashlib.sha256()
            for f in files:
                m.update(str(f.relative_to(p)).encode())
                m.update(b"\0")
                _hash_file(f, m)
            return m.hexdigest()
    else:
        raise ValueError(f"cannot fingerprint {p}: neither a file nor a directory")

    hit = _FINGERPRINTS.get(key)
    if hit is not None:
        return hit
    value = compute()
    if time.time_ns() - newest > _RACE_WINDOW_NS:
        _FINGERPRINTS[key] = value
    return value


def _path_identity(path):
    """Identity of a file or directory on disk: its content, and a file's basename.

    Where a file lives is not part of it -- one potential reached through two paths is one
    potential, and a key carrying the path would miss on the copy -- but what it is called
    is. A directory's own name is dropped and the names inside it are kept. That is the
    shape fleche's ``temppath`` branch gives a :class:`pathlib.Path`; on fleche main a
    ``Path`` is still ``Indigestible``. The digests differ -- what matches is which two
    files count as the same file -- so deferring to upstream's hashing later moves no key.

    Args:
        path: The file or directory.

    Returns:
        A tuple fleche can digest.

    Raises:
        Indigestible: the path is missing, is neither a file nor a directory, or cannot be
            read. fleche then runs the call uncached rather than failing it.
    """
    p = Path(path)
    try:
        if p.is_dir():
            return ("DirectoryBlob", file_fingerprint(p))
        return ("FileBlob", p.name, file_fingerprint(p))
    except (OSError, ValueError) as e:
        raise Indigestible(p, f"cannot be read: {type(e).__name__}: {e}") from None


def register_calculator(class_name: str, extractor=None) -> None:
    """Teach :func:`calculator_digest` about a calculator class, by name.

    Args:
        class_name: The class's ``__name__``. Matching walks the MRO by name, so a subclass
            is covered by its parent's registration and this module imports no calculator
            backend.
        extractor: Takes the calculator and returns anything fleche can digest -- whatever
            tells two instances of the class apart. ``None`` instead adds the class to
            :data:`PARAMETER_FREE`, which says that an *empty* ``todict()`` is a complete
            answer for it. That is a claim about the empty case alone: a class whose
            ``todict()`` is non-empty is already identified by it and needs no registration
            either way.
    """
    if extractor is None:
        PARAMETER_FREE.add(class_name)
    else:
        _EXTRACTORS[class_name] = extractor


def _grace_runtime(calc):
    """Identity of a ``GRACERuntimeCalculator``: its model file, uq and dispersion.

    The npz is the whole model, weights included, so its contents identify it. uq and
    dispersion change the numbers rather than only the speed.

    Args:
        calc: The calculator.

    Returns:
        A mapping fleche can digest.

    Raises:
        Indigestible: the model file cannot be read.
    """
    return {"model": _path_identity(calc.model.path),
            "uq": bool(getattr(calc, "uq_enabled", False)),
            "dispersion": repr(getattr(calc, "dispersion", None))}


def _file_backed(calc, key: str, label: str = "potential"):
    """``todict()``, with *key* replaced by the identity of the file it names.

    pyace and EAM share a shape: the constructor parses a potential file into something in
    memory, and ase keeps the constructor argument in ``calc.parameters``, so ``todict()``
    still carries it. The file is identified by its contents, because refitting a potential
    in place would otherwise leave the key unchanged and every cached value stale. The same
    argument also accepts an object the caller built itself, which identifies nothing that
    survives the process, and that is refused. The rest of ``todict()`` rides along: for
    pyace, ``recursive``, ``fast_nl`` and the gamma bounds all change the numbers.

    Args:
        calc: The calculator.
        key: The ``todict()`` key that holds the potential file.
        label: The name that entry takes in the result.

    Returns:
        A mapping fleche can digest.

    Raises:
        Indigestible: ``todict()`` raised, *key* names no file on disk, or the file cannot
            be read.
    """
    try:
        params = dict(calc.todict())
    except Exception as e:                                             # noqa: BLE001
        raise _indigestible(calc, f"todict() raised {type(e).__name__}: {e}") from None
    value = params.pop(key, None)
    if isinstance(value, (str, os.PathLike)) and Path(value).exists():
        return {label: _path_identity(value), **params}
    raise _indigestible(
        calc, f"its {key} is an in-memory object, not a file this process can hash")


def _pyace(calc):
    """Identity of a ``PyACECalculator``: its basis-set file and the rest of ``todict()``."""
    return _file_backed(calc, "basis_set")


def _eam(calc):
    """Identity of an ``EAM``: its potential file and the rest of ``todict()``.

    ``EAM(potential='Cu.eam.alloy')`` keeps that path in ``parameters``. Built from arrays
    instead -- ``EAM(elements=['Al'], embedded_energy=..., ...)``, object arrays of ``scipy``
    splines -- it has no file, and nothing on it identifies the potential beyond this
    process, so it refuses.
    """
    return _file_backed(calc, "potential")


def _saved_model_tensors(model):
    """Every tensor hanging off a loaded SavedModel, as ``(dotted name, tensor)``, sorted.

    ``_trackable_children()`` is TF's own restore graph -- the structure that put the values
    back when the model was loaded -- so the walk reaches the weights, the element map and
    the ZBL table alike. It is private, so a TF that renames it yields nothing here and the
    caller refuses rather than keying on a quarter of a model. The walk skips objects it has
    already seen and stops at `_TRACKABLE_DEPTH`.

    Args:
        model: A ``tf.saved_model.load`` result.

    Returns:
        ``(dotted name, tensor)`` pairs, sorted by name.
    """
    found, seen = [], set()

    def walk(obj, path):
        if id(obj) in seen or len(path) > _TRACKABLE_DEPTH:
            return
        seen.add(id(obj))
        try:
            children = obj._trackable_children()
        except Exception:                                              # noqa: BLE001
            return
        for name, child in children.items():
            here = path + (str(name),)
            if hasattr(child, "numpy") and hasattr(child, "dtype"):
                found.append((".".join(here), child))
            walk(child, here)

    walk(model, ())
    return sorted(found, key=lambda kv: kv[0])


def _tensor_digest(model) -> Digest:
    """Digest of every tensor under *model*, one array at a time.

    ``fleche.digest`` does the arrays, including dtype and shape, and takes an object-dtype
    array by value rather than by the addresses ``tobytes()`` returns. The element map is
    such an array, which is why this package requires fleche 0.22.2.

    Args:
        model: A loaded SavedModel.

    Returns:
        The digest.

    Raises:
        Indigestible: no tensor is reachable through ``_trackable_children()``.
    """
    tensors = _saved_model_tensors(model)
    if not tensors:
        raise Indigestible(model, "no tensors are reachable through _trackable_children()")
    # One at a time: `tensor.numpy()` copies, and a GRACE model is ~150 MB of float64.
    return digest(tuple((name, digest(numpy.asarray(t.numpy()))) for name, t in tensors))


def _model_digest(model) -> Digest:
    """:func:`_tensor_digest`, memoised weakly so a dropped model does not keep its digest.

    Args:
        model: A loaded SavedModel. One that cannot be weak-referenced is digested afresh
            on every call.

    Returns:
        The digest.
    """
    try:
        hit = _MODEL_DIGEST.get(model)
    except TypeError:           # not weak-referenceable: correctness first, pay the rehash
        return _tensor_digest(model)
    if hit is None:
        hit = _MODEL_DIGEST[model] = _tensor_digest(model)
    return hit


def _tensorpotential(calc):
    """Identity of a ``TPCalculator``: its models' tensors and its inference settings.

    ``__init__`` replaces the path it was handed with ``TensorPotential.load_model(path)``
    and keeps only the result, so the path is on neither the calculator nor the loaded
    object, and ``todict()`` is ``{}``. The tensors are on it, and they identify the model
    more tightly than a path could: an fp32 re-export of one training run lands on its own
    key without anyone saying so.

    Args:
        calc: The calculator. Digesting one 9 M-parameter GRACE model takes about half a
            second, memoised per loaded model.

    Returns:
        A mapping fleche can digest.

    Raises:
        Indigestible: a model exposes no tensors.
    """
    models = [_model_digest(model) for model in calc.models]
    builder = getattr(calc, "geom_data_builder", None)
    return {
        "models": models,
        # a numpy scalar, so float() keeps the key off numpy's repr
        "cutoff": None if calc.cutoff is None else float(calc.cutoff),
        "fidelity": getattr(calc, "fidelity", None),
        "min_dist": getattr(calc, "min_dist", None),
        "extra_properties": getattr(calc, "extra_properties", None),
        # fp32 and fp64 inference off one model are different numbers.
        "float_dtype": str(getattr(builder, "float_dtype", None)),
    }


def _single_point(calc):
    """Identity of a ``SinglePointCalculator``: its stored results and their configuration.

    It *is* its results -- it cannot compute anything else. That is what separates it from a
    real calculator, whose cached ``results`` need not be digested because it would recompute
    the same numbers; this one raises instead, so two holding different energies behave
    differently and must not share a key. ``get_property`` also calls ``check_state`` and
    refuses once the atoms have moved away from the configuration it was built from, so that
    configuration is part of the identity. ``__init__`` stores ``atoms.copy()``, which
    carries no calculator of its own, so this nests exactly one level deep.

    Args:
        calc: The calculator. ``SinglePointDFTCalculator`` reaches this through the MRO, and
            its extras are observable through ``get_fermi_level()`` and friends.

    Returns:
        A mapping fleche can digest.
    """
    identity = {"results": calc.results, "atoms": atoms_digest(calc.atoms)}
    for attr in ("eFermi", "bz_kpts", "ibz_kpts", "bz2ibz"):
        if hasattr(calc, attr):
            identity[attr] = getattr(calc, attr)
    kpts = getattr(calc, "kpts", None)
    if kpts is not None:
        identity["kpts"] = [(k.weight, k.s, k.k, k.eps_n, k.f_n) for k in kpts]
    return identity


# Known model-backed calculators, keyed by class NAME so that importing this module pulls in
# no machine-learning stack. Anything else goes through register_calculator() at the call site.
register_calculator("GRACERuntimeCalculator", _grace_runtime)
register_calculator("PyACECalculator", _pyace)
register_calculator("TPCalculator", _tensorpotential)
register_calculator("SinglePointCalculator", _single_point)
register_calculator("EAM", _eam)


def _indigestible(value, why: str) -> Indigestible:
    """An ``Indigestible`` for *value*, carrying *why* and the way out.

    Args:
        value: The value that did not hash. It is ``args[0]``, as fleche raises it.
        why: What stopped it, as a sentence fragment.

    Returns:
        The exception, for the caller to raise.
    """
    return Indigestible(
        value,
        f"{why}; register_calculator({type(value).__name__!r}, extractor) "
        f"to say what identifies it.")


def constraint_digest(con) -> Digest:
    """Digest of an ASE constraint, through its ``todict()``.

    Registered as a hook, so a constraint digests the same on its own as inside an ``Atoms``.

    Args:
        con: The constraint.

    Returns:
        The digest.

    Raises:
        Indigestible: the constraint has no ``todict()``.
    """
    try:
        return digest(con.todict())
    except AttributeError:
        raise Indigestible(con) from None


def atoms_digest(structure: Atoms) -> Digest:
    """Digest of an ``Atoms``: cell, pbc and arrays, plus constraints, info and calculator.

    The last three enter the digest when they are there -- ``constraints`` and ``info`` when
    non-empty, ``structure.calc`` when one is attached -- because each of them influences
    what code holding the structure does with it. ASE's optimizers and ``Vibrations`` take
    the calculator off the structure rather than as an argument, and a constrained relaxation
    of a cell is not the unconstrained one.

    The measure is observable behaviour in ASE, not physical sameness: two cells alike but
    for an attached calculator answer ``get_potential_energy()`` differently, so they get two
    keys. That includes a structure read back from a trajectory, which ``ase.io.read`` hands
    a ``SinglePointCalculator``.

    Args:
        structure: The structure.

    Returns:
        The digest.

    Raises:
        Indigestible: a constraint has no ``todict()``, or the attached calculator cannot be
            identified -- in which case the structure's behaviour is not known either.
    """
    parts = [
        "Atoms" if type(structure) is Atoms else str(type(structure)),
        digest(structure.cell),
        digest(structure.pbc),
        digest(structure.arrays),
    ]
    # Absent constraints and info are not told apart from empty ones.
    if len(structure.constraints):
        parts.append(("constraints",
                      tuple(digest(c) for c in structure.constraints)))
    if structure.info:
        parts.append(("info", digest(structure.info)))
    if structure.calc is not None:
        try:
            parts.append(("calc", digest(structure.calc)))
        except Indigestible as exc:
            raise Indigestible(structure,
                               "its attached calculator cannot be digested",
                               *exc.args) from exc
    return digest(tuple(parts))


def vibrations_digest(vibrations: VibrationsData) -> Digest:
    """Digest of a ``VibrationsData``: its structure, its indices and its Hessian.

    Args:
        vibrations: The vibrational data.

    Returns:
        The digest.
    """
    return digest((
        "VibrationsData",
        digest(vibrations.get_atoms()),
        digest(vibrations.get_indices()),
        digest(vibrations.get_hessian_2d()),
    ))


def calculator_digest(calc: Calculator) -> Digest:
    """Digest of a calculator.

    Identity comes from the first of three that applies: an extractor registered for the
    class with :func:`register_calculator`, a non-empty ``todict()``, or an empty
    ``todict()`` on a class listed in :data:`PARAMETER_FREE`. Anything else raises, and
    fleche runs the call uncached with a warning.

    ``todict()`` alone is not enough because it is a serialisation contract for calculators
    whose parameters are their definition, and a model-backed calculator breaks it silently:
    ``GRACERuntimeCalculator.todict()`` returns ``{}`` for a 75 MB model, and an empty dict
    is both a valid answer and what no answer looks like. Hence the registry, and hence the
    refusal -- a slow run is recoverable, a cache hit for a different model is not.

    Args:
        calc: The calculator.

    Returns:
        The digest.

    Raises:
        Indigestible: ``todict()`` raised, or nothing identifies the calculator.
    """
    for cls in type(calc).__mro__:
        if cls.__name__ in _EXTRACTORS:
            return digest((cls.__name__, "extractor", _EXTRACTORS[cls.__name__](calc)))

    try:
        params = calc.todict()
    except Exception as e:                                           # noqa: BLE001
        raise _indigestible(calc, f"todict() raised {type(e).__name__}: {e}") from None

    if params:
        return digest((type(calc).__name__, "todict", params))

    if any(cls.__name__ in PARAMETER_FREE for cls in type(calc).__mro__):
        return digest((type(calc).__name__, "parameter-free"))

    raise _indigestible(calc, "todict() is empty and nothing identifies it")


def thermo_mode_digest(mode: AbstractMode) -> Digest:
    """Digest of a thermochemistry mode: its class and its attributes.

    Args:
        mode: The mode.

    Returns:
        The digest.
    """
    return digest((
        type(mode).__name__,
        vars(mode),
    ))


def thermochemistry_digest(thermo: BaseThermoChem) -> Digest:
    """Digest of a thermochemistry object: its class and its attributes.

    Args:
        thermo: The thermochemistry object.

    Returns:
        The digest.
    """
    return digest((
        type(thermo).__name__,
        vars(thermo),
    ))


digest_hooks = [
        (Atoms, atoms_digest),
        (FixConstraint, constraint_digest),
        (VibrationsData, vibrations_digest),
        (Calculator, calculator_digest),
        (AbstractMode, thermo_mode_digest),
        (BaseThermoChem, thermochemistry_digest),
]


def _leaf(intern, value):
    """Destructurer for an atomic value: depth 0, inlined like an ``int``."""
    return value, 0


def _atoms_is_big(value, level: int) -> bool:
    # The per-atom arrays are where an Atoms' size grows; cell, pbc and info are small.
    return sum(a.nbytes for a in value.arrays.values()) >= 1 << level


def _is_light_atoms(value) -> bool:
    # An attached calculator is pickled with the structure and can be a whole model,
    # so only a structure without one, or with stored results only, is inlined.
    return isinstance(value, Atoms) and (
        value.calc is None or isinstance(value.calc, SinglePointCalculator)
    )


#: The destructurers fleche loads from this package's ``fleche``/``destructure`` entry point:
#: an ``Atoms`` without a live calculator is a leaf, inlined into its parent like an ``int``.
destructurers = [(_is_light_atoms, _leaf, _atoms_is_big)]

