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


class DataSource:
    """Read the committed lightweight baseline or an original data ZIP."""

    def __init__(self, path):
        self.path = path
        self.archive = None

    def __enter__(self):
        if not self.path.is_dir():
            self.archive = ZipFile(self.path)
        return self

    def __exit__(self, *exc):
        if self.archive is not None:
            self.archive.close()

    def read(self, name):
        if self.archive is not None:
            return self.archive.read(name)
        return (self.path / name).read_bytes()

    def contains(self, name):
        if self.archive is not None:
            return name in self.archive.namelist()
        return (self.path / name).is_file()


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
    parser.add_argument('--data', type=Path, default=repo / 'baseline/v2',
                        help='Baseline directory or original STEP_EVENT_MCQ_V2_DATA.zip')
    parser.add_argument('--review', type=Path, default=repo / 'annotations/STEP-EVENT-V2-REVIEW-annotator1.csv')
    parser.add_argument('--output', type=Path, default=repo / 'runs/v2-review',
                        help='New output directory; frozen results/ stays unchanged')
    parser.add_argument('--verify-frames', action='store_true')
    args = parser.parse_args()
    if not args.data.exists():
        parser.error(f'Data source does not exist: {args.data}. See docs/DATA.md.')
    if not args.review.is_file():
        parser.error(f'Review file does not exist: {args.review}')
    review_rows = list(csv.DictReader(io.StringIO(args.review.read_text(encoding='utf-8-sig'))))
    reviews = unique_index(review_rows, 'review_id')
    counts = collections.Counter()
    joined = []
    with DataSource(args.data) as archive:
        required = ['QA_FROZEN.jsonl', 'COMPARISON.jsonl']
        has_raw_samples = archive.contains('VOTES.jsonl')
        if has_raw_samples:
            required.append('VOTES.jsonl')
        if args.verify_frames:
            required.append('FRAME_MANIFEST_PORTABLE.json')
        for name in required:
            if not archive.contains(name):
                parser.error(f'Missing {name} in data source. See docs/DATA.md.')
        if args.verify_frames:
            manifest = json.loads(archive.read('FRAME_MANIFEST_PORTABLE.json'))
            frames = [f for items in manifest.values() for f in items]
            if len(manifest) != 10 or len(frames) != 320:
                raise ValueError('Unexpected video/frame counts')
            if any(not archive.contains(f['relative_path']) for f in frames):
                parser.error('Frame verification needs the full data ZIP or extracted frames. '
                             'Use --data artifacts/STEP_EVENT_MCQ_V2_DATA.zip; see docs/DATA.md.')
        input_sha256 = {name: hashlib.sha256(archive.read(name)).hexdigest()
                        for name in required}
        questions = jsonl(archive.read('QA_FROZEN.jsonl').decode())
        comparisons = jsonl(archive.read('COMPARISON.jsonl').decode())
        votes = (unique_index(jsonl(archive.read('VOTES.jsonl').decode()), 'review_id')
                 if has_raw_samples else None)
        qindex = unique_index(questions, 'review_id')
        cindex = unique_index(comparisons, 'review_id')
        if not (set(qindex) == set(cindex) == set(reviews)):
            raise ValueError('Question, comparison, votes, and review IDs do not match exactly')
        if votes is not None and set(votes) != set(qindex):
            raise ValueError('Raw sample IDs do not match the frozen questions')
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
            stored = {k.upper(): v for k, v in comparison['vote']['votes'].items()}
            if (comparison['vote']['fixed_denominator'] != 10
                    or any(k not in legal or type(n) is not int or n < 0 for k, n in stored.items())
                    or sum(stored.values()) > 10):
                raise ValueError(f'Invalid frozen vote counts: {rid}')
            if votes is not None:
                samples = votes[rid]['samples']
                if len(samples) != 10:
                    raise ValueError(f'Not ten original sampling slots: {rid}')
                tallies = collections.Counter()
                for sample in samples:
                    answer = (sample.get('answer') or '').upper()
                    if sample['status'] == 'VALID' and answer in legal:
                        tallies[answer] += 1
                if dict(tallies) != stored:
                    raise ValueError(f'Raw vote tally differs from frozen comparison: {rid}')
            else:
                tallies = collections.Counter(stored)
            counts['sample_slots'] += comparison['vote']['fixed_denominator']
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
            for frame in frames:
                actual = hashlib.sha256(archive.read(frame['relative_path'])).hexdigest()
                if actual != frame['sha256']:
                    raise ValueError(f"Frame hash mismatch: {frame['relative_path']}")
            counts['verified_frame_hashes'] = len(frames)
    summary = dict(
        reference='One human reviewer, development cohort; not definitive ground truth',
        scorable_definition='legal human option AND answerable_on_public32=yes AND unique_answer=yes',
        strict_majority='at least 6 out of the original 10 slots; original parser only',
        raw_samples_verified=has_raw_samples,
        sample_slots_basis=('raw_sample_records' if has_raw_samples
                            else 'frozen_comparison_fixed_denominator'),
        counts=dict(counts),
        graph_accuracy_on_scorable=fraction(counts['graph_correct'], counts['scorable']),
        majority_answered_accuracy=fraction(counts['majority_correct'], counts['paired']),
        paired_graph_accuracy=fraction(counts['paired_graph_correct'], counts['paired']),
        paired_majority_accuracy=fraction(counts['paired_majority_correct'], counts['paired']),
        majority_coverage_on_scorable=fraction(counts['paired'], counts['scorable']),
        graph_correct_yield_on_scorable=fraction(counts['graph_correct'], counts['scorable']),
        majority_correct_yield_on_scorable=fraction(counts['majority_correct'], counts['scorable']),
        data_sha256=(hashlib.sha256(args.data.read_bytes()).hexdigest()
                     if args.data.is_file() else None),
        input_sha256=input_sha256,
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
