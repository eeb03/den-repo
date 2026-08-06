# Test fixtures

## `ids_dt_sample.dt`

The unmodified header block plus the first 8 trace records of
`rebar/yangben.MIS/180124AA.ZON/LID10002.dt` from **Zenodo record
14637589** (*GPR DATASET*, GPR Group of Guangzhou University,
DOI 10.5281/zenodo.14637589, CC-BY-4.0).

Truncated to 8 traces so the IDS `.dt` adapter can be tested deterministically
without requiring the 3.8 GB source archive. Bytes are copied verbatim -- no
values were synthesised or altered -- so the parser is exercised against real
acquisition data. The full dataset is not committed; see
`datasets/raw/zenodo/14637589/PROVENANCE.json` after fetching it.
