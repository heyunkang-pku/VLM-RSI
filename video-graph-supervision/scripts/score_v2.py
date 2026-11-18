#!/usr/bin/env python3
"""Recompute the frozen v2 single-review comparison; Python standard library only."""
import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile


def jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def unique_index(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if value in result:
            raise ValueError(f"Duplicate {key}: {value}")
        result[value] = row
    return result


def fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=repo / 'artifacts/STEP_EVENT_MCQ_V2_DATA.zip')
    parser.add_argument('--review', type=Path, default=repo / 'annotations/STEP-EVENT-V2-REVIEW-annotator1.csv')
    parser.add_argument('--output', type=Path, default=repo / 'results')
    parser.add_argument('--verify-frames', action='store_true')
    args = parser.parse_args()
    review_rows = list(csv.DictReader(io.StringIO(args.review.read_text(encoding='utf-8-sig'))))
    reviews = unique_index(review_rows, 'review_id')
    counts = collections.Counter()
    joined = []
    with ZipFile(args.data) as archive:
        questions = jsonl(archive.read('QA_FROZEN.jsonl').decode())
        comparisons = jsonl(archive.read('COMPARISON.jsonl').decode())
        votes = unique_index(jsonl(archive.read('VOTES.jsonl').decode()), 'review_id')
        qindex = unique_index(questions, 'review_id')
        cindex = unique_index(comparisons, 'review_id')
        if not (set(qindex) == set(cindex) == set(votes) == set(reviews)):
            raise ValueError('Question, comparison, votes, and review IDs do not match exactly')
        if len(questions) != 26:
            raise ValueError('This tool targets the frozen 26-question v2 cohort')
        for number, question in enumerate(questions, 1):
            rid = question['review_id']
            comparison = cindex[rid]
            review = reviews[rid]
            options = question['options']
            legal = set('ABCD'[:len(options)])
            graph = question['graph_answer'].upper()
            if graph not in legal or comparison['graph_answer'].upper() != graph:
                raise ValueError(f'Invalid or inconsistent graph answer: {rid}')
            samples = votes[rid]['samples']
            if len(samples) != 10:
                raise ValueError(f'Not ten original sampling slots: {rid}')
            tallies = collections.Counter()
            for sample in samples:
                answer = (sample.get('answer') or '').upper()
                if sample['status'] == 'VALID' and answer in legal:
                    tallies[answer] += 1
                counts['sample_slots'] += 1
            stored = {k.upper(): v for k, v in comparison['vote']['votes'].items()}
            if dict(tallies) != stored:
                raise ValueError(f'Raw vote tally differs from frozen comparison: {rid}')
            majority = next((k for k, n in tallies.items() if n >= 6), '')
            stored_majority = (comparison['vote']['strict_majority_answer'] or '').upper()
            if majority != stored_majority:
                raise ValueError(f'Strict-majority result differs: {rid}')
            human = review['independent_answer'].upper()
            scorable = (human in legal and review['answerable_on_public32'] == 'yes'
                        and review['unique_answer'] == 'yes')
            counts['total'] += 1
            counts['majority_answered'] += bool(majority)
            counts['graph_vote_agreement'] += bool(majority) and graph == majority
            full_disagreement = bool(majority) and graph != majority and tallies[majority] == 10
            counts['full_vote_disagreements'] += full_disagreement
            if scorable:
                counts['scorable'] += 1
                counts['graph_correct'] += graph == human
                counts['majority_correct'] += majority == human
                counts['majority_wrong'] += bool(majority) and majority != human
                counts['majority_abstained'] += not majority
                if majority:
                    counts['paired'] += 1
                    counts['paired_graph_correct'] += graph == human
                    counts['paired_majority_correct'] += majority == human
                    outcome = ('both_correct' if graph == human and majority == human else
                               'only_graph_correct' if graph == human else
                               'only_majority_correct' if majority == human else 'both_wrong')
                    counts[outcome] += 1
            else:
                counts['unscorable'] += 1
                counts['unscorable_majority_answered'] += bool(majority)
            joined.append(dict(
                review_number=number, review_id=rid, video_id=question['video_id'],
                type=question['type'], question=question['question'],
                options=json.dumps(options, ensure_ascii=False), graph_answer=graph,
                majority_answer=majority, votes=json.dumps(dict(tallies), sort_keys=True),
                human_answer=human, annotator_id=review['annotator_id'],
                answerable_on_public32=review['answerable_on_public32'],
                unique_answer=review['unique_answer'], requires_multiframe=review['requires_multiframe'],
                scorable=scorable, graph_correct=(graph == human if scorable else ''),
                majority_correct=(majority == human if scorable and majority else ''),
                full_vote_disagreement=full_disagreement))
        if args.verify_frames:
            manifest = json.loads(archive.read('FRAME_MANIFEST_PORTABLE.json'))
            frames = [f for items in manifest.values() for f in items]
            if len(manifest) != 10 or len(frames) != 320:
                raise ValueError('Unexpected video/frame counts')
            for frame in frames:
                actual = hashlib.sha256(archive.read(frame['relative_path'])).hexdigest()
                if actual != frame['sha256']:
                    raise ValueError(f"Frame hash mismatch: {frame['relative_path']}")
            counts['verified_frame_hashes'] = len(frames)
    summary = dict(
        reference='One human reviewer, development cohort; not definitive ground truth',
        scorable_definition='legal human option AND answerable_on_public32=yes AND unique_answer=yes',
        strict_majority='at least 6 out of the original 10 slots; original parser only',
        counts=dict(counts),
        graph_accuracy_on_scorable=fraction(counts['graph_correct'], counts['scorable']),
        majority_answered_accuracy=fraction(counts['majority_correct'], counts['paired']),
        paired_graph_accuracy=fraction(counts['paired_graph_correct'], counts['paired']),
        paired_majority_accuracy=fraction(counts['paired_majority_correct'], counts['paired']),
        majority_coverage_on_scorable=fraction(counts['paired'], counts['scorable']),
        graph_correct_yield_on_scorable=fraction(counts['graph_correct'], counts['scorable']),
        majority_correct_yield_on_scorable=fraction(counts['majority_correct'], counts['scorable']),
        data_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
        review_sha256=hashlib.sha256(args.review.read_bytes()).hexdigest())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'V2_SINGLE_REVIEW_SUMMARY.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with (args.output / 'V2_REVIEW_JOINED.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(joined[0]))
        writer.writeheader()
        writer.writerows(joined)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
