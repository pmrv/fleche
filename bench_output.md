
<details open>
<summary><b>Significant Changes (>5%)</b></summary>

<div style="overflow-x: auto;">

| benchmark | name | storage | Old Time | New Time | % Change |
| --- | --- | --- | --- | --- | --- |
| integration_miss | Memory+Sqlite(:memory:)/compute_heavy |  | 2.3 ms | 3.9 ms | 🔴 +69.6% |
| integration_miss | Pickle+Sql/compute_heavy |  | 5 ms | 8.4 ms | 🔴 +68.0% |
| storage_save |  | CloudpickleFile_Signed/nested_structures | 320 µs | 510 µs | 🔴 +59.4% |
| storage_save |  | DillFile/nested_structures | 330 µs | 520 µs | 🔴 +57.6% |
| storage_save |  | PickleFile/small_strings | 280 µs | 440 µs | 🔴 +57.1% |
| storage_save |  | DillFile_Signed/nested_structures | 350 µs | 540 µs | 🔴 +54.3% |
| integration_miss | H5+Sql/lightweight |  | 7.8 ms | 12 ms | 🔴 +53.8% |
| integration_miss | Pickle+Sql/lightweight |  | 5 ms | 7.6 ms | 🔴 +52.0% |
| integration_miss | H5+Sql/compute_heavy |  | 8.2 ms | 12 ms | 🔴 +46.3% |
| storage_save |  | CloudpickleFile/small_strings | 290 µs | 420 µs | 🔴 +44.8% |
| storage_save |  | PickleFile_Signed/small_strings | 300 µs | 430 µs | 🔴 +43.3% |
| storage_save |  | DillFile_Signed/small_strings | 350 µs | 490 µs | 🔴 +40.0% |
| storage_save |  | DillFile/small_strings | 330 µs | 460 µs | 🔴 +39.4% |
| integration_contains_hit | Memory+Sqlite(:memory:)/data_heavy |  | 1.3 ms | 1.8 ms | 🔴 +38.5% |
| storage_save |  | CloudpickleFile/numpy_arrays | 470 µs | 640 µs | 🔴 +36.2% |
| integration_contains_hit | H5+Sql/lightweight |  | 1.4 ms | 1.9 ms | 🔴 +35.7% |
| integration_miss | H5+Sql/data_heavy |  | 6.2 ms | 8.4 ms | 🔴 +35.5% |
| integration_miss | Memory/compute_heavy |  | 570 µs | 770 µs | 🔴 +35.1% |
| storage_save |  | PickleFile/numpy_arrays | 440 µs | 590 µs | 🔴 +34.1% |
| integration_hit | H5+Sql/compute_heavy |  | 6.2 ms | 8.3 ms | 🔴 +33.9% |
| integration_contains_miss | Memory+Sqlite(:memory:)/data_heavy |  | 630 µs | 840 µs | 🔴 +33.3% |
| integration_hit | H5+Sql/lightweight |  | 6.1 ms | 8.1 ms | 🔴 +32.8% |
| storage_save |  | DillFile_Signed/numpy_arrays | 910 µs | 1.2 ms | 🔴 +31.9% |
| storage_save |  | DillFile/numpy_arrays | 670 µs | 880 µs | 🔴 +31.3% |
| storage_contains_hit |  | DillFile/nested_structures | 85 µs | 110 µs | 🔴 +29.4% |
| storage_load |  | DillFile/nested_structures | 85 µs | 110 µs | 🔴 +29.4% |
| integration_hit | Memory+Sqlite(:memory:)/data_heavy |  | 1.4 ms | 1.8 ms | 🔴 +28.6% |
| integration_contains_hit | Pickle+Sql/lightweight |  | 1.4 ms | 1.8 ms | 🔴 +28.6% |
| integration_hit | Memory+Sqlite(:memory:)/compute_heavy |  | 1.4 ms | 1.8 ms | 🔴 +28.6% |
| integration_contains_miss | Pickle+Sql/lightweight |  | 650 µs | 830 µs | 🔴 +27.7% |
| integration_hit | H5+Sql/data_heavy |  | 6.2 ms | 7.9 ms | 🔴 +27.4% |
| storage_contains_hit |  | CloudpickleFile/nested_structures | 78 µs | 98 µs | 🔴 +25.6% |
| storage_load |  | CloudpickleFile_Signed/nested_structures | 88 µs | 110 µs | 🔴 +25.0% |
| storage_load |  | CloudpickleFile/nested_structures | 79 µs | 98 µs | 🔴 +24.1% |
| integration_miss | Memory/lightweight |  | 420 µs | 520 µs | 🔴 +23.8% |
| storage_save |  | CloudpickleFile_Signed/numpy_arrays | 720 µs | 890 µs | 🔴 +23.6% |
| integration_hit | Pickle+Sql/compute_heavy |  | 1.7 ms | 2.1 ms | 🔴 +23.5% |
| integration_miss | Pickle+Sql/data_heavy |  | 1.7 ms | 2.1 ms | 🔴 +23.5% |
| integration_miss | Memory+Sqlite(:memory:)/data_heavy |  | 1.3 ms | 1.6 ms | 🔴 +23.1% |
| storage_evict |  | Memory/small_strings | 530 ns | 650 ns | 🔴 +22.6% |
| integration_contains_miss | Pickle+Sql/data_heavy |  | 670 µs | 820 µs | 🔴 +22.4% |
| integration_contains_miss | Pickle+Sql/compute_heavy |  | 670 µs | 820 µs | 🔴 +22.4% |
| integration_hit | Pickle+Sql/data_heavy |  | 1.8 ms | 2.2 ms | 🔴 +22.2% |
| integration_contains_miss | Memory/data_heavy |  | 180 µs | 220 µs | 🔴 +22.2% |
| storage_contains_hit |  | CloudpickleFile_Signed/nested_structures | 90 µs | 110 µs | 🔴 +22.2% |
| integration_contains_miss | Memory/lightweight |  | 180 µs | 220 µs | 🔴 +22.2% |
| integration_contains_miss | Memory+Sqlite(:memory:)/compute_heavy |  | 630 µs | 770 µs | 🔴 +22.2% |
| integration_hit | Memory/lightweight |  | 230 µs | 280 µs | 🔴 +21.7% |
| integration_contains_hit | Memory/lightweight |  | 230 µs | 280 µs | 🔴 +21.7% |
| storage_contains_miss |  | DillFile/nested_structures | 60 µs | 73 µs | 🔴 +21.7% |
| integration_contains_hit | Pickle+Sql/data_heavy |  | 1.4 ms | 1.7 ms | 🔴 +21.4% |
| storage_save |  | CloudpickleFile/nested_structures | 380 µs | 460 µs | 🔴 +21.1% |
| integration_hit | Memory/compute_heavy |  | 240 µs | 290 µs | 🔴 +20.8% |
| storage_evict |  | CloudpickleFile_Signed/numpy_arrays | 79 µs | 95 µs | 🔴 +20.3% |
| storage_contains_hit |  | Memory/small_strings | 1 µs | 1.2 µs | 🔴 +20.0% |
| storage_contains_miss |  | DillFile/numpy_arrays | 60 µs | 72 µs | 🔴 +20.0% |
| storage_contains_miss |  | CloudpickleFile/nested_structures | 60 µs | 72 µs | 🔴 +20.0% |
| storage_load |  | DillFile_Signed/nested_structures | 100 µs | 120 µs | 🔴 +20.0% |
| storage_contains_miss |  | CloudpickleFile_Signed/nested_structures | 60 µs | 72 µs | 🔴 +20.0% |
| integration_contains_miss | H5+Sql/lightweight |  | 660 µs | 790 µs | 🔴 +19.7% |
| storage_save |  | PickleFile_Signed/numpy_arrays | 690 µs | 820 µs | 🔴 +18.8% |
| storage_contains_hit |  | CloudpickleFile/numpy_arrays | 110 µs | 130 µs | 🔴 +18.2% |
| storage_save |  | CloudpickleFile_Signed/small_strings | 390 µs | 460 µs | 🔴 +17.9% |
| integration_contains_miss | H5+Sql/data_heavy |  | 670 µs | 790 µs | 🔴 +17.9% |
| digest | Nested (Random Hypothesis) |  | 4.5 ms | 5.3 ms | 🔴 +17.8% |
| integration_hit | Pickle+Sql/lightweight |  | 1.7 ms | 2 ms | 🔴 +17.6% |
| integration_contains_miss | Memory+Sqlite(:memory:)/lightweight |  | 630 µs | 740 µs | 🔴 +17.5% |
| integration_miss | Memory+Sqlite(:memory:)/lightweight |  | 2.3 ms | 2.7 ms | 🔴 +17.4% |
| integration_contains_hit | Memory/data_heavy |  | 230 µs | 270 µs | 🔴 +17.4% |
| storage_evict |  | DillFile_Signed/nested_structures | 47 µs | 55 µs | 🔴 +17.0% |
| storage_evict |  | DillFile/nested_structures | 47 µs | 55 µs | 🔴 +17.0% |
| digest | Numpy (integers, len>100) |  | 12 ms | 14 ms | 🔴 +16.7% |
| storage_evict |  | SqlFile/calls | 3 ms | 3.5 ms | 🔴 +16.7% |
| storage_load |  | DillFile/numpy_arrays | 120 µs | 140 µs | 🔴 +16.7% |
| storage_contains_hit |  | DillFile/numpy_arrays | 120 µs | 140 µs | 🔴 +16.7% |
| integration_contains_miss | H5+Sql/compute_heavy |  | 680 µs | 790 µs | 🔴 +16.2% |
| integration_hit | Memory/data_heavy |  | 250 µs | 290 µs | 🔴 +16.0% |
| storage_evict |  | CloudpickleFile/numpy_arrays | 78 µs | 90 µs | 🔴 +15.4% |
| integration_contains_miss | Memory/compute_heavy |  | 200 µs | 230 µs | 🔴 +15.0% |
| storage_contains_miss |  | CloudpickleFile/numpy_arrays | 60 µs | 69 µs | 🔴 +15.0% |
| storage_evict |  | CloudpickleFile_Signed/nested_structures | 48 µs | 55 µs | 🔴 +14.6% |
| storage_evict |  | BagOfHoldingH5File/numpy_arrays | 76 µs | 87 µs | 🔴 +14.5% |
| integration_contains_hit | Memory+Sqlite(:memory:)/compute_heavy |  | 1.4 ms | 1.6 ms | 🔴 +14.3% |
| storage_load |  | CloudpickleFile_Signed/numpy_arrays | 350 µs | 400 µs | 🔴 +14.3% |
| storage_evict |  | SqlMemory/calls | 1.4 ms | 1.6 ms | 🔴 +14.3% |
| integration_hit | Memory+Sqlite(:memory:)/lightweight |  | 1.4 ms | 1.6 ms | 🔴 +14.3% |
| integration_contains_hit | Memory+Sqlite(:memory:)/lightweight |  | 1.4 ms | 1.6 ms | 🔴 +14.3% |
| storage_load |  | DillFile_Signed/numpy_arrays | 360 µs | 410 µs | 🔴 +13.9% |
| storage_evict |  | DillFile/numpy_arrays | 82 µs | 93 µs | 🔴 +13.4% |
| storage_contains_miss |  | DillFile_Signed/nested_structures | 60 µs | 68 µs | 🔴 +13.3% |
| integration_contains_hit | H5+Sql/compute_heavy |  | 1.5 ms | 1.7 ms | 🔴 +13.3% |
| integration_contains_hit | H5+Sql/data_heavy |  | 1.5 ms | 1.7 ms | 🔴 +13.3% |
| integration_contains_hit | Pickle+Sql/compute_heavy |  | 1.5 ms | 1.7 ms | 🔴 +13.3% |
| storage_evict |  | PickleFile_Signed/numpy_arrays | 77 µs | 87 µs | 🔴 +13.0% |
| integration_contains_hit | Memory/compute_heavy |  | 240 µs | 270 µs | 🔴 +12.5% |
| storage_save |  | BagOfHoldingH5File/numpy_arrays | 2.5 ms | 2.8 ms | 🔴 +12.0% |
| storage_load |  | BagOfHoldingH5File/numpy_arrays | 2.5 ms | 2.8 ms | 🔴 +12.0% |
| digest | Numpy (integers, len<100) |  | 1.7 ms | 1.9 ms | 🔴 +11.8% |
| storage_load |  | PickleFile_Signed/numpy_arrays | 340 µs | 380 µs | 🔴 +11.8% |
| storage_evict |  | Memory/nested_structures | 710 ns | 630 ns | 🟢 -11.3% |
| storage_contains_miss |  | BagOfHoldingH5File/numpy_arrays | 180 µs | 200 µs | 🔴 +11.1% |
| storage_evict |  | BagOfHoldingH5File/small_strings | 64 µs | 71 µs | 🔴 +10.9% |
| storage_contains_miss |  | DillFile_Signed/numpy_arrays | 60 µs | 66 µs | 🔴 +10.0% |
| storage_contains_hit |  | DillFile_Signed/nested_structures | 100 µs | 110 µs | 🔴 +10.0% |
| storage_contains_miss |  | SqlMemory/calls | 400 µs | 440 µs | 🔴 +10.0% |
| storage_contains_miss |  | PickleFile_Signed/numpy_arrays | 64 µs | 70 µs | 🔴 +9.4% |
| storage_load |  | CloudpickleFile/numpy_arrays | 110 µs | 120 µs | 🔴 +9.1% |
| storage_save |  | SqlMemory/calls | 3.3 ms | 3.6 ms | 🔴 +9.1% |
| storage_contains_hit |  | SqlMemory/calls | 1.1 ms | 1.2 ms | 🔴 +9.1% |
| storage_load |  | SqlMemory/calls | 1.1 ms | 1.2 ms | 🔴 +9.1% |
| storage_contains_hit |  | CloudpickleFile_Signed/numpy_arrays | 340 µs | 370 µs | 🔴 +8.8% |
| storage_contains_hit |  | SqlFile/calls | 1.2 ms | 1.3 ms | 🔴 +8.3% |
| storage_load |  | SqlFile/calls | 1.2 ms | 1.3 ms | 🔴 +8.3% |
| storage_contains_hit |  | DillFile_Signed/numpy_arrays | 370 µs | 400 µs | 🔴 +8.1% |
| storage_contains_hit |  | BagOfHoldingH5File/numpy_arrays | 2.5 ms | 2.7 ms | 🔴 +8.0% |
| storage_evict |  | CloudpickleFile/nested_structures | 52 µs | 56 µs | 🔴 +7.7% |
| storage_contains_hit |  | PickleFile/small_strings | 78 µs | 84 µs | 🔴 +7.7% |
| storage_evict |  | DillFile_Signed/numpy_arrays | 78 µs | 84 µs | 🔴 +7.7% |
| storage_evict |  | CloudpickleFile/small_strings | 67 µs | 72 µs | 🔴 +7.5% |
| storage_evict |  | DillFile/small_strings | 68 µs | 73 µs | 🔴 +7.4% |
| storage_contains_miss |  | Memory/small_strings | 1.4 µs | 1.5 µs | 🔴 +7.1% |
| storage_contains_miss |  | Memory/numpy_arrays | 1.4 µs | 1.5 µs | 🔴 +7.1% |
| storage_contains_miss |  | Memory/nested_structures | 1.4 µs | 1.5 µs | 🔴 +7.1% |
| storage_load |  | CloudpickleFile_Signed/small_strings | 87 µs | 93 µs | 🔴 +6.9% |
| storage_contains_miss |  | CloudpickleFile_Signed/numpy_arrays | 60 µs | 64 µs | 🔴 +6.7% |
| storage_contains_miss |  | PickleFile/numpy_arrays | 60 µs | 64 µs | 🔴 +6.7% |
| storage_evict |  | Memory/numpy_arrays | 940 ns | 1 µs | 🔴 +6.4% |
| storage_save |  | BagOfHoldingH5File/small_strings | 1.7 ms | 1.8 ms | 🔴 +5.9% |
| storage_save |  | Memory/small_strings | 700 ns | 740 ns | 🔴 +5.7% |
| storage_contains_hit |  | PickleFile_Signed/numpy_arrays | 350 µs | 370 µs | 🔴 +5.7% |
| integration_miss | Memory/data_heavy |  | 180 µs | 190 µs | 🔴 +5.6% |
| digest | List (integers, len>100) |  | 56 ms | 53 ms | 🟢 -5.4% |
| digest | List (integers, len<100) |  | 1.9 ms | 2 ms | 🔴 +5.3% |
| digest | Float |  | 580 µs | 550 µs | 🟢 -5.2% |

</div>
</details>

<details>
<summary><b>Digest Benchmarks</b></summary>

<div style="overflow-x: auto;">

| name | digest |
| --- | --- |
| List (integers, len>100) | 🟥 53 ms |
| Numpy (integers, len>100) | 🟩 14 ms |
| Nested (Random Hypothesis) | 🟩 5.3 ms |
| Dict (small) | 🟩 4.2 ms |
| List (integers, len<100) | 🟩 2 ms |
| Numpy (integers, len<100) | 🟩 1.9 ms |
| String (len>100) | 🟩 560 µs |
| Float | 🟩 550 µs |
| None | 🟩 350 µs |
| Integer | 🟩 320 µs |
| String (len<100) | 🟩 280 µs |


</div>
</details>

<details>
<summary><b>Value Storage Benchmarks</b></summary>

<div style="overflow-x: auto;">

<h4>Workload: numpy_arrays</h4>

| storage | contains_hit | contains_miss | evict | load | save |
| --- | --- | --- | --- | --- | --- |
| 🟠 BagOfHoldingH5File | 🟥 2.7 ms | 🟥 200 µs | 🟥 87 µs | 🟥 2.8 ms | 🟥 2.8 ms |
| 🟡 DillFile_Signed | 🟩 400 µs | 🟩 66 µs | 🟧 84 µs | 🟩 410 µs | 🟨 1.2 ms |
| 🔵 CloudpickleFile_Signed | 🟩 370 µs | 🟩 64 µs | 🟥 95 µs | 🟩 400 µs | 🟩 890 µs |
| 🟢 PickleFile_Signed | 🟩 370 µs | 🟨 70 µs | 🟥 87 µs | 🟩 380 µs | 🟩 820 µs |
| 🟡 DillFile | 🟩 140 µs | 🟨 72 µs | 🟥 93 µs | 🟩 140 µs | 🟩 880 µs |
| 🔵 CloudpickleFile | 🟩 130 µs | 🟨 69 µs | 🟥 90 µs | 🟩 120 µs | 🟩 640 µs |
| 🟢 PickleFile | 🟩 110 µs | 🟩 64 µs | 🟧 82 µs | 🟩 110 µs | 🟩 590 µs |
| 🟣 Memory | 🟩 6.6 µs | 🟩 1.5 µs | 🟩 1 µs | 🟩 6.9 µs | 🟩 6 µs |


<h4>Workload: small_strings</h4>

| storage | contains_hit | contains_miss | evict | load | save |
| --- | --- | --- | --- | --- | --- |
| 🟠 BagOfHoldingH5File | 🟥 2.4 ms | 🟥 180 µs | 🟥 71 µs | 🟥 2.4 ms | 🟥 1.8 ms |
| 🟡 DillFile_Signed | 🟩 100 µs | 🟩 59 µs | 🟥 70 µs | 🟩 100 µs | 🟩 490 µs |
| 🔵 CloudpickleFile_Signed | 🟩 90 µs | 🟩 59 µs | 🟥 68 µs | 🟩 93 µs | 🟩 460 µs |
| 🟡 DillFile | 🟩 87 µs | 🟩 60 µs | 🟥 73 µs | 🟩 87 µs | 🟩 460 µs |
| 🟢 PickleFile_Signed | 🟩 90 µs | 🟩 59 µs | 🟥 68 µs | 🟩 88 µs | 🟩 430 µs |
| 🟢 PickleFile | 🟩 84 µs | 🟩 59 µs | 🟥 69 µs | 🟩 77 µs | 🟩 440 µs |
| 🔵 CloudpickleFile | 🟩 77 µs | 🟨 63 µs | 🟥 72 µs | 🟩 77 µs | 🟩 420 µs |
| 🟣 Memory | 🟩 1.2 µs | 🟩 1.5 µs | 🟩 650 ns | 🟩 1 µs | 🟩 740 ns |


<h4>Workload: nested_structures</h4>

| storage | contains_hit | contains_miss | evict | load | save |
| --- | --- | --- | --- | --- | --- |
| 🟡 DillFile_Signed | 🟥 110 µs | 🟥 68 µs | 🟥 55 µs | 🟥 120 µs | 🟥 540 µs |
| 🟡 DillFile | 🟥 110 µs | 🟥 73 µs | 🟥 55 µs | 🟥 110 µs | 🟥 520 µs |
| 🔵 CloudpickleFile_Signed | 🟥 110 µs | 🟥 72 µs | 🟥 55 µs | 🟥 110 µs | 🟥 510 µs |
| 🔵 CloudpickleFile | 🟧 98 µs | 🟥 72 µs | 🟥 56 µs | 🟧 98 µs | 🟧 460 µs |
| 🟣 Memory | 🟩 1.1 µs | 🟩 1.5 µs | 🟩 630 ns | 🟩 1.1 µs | 🟩 730 ns |


</div>
</details>

<details>
<summary><b>Call Storage Benchmarks</b></summary>

<div style="overflow-x: auto;">

| storage | contains_hit | contains_miss | evict | load | save |
| --- | --- | --- | --- | --- | --- |
| 🔴 SqlFile | 🟥 1.3 ms | 🟥 460 µs | 🟥 3.5 ms | 🟥 1.3 ms | 🟥 5.4 ms |
| 🔴 SqlMemory | 🟩 1.2 ms | 🟩 440 µs | 🟩 1.6 ms | 🟩 1.2 ms | 🟩 3.6 ms |


</div>
</details>

<details>
<summary><b>Integration Benchmarks</b></summary>

<div style="overflow-x: auto;">

<h4>Workload: lightweight</h4>

| name | contains_hit | contains_miss | hit | miss |
| --- | --- | --- | --- | --- |
| 🟠 H5+Sql | 🟥 1.9 ms | 🟥 790 µs | 🟥 8.1 ms | 🟥 12 ms |
| 🟢 Pickle+Sql | 🟥 1.8 ms | 🟥 830 µs | 🟩 2 ms | 🟨 7.6 ms |
| 🟤 Memory+Sqlite(:memory:) | 🟧 1.6 ms | 🟧 740 µs | 🟩 1.6 ms | 🟩 2.7 ms |
| 🟣 Memory | 🟩 280 µs | 🟩 220 µs | 🟩 280 µs | 🟩 520 µs |


<h4>Workload: compute_heavy</h4>

| name | contains_hit | contains_miss | hit | miss |
| --- | --- | --- | --- | --- |
| 🟠 H5+Sql | 🟥 1.7 ms | 🟥 790 µs | 🟥 8.3 ms | 🟥 12 ms |
| 🟢 Pickle+Sql | 🟥 1.7 ms | 🟥 820 µs | 🟩 2.1 ms | 🟧 8.4 ms |
| 🟤 Memory+Sqlite(:memory:) | 🟥 1.6 ms | 🟥 770 µs | 🟩 1.8 ms | 🟩 3.9 ms |
| 🟣 Memory | 🟩 270 µs | 🟩 230 µs | 🟩 290 µs | 🟩 770 µs |


<h4>Workload: data_heavy</h4>

| name | contains_hit | contains_miss | hit | miss |
| --- | --- | --- | --- | --- |
| 🟠 H5+Sql | 🟥 1.7 ms | 🟥 790 µs | 🟥 7.9 ms | 🟥 8.4 ms |
| 🟢 Pickle+Sql | 🟥 1.7 ms | 🟥 820 µs | 🟩 2.2 ms | 🟩 2.1 ms |
| 🟤 Memory+Sqlite(:memory:) | 🟥 1.8 ms | 🟥 840 µs | 🟩 1.8 ms | 🟩 1.6 ms |
| 🟣 Memory | 🟩 270 µs | 🟩 220 µs | 🟩 290 µs | 🟩 190 µs |


</div>
</details>
