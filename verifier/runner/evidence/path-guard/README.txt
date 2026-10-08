r14 path guard: record of the reviewed defect and of the correction (candidate runner; nothing adopted).

Before (runner at fa970d2, observed once in a scratch copy of the run2 capture; the polluted copy is not kept):
  --capture C --out C/runner-output  ->  snapshot_capture() copied the output directory into its own snapshot,
  recursion depth 173, 4537 files, ~60 MB written inside the capture copy, exit 40 SNAPSHOT_IO.

After (source pinned at 4bd215e):
  refusals.txt   --out equal to the capture, nested in it, and reached through a symlink alias: exit 2 with the usage message,
                 before any file is created; the capture was compared with the original afterwards (identical).
  t_static.out, t_snapshot.out, t_stages.out   affected test suites (16 + 7 + 22 tests, all OK).
  smoke.stdout/stderr, verdict.json, run-info.json   one anchored smoke run (run2 capture, its ANCHOR.sha256, separate --out,
                 network-isolated): BINDING_MATCH, exit 0, same outcome as validation-1 and validation-2-r13.
Historical evidence directories are untouched. Machine paths in text files are replaced by $SP.
