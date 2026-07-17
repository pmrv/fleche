# Changelog

## [0.20.0](https://github.com/pmrv/fleche/compare/0.19.2...0.20.0) (2026-07-17)


### Features

* **storage:** default prefix_length=2 and remaining_depth=1 ([#749](https://github.com/pmrv/fleche/issues/749)) ([7be2504](https://github.com/pmrv/fleche/commit/7be25041a6088e1002bd3c10d7c29a4b95be514b))
* **storage:** refix() re-sharding and prefix-length layout validation for HDF5 backend ([#748](https://github.com/pmrv/fleche/issues/748)) ([efb1c84](https://github.com/pmrv/fleche/commit/efb1c84d66ad05faaaa6ca6224eb66e4cb6e64ec))
* **storage:** support fixed prefix-length multi-bagging for HDF5 backend ([#746](https://github.com/pmrv/fleche/issues/746)) ([7eb272a](https://github.com/pmrv/fleche/commit/7eb272a5590940aaf84d3ed28eba2a50f434c64a))

## [0.19.2](https://github.com/pmrv/fleche/compare/0.19.1...0.19.2) (2026-07-06)


### Bug Fixes

* don't double-bind an already-bound BoundWrapper in wrap_executor.submit ([#724](https://github.com/pmrv/fleche/issues/724)) ([21f7ce3](https://github.com/pmrv/fleche/commit/21f7ce332d04729c96f5690bcd5ed7faafd1a5b4))

## [0.19.1](https://github.com/pmrv/fleche/compare/0.19.0...0.19.1) (2026-07-06)


### Bug Fixes

* always bind non-fleche callables in wrap_executor.submit ([#722](https://github.com/pmrv/fleche/issues/722)) ([3a8e8c2](https://github.com/pmrv/fleche/commit/3a8e8c2f8c7964302889a31d0b287e931136b604))

## [0.19.0](https://github.com/pmrv/fleche/compare/0.18.0...0.19.0) (2026-07-06)


### Features

* **config:** add [default] root tag to stop upward config merge ([#719](https://github.com/pmrv/fleche/issues/719)) ([7cd34df](https://github.com/pmrv/fleche/commit/7cd34df4e9cdfc46f7561eb03cb9fa1b55a74e34))

## [0.18.0](https://github.com/pmrv/fleche/compare/0.17.0...0.18.0) (2026-07-01)


### Features

* add CachePool, a read-only collection of caches ([#689](https://github.com/pmrv/fleche/issues/689)) ([9cbcfbe](https://github.com/pmrv/fleche/commit/9cbcfbee99b76b708c394a841fececd656f39f33))
* **storage:** guard MemoryBackend subclasses against silent __hash__ loss ([#683](https://github.com/pmrv/fleche/issues/683)) ([f8ce0c8](https://github.com/pmrv/fleche/commit/f8ce0c8c9d180bfbba92e391792ab9105aebb7d7))


### Bug Fixes

* **digest:** hash pandas DataFrame/Series/Index by content ([#675](https://github.com/pmrv/fleche/issues/675)) ([0e95163](https://github.com/pmrv/fleche/commit/0e95163bb8bda1bb9f1e3df2a6d5841f0c259bde))

## [0.17.0](https://github.com/pmrv/fleche/compare/0.16.0...0.17.0) (2026-06-21)


### Features

* **cache:** BaseCache(OperationContext) + PerKeyLockMixin on Cache (steps 4-5 of [#569](https://github.com/pmrv/fleche/issues/569)) ([#622](https://github.com/pmrv/fleche/issues/622)) ([095432d](https://github.com/pmrv/fleche/commit/095432d141925204eea951f4de2173d5558d8aa1))


### Bug Fixes

* **benchmarks:** restore __hash__ on raw Memory subclasses ([#632](https://github.com/pmrv/fleche/issues/632)) ([17b681b](https://github.com/pmrv/fleche/commit/17b681b0c5bcb38471a420c65c1d5cacc20e50d0))
* **caches:** make redigest() save+evict atomic per key ([#451](https://github.com/pmrv/fleche/issues/451)) ([#631](https://github.com/pmrv/fleche/issues/631)) ([d22e882](https://github.com/pmrv/fleche/commit/d22e882365220b262a892f679def6d78480d4132))
* **caches:** serialize CacheStack.load() auto-transfer to base cache ([#629](https://github.com/pmrv/fleche/issues/629)) ([f70f72c](https://github.com/pmrv/fleche/commit/f70f72c37a799c307aee5c7c57810063088cdf2d))
* **digest:** handle type objects without raising Indigestible ([#651](https://github.com/pmrv/fleche/issues/651)) ([55a8d9a](https://github.com/pmrv/fleche/commit/55a8d9a32fbbc4ca546dcc3413949cd62699c68b))
* **query:** make transfer check-then-save atomic via target per-key lock ([#630](https://github.com/pmrv/fleche/issues/630)) ([5f0d05f](https://github.com/pmrv/fleche/commit/5f0d05f255680c1b288aaf4e675baeef5a3f17a7))
* **tests:** allow byte-distinct NaNs to digest differently ([#666](https://github.com/pmrv/fleche/issues/666)) ([973dbd0](https://github.com/pmrv/fleche/commit/973dbd0bdec327d1d3a6f9699100b1c20d9da610))
* **wrapper:** narrow _in_flight to the cache-write gap, not full computation ([#627](https://github.com/pmrv/fleche/issues/627)) ([8b0abaa](https://github.com/pmrv/fleche/commit/8b0abaa922f3135846873158e7809047f18ad2cc))


### Performance Improvements

* avoid double H5Bag file open on load ([#616](https://github.com/pmrv/fleche/issues/616)) ([8fbcae4](https://github.com/pmrv/fleche/commit/8fbcae4a5efe35285d0454a7bdd7c8a2fc3f49f8))

## [0.16.0](https://github.com/pmrv/fleche/compare/0.15.0...0.16.0) (2026-05-30)


### Features

* add LazyCall.to_digested_call() — public inverse of DigestedCall.fetch() ([#599](https://github.com/pmrv/fleche/issues/599)) ([a4e06f8](https://github.com/pmrv/fleche/commit/a4e06f8fbf88d44b84aaf5586b6b7a3efdbdb34c))
* **storage:** add `intent` parameter to `_operation_context` (step 1 of [#569](https://github.com/pmrv/fleche/issues/569)) ([#601](https://github.com/pmrv/fleche/issues/601)) ([6562c7f](https://github.com/pmrv/fleche/commit/6562c7f9cc8ba9efa4198ac52af4aeea5fcf4672))

## [0.15.0](https://github.com/pmrv/fleche/compare/0.14.0...0.15.0) (2026-05-28)


### Features

* **config:** make 'default' a special name resolving to the configured default cache ([#590](https://github.com/pmrv/fleche/issues/590)) ([d6aa58f](https://github.com/pmrv/fleche/commit/d6aa58fe97cb1cd4ebc650518fbf74cde8c88c0c))
* **remote:** add workdir option to SshCache ([b66f976](https://github.com/pmrv/fleche/commit/b66f9764d2855fadc582cae3b42447570ecc00ee))
* **remote:** SshCache for sharing fleche caches across machines ([8c6ef49](https://github.com/pmrv/fleche/commit/8c6ef49c9b9c86cec4ffeed08d789bc527afb1f2))


### Bug Fixes

* **config:** intern the default cache under None so it is reused ([a3a6c74](https://github.com/pmrv/fleche/commit/a3a6c74356bf6b3658b866c25879210e8f5ad824))
* **types:** resolve latent ty 0.0.40 errors surfaced by this branch ([9261951](https://github.com/pmrv/fleche/commit/926195124a7db1c7b8b59df0a34bd404591ac482))

## [0.14.0](https://github.com/pmrv/fleche/compare/0.13.1...0.14.0) (2026-05-27)


### Features

* **config:** walk CWD→HOME and merge fleche.toml files ([#553](https://github.com/pmrv/fleche/issues/553)) ([c3f3d20](https://github.com/pmrv/fleche/commit/c3f3d2014ad3c78e4af5503f8ad35e4fb8eeb99a))
* **metadata:** add Environment and Git metadata ([#565](https://github.com/pmrv/fleche/issues/565)) ([c671895](https://github.com/pmrv/fleche/commit/c67189557293558d9f29dcdcaae926f88e3dbcf0))
* **metadata:** add Version metadata capturing fleche version ([a813391](https://github.com/pmrv/fleche/commit/a813391c242eab32c68c9dc7c91c1696de0675a7))
* **metadata:** also record python_version in Environment ([e44a759](https://github.com/pmrv/fleche/commit/e44a7599a78b4cf74ce900103b35b775a03d6322))
* **query:** add QueryIterator.transfer for replaying matches into a target cache ([#566](https://github.com/pmrv/fleche/issues/566)) ([b3d60dc](https://github.com/pmrv/fleche/commit/b3d60dcb57422b212c455c060286791748a0ff24))
* **query:** shrink lookup keys in QueryIterator.table by default ([ce44ebb](https://github.com/pmrv/fleche/commit/ce44ebb76866bef8389bbfe40c93add44d777d25))


### Bug Fixes

* **call:** fall back to permissive signature for un-introspectable builtins ([#559](https://github.com/pmrv/fleche/issues/559)) ([d7bd30d](https://github.com/pmrv/fleche/commit/d7bd30d336080feacdc9355348bd27488c3f0149))
* **config:** default XDG_CONFIG_HOME to ~/.config per spec ([56fb9a9](https://github.com/pmrv/fleche/commit/56fb9a99f424bd79ff0a49e9723fc4e9b013a14d))
* rename put() parameter call→value to match parent class signature ([#546](https://github.com/pmrv/fleche/issues/546)) ([1f8b822](https://github.com/pmrv/fleche/commit/1f8b82288ff8234502c77edd61df0023b0663525))
* **sql:** handle legacy INTEGER version column on load ([#578](https://github.com/pmrv/fleche/issues/578)) ([1040f0d](https://github.com/pmrv/fleche/commit/1040f0d7cdc188de0af161cd18bcc2d2930bf15e))
* **types:** satisfy ty after variadic shrink ([fe7245a](https://github.com/pmrv/fleche/commit/fe7245a35674f81f983bc28a15586ce580c399a9))


### Performance Improvements

* **caches:** batch shrink via shrink(*keys) variadic API ([c9e64c4](https://github.com/pmrv/fleche/commit/c9e64c4aea00a54c9e86752ba3a291784dda5786))
* **sql:** replace ORM-materialised _evict with bulk DELETE ([#535](https://github.com/pmrv/fleche/issues/535)) ([e0eca8f](https://github.com/pmrv/fleche/commit/e0eca8f3e83a37a4dfeddb588605c8a84fc0f61b))
