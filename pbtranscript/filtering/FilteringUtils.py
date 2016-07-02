#!/usr/bin/env python
"""
Filter collapsed isoforms by count or subset.
"""
import os.path as op

from collections import defaultdict
from pbcore.io import FastaReader, FastaWriter, FastqReader, FastqWriter
from pbtranscript.io import GroupReader, AbundanceReader, AbundanceWriter, \
        CollapseGffReader, CollapseGffWriter, SampleIsoformName, parse_ds_filename
from pbtranscript.collapsing import can_merge, compare_fuzzy_junctions


__author__ = 'etseng@pacb.com'


__all__ = ["filter_by_count", "filter_out_subsets"]


def good_isoform_ids_by_count(in_group_filename, in_abundance_filename, min_count):
    """Return a list of collapsed isoforms ids whose supportive FL
    count >= min_count.
    Parameters:
      in_group_filename -- group file of collapsed isoforms
      in_abundance_filename -- abundance file of collapsed isoforms
      min_count -- min number of supportive FL reads to be 'good'
    """
    # read group file
    group_max_count_fl = {}
    group_max_count_nfl = {}
    with GroupReader(in_group_filename) as g_reader:
        for g in g_reader:
            pbid, members = g.name, g.members
            group_max_count_fl[pbid] = 0
            group_max_count_nfl[pbid] = 0
            for m in members:
                s = SampleIsoformName.fromString(m)
                group_max_count_fl[pbid] = max(group_max_count_fl[pbid], s.num_fl)
                group_max_count_nfl[pbid] = max(group_max_count_nfl[pbid], s.num_nfl)

    # read abundance to decide good collapsed isoforms based on count
    good = [r.pbid for r in AbundanceReader(in_abundance_filename)
            if r.count_fl >= min_count and group_max_count_fl[r.pbid] >= min_count]

    return good


def remove_subset_isoforms_from_list(recs, max_fuzzy_junction):
    """Given a list of collapsed isoform records, remove
    records which are a subset of any other record.
    Parameters:
      recs -- a list of records, sorted by start
      max_fuzzy_junction -- max edit distance to merge two fuzzy junctions.
    """
    # recs must be sorted by start becuz that's the order they are written
    i = 0
    while i < len(recs)-1:
        j = i + 1
        while j < len(recs):
            if recs[j].start > recs[i].end:
                break
            m = compare_fuzzy_junctions(r1_exons=recs[i].ref_exons, r2_exons=recs[j].ref_exons,
                                        max_fuzzy_junction=max_fuzzy_junction)
            if can_merge(m=m, r1=recs[i], r2=recs[j], allow_extra_5exon=True,
                         max_fuzzy_junction=max_fuzzy_junction):
                if m == 'super': # pop recs[j]
                    recs.pop(j)
                else:
                    recs.pop(i)
                    j += 1
            else:
                j += 1
        i += 1


def good_isoform_ids_by_removing_subsets(in_gff_filename, max_fuzzy_junction):
    """Return a list of collapsed isoforms ids by removing isoforms which
    are a subset of any other isoform.
    Parameters:
      in_gff_filename -- input collapsed gff file
    """
    recs_dict = defaultdict(lambda: [])

    with CollapseGffReader(in_gff_filename) as gff_reader:
        for r in gff_reader:
            assert r.seqid.startswith('PB.')
            recs_dict[int(r.seqid.split('.')[1])].append(r)

    good = []
    keys = recs_dict.keys()
    keys.sort()
    for k in recs_dict:
        recs = recs_dict[k]
        remove_subset_isoforms_from_list(recs, max_fuzzy_junction=max_fuzzy_junction)
        for r in recs:
            good.append(r.seqid)

    return good


def _validate_inputs(in_group_filename=None, in_abundance_filename=None,
                     in_gff_filename=None, in_rep_filename=None):
    """Validate existence of inputs."""
    def _validate_one_input(in_filename, filetype):
        if in_filename is not None and not op.exists(in_filename):
            raise IOError("Could not find %s file %s" % (filetype, in_filename))

    _validate_one_input(in_rep_filename, "rep")
    _validate_one_input(in_group_filename, "group")
    _validate_one_input(in_abundance_filename, "abundance")
    _validate_one_input(in_gff_filename, "gff")


def write_good_collapsed_isoforms(in_abundance_filename, in_gff_filename, in_rep_filename,
                                  out_abundance_filename, out_gff_filename, out_rep_filename,
                                  good):
    """Write good collapsed isoforms."""
    in_suffix = parse_ds_filename(in_rep_filename)[1]
    out_suffix = parse_ds_filename(out_rep_filename)[1]
    if in_suffix != out_suffix:
        raise ValueError("Format of input %s and output %s must match." %
                         (in_rep_filename, out_rep_filename))
    if in_suffix not in ("fasta", "fastq"):
        raise ValueError("Format of input %s and output %s must be either FASTA or FASTQ." %
                         (in_rep_filename, out_rep_filename))

    # then read gff, and write good gff record.
    with CollapseGffWriter(out_gff_filename) as gff_writer:
        for r in CollapseGffReader(in_gff_filename):
            if r.seqid in good:
                gff_writer.writeRecord(r)

    # next read rep fasta/fastq, and write good rep fasta/fastq record.
    rep_reader = FastaReader(in_rep_filename) if in_suffix == "fasta" \
                 else FastqReader(in_rep_filename)
    rep_writer = FastaWriter(out_rep_filename) if in_suffix == "fasta" \
                 else FastqWriter(out_rep_filename)
    for r in rep_reader:
        # r.name e.g., PB.1.1|PB.1.1:10712-11643(+)|i0_HQ_sample18ba5d|c1543/f8p1/465
        if r.name.split('|')[0] in good:
            rep_writer.writeRecord(r)

    # finally write abundance info of good records.
    with AbundanceReader(in_abundance_filename) as a_reader, \
        AbundanceWriter(out_abundance_filename, comments=a_reader.comments) as a_writer:
        for r in a_reader:
            if r.pbid in good:
                a_writer.writeRecord(r)


def filter_by_count(in_group_filename, in_abundance_filename,
                    in_gff_filename, in_rep_filename,
                    out_abundance_filename, out_gff_filename, out_rep_filename,
                    min_count):
    """Remove collapsed isoforms in in_rep_filename whose supportive
       FLNC reads <= min_count, and write the remaining good collapsed isoforms
       to output abundance file, gff file, and rep.fasta|fastq file.

    Parameters:
      in_group_filename -- collapsed isoforms' pbid --> associated ICE clusters
      in_abundance_filename -- collapsed isoforms' pbid, count_fl, count_nfl, ...
      in_gff_filename -- collapsed isoforms' pbid, chr, strand, start, end, ...
      in_rep_filename -- representative sequences of collapsed isoforms
      min_count -- min number of supportive FL reads to classify a collapsed isoform as good
    """
    _validate_inputs(in_group_filename=in_group_filename,
                     in_abundance_filename=in_abundance_filename,
                     in_gff_filename=in_gff_filename,
                     in_rep_filename=in_rep_filename)

    good = good_isoform_ids_by_count(in_group_filename=in_group_filename,
                                     in_abundance_filename=in_abundance_filename,
                                     min_count=min_count)

    write_good_collapsed_isoforms(in_abundance_filename=in_abundance_filename,
                                  in_gff_filename=in_gff_filename,
                                  in_rep_filename=in_rep_filename,
                                  out_abundance_filename=out_abundance_filename,
                                  out_gff_filename=out_gff_filename,
                                  out_rep_filename=out_rep_filename, good=good)


def filter_out_subsets(in_abundance_filename, in_gff_filename, in_rep_filename,
                       out_abundance_filename, out_gff_filename, out_rep_filename,
                       max_fuzzy_junction):
    """Remove collapsed isoforms in in_rep_filename which are a subset of
       another isoform, and wirte the remaining good isoforms to output
       abundance file, gff file, rep.fasta|fastq file.
    Parameters:
       max_fuzzy_junction -- max edit distance between fuzzy junctions
    """
    _validate_inputs(in_abundance_filename=in_abundance_filename,
                     in_gff_filename=in_gff_filename,
                     in_rep_filename=in_rep_filename)

    good = good_isoform_ids_by_removing_subsets(in_gff_filename=in_gff_filename,
                                                max_fuzzy_junction=max_fuzzy_junction)

    write_good_collapsed_isoforms(in_abundance_filename=in_abundance_filename,
                                  in_gff_filename=in_gff_filename,
                                  in_rep_filename=in_rep_filename,
                                  out_abundance_filename=out_abundance_filename,
                                  out_gff_filename=out_gff_filename,
                                  out_rep_filename=out_rep_filename, good=good)
