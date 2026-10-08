# Environment file for ts-prototype/scripts/run_lifecycle.sh (candidate normative path). Replace only the host-specific paths marked <...>.
# Values taken from deployment/candidate/definition-manifest.json are fixed here and must not be edited.
REPO=<path of the checkout; HEAD must satisfy the source-pin check in RUN.md>
BIN=<directory holding s3-facade, s3-capture, s3-keygen built by the recipe in RUN.md>
PY=<python3 with cryptography and cbor2 (tooling only; the S3-C runner needs the standard library only)>
S1=<S1 checkout at e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1, clean>
S2A=<S2a checkout at 741d56d36d7b2bfe2e9e0080a1cba4393e4a47da, clean>
S2B=<S2b checkout at 8eaa91cad1ffa963158b365c6d0d7316f4965e89, clean>
ENTRY=$REPO/verifier/artifacts/s3-spike-entry
G5=$REPO/verifier/artifacts/s3-g5
GLUE=$REPO/spike/glue/s3_spike_chain.py
LEAN_BIN=<bin directory of the pinned Lean (conda-forge lean4 4.33.0)>
# key custody directories (outside the repository; created before the freeze, see RUN.md "Keys")
ISS_KEYS=<custody>/candidate-issuers      # volmax-owner.pem admitter-one.pem admitter-two.pem intruder-x.pem operator.pem
TS_KEYS=<custody>/candidate-receipt       # ts.pem
NOTE_KEYS=<custody>/candidate-checkpoint  # note.skey note.vkey
DEFINITION=$REPO/deployment/candidate
OUT=$REPO/ts-prototype/evidence/s3b-capture   # empty or absent; inside the checkout (under evidence/, which the pin check excludes) so that the operator can commit the anchor
OWNER=volmax-owner
TS_ISS=https://ts.example/volmax-s3
ORIGIN=volmax-s3/ts
PORT=19900
LABEL=S3-B-CANDIDATE
LAYOUT=ml2
