# Changelog

## 1.0.0 (2026-11-16)


### ⚠ BREAKING CHANGES

* **digest:** digesting numpy arrays, np.bool_, np.timedelta64 or pandas objects requires fleche-numpy / fleche-pandas (the fleche[numpy] and fleche[pandas] extras). A type with both __digest__ and an entry-point hook digests by __digest__. fleche._hashing is renamed fleche.hashing.

### Features

* **digest:** move numpy and pandas digests into sister packages ([#1058](https://github.com/pmrv/fleche/issues/1058)) ([4aaebce](https://github.com/pmrv/fleche/commit/4aaebcedfd19d398a082427d88bc135b423314e5))
