#!/usr/bin/env python

"""
Compare collapsed, filtered isoseq outputs against ground truth
reference transcripts.
Usage:
    compare_reference_transcripts.py isoseq_output.fasta reference_transcripts.fasta output
"""
from __future__ import print_function

import argparse
import sys

from pbcore.io import FastaReader, FastqReader, FastaWriter
from pbtranscript.io import BLASRM5Reader
from pbtranscript.Utils import execute, realpath, real_upath


def is_fuzzy(r, max_fuzzy_junction):
    """Return True if max consecutive mismatches <= max_fuzzy_junction; else False."""
    max_mismatches = 0
    mismatches = 0
    for m in r.alnStr:
        if m == '|':
            max_mismatches = max(max_mismatches, mismatches)
            mismatches = 0
        else:
            mismatches += 1
    max_mismatches = max(max_mismatches, mismatches)
    return max_mismatches <= max_fuzzy_junction


class CompareReferenceTranscripts(object):
    """Compare collapsed filtered isoseq outputs in FASTA
       against reference transcripts."""
    def __init__(self, isoseq_output_fn, reference_transcripts_fn,
                 output_analysis_fn, min_true_positive, max_false_positive,
                 min_seq_similarity, max_fuzzy_junction):
        self.isoseq_output_fn = isoseq_output_fn
        self.reference_transcripts_fn = reference_transcripts_fn
        self.output_analysis_fn = output_analysis_fn

        if isoseq_output_fn.endswith(".fasta") or isoseq_output_fn.endswith(".fa"):
            self.isoforms = [r for r in FastaReader(isoseq_output_fn)]
            self.isoseq_output_fa = self.isoseq_output_fn
        elif isoseq_output_fn.endswith(".fastq") or isoseq_output_fn.endswith(".fq"):
            self.isoforms = [r for r in FastqReader(isoseq_output_fn)]
            self.isoseq_output_fa = self.output_analysis_fn + ".isoseq.fa"
            with FastaWriter(self.isoseq_output_fa) as writer:
                for r in self.isoforms:
                    writer.writeRecord(r.name, r.sequence)

        self.reference_transcripts = [r for r in FastaReader(reference_transcripts_fn)]

        self.min_true_positive = min_true_positive
        self.max_false_positive = max_false_positive
        self.min_seq_similarity = min_seq_similarity if min_seq_similarity <= 1 \
                                  else min_seq_similarity / 100.0
        self.max_fuzzy_junction = max_fuzzy_junction

        self.alns = self.filter_alns(self.map_isoforms_to_reference_transcripts())

    def map_isoforms_to_reference_transcripts(self):
        """Map isoforms to reference transcripts."""
        m5out = self.output_analysis_fn + ".blasr.out.m5"
        cmd = 'blasr %s %s --bestn 1 -m 5 --out %s' % \
              (real_upath(self.isoseq_output_fa),
               real_upath(self.reference_transcripts_fn),
               real_upath(m5out))
        execute(cmd)
        return [r for r in BLASRM5Reader(m5out)]

    def filter_alns(self, alns):
        """Filter alignments based on similarity"""
        _alns = []
        for r in alns:
            if r.identity / 100.0 < self.min_seq_similarity:
                print("Ignored mapping (%s, %s) because identity %s < %s" % \
                        (r.qID, r.sID, r.identity / 100.0, self.min_seq_similarity))
                continue
            if not is_fuzzy(r, self.max_fuzzy_junction):
                print("Ignored mapping (%s, %s) because edit distance > %s" % \
                        (r.qID, r.sID, self.max_fuzzy_junction))
                continue

            _alns.append(r)
        print("Ignored %s mappings in total" % (len(alns) - len(_alns)), end=' ')
        return _alns

    @property
    def refs_detected(self):
        """Return a set of reference transcripts detected."""
        return set([a.sID for a in self.alns])

    @property
    def n_refs_detected(self):
        """Return number of reference transcripts detected."""
        return len(self.refs_detected)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        errmsgs = []
        if self.n_true_positive < self.min_true_positive:
            errmsgs.append("num of true positive %s < %s" %
                           (self.n_true_positive, self.min_true_positive))
        if self.n_false_positive > self.max_false_positive:
            errmsgs.append("num of false positive %s > %s" %
                           (self.n_false_positive, self.max_false_positive))
        if len(errmsgs) != 0:
            raise ValueError("\n".join(errmsgs))

    @property
    def n_refs(self):
        """number of reference transcripts in total"""
        return len(self.reference_transcripts)

    @property
    def n_isoforms(self):
        """number of isoforms."""
        return len(self.isoforms)

    @property
    def n_true_positive(self):
        """Return number of true positives"""
        return self.n_refs_detected

    @property
    def n_false_positive(self):
        """Return number of false positives (isoforms not in reference transcripts set)"""
        return self.n_isoforms - self.n_refs_detected

    def run(self):
        """Run"""
        writer = open(self.output_analysis_fn, 'w')
        writer.write("#isoseq_output_fn = %s\n" % realpath(self.isoseq_output_fn))
        writer.write("#reference_transcripts_fn = %s\n" % realpath(self.reference_transcripts_fn))

        writer.write("#total_num_isoforms = %s\n" % self.n_isoforms)
        writer.write("#total_num_reference_transcripts = %s\n" % self.n_refs)

        writer.write("#num_true_positive = %s\n" % self.n_true_positive)
        writer.write("#num_false_positive = %s\n" % self.n_false_positive)

        for ref in self.reference_transcripts:
            is_detected = ref.name in self.refs_detected
            writer.write("%s\t%s\t%s\n" % (ref.name, len(ref.sequence),
                                           'DETECTED' if is_detected else 'MISSED'))
        writer.close()


def run(args):
    """Construct an instance of Compare_IsoSeq_Runs and do the comparison."""
    with CompareReferenceTranscripts(isoseq_output_fn=args.isoseq_output_fn,
                                     reference_transcripts_fn=args.reference_transcripts_fn,
                                     output_analysis_fn=args.output_analysis_fn,
                                     min_true_positive=args.min_true_positive,
                                     max_false_positive=args.max_false_positive,
                                     min_seq_similarity=args.min_seq_similarity,
                                     max_fuzzy_junction=args.max_fuzzy_junction) as runner:
        runner.run()

def get_parser():
    """Get argument parser."""
    helpstr = "Compare collapsed filtered isoforms in FASTA/FASTQ generated by Iso-Seq" + \
              "against ground truth reference transcripts."
    parser = argparse.ArgumentParser(description=helpstr)
    parser.add_argument("isoseq_output_fn", action="store", type=str,
                        help="Collapsed filtered isoforms in FASTA/FASTQ generated by Iso-Seq")
    parser.add_argument("reference_transcripts_fn", action="store", type=str,
                        help="Ground truth reference transcripts in FASTA")
    parser.add_argument("output_analysis_fn", action="store", type=str,
                        help="Output analysis file")
    parser.add_argument("--min_true_positive", action="store", type=int, default=0,
                        help="Minimum number of true positives to consider Iso-Seq run successful")
    parser.add_argument("--max_false_positive", action="store", type=int, default=sys.maxsize,
                        help="Maximum number of false positives (collapsed filtered isoforms " +
                        "which are not in reference set) to consider Iso-Seq run successful")
    parser.add_argument("--min_seq_similarity", action="store", dest="min_seq_similarity",
                        type=float, help="Minimum sequence similarity.", default=0.99)
    parser.add_argument("--max_fuzzy_junction", action="store", dest="max_fuzzy_junction",
                        type=int, default=5,
                        help="Maximum edit distance between exons to consider them mergable.")
    return parser

if __name__ == "__main__":
    run(get_parser().parse_args(sys.argv[1:]))
