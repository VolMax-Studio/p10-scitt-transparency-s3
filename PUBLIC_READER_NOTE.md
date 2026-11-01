# Public Reader Note — reference pins, licensing, and historical consistency

**Reference state: 2026-11-01.** This is a forward-facing maintenance and locator note. It does not amend any signed tag, create a new ratification, change P10 semantics, or claim conformance.

## Why this note exists

We apologize for inconsistencies between some historical content pins and later publication, licensing, and repository documentation.

P10 has been developed across several bounded workstreams in parallel, with formal semantics, replay, transparency, packaging, and follow-on integration work moving at different times. In a few places, public/licensing documentation advanced after an already-frozen content pin, and one later public-status statement was not kept synchronized. That explains how the mismatch occurred, but it does not transfer the burden to an external reader. This note exists so a reader can reconstruct the public reference state without having to ask the maintainer for private interpretation.

## Reading rule

1. **Use the signed historical tag as the content/authority pin** when reconstructing the ratified or accepted result.
2. **Use the later public-license state as the license grant** where the historical tag predates that grant. The old tag tree is intentionally left unchanged so its historical identity remains intact.
3. The current repository license grant is intended to apply to the original VolMax Studio project content already present in the historical pins listed below, even where the old tag tree itself did not yet contain the later license file. Third-party material remains under its own applicable terms and notices.
4. A later `main` commit is not automatically a substitute for a ratified content pin. Where later code or application work exists, the table below says so explicitly.
5. This note is a locator and maintenance correction only. It does not supply missing semantics, reinterpret a frozen specification, or turn an outside reading into a conformance result.

## Cross-repository reference map

| Layer | Historical content pin | License state at that pin | Public license reference as of 2026-11-01 | Relationship |
|---|---|---|---|---|
| **S1** `VolMax-Studio/p10-underdetermination-lean-s1` | `v0.1.0-s1-ratified` → `e4db3747eaeeb1a07227bb9029f9a9c3b566cdb1` | No root license file | `main` reference `970e535366fc70d809d50f8bf3f152f8020d4de9`, MIT | Tag → license-bearing reference changes licensing and documentation/checksum/binding material; no executable or formal source file changes. |
| **S2a** `VolMax-Studio/p10-coverage-lean-s2` | `v0.1.0-s2a-ratified` → `741d56d36d7b2bfe2e9e0080a1cba4393e4a47da` | Placeholder says no license selected / rights reserved | `main` reference `7f7eb77d545df3119c52577990414c4575666b18`, MIT | Later changes are license/README/dependency/binding documentation; no implementation-code change. |
| **S2b** `VolMax-Studio/p10-replay-verifier` | `v0.1.0-s2b-complete` → `8eaa91cad1ffa963158b365c6d0d7316f4965e89` | No root license file | `v0.1.1-s2b-public` → `8e89f9a4192bdd0ab280556701dc595eb55539d2`, MIT OR Apache-2.0 | Direct diff checked: the public tag adds licensing, notice, README, security, and integration documentation; verifier code and conformance vectors are unchanged. |
| **S3** `VolMax-Studio/p10-scitt-transparency-s3` | `v0.1.0-s3-accepted` → `5acc277a13dc122e39fcb5f9f3e646b06cc95009` | No root license file | license-bearing `main` reference `15f93adb9d7c5be8b70e730d56e735ea85a94172`, MIT OR Apache-2.0 | `main` contains substantial later Workbench/reproduction work and is **not** tree-equivalent to the accepted tag. Use the accepted tag for the executed-instance boundary. |

The license references above are stable locator commits for this note. Later maintenance commits may move `main` without changing the historical content pins.

## S2b: complete tag versus public tag

For reconstruction of the exact ratified S2b checkpoint, use:

- `v0.1.0-s2b-complete` (`8eaa91cad1ffa963158b365c6d0d7316f4965e89`).

For a licensed public checkout of the same verifier/conformance-vector implementation, use:

- `v0.1.1-s2b-public` (`8e89f9a4192bdd0ab280556701dc595eb55539d2`).

The verifier implementation and conformance vectors do not change across those two pins. The later public tag adds the public licensing/security/integration-documentation layer.

## S3 accepted leaf 7: public locator correction

The accepted S3 tag already contains the retained target statement bytes. Any earlier statement saying that the retained leaf-7 bytes were not public should be treated as corrected.

At `v0.1.0-s3-accepted` (`5acc277a13dc122e39fcb5f9f3e646b06cc95009`):

- path: `ts-prototype/evidence/s3b-capture/capture/prefix/000007.cose`
- size: `7516` bytes
- SHA-256: `73273d96f81aebfa35ff2298f99198328664a1ab6bec442ba5f4ce0003f8a16e`
- capture index: `ts-prototype/evidence/s3b-capture/capture/capture.json`
- index/role in that capture: `7` / `p10-target`

The digest is also the executed-instance Appendix C `C09` value in `draft-nestorov-scitt-p10-underdetermination-02`.

## Correction to the publication/licensing status described in `-02`

As of this reference state, S1, S2a, S2b, and S3 are publicly readable repositories.

Section 10.8 of `draft-nestorov-scitt-p10-underdetermination-02` describes S3 as private and says that no public S3 license grant is claimed. That publication-status sentence is stale relative to the repository state documented here. The published `-02` is an immutable Internet-Draft revision and is not being rewritten in place; a later draft revision should align the availability/licensing paragraph with this public state.

The S1 and S2a statements in `-02` about the license files present **at the historical ratified tags** remain accurate as historical tree facts. What changed later is the public license grant on the maintained repository state, as recorded above.

This note does not claim the exact date on which repository visibility changed.

## If another mismatch is found

Please treat an unresolved mismatch as an ambiguity in the public material rather than inferring private intent. The project preference is to correct public locators and documentation forward while preserving signed historical objects unchanged.
