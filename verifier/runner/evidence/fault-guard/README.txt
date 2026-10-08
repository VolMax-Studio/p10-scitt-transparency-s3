r18 fault guard: record of the correction (candidate runner; nothing adopted).
Source pinned at commit 11251894a9b6a0638772da7b0cd1f0972a96ad07; s3c_verify.py 7e6c457a…f628, s3c_chain.py de3450bb…0494 (unchanged), PINNED_INPUTS.json 3a1550f8…9912 (unchanged).
  t_faults.out, t_static.out, t_snapshot.out, t_stages.out   affected suites (5 + 16 + 7 + 22 tests, all OK). t_faults.out is new: executable-copy failure and unexpected chain
                 exceptions (OSError, RuntimeError) end as S3-FAIL(infrastructure), exit 40, verdict.json and a diagnostic; a control with a fake successful chain gives BINDING_MATCH; usage errors keep exit 2.
                 Against the pre-fix runner (fa0baf2) three of these five tests fail (the escaped OSError / exception).
  run1, run2     two offline anchored runs of the existing run2 capture (ts-prototype/evidence/lifecycle-run2, its ANCHOR.sha256) with the supplied verifier/artifacts executables, no --no-offline:
                 BINDING_MATCH, exit 0, network_isolated=true, executables_pinned entry=true g5=true, verdict.json byte-identical in both runs. run-info.json is incidental.
Earlier evidence is unchanged; no Rust artifact was rebuilt, no key regenerated, no lifecycle capture made. Machine paths in text files are replaced by $SP.
