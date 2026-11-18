# V2 reconstruction assumptions, frozen before execution

- Keep the same 3 videos and 40 S1-selected keyframes. V0/V1 remain immutable.
- Native Supplement A.1 chain, model/revision, 5 seeds, frequency denominator, native verification and temporal topology retained.
- Complete V1 prefixes may be reused only with identical actual prompt, seed, temperature and input pixel hashes. After changed upstream, regenerate all descendants.
- A truncated text extraction is reapplied to literal sentences of the same visual narrative, at most 24 chunks, same supplementary task. This extraction-granularity recovery is a reconstruction assumption, not a disclosed author setting. All chunks must complete. No synthetic combined model response is written.
- One image-description request cap 8192, text extraction4096, classification/verification512; single-request timeout1200s, no-progress2400s. These are request protection settings, no total GPU budget threshold.
- Native dynamic identity/static merge/motion and crossclip Reference remain separate from question-conditioned VQS checks. All new phases use disjoint request namespaces.
- Clip Event edge exact topology/prompt remains underdetermined. Subsequent clip boundary anchors/holistic description will be explicitly tagged reconstruction, with observed clip ranges, not precise action intervals or independent truth.
- No training, weight updates, new rewards, G_raw or added video pool.
