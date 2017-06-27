#!/usr/bin/env python

"""
Utils for mapping isoforms to reference genomes and sort.

Class ContiVec encodes base coverage and evidence of alternative junctions
of an isoform as np.array, and provides function to_exons() in order to
convert np.array to exons.
"""

import os
import os.path as op
import logging
import random
import string
from collections import defaultdict
import numpy as np
from pbcore.io import FastaWriter, FastqWriter, ContigSet
from pbtranscript.Utils import execute, rmpath, as_contigset, realpath
from pbtranscript.io import ContigSetReaderWrapper, FastaRandomReader, FastqRandomReader, \
    CollapseGffRecord, CollapseGffReader, CollapseGffWriter, \
    GroupRecord, GroupReader, GroupWriter, parse_ds_filename
from pbtranscript.collapsing import c_branch, IntervalTree

__all__ = ["ContiVec",
           "copy_sam_header",
           "map_isoforms_and_sort",
           "sort_sam",
           "concatenate_sam",
           "transfrag_to_contig",
           "exons_match_sam_record",
           "compare_exon_matrix",
           "iterative_merge_transcripts",
           "get_fl_from_id",
           "can_merge",
           "collapse_sam_records",
           "compare_fuzzy_junctions",
           "collapse_fuzzy_junctions",
           "pick_rep"]

logger = logging.getLogger(op.basename(__file__))


def copy_sam_header(in_sam, out_sam):
    """Copy headers of input sam to output sam."""
    with open(in_sam, 'r') as reader, \
        open(out_sam, 'w') as writer:
        for line in reader:
            if line.startswith('@'):
                writer.write(line)
            else:
                break


def map_isoforms_and_sort(input_filename, sam_filename,
                          gmap_db_dir, gmap_db_name, gmap_nproc):
    """
    Map isoforms to references by gmap, generate a sam output and sort sam.
    Parameters:
        input_filename -- input isoforms. e.g., hq_isoforms.fasta|fastq|xml
        sam_filename -- output sam file, produced by gmap and sorted.
        gmap_db_dir -- gmap database directory
        gmap_db_name -- gmap database name
        gmap_nproc -- gmap nproc
    """
    unsorted_sam_filename = sam_filename + ".tmp"
    log_filename = sam_filename + ".log"

    gmap_input_filename = input_filename
    if input_filename.endswith('.xml'):
        # must consolidate dataset xml to FASTA/FASTQ
        w = ContigSetReaderWrapper(input_filename)
        gmap_input_filename = w.consolidate(out_prefix=sam_filename+'.input')
    if not op.exists(gmap_input_filename):
        raise IOError("Gmap input file %s does not exists" % gmap_input_filename)

    # In order to prevent mount issues, cd to ${gmap_db_dir} and ls ${gmap_db_name}.* files
    cwd = realpath(os.getcwd())
    cmd_args = ['cd %s' % op.join(gmap_db_dir, gmap_db_name),
                'ls *.iit *meta', 'sleep 3', 'cd %s' % cwd]
    execute(' && '.join(cmd_args))

    cmd_args = ['gmap', '-D {d}'.format(d=gmap_db_dir),
                '-d {name}'.format(name=gmap_db_name),
                '-t {nproc}'.format(nproc=gmap_nproc),
                '-n 0',
                '-z sense_force',
                '--cross-species',
                '-f samse',
                '--max-intronlength-ends 200000', # for long genes
                gmap_input_filename,
                '>', unsorted_sam_filename,
                '2>{log}'.format(log=log_filename)]
    # Call gmap to map isoforms to reference and output sam.
    try:
        execute(' '.join(cmd_args))
    except Exception:
        logging.debug("gmap failed, try again.")
        execute('sleep 3')
        execute(' '.join(cmd_args))

    # sort sam file
    sort_sam(in_sam=unsorted_sam_filename, out_sam=sam_filename)

    # remove intermediate unsorted sam file.
    rmpath(unsorted_sam_filename)


def sort_sam(in_sam, out_sam):
    """
    Sort input sam file and write to output sam file.
    """
    # Copy SAM headers
    copy_sam_header(in_sam=in_sam, out_sam=out_sam)

    # Call sort to sort gmap output sam file
    cmd_args = ['sort', '-k 3,3', '-k 4,4n', in_sam,
                '| grep -v \'^@\' ', ' >> ', out_sam]

    if os.stat(in_sam).st_size == 0: # overwrite cmds if file is empty
        cmd_args = ['touch', out_sam]

    execute(' '.join(cmd_args))


def concatenate_sam(in_sam_files, sam_out):
    """Concatenate input sam files to sam_out."""
    if sam_out in in_sam_files:
        raise IOError("Can not overwrite input sam file %s as output file." % sam_out)

    def _get_pgid(r):
        """return pbid from a PG header '@PG\tID:xxx\t...'"""
        assert r.startswith('@PG')
        return [i[3:] for i in r.split('\t') if i.startswith('ID:')][0]

    def _get_pgheader(r, pg_ids):
        """if PG ID of a PG header l is in set pg_ids, make a PG header with a new ID;
        otherwise, return l"""
        assert r.startswith('@PG')
        pgid = _get_pgid(r)
        if pgid not in pg_ids:
            return r
        suffix = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))
        ret = [i for i in r.split('\t') if not i.startswith('ID:')]
        ret.insert(1, "ID:%s_%s" % (pgid, suffix))
        return '\t'.join(ret)

    # First save sam headers in c_header
    c_header = []
    has_hd = False
    pg_ids = set()
    for in_sam in in_sam_files:
        with open(in_sam, 'r') as reader:
            for r in reader:
                r = r.strip()
                if r.startswith("@"):
                    if r.startswith("@HD") and not has_hd:
                        has_hd = True
                        c_header.append(r)
                    else:
                        if r.startswith("@PG"):
                            try:
                                c_header.append(_get_pgheader(r, pg_ids))
                                pg_ids.add(_get_pgid(r))
                            except ValueError: # ignore bad PG
                                pass
                        elif r not in c_header:
                            c_header.append(r)
                else:
                    break

    # Start to write
    with open(sam_out, 'w') as writer:
        writer.write("\n".join(c_header) + "\n")
        for in_sam in in_sam_files:
            with open(in_sam, 'r') as reader:
                for r in reader:
                    r = r.strip()
                    if not r.startswith("@"):
                        writer.write("%s\n" % r)


INTINF = 999999

def transfrag_to_contig(gmap_sam_records, skip_5_exon_alt=True):
    """
    Goes through a set of overlapping GMAP records (strand-aware), and
    fills in the baseC (base coverage)

    Returns contiVec, offset, chrom, strand
    """
    records = gmap_sam_records
    assert len(records) > 0
    # first figure out how long the "pseudo-chromosome" size is
    offset = records[0].sStart
    chrom = records[0].sID
    strand = records[0].flag.strand

    # set of this fake "chromosome" to be as long as needed
    chrom_size = max(x.sEnd for x in records) - records[0].sStart

    contiVec = ContiVec(chrom_size)
    for r in records:
        for i, e in enumerate(r.segments):
            # fill base coverage
            contiVec.baseC[(e.start-offset):(e.end-offset)] += 1

            # in the original code, the mapped start altC was set to -MAX and end to MAX
            # add this alt. of beginning if
            # (a) not first or last exon
            # (b) is first exon and strand - (so is 3')
            # (c) is first exon and strand + and not skip_5_exon_alt (so is 5')
            # (d) is last exon and strand - and not skip_5_exon_alt (so is 5')
            # (e) is last exon and strand + (so is 3')
            if (i != 0) or (i != len(r.segments)-1) or \
                (i == 0 and (strand == '-' or not skip_5_exon_alt)) or \
                (i == len(r.segments)-1 and (strand == '+' or not skip_5_exon_alt)):
                contiVec.altC_neg[(e.start-offset)] -= INTINF
            # add this alt. of end if
            # (a) not first or last exon
            # (b) is last exon and strand + (so is 3')
            # (c) is last exon and strand - and not skip_5_exon_alt (so is 5')
            # (d) is first exon and strand + and not skip_5_exon_alt (so is 5')
            # (e) is first exon and strand - (so is 3')
            if (i != 0) or (i != len(r.segments)-1) or \
                (i == len(r.segments) - 1 and (strand == '-' or not skip_5_exon_alt)) or \
                (i == 0 and (strand == '+' or not skip_5_exon_alt)):
                contiVec.altC_pos[(e.end-offset-1)] += INTINF  # adjust to 0-based
    return contiVec, offset, chrom, strand


def exons_match_sam_record(record, exons,
                           tolerate_middle=0, tolerate_end=10**4,
                           ok_to_miss_matches=False, intervals_adjacent=True):
    """
    Goes through segments in the input sam record and check if it matches any exon
    in input exons.
    Returns [matches], a list of exons that the input record and exons share.

    record --- a gmap SAM record containing the full contig alignment of a FL long read
    exons --- exons (an Interval node tree obj) created from a grouped sam records
    """
    result = []
    num_exons = len(record.segments)
    for i, e in enumerate(record.segments):
        # allow the first and last exon to be longer or shorter in
        # either the long read or the detected exons
        # however for middle exons the matching should be pretty precise
        # TODO: parameterize this
        if i == 0 and num_exons > 1:
            tolerate_l = tolerate_end
            tolerate_r = tolerate_middle
        elif i == 0 and num_exons == 1:
            tolerate_l = tolerate_end
            tolerate_r = tolerate_end
        elif i == len(record.segments) - 1 and num_exons > 1:
            tolerate_l = tolerate_middle
            tolerate_r = tolerate_end
        else:
            tolerate_l = tolerate_middle
            tolerate_r = tolerate_middle
        matches = c_branch.exon_matching(exon_tree=exons, ref_exon=e,
                                         match_extend_tolerate_left=tolerate_l,
                                         match_extend_tolerate_right=tolerate_r,
                                         intervals_adjacent=intervals_adjacent)
        if matches is None:
            if not ok_to_miss_matches:
                return None
        else:
            if (len(result) >= 1 and result[-1].value >= matches[0].value) and \
                (not ok_to_miss_matches):
                return None
            result += matches
    return result


def compare_exon_matrix(m1, m2, node_d, strand, merge5=True):
    """
    m1, m2 are 1-d array where m1[0, i] is 1 if it uses the i-th exon, otherwise 0
    compare the two and merge them if they are compatible
    (i.e. only differ by first/last exon ends)

    merge5 -- if True, allow extra 5' exons as long as the rest is the same
              if False, then m1 and m2 must have the same first (5') exon and only allowed
                        if the difference is the very start

    an example of exon matrix m = np.asarray([ [1, 0, 1, 1, 1, 1, 0] ]) indicates
    that m contains exons of indices (0, 2, 3, 4, 5), mssing exons of indices(1, 6)

    return {True|False}, {merged array|None}
    """
    l1 = m1.nonzero()[1]
    l2 = m2.nonzero()[1]

    # let l1 be the one that has the earliest start
    if l2[0] < l1[0]:
        l1, l2 = l2, l1

    # does not intersect at all
    if l1[-1] < l2[0]:
        return False, None

    n1 = len(l1)
    n2 = len(l2)

    # not ok if this is at the 3' end and does not share the last exon;
    # if 5' end, ok to miss exons as long as rest agrees
    i, j = None, None
    for i in xrange(n1):
        if l1[i] == l2[0]:
            break
        elif i > 0 and (strand == '-' and node_d[l1[i-1]].end != node_d[l1[i]].start):
            return False, None # 3' end disagree
        elif i > 0 and (strand == '+' and not merge5 and node_d[l1[i-1]].end != node_d[l1[i]].start):
            # 5' end disagree, in other words m1 has an extra 5' exon that
            # m2 does not have and merge5 is no allowed
            return False, None
    # at this point: l1[i] == l2[0]
    assert i is not None

    for j in xrange(i, min(n1, n2+i)):
        # matching l1[j] with l2[j-i]
        if l1[j] != l2[j-i]: # they must not match
            return False, None
    assert j is not None

    # pre: l1 and l2 agree up to j, j-i
    if j == n1-1: # check that the remaining of l2 are adjacent
        if j-i == n2-1:
            return True, m1
        for k in xrange(j-i+1, n2):
            # case 1: this is the 3' end, check that there are no additional 3' exons
            if strand == '+' and node_d[l2[k-1]].end != node_d[l2[k]].start:
                return False, None
            # case 2: this is the 5' end, check that there are no additional 5' exons unless allowed
            if strand == '-' and not merge5 and node_d[l2[k-1]].end != node_d[l2[k]].start:
                return False, None
        m1[0, l2[j-i+1]:] = m1[0, l2[j-i+1]:] + m2[0, l2[j-i+1]:]
        return True, m1
    elif j-i == n2-1:
        for k in xrange(j+1, n1):
            # case 1, but for m1
            if strand == '+' and node_d[l1[k-1]].end != node_d[l1[k]].start:
                return False, None
            # case 2, but for m1
            if strand == '-' and not merge5 and node_d[l1[k-1]].end != node_d[l1[k]].start:
                return False, None
        return True, m1

    raise Exception, "Should not happen"


def iterative_merge_transcripts(result_list, node_d, merge5=True):
    """
    result_list --- list of (qID, strand, binary exon sparse matrix)
    """
    # sort by strand then starting position
    result_list.sort(key=lambda x: (x[1], x[2].nonzero()[1][0]))
    i = 0
    while i < len(result_list) - 1:
        j = i + 1
        while j < len(result_list):
            id1, strand1, m1 = result_list[i]
            id2, strand2, m2 = result_list[j]
            if (strand1 != strand2) or (m1.nonzero()[1][-1] < m2.nonzero()[1][0]):
                break
            else:
                flag, m3 = compare_exon_matrix(m1, m2, node_d, strand1, merge5)
                if flag:
                    result_list[i] = (id1+','+id2, strand1, m3)
                    result_list.pop(j)
                else:
                    j += 1
        i += 1


class ContiVec(object):
    """
    Original struct: 'BC'
    """
    def __init__(self, size):
        # baseC was .B in the original code, base coverage
        self.baseC = np.zeros(size, dtype=np.int)
        # altC_pos was .C in the original code, evidence for alternative junction
        self.altC_pos = np.zeros(size, dtype=np.int)
        self.altC_neg = np.zeros(size, dtype=np.int)

    def __eq__(self, other):
        return all(self.baseC == other.baseC) and \
               all(self.altC_pos == other.altC_pos) and \
               all(self.altC_neg == other.altC_neg)

    def to_exons(self, offset):
        """
        Go through this contiVec to identify the exons using base coverage (.baseC)
        and alt junction evidence (.altC)
        Returns exons found.
        """
        return c_branch.exon_finding(baseC=self.baseC, altC_neg=self.altC_neg,
                                     altC_pos=self.altC_pos, size=len(self.baseC),
                                     threshSplit=2, threshBase=0, offset=offset)


def collapse_sam_records(records, cuff_index, cov_threshold,
                         allow_extra_5exon, skip_5_exon_alt,
                         good_gff_writer, bad_gff_writer, group_writer,
                         tolerate_end=100, starting_isoform_index=0, gene_prefix='PB'):
    """
    Given a set of gmap sam records
    (1) parse them by running through transfrag_to_contig, and return contiVec
    (2) find exons based on contiVec
    (3) go through each record, get the list of "nodes" they corresspond to
    (4) collapse identical records (53mergeing)

    Write collapsed isoforms out to GTF format. Collapsed isoforms with
    coverage > cov_threshold go to good_gff_writer, otherwise, go to bad_gff_writer.
    Write supportive records of collapsed isoforms to group_writer.

    Returns result and merged_result, where
    result: [ (r.qID, r.strand, nparray representing r) for r in records]
    result_merge: merged result
    """
    contiVec, offset, chrom, strand = transfrag_to_contig(gmap_sam_records=records,
                                                          skip_5_exon_alt=skip_5_exon_alt)
    exons = contiVec.to_exons(offset=offset)

    p = []
    exons.traverse(p.append)
    node_d = dict((x.interval.value, x) for x in p)
    mat_size = max(x.interval.value for x in p) + 1
    result = []
    for r in records:
        matched_exons = exons_match_sam_record(record=r, exons=exons, tolerate_end=tolerate_end)
        m = np.zeros((1, mat_size), dtype=np.int)
        for _exon in matched_exons:
            m[0, _exon.value] = 1
        result.append((r.qID, r.flag.strand, m))

    result_merged = list(result)
    iterative_merge_transcripts(result_merged, node_d, allow_extra_5exon)

    if len(result) > 0 and len(result_merged) > 0:
        logging.debug("merged %s (%s, ...) down to %s transcripts",
                      len(result), result[0][0], len(result_merged))

    isoform_index = starting_isoform_index
    # make the exon value --> interval dictionary

    for ids, _strand, m in result_merged:
        assert strand == _strand
        if ids.count(',')+1 < cov_threshold:
            f_out = bad_gff_writer
        else:
            f_out = good_gff_writer
        isoform_index += 1
        segments = [node_d[x] for x in m.nonzero()[1]]

        gene_id = "{p}.{i}".format(p=gene_prefix, i=cuff_index)
        transcript_id = "{g}.{j}".format(g=gene_id, j=isoform_index)
        group_writer.writeRecord(GroupRecord(name=transcript_id, members=ids.split(',')))

        gff_record = CollapseGffRecord(seqid=chrom, feature='transcript',
                                       start=segments[0].start+1, end=segments[-1].end,
                                       strand=strand, gene_id=gene_id, transcript_id=transcript_id)
        f_out.writeRecord(gff_record)

        i = 0
        j = 0
        for j in xrange(1, len(segments)):
            if segments[j].start != segments[j-1].end:
                gene_id = "{p}.{i}".format(p=gene_prefix, i=cuff_index)
                transcript_id = "{g}.{j}".format(g=gene_id, j=isoform_index)
                gff_record = CollapseGffRecord(seqid=chrom, feature='exon',
                                               start=segments[i].start+1, end=segments[j-1].end,
                                               strand=strand, gene_id=gene_id, transcript_id=transcript_id)
                f_out.writeRecord(gff_record)
                i = j

        # write the last one
        gene_id = "{p}.{i}".format(p=gene_prefix, i=cuff_index)
        transcript_id = "{g}.{j}".format(g=gene_id, j=isoform_index)
        gff_record = CollapseGffRecord(seqid=chrom, feature='exon',
                                       start=segments[i].start+1, end=segments[j].end,
                                       strand=strand, gene_id=gene_id, transcript_id=transcript_id)
        f_out.writeRecord(gff_record)

    return result, result_merged


def overlaps(s1, s2):
    """Returns True if Interval s1 overlaps with Interval s2, or False otherwise."""
    return max(0, min(s1.end, s2.end) - max(s1.start, s2.start)) > 0


def compare_fuzzy_junctions(r1_exons, r2_exons, max_fuzzy_junction=0):
    """
    Compares two lists of Intervals (exons), and returns their relationship allowing
    for very small amounts of diff.

    r1_exons: a list of Intervals (exons)
    r2_exons: a list of Intervals (exons)

    Returns:
    super -- if r1_exons is a superset of r2_exons
    exact -- if r1_exons exactly matches r2_exons
    subset -- if r1_exons is a subset of r2_exons
    partial -- if some but not all exons agree
    nomatch -- if r1_exons and r2_exons do not match.

    <max_fuzzy_junction> allows for very small amounts of diff between internal exons
    useful for chimeric & slightly bad mappings
    """
    found_overlap = False
    # super/partial --- i > 0, j = 0
    # exact/partial --- i = 0, j = 0
    # subset/partial --- i = 0, j > 0
    i, j = -1, -1
    for i, x in enumerate(r1_exons):
        # find the first matching r2, which could be further downstream
        for j, y in enumerate(r2_exons):
            if i > 0 and j > 0:
                break
            if overlaps(x, y):
                found_overlap = True
                break
        if found_overlap:
            break

    # Could not find any exon in r2_exons which matches the very first exon in r1_exons
    if not found_overlap:
        return "nomatch"

    # now we have r1_exons[i] matched to r2_exons[j]
    # if just one exon, then regardless of how much overlap there is, just call it exact
    if len(r1_exons) == 1:
        if len(r2_exons) == 1:
            return "exact"
        else: # r1_exons has one exon, and r2_exons has multi exons
            if r1_exons[0].end <= r2_exons[j].end:
                return "subset"
            else:
                return "partial"
    else:
        # r1_exons has multiple exons and r2_exons has exactly one exon and
        # r1_exons[0] overlaps r2_exons[0], r1_exons is superset of r2_exons
        if len(r2_exons) == 1:
            return "super"
        else: # both have multi-exon, check that all remaining junctions agree
            k = 0
            while i+k+1 < len(r1_exons) and j+k+1 < len(r2_exons):
                if abs(r1_exons[i+k].end-r2_exons[j+k].end) > max_fuzzy_junction or \
                   abs(r1_exons[i+k+1].start-r2_exons[j+k+1].start) > max_fuzzy_junction:
                    return "partial"
                k += 1
            #print i, j, k
            if i+k+1 == len(r1_exons):
                if j+k+1 == len(r2_exons):
                    # Both at ends
                    if i == 0:
                        if j == 0:
                            return "exact" # Both match from the very first exon to the last exon
                        else:
                            return "subset" # j > 0, r2_exons[j..last] match r1_exons[0..last]
                    else:
                        return "super" # i > 0, r1_exons[i..last] match r2_exons[j..last]
                else: # r1_exons is at end, r2_exons not at end
                    if i == 0:
                        return "subset"
                    else:  # i > 0
                        if abs(r1_exons[i+k-1].end-r2_exons[j+k-1].end) > max_fuzzy_junction or \
                           abs(r1_exons[i+k].start-r2_exons[j+k].start) > max_fuzzy_junction:
                            return "partial"
                        else:
                            return "concordant" # r1_exons[i..last] match r2_exons[0..middle]
            else: # r1_exons not at end, r2_exons must be at end
                if j == 0:
                    return "super" # r1_exons is superset of r2_exons
                else: # j > 0, i = 0
                    if abs(r1_exons[i+k-1].end-r2_exons[j+k-1].end) > max_fuzzy_junction or \
                       abs(r1_exons[i+k].start-r2_exons[j+k].start) > max_fuzzy_junction:
                        return "partial"
                    else:
                        return "concordant" # r1_exons[0..middle] match r2_exons[j..last]


def get_fl_from_id(members):
    """Get number of FLNC reads from read ids."""
    assert isinstance(members, list)
    # ex: 13cycle_1Mag1Diff|i0HQ_SIRV_1d1m|c139597/f1p0/178
    try:
        return sum(int(_id.split('/')[1].split('p')[0][1:]) for _id in members)
    except (IndexError, ValueError):
        raise ValueError("Could not get FL num from %s" % members)


def can_merge(m, r1, r2, allow_extra_5exon, max_fuzzy_junction):
    """
    Returns True if r1 and r2 can be merged.
    Parameters:
      m -- input match pattern, can be exact, subset, super, partial, nonmatch
      r1, r2 -- GmapRecord
    """
    if m == 'exact':
        return True
    else:
        if not allow_extra_5exon:
            return False
    # below is continued only if (a) is 'subset' or 'super' AND (b) allow_extra_5exon is True
    if m == 'subset':
        r1, r2 = r2, r1 #  rotate so r1 is always the longer one
    if m == 'super' or m == 'subset':
        n2 = len(r2.ref_exons)
        # check that (a) r1 and r2 end on same 3' exon, that is the last acceptor site agrees
        # AND (b) the 5' start of r2 is sandwiched between the matching r1 exon coordinates
        if r1.strand == '+':
            return abs(r1.ref_exons[-1].start - r2.ref_exons[-1].start) <= max_fuzzy_junction and \
                r1.ref_exons[-n2].start <= r2.ref_exons[0].start < r1.ref_exons[-n2].end
        else:
            return abs(r1.ref_exons[0].end - r2.ref_exons[0].end) <= max_fuzzy_junction and \
                r1.ref_exons[n2-1].start <= r2.ref_exons[-1].end < r1.ref_exons[n2].end
    return False


def collapse_fuzzy_junctions(gff_filename, group_filename,
                             fuzzy_gff_filename, fuzzy_group_filename,
                             allow_extra_5exon, max_fuzzy_junction):
    """
    Collapses those transcripts in gff_filename which have fuzzy junctions.
    Returns fuzzy_match

    Parameters:
      gff_filename -- input unfuzzy gff filename
      group_filename -- input unfuzzy group filename
      fuzzy_gff_filename -- output gff filename in which transcripts with fuzzy
                            junctions are further collapsed.
      fuzzy_group_filename -- output group filename
      allow_etra_5exon -- whether or not to allow extra 5 exons
      max_fuzzy_junction -- maximum differences to call two exons match
    """

    d = {} # seqid --> GmapRecord
    recs = defaultdict(lambda: {'+':IntervalTree(), '-':IntervalTree()}) # chr --> strand --> tree
    fuzzy_match = defaultdict(lambda: []) # seqid --> [seqid of fuzzy match GmapRecords]
    for r in CollapseGffReader(gff_filename):
        # r : a GmapRecord which represents a transcript and its associated exons.
        d[r.seqid] = r
        has_match = False
        for r2 in recs[r.chr][r.strand].find(r.start, r.end):
            # Compare r1 with r2 and get match pattern, exact, super, subset, partial or nonmatch
            m = compare_fuzzy_junctions(r.ref_exons, r2.ref_exons, max_fuzzy_junction=max_fuzzy_junction)
            if can_merge(m, r, r2, allow_extra_5exon=allow_extra_5exon, max_fuzzy_junction=max_fuzzy_junction):
                logging.debug("Collapsing fuzzy transcript %s to %s", r.seqid, r2.seqid)
                fuzzy_match[r2.seqid].append(r.seqid) # collapse r to r2
                has_match = True
                break
        if not has_match:
            logging.debug("No fuzzy transcript found for %s", r.seqid)
            recs[r.chr][r.strand].insert(r.start, r.end, r)
            fuzzy_match[r.seqid] = [r.seqid]

    # Get group info from input group_filename
    group_info = {group.name: group.members for group in GroupReader(group_filename)}

    # pick for each fuzzy group the one that has the most exons (if tie, then most FL)
    keys = fuzzy_match.keys()
    keys.sort(key=lambda x: map(int, x.split('.')[1:]))

    fuzzy_gff_writer = CollapseGffWriter(fuzzy_gff_filename)
    fuzzy_group_writer = GroupWriter(fuzzy_group_filename)
    for k in keys: # Iterates over each group of fuzzy match GmapRecords
        all_members = []
        # Assume the first GmapRecord is the best to represent this fuzzy match GmapRecords group
        best_pbid = fuzzy_match[k][0] # e.g., PB.1.1
        if not best_pbid in group_info:
            raise ValueError("Could not find %s in Group file %s" % (best_pbid, group_filename))
        best_size, best_num_exons = len(group_info[best_pbid]), len(d[best_pbid].ref_exons)
        all_members += group_info[best_pbid]
        for pbid in fuzzy_match[k][1:]: # continue to look for better representative
            if not pbid in group_info:
                raise ValueError("Could not find %s in Group file %s" % (pbid, group_filename))
            _size = get_fl_from_id(group_info[pbid])
            _num_exons = len(d[pbid].ref_exons)
            all_members += group_info[pbid]
            if _num_exons > best_num_exons or (_num_exons == best_num_exons and _size > best_size):
                best_pbid, best_size, best_num_exons = pbid, _size, _num_exons
        # Write the best GmapRecord of the group to fuzzy_gff_filename
        fuzzy_gff_writer.writeRecord(d[best_pbid])
        # Write all members of the group to fuzzy_group_filename
        fuzzy_group_writer.writeRecord(GroupRecord(best_pbid, all_members))
    fuzzy_gff_writer.close()
    fuzzy_group_writer.close()

    return fuzzy_match


def pick_rep(isoform_filename, gff_filename,
             group_filename, output_filename,
             pick_least_err_instead=False,
             bad_gff_filename=None):
    """
    For each group of collapsed sam records, select the representative record.

    If is FASTA file -- then always pick the longest one
    If is FASTQ file -- then
          If pick_least_err_instead is True, pick the one w/ least number of expected base errors
          Else, pick the longest one
    """
    fd = None
    is_fq = False
    dummy_prefix, _suffix = parse_ds_filename(isoform_filename)
    if _suffix == "fasta":
        fd = FastaRandomReader(isoform_filename)
    elif _suffix == "fastq":
        fd = FastqRandomReader(isoform_filename)
        is_fq = True
    elif _suffix == "contigset.xml":
        fd = ContigSet(isoform_filename)
        _fns = fd.toExternalFiles()
        if len(_fns) == 1 and _fns[0].endswith(".fq") or _fns[0].endswith(".fastq"):
            fd = FastqRandomReader(_fns[0])
            is_fq = True
        else:
            if not fd.isIndexed:
                # Must be indexed FASTA, or exactly contains one FASTQ file
                raise IOError("%s must contain either indexed FASTA files or " % isoform_filename +
                              "contain exactly one FASTQ file!")
    else:
        raise IOError("Unable to recognize file type of %s." % isoform_filename)

    fa_out_fn, fq_out_fn, ds_out_fn = None, None, None

    _prefix, _suffix = parse_ds_filename(output_filename)
    if _suffix == "fasta":
        fa_out_fn = output_filename
    elif _suffix == "fastq":
        if not is_fq:
            raise ValueError("Input file %s is not FASTQ while output is." % isoform_filename)
        else:
            fq_out_fn = output_filename
    elif _suffix == "contigset.xml": # output is contigset.xml
        ds_out_fn = output_filename
        fa_out_fn = _prefix + ".fasta"
        if is_fq:
            fq_out_fn = _prefix + ".fastq"
    else:
        raise IOError("Unable to recognize file type of %s." % output_filename)

    fa_writer = FastaWriter(fa_out_fn) if fa_out_fn is not None else None
    fq_writer = FastqWriter(fq_out_fn) if fq_out_fn is not None else None

    coords = {}
    for r in CollapseGffReader(gff_filename):
        tid = r.transcript_id
        coords[tid] = "{0}:{1}-{2}({3})".format(r.seqid, r.start, r.end, r.strand)

    if bad_gff_filename is not None:
        for r in CollapseGffReader(gff_filename):
            tid = r.transcript_id
            coords[tid] = "{0}:{1}-{2}({3})".format(r.seqid, r.start, r.end, r.strand)

    for group in GroupReader(group_filename):
        pb_id, members = group.name, group.members
        if not pb_id in coords:
            raise ValueError("Could not find %s in %s and %s" %
                             (pb_id, gff_filename, bad_gff_filename))
        #logging.info("Picking representative sequence for %s", pb_id)
        best_id = None
        best_seq = None
        best_qual = None
        best_err = 9999999
        err = 9999999
        max_len = 0

        for x in members:
            if is_fq and pick_least_err_instead:
                err = sum(i**-(i/10.) for i in fd[x].quality)
            if (is_fq and pick_least_err_instead and err < best_err) or \
               ((not is_fq or not pick_least_err_instead) and len(fd[x].sequence) >= max_len):
                best_id = x
                best_seq = fd[x].sequence
                if is_fq:
                    best_qual = fd[x].quality
                    best_err = err
                max_len = len(fd[x].sequence)

        _id_ = "{0}|{1}|{2}".format(pb_id, coords[pb_id], best_id)
        _seq_ = best_seq
        if fq_writer is not None:
            fq_writer.writeRecord(_id_, _seq_, best_qual)
        if fa_writer is not None:
            fa_writer.writeRecord(_id_, _seq_)

    if fa_writer is not None:
        fa_writer.close()
    if fq_writer is not None:
        fq_writer.close()
    if ds_out_fn is not None:
        as_contigset(fa_out_fn, ds_out_fn)
