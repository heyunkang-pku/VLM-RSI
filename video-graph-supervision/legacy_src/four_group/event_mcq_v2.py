"""V2: attributed narrative pseudo-labels, isolated from executable event QA.
No graph is altered. Mechanical provenance validity does not establish visual truth.
"""
import collections
import copy
import csv
import json
import os
import random
import shutil
import re
from pathlib import Path
from step_six.common import (j, rows, jl, filehash, h, norm, parsejson,
                            make_runtime, choose_gpu, allocation, cost)
from stsg_pilot.runtime import save, emit
from four_group.event_mcq import BASE, compact, similar
from four_group.results import aggregate

TYPES = ('event_order', 'event_after', 'state_change', 'motion_direction')
PROMPT = '''You are a graph-only Questioner, not a visual truth verifier. Generate at most ONE English event multiple-choice QA pair of the requested type from the supplied frozen graph. Return a complete QA pair, including your graph pseudo-answer. Use 2 to 4 natural, distinct, mutually exclusive options; do not invent filler options. Option positions will be shuffled by code.
The answer must require information from two or more moments: event order, what happened after an event, change in an object's state, or an object's motion direction. Locate events by their actions, not exact public timestamps. Skip single-time color/material questions and questions answerable from a single static frame. Do not reveal the answer in the question, its presuppositions, option wording, or an internal ID. Do not infer absence from missing action records or infer intervening actions from static endpoints.
IMPORTANT V2 EVIDENCE POLICY: clip_observations.description and motion_edges.action are admissible unverified pseudo-label evidence when their actual words explicitly express the requested ordering, change, or direction. A holistic description that explicitly says then/after/before can support narrative ordering. Cite its original record_id and exact, contiguous quotation(s) expressing BOTH relevant actions and their relation. Record evidence_granularity as whole_clip or observation_window. Observation start/end only delimit evidence scope, never precise action boundaries. usable_for_program_QA=false means that an action is not executable by a program; it does NOT invalidate its explicit textual description for an unverified narrative pseudo-label.
Do NOT require precise action onsets/offsets, separate program-executable event nodes, or identity edges for simple explicitly narrated order. Require those only if your particular question actually needs them (e.g. distinguishing indistinguishable repeated action instances, exact event timing, or identifying the same physical instance across ambiguous descriptions). If necessary binding/timing is unresolved, conflicting, ambiguous, or missing, output no candidate and explain the gap. A description that only says 'various actions occurred' is insufficient. Do not use the order of sentences alone if the temporal relation is not actually expressed. A whole-clip description with explicit relations IS allowed. Avoid unsupported 'immediately', 'first', 'last', or 'only' assertions.
Use original graph record IDs and original frame IDs only in private evidence fields. Supporting frames for narrative evidence may be the full original observation window; this is NOT frame-level localization. Do not claim to have inspected images; none are supplied. Fact IDs may be empty for a quotation-supported narrative answer. Never repair the graph or invent visual facts.
Return JSON only: {"candidates":[{"question":"English question", "options":["choice","choice"], "answer_index":0, "type":"REQUESTED_TYPE", "event_or_action_edge_ids":["original record id"], "fact_ids":[], "identity_connection_ids":[], "evidence_frame_ids":["original frame ids covering the observation"], "evidence_granularity":"whole_clip|observation_window", "text_evidence":[{"record_id":"original record id", "field":"description|action", "quote":"EXACT substring of the field"}], "cross_frame_reason":"one sentence specifying the relation and why multiple moments are required", "requirements":{"precise_event_bounds":false,"executable_event_instances":false,"cross_frame_identity_binding":false}, "requirement_reasons":{"precise_event_bounds":"why required or not needed", "executable_event_instances":"why required or not needed", "cross_frame_identity_binding":"why required or not needed"}}], "unanswerable":[{"type":"REQUESTED_TYPE","reason":"specific reason if no candidate"}]}.
'''

def records_for(graph):
    records = {}
    for r in graph['clip_observations']:
        records[r['id']] = {'fields': {'description': r['description']},
                            'frame_ids': r['input_frame_ids'],
                            'interval': r['observation_interval_sec'], 'kind': 'clip', 'raw': r}
    for r in graph['motion_edges']:
        records[r['id']] = {'fields': {'action': r['action']},
                            'frame_ids': r['necessary_source_frames'],
                            'interval': r['observation_interval_sec'], 'kind': 'motion', 'raw': r}
    return records

def duplicate(question, exclusions):
    # Finite, documented surface detector, not a semantic gold judge.
    def canonical(s):
        s = s.lower().replace('earlier', 'first').replace('prior to', 'before')
        s = re.sub(r'\b(?:the|a|an|did|does|do|was|were|is|it|on|of|to)\b', ' ', s)
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z ]', ' ', s)).strip()
    a = canonical(question)
    for b in exclusions:
        if similar(question, b) or similar(a, canonical(b)):
            return True
        aa, bb = set(a.split()), set(canonical(b).split())
        if len(aa & bb) / max(1, len(aa | bb)) >= .7:
            return True
    return False

def manual_relation_duplicate(q):
    """Conservative semantic signatures for the 12 supplied development items.
    Symmetric ordering pairs also exclude next-event paraphrases of that pair.
    They are exclusions only, never labels or new graph facts.
    """
    text = (q['question'] + ' ' + ' '.join(q['options'])).lower()
    vid, typ = q.get('video_id'), q['type']
    has = lambda pattern: bool(re.search(pattern, text))
    if typ in ('event_order', 'event_after'):
        if vid == 'video_109':
            clear = has(r'clear|transparent')
            whitegreen = has(r'white|green')
            beigeblue = has(r'beige|blue|light.colou?red')
            return clear and (whitegreen or beigeblue)
        if vid == 'video_44':
            remote, cable, mug = has(r'remote'), has(r'cable|cord|wire'), has(r'mug|red cup')
            return remote and (cable or mug)
        if vid == 'video_101':
            return has(r'white') and has(r'black|dark')
        if vid == 'video_33':
            return has(r'wallet') and has(r'feet|camera|tilt|pan.down')
    if typ == 'motion_direction' and vid == 'video_108':
        return has(r'ball') and has(r'first|initial|begin|start')
    if typ == 'state_change':
        if vid == 'video_33':
            return has(r'wallet') and has(r'open|clos|fold') and has(r'first|initial|pick')
        if vid == 'video_76':
            return has(r'cup') and has(r'first|initial') and has(r'lift|pick|remove|return')
        if vid == 'video_109':
            return has(r'cup') and has(r'number|count|increase|decrease|more|fewer')
        if vid == 'video_108':
            return has(r'ball') and has(r'start|begin|initial') and has(r'end|final')
    return False

def validate(q, graph, valid_frames, exclusions, requested_type):
    """Check structure, literal attribution and conditional advanced requirements.
    No semantic model is used; quote entailment and visual correctness remain pending.
    """
    try:
        assert q['type'] == requested_type and requested_type in TYPES, 'WRONG_TYPE'
        options = q['options']
        assert isinstance(options, list) and 2 <= len(options) <= 4, 'OPTION_COUNT'
        assert all(isinstance(o, str) and norm(o) for o in options), 'EMPTY_OPTION'
        assert len(set(map(norm, options))) == len(options), 'DUPLICATE_OPTIONS'
        assert type(q['answer_index']) is int and 0 <= q['answer_index'] < len(options), 'ANSWER_INDEX'
        assert isinstance(q['question'], str) and q['question'].strip(), 'EMPTY_QUESTION'
        public = q['question'] + ' ' + ' '.join(options)
        assert not re.search(r'\b(?:at what time|what time|how many seconds|which timestamp)\b', q['question'], re.I), 'PRECISE_TIME_QUESTION_NOT_ALLOWED'
        assert not re.search(r'\b(?:src_\d+|video_\d+|event_[a-f0-9]+|o\d+)\b|\d+(?:\.\d+)?\s*(?:seconds?|secs?)', public), 'PUBLIC_ID_OR_TIME'
        assert not re.search(r'(?:correct answer|answer is|correct option)\s*[:=]?', q['question'], re.I), 'EXPLICIT_ANSWER_LEAK'
        # Naming compared actions in a 'which first' question is legitimate, not a leak.
        assert not duplicate(q['question'], exclusions), 'EXACT_OR_NEAR_DUPLICATE'
        assert not (exclusions and manual_relation_duplicate(q)), 'MANUAL12_RELATION_SIGNATURE_DUPLICATE'
        assert q['cross_frame_reason'].strip(), 'MISSING_CROSS_FRAME_REASON'
        assert q['evidence_granularity'] in ('whole_clip', 'observation_window'), 'EVIDENCE_GRANULARITY'
        records = records_for(graph)
        ids = q['event_or_action_edge_ids']
        assert ids and len(ids) == len(set(ids)) and set(ids) <= records.keys(), 'INVALID_RECORD_IDS'
        frame_ids = q['evidence_frame_ids']
        assert len(set(frame_ids)) >= 2 and set(frame_ids) <= valid_frames, 'INVALID_FRAME_IDS'
        assert set(frame_ids) <= {f for rid in ids for f in records[rid]['frame_ids']}, 'FRAMES_OUTSIDE_CITED_OBSERVATIONS'
        evidence = q['text_evidence']
        assert evidence and {e['record_id'] for e in evidence} == set(ids), 'INCOMPLETE_RECORD_ATTRIBUTION'
        for e in evidence:
            record = records[e['record_id']]
            assert e['field'] in record['fields'], 'INVALID_EVIDENCE_FIELD'
            assert len(e['quote'].strip()) >= 16 and e['quote'] in record['fields'][e['field']], 'QUOTE_NOT_EXACT'
        fact_ids = {r['id'] for r in graph['facts']}
        assert set(q.get('fact_ids', [])) <= fact_ids, 'INVALID_FACT_IDS'
        positive = {r['id']: r for p in graph['identity_pair_ledger'] for r in p['positive_or_conflicting_results'] if r['verdict'] == 'YES' and 'CONFLICT' not in r['state']}
        assert set(q.get('identity_connection_ids', [])) <= positive.keys(), 'INVALID_IDENTITY_REFERENCE'
        req = q['requirements']
        reasons = q['requirement_reasons']
        for key in ('precise_event_bounds', 'executable_event_instances', 'cross_frame_identity_binding'):
            assert type(req[key]) is bool and reasons[key].strip(), 'MISSING_REQUIREMENT_REASON'
        if req['precise_event_bounds']:
            assert all(records[rid]['raw'].get('event_interval_sec') for rid in ids), 'REQUIRED_PRECISE_BOUNDS_MISSING'
        if req['executable_event_instances']:
            assert all(records[rid]['raw'].get('usable_for_program_QA', False) for rid in ids), 'REQUIRED_EXECUTABLE_EVENT_MISSING'
        if req['cross_frame_identity_binding']:
            assert q.get('identity_connection_ids'), 'REQUIRED_IDENTITY_BINDING_MISSING'
        return None
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError) as e:
        return str(e) or type(e).__name__

def sentence_catalog(graph):
    catalog = {}
    for rid, record in records_for(graph).items():
        catalog[rid] = {}
        for field, source in record['fields'].items():
            # Null is absent evidence, never the text 'None' and never a fabricated sentence.
            if not isinstance(source, str):
                catalog[rid][field] = []
                continue
            # Slice at punctuation+whitespace, preserving original character offsets.
            bounds = [0] + [m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=[A-Z])', source)] + [len(source)]
            catalog[rid][field] = [{'sentence_id': i, 'start': a, 'end': b, 'text': source[a:b]} for i,(a,b) in enumerate(zip(bounds,bounds[1:])) if source[a:b].strip()]
    return catalog

def materialize_citations(q, graph):
    """Only resolve explicitly selected source sentences. Never fuzzy-match prose.
    Reject nonconsecutive IDs, bad IDs or a supplied inconsistent quote.
    """
    q = copy.deepcopy(q)
    catalog, records = sentence_catalog(graph), records_for(graph)
    for e in q['text_evidence']:
        rid, field = e['record_id'], e['field']
        assert rid in catalog and field in catalog[rid], 'INVALID_SENTENCE_SOURCE'
        ids = e['sentence_ids']
        assert isinstance(ids,list) and ids and all(type(i) is int for i in ids), 'INVALID_SENTENCE_IDS'
        assert ids == list(range(ids[0],ids[-1]+1)), 'NONCONTIGUOUS_SENTENCE_IDS'
        ss = {v['sentence_id']:v for v in catalog[rid][field]}
        assert set(ids)<=ss.keys(), 'UNKNOWN_SENTENCE_ID'
        start,end = ss[ids[0]]['start'],ss[ids[-1]]['end']
        quote = records[rid]['fields'][field][start:end]
        assert 'quote' not in e or e['quote']==quote, 'SUPPLIED_QUOTE_CONFLICTS_WITH_SELECTED_SENTENCES'
        e.update(quote=quote, source_char_range=[start,end], quote_source='DETERMINISTIC_SOURCE_SLICE_NOT_MODEL_TRANSCRIPTION')
    return q

def narrative_view(graph):
    """Lossless projection of original clip/Motion records, not a new graph.
    Static FSG and identity ledger are deliberately not sent in this version.
    """
    return {key: copy.deepcopy(graph[key]) for key in ('clip_observations', 'motion_edges')} | {'source_sentence_catalog': sentence_catalog(graph)}

def generate(rt, root, stage, vid, typ, media, graph, exclusions, diagnostic=False):
    out = root / stage / vid / typ
    out.mkdir(parents=True, exist_ok=True)
    result_file = out / 'RESULT.json'
    prompt = PROMPT.replace('REQUESTED_TYPE', typ).replace('and exact, contiguous quotation(s) expressing BOTH relevant actions and their relation', 'and consecutive source sentence_ids expressing BOTH relevant actions and their relation').replace(chr(34)+'quote'+chr(34)+':'+chr(34)+'EXACT substring of the field'+chr(34), chr(34)+'sentence_ids'+chr(34)+':[0,1]') + '\nRequested type: ' + typ
    if diagnostic:
        prompt += '\nThis is a generation/provenance diagnostic only. Formal exclusions are intentionally NOT applied here. Do not copy examples; no examples are provided. Diagnostic outputs will never enter formal voting.'
    else:
        prompt += '\nExcluded old/development questions; do not repeat or paraphrase any: ' + json.dumps(exclusions, ensure_ascii=False)
    view = narrative_view(graph)
    save(out / 'ACTUAL_GRAPH_VIEW.json', view)
    prompt += '\nFrozen graph NARRATIVE RECORD PROJECTION (unchanged original records; not a new graph): ' + json.dumps(view, ensure_ascii=False, separators=(',', ':'))
    prompt += '\nFINAL FORMAT REMINDER: Requested type is ' + typ + '. Do NOT ask when/how many seconds/at what time. Record IDs are case-sensitive. Copy IDs verbatim from this whitelist: ' + json.dumps(list(records_for(graph))) + '. Select consecutive sentence_ids from source_sentence_catalog for each cited record/field; do NOT output a quote or paraphrase. Code will copy exactly those source sentences. For a whole-clip description cite its event_... id, never the literal collection name clip_observations or an invented motion: prefix. The same original record_id must appear in event_or_action_edge_ids and text_evidence. No static fact or cross-frame identity ledger is supplied in this narrative-only view; if the question requires external binding or exact timing, report unknown. Return only the requested JSON.'
    if result_file.exists():
        assert (out / 'PROMPT.txt').read_text() == prompt, 'RESUME_PROMPT_CHANGED'
        emit('event_v2_generation_reused', video=vid, type=typ, stage=stage)
        return j(result_file)
    (out / 'PROMPT.txt').write_text(prompt)
    row = {'video_id': vid, 'type': typ, 'stage': stage, 'status': 'FAILED', 'candidates': [], 'attempts': [], 'diagnostic_only': diagnostic}
    try:
        rt.mode = 'text'
        # One fixed recovery only for output truncation; never retry empty outputs.
        for cap in (4096, 8192):
            r = rt.ask(media, [], prompt, role=stage + '_' + typ, owner=vid + ':' + typ,
                       max_tokens=cap, temperature=0, seed=2026111402)
            save(out / ('RAW_' + str(cap) + '.json'), r)
            row['attempts'].append({'request_id': r['request_id'], 'cap': cap, 'hit_cap': r['output_hit_cap']})
            if not r['output_hit_cap']:
                break
        assert not r['output_hit_cap'], 'OUTPUT_TRUNCATED_AFTER_FINITE_RECOVERY'
        reply = parsejson(r['raw_response'])
        assert isinstance(reply['candidates'], list) and len(reply['candidates']) <= 1, 'CANDIDATE_CAP_OR_TYPE'
        row.update(status='COMPLETED', unanswerable=reply.get('unanswerable', []))
        frames = {f['frame_id'] for f in media['class_video_views']}
        for q in reply['candidates']:
            q = copy.deepcopy(q)
            q['video_id'] = vid
            try:
                q = materialize_citations(q, graph)
                reason = validate(q, graph, frames, [] if diagnostic else exclusions, typ)
            except (AssertionError,KeyError,TypeError,ValueError) as e:
                reason = str(e) or type(e).__name__
            q.update(video_id=vid, rejection_reason=reason, status='REJECTED' if reason else 'PROVENANCE_VALID_UNVERIFIED_PSEUDOLABEL', label_status='UNVERIFIED_GRAPH_TEXT_PSEUDOLABEL', semantic_entailment='PENDING_INDEPENDENT_REVIEW', visual_correctness='PENDING', support_frame_role='OBSERVATION_SCOPE_NOT_LOCALIZED_ACTION_FRAMES')
            q['attributed_records'] = [{**records_for(graph)[rid], 'record_id': rid} for rid in q.get('event_or_action_edge_ids', []) if rid in records_for(graph)]
            row['candidates'].append(q)
        if not row['candidates'] and not row['unanswerable']:
            row['unanswerable'] = [{'type': typ, 'reason': 'MODEL_EMPTY_NO_REASON'}]
    except Exception as e:
        row['error'] = repr(e)
    save(result_file, row)
    emit('event_v2_generation', video=vid, type=typ, stage=stage, candidates=len(row['candidates']), accepted=sum(q['rejection_reason'] is None for q in row['candidates']), error=row.get('error'))
    return row

def freeze_candidate(q, media):
    q = copy.deepcopy(q)
    old_answer_index = q['answer_index']
    order = list(range(len(q['options'])))
    random.Random(h([q['video_id'], q['question'], 'event_v2_options'])).shuffle(order)
    q['original_options'] = q['options'][:]
    q['original_answer_index'] = old_answer_index
    q['option_permutation'] = order
    q['options'] = [q['options'][i] for i in order]
    q['answer_index'] = order.index(old_answer_index)
    q['graph_answer'] = 'ABCD'[q['answer_index']]
    q['review_id'] = 'event_v2_' + h([q['video_id'], q['question'], q['options']])[:12]
    q['public_frame_manifest_sha256'] = h(media)
    return q

def export(root, qa, votes, stats):
    byid = {v['review_id']: v for v in votes}
    comparison = []
    for q in qa:
        v = byid.get(q['review_id'])
        comparison.append({k: q[k] for k in ['review_id', 'video_id', 'type', 'question', 'options', 'graph_answer']} | {'vote': v['vote'] if v else None, 'strict_agreement': v['strict_agreement'] if v else None, 'plurality_agreement': v['plurality_agreement'] if v else None, 'accuracy': 'PENDING_INDEPENDENT_ANSWER'})
    jl(root / 'COMPARISON.jsonl', comparison)
    with (root / 'COMPARISON.csv').open('w', newline='', encoding='utf-8-sig') as f:
        fields = ['review_id', 'video_id', 'type', 'question', 'options', 'graph_answer', 'votes', 'plurality_answer', 'top_vote_count', 'tie', 'strict_majority_answer', 'strict_abstention_reason', 'strict_agreement', 'plurality_agreement']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in comparison:
            vote = r['vote'] or {}
            w.writerow({k: json.dumps(r.get(k, vote.get(k)), ensure_ascii=False) for k in fields})
    yield_rows = []
    for row in stats:
        qs = [q for q in qa if q['video_id'] == row['video_id'] and q['type'] == row['type']]
        vs = [byid[q['review_id']] for q in qs if q['review_id'] in byid]
        yield_rows.append({'video_id': row['video_id'], 'type': row['type'], 'generation_status': row['status'], 'raw_candidates': len(row['candidates']), 'frozen_questions': len(qs), 'rejection_reasons': [q['rejection_reason'] for q in row['candidates'] if q['rejection_reason']], 'unanswerable': row.get('unanswerable'), 'error': row.get('error'), 'strict_answered': sum(v['vote']['strict_majority_status'] == 'ANSWERED' for v in vs), 'strict_matches': sum(v['strict_agreement'] is True for v in vs)})
    save(root / 'YIELD_BY_VIDEO_TYPE.json', yield_rows)
    both = sum(v['vote']['strict_majority_status'] == 'ANSWERED' for v in votes)
    matches = sum(v['strict_agreement'] is True for v in votes)
    save(root / 'SUMMARY.json', {'videos_in_denominator': 10, 'type_attempts': len(stats), 'frozen_questions': len(qa), 'types': dict(collections.Counter(q['type'] for q in qa)), 'graph_label_coverage_on_frozen_QA': 1.0 if qa else None, 'strict_voting_coverage_on_frozen_QA': both / len(qa) if qa else None, 'both_answered': both, 'strict_matches': matches, 'strict_agreement_among_both_answered': matches / both if both else None, 'actual_sample_slots': sum(len(v['samples']) for v in votes), 'ties': sum(v['vote']['tie'] for v in votes), 'accuracy': 'PENDING_INDEPENDENT_ANSWERS', 'agreement_is_not_accuracy': True, 'cost': cost(root)})

def main():
    cfg = j('config/four_group.json')
    cfg.update(protocol_version='GRAPH-EVENT-MCQ-v2.2-SOURCE-SENTENCE-CITATIONS', event_types=list(TYPES), options_range=[2,4], candidates_per_video_type=1, questioner_caps=[4096,8192], questioner_seed=2026111402, diagnostic_videos=['video_44','video_109'], voting_fixed_denominator=10, voting_strict_threshold=6, exact_quote_check_not_truth_evaluation=True, questioner_graph_projection='original clip_observations+motion_edges only; no static facts or identity ledger; full source graph retained separately')
    root = Path('/scratch/haozhe/.cache/vlm-rsi/event-mcq-v2') / os.environ['ORX_RUN_ID']
    resume = cfg.get('event_mcq_resume_root')
    if resume and not root.exists():
        shutil.copytree(resume, root)
        history = root / 'prior_run' / Path(resume).name
        history.mkdir(parents=True, exist_ok=True)
        for name in ['effective_config.json','PROTOCOL_FROZEN.json']:
            shutil.copy2(root / name, history / name)
        if (root / 'Questioner' / 'ALLOCATION.json').exists():
            shutil.copy2(root / 'Questioner' / 'ALLOCATION.json', history / 'ALLOCATION.json')
        save(history / 'RESUME.json', {'source_root':resume,'destination_root':str(root),'new_commit':os.environ['ORX_COMMIT'],'copy_before_new_calls':True,'completed_prompts_must_match_exactly':True})
    root.mkdir(parents=True, exist_ok=True)
    save(root / 'effective_config.json', cfg)
    media = j(BASE / 'PUBLIC32_FROZEN.json')
    save(root / 'MEDIA_FROZEN.json', media)
    graphs, hashes, old = {}, {}, []
    for batch in ['first2', 'remaining8']:
        folder = BASE / batch
        g, facts, pairs = [j(folder / n) for n in ['GRAPH_SHARED_FROZEN.json', 'FACT_REGISTRY.json', 'SOURCE_TEMPORAL_PAIRS.json']]
        hashes[batch] = {n: filehash(folder / n) for n in ['GRAPH_SHARED_FROZEN.json', 'FACT_REGISTRY.json', 'SOURCE_TEMPORAL_PAIRS.json']}
        old += [q['question'] for q in rows(folder / 'S_FROZEN_QA.jsonl') + rows(folder / 'P_FROZEN_QA.jsonl')]
        for vid in media:
            if any(n.startswith(vid + '/') for n in g['source_nodes']):
                graphs[vid] = compact(g, facts, pairs, vid)
                save(root / 'graph_inputs' / (vid + '.json'), graphs[vid])
    prior = Path(cfg['followup_finalize_root']) / 'FROZEN_ALL_QA.jsonl'
    old += [q['question'] for q in rows(prior) if q.get('cohort') == 'new_temporal']
    manual = j('config/manual12_exclusions.json')
    assert len(manual) == 12, 'MANUAL12_NOT_AVAILABLE'
    exclusions = list(dict.fromkeys(old + [x['question'] for x in manual]))
    save(root / 'EXCLUSIONS.json', {'texts': exclusions, 'manual12': manual, 'manual_answers_are_not_used': True, 'rule': 'v1 surface thresholds OR canonical thresholds OR canonical token Jaccard>=0.7; finite surface detector, not certified semantic equivalence', 'questioner_also_instructed_not_to_paraphrase': True, 'manual12_relation_signatures': 'four_group.event_mcq_v2.manual_relation_duplicate; symmetric event-pair/state/direction signature exclusions; not correctness labels'})
    save(root / 'SOURCE_HASHES.json', hashes)
    save(root / 'PROTOCOL_FROZEN.json', {'config': cfg, 'source_commit': os.environ['ORX_COMMIT'], 'source_hashes': hashes, 'media_sha256': filehash(root / 'MEDIA_FROZEN.json'), 'exclusions_sha256': filehash(root / 'EXCLUSIONS.json'), 'diagnostic_outputs_never_enter_formal_QA': True})
    rt = make_runtime(cfg, root / 'Questioner', 'event_v2_graph_text', choose_gpu())
    accepted, stats, diagnostics = [], [], []
    try:
        # Real model preflight: narrative order must pass on BOTH fixed videos.
        for vid in cfg['diagnostic_videos']:
            diagnostics.append(generate(rt, root, 'preflight', vid, 'event_order', media[vid], graphs[vid], [], True))
        passed = all(any(q['rejection_reason'] is None for q in r['candidates']) for r in diagnostics)
        save(root / 'PREFLIGHT.json', {'passed': passed, 'rows': diagnostics, 'not_formal_questions': True, 'exclusions_not_applied_only_in_preflight': True})
        if not passed:
            save(root / 'STATUS.json', {'stage': 'PREFLIGHT_FAILED_SAVED_STOPPED', 'voting_started': False})
            emit('event_v2_preflight_failed', root=str(root))
            return
        for vid in sorted(media, key=lambda v: int(v.split('_')[-1])):
            for typ in TYPES:
                row = generate(rt, root, 'formal', vid, typ, media[vid], graphs[vid], exclusions + [q['question'] for q in accepted])
                for q in row['candidates']:
                    if q['rejection_reason'] is None:
                        accepted.append(freeze_candidate(q, media[vid]))
                stats.append(row)
                jl(root / 'CANDIDATE_LEDGER.jsonl', [q for s in stats for q in s['candidates']])
                save(root / 'GENERATION_PROGRESS.json', {'type_attempts_done': len(stats), 'questions_provisional': len(accepted)})
    finally:
        allocation(rt, root / 'Questioner')
    # Free Questioner model before Solver allocation.
    del rt
    import gc
    gc.collect()
    import torch
    torch.cuda.empty_cache()
    jl(root / 'QA_FROZEN.jsonl', accepted)
    save(root / 'FREEZE.json', {'QA_sha256': filehash(root / 'QA_FROZEN.jsonl'), 'media_sha256': filehash(root / 'MEDIA_FROZEN.json'), 'graph_hashes': hashes, 'frozen_before_any_solver_call': True})
    jl(root / 'REVIEW_NO_ANSWERS.jsonl', [{k:q[k] for k in ['review_id','video_id','type','question','options']} | {'frames': [{'frame_id':f['frame_id'],'relative_path': str(Path('frames') / q['video_id'] / Path(f['file']).name), 'time_sec':f['time_sec'], 'sha256':f['sha256']} for f in media[q['video_id']]['class_video_views']]} for q in accepted])
    emit('event_v2_freeze', questions=len(accepted), root=str(root))
    votes = []
    if accepted:
        solver = make_runtime(dict(cfg, model_path=cfg['solver_model_path'], model_revision=cfg['solver_model_revision']), root / 'Solver', 'event_v2_v4_solver', choose_gpu())
        try:
            for q in accepted:
                target = root / 'votes' / (q['review_id'] + '.json')
                v = j(target) if target.exists() else {'review_id': q['review_id'], 'samples': []}
                for i in range(len(v['samples']), 10):
                    letters = 'ABCD'[:len(q['options'])]
                    prompt = 'Choose the best option using only the supplied video and public question. Return JSON {"answer":"' + '|'.join(letters) + '"}; use null if evidence is insufficient.\n' + q['question'] + '\n' + '\n'.join(f'{c}. {o}' for c,o in zip(letters,q['options']))
                    s = {'sample_index': i, 'seed': 20261101030+i, 'status': 'FAILED', 'answer': None}
                    try:
                        solver.mode = 'video'
                        r = solver.ask(media[q['video_id']], [], prompt, role='v4_event_mcq_v2', owner=q['review_id']+':'+str(i), temperature=.7, max_tokens=2048, seed=s['seed'])
                        s.update(raw_response=r['raw_response'], request_id=r['request_id'], output_hit_cap=r['output_hit_cap'], input_hashes=r['input_hashes'], shown_frame_ids=r['shown_frame_ids'], frame_content_hashes=r['frame_content_hashes'], actual_source_times_sec=r['actual_source_times_sec'])
                        expected = media[q['video_id']]['class_video_views']
                        assert r['shown_frame_ids'] == [f['frame_id'] for f in expected] and r['frame_content_hashes'] == [f['sha256'] for f in expected] and r['actual_source_times_sec'] == [f['time_sec'] for f in expected], 'PUBLIC32_INPUT_MISMATCH'
                        assert not r['output_hit_cap'], 'TRUNCATED'
                        a = parsejson(r['raw_response']).get('answer')
                        a = a.strip().upper() if isinstance(a,str) else None
                        s.update(answer=a if a in list(letters) else None, status='VALID' if a in list(letters) else 'ABSTAIN')
                    except Exception as e:
                        s['error'] = repr(e)
                    v['samples'].append(s)
                    save(target, v)
                v['vote'] = aggregate(v['samples'])
                v['graph_answer'] = q['graph_answer']
                v['strict_agreement'] = v['vote']['strict_majority_answer'] == q['graph_answer'].lower() if v['vote']['strict_majority_status']=='ANSWERED' else None
                v['plurality_agreement'] = v['vote']['plurality_answer'] == q['graph_answer'].lower() if v['vote']['plurality_answer'] else None
                save(target, v)
                votes.append(v)
                jl(root / 'VOTES.jsonl', votes)
                emit('event_v2_vote_complete', review_id=q['review_id'], votes=v['vote']['votes'], strict=v['vote']['strict_majority_status'])
        finally:
            allocation(solver, root / 'Solver')
    assert filehash(root / 'QA_FROZEN.jsonl') == j(root / 'FREEZE.json')['QA_sha256']
    for batch, hh in hashes.items():
        assert all(filehash(BASE / batch / n) == sha for n, sha in hh.items()), 'SOURCE_GRAPH_MODIFIED'
    export(root, accepted, votes, stats)
    save(root / 'STATUS.json', {'stage':'COMPLETE', 'questions':len(accepted), 'vote_sample_slots':sum(len(v['samples']) for v in votes)})
    emit('event_v2_complete', root=str(root), questions=len(accepted))

if __name__ == '__main__':
    main()
