#!/usr/bin/env python
"""
Analysis done after mapping to genome is done, including
(1) Collapse redundant isoforms into transcripts, then merge transcripts
    which have merge-able fuzzy junctions.
(2) Generate read status for FL and nFL reads and make abundance file for collapsed isoforms
(3) Filter collapsed isoforms by abundance
(4) Filter collapsed isoforms by subsetting.

Input:
    0 - A FASTA/FASTQ/ContigSet file containing uncollapsed isoforms (hq_polished)
    1 - A SORTED GMAP SAM file containing alignments mapping uncollapsed
        isoforms to reference genomes (produced by map_isoforms_to_genome)
Output:
    0 - A GFF file containing filtered collapsed isoforms.
    1 - A Group file which associates collapsed isoforms with uncollapsed isoforms
    2 - A Abundnace file containing abundance info of filtered collapsed isoforms
    3 - A FASTQ file containing representative sequences of filtered collapsed isoforms.
"""

import sys
import logging

from pbcommand.cli.core import pbparser_runner
from pbcommand.models import FileTypes
from pbcommand.utils import setup_log

from pbtranscript.Utils import ln, realpath
from pbtranscript.io import parse_ds_filename
from pbtranscript.PBTranscriptOptions import get_base_contract_parser
from pbtranscript.collapsing import CollapsedFiles, FilteredFiles, CollapseIsoformsRunner
from pbtranscript.counting import CountRunner
from pbtranscript.filtering import filter_by_count, filter_out_subsets

import pbtranscript.tasks.collapse_mapped_isoforms as cmi
import pbtranscript.tasks.filter_collapsed_isoforms as fci


log = logging.getLogger(__name__)


class Constants(object):
    """Constants used in tool contract."""
    TOOL_ID = "pbtranscript.tasks.post_mapping_to_genome"
    DRIVER_EXE = "python -m %s --resolved-tool-contract " % TOOL_ID
    PARSER_DESC = __doc__


def  add_post_mapping_to_genome_io_arguments(arg_parser):
    """Add io arguments to parser."""
    helpstr = "Input uncollapsed isoforms in a FASTQ file."
    arg_parser.add_argument("in_isoforms", type=str, help=helpstr)

    helpstr = "Input SORTED SAM file mapping uncollapsed isoforms to reference genome using GMAP."
    arg_parser.add_argument("in_sam", type=str, help=helpstr)

    helpstr = "Input pickle file (e.g., hq_lq_pre_dict.pickle) which maps HQ " + \
              "(LQ) isoforms' sample prefixes to cluster output directories."
    arg_parser.add_argument("in_pickle", type=str, help=helpstr)

    helpstr = "Output collapsed, filtered isoforms to a FASTQ file."
    arg_parser.add_argument("out_isoforms", type=str, help=helpstr)

    helpstr = "Output collapsed, filtered isoforms in a GFF file."
    arg_parser.add_argument("out_gff", default=None, type=str, help=helpstr)

    opio_group = arg_parser.add_argument_group("optional io arguments")
    helpstr = "Output abundance info of collapsed, filtered isoforms to an Abundance TXT file."
    opio_group.add_argument("--abundance_fn", dest="out_abundance", default=None,
                            type=str, help=helpstr)

    helpstr = "Output group info of collapsed isoforms to a Group TXT file."
    opio_group.add_argument("--group_fn", dest="out_group", default=None,
                            type=str, help=helpstr)

    helpstr = "Output read status of FL and nFL reads to a ReadStat TXT file."
    opio_group.add_argument("--read_stat_fn", dest="out_read_stat", default=None,
                            type=str, help=helpstr)
    return arg_parser


def add_post_mapping_to_genome_arguments(arg_parser):
    """Add option arguments to parser."""
    cmi.add_collapse_mapped_isoforms_arguments(arg_parser)
    fci.add_filter_collapsed_isoforms_arguments(arg_parser)
    return arg_parser


def add_post_mapping_to_genome_tcp_options(tcp):
    """Add post mapping to genome tcp options"""
    cmi.add_collapse_mapped_isoforms_tcp_options(tcp)
    fci.add_filter_collapsed_isoforms_tcp_options(tcp)
    return tcp


def post_mapping_to_genome_runner(in_isoforms, in_sam, in_pickle,
                                  out_isoforms, out_gff, out_abundance, out_group, out_read_stat,
                                  min_aln_coverage=cmi.Constants.MIN_ALN_COVERAGE_DEFAULT,
                                  min_aln_identity=cmi.Constants.MIN_ALN_IDENTITY_DEFAULT,
                                  min_flnc_coverage=cmi.Constants.MIN_FLNC_COVERAGE_DEFAULT,
                                  max_fuzzy_junction=cmi.Constants.MAX_FUZZY_JUNCTION_DEFAULT,
                                  allow_extra_5exon=cmi.Constants.ALLOW_EXTRA_5EXON_DEFAULT,
                                  skip_5_exon_alt=cmi.Constants.SKIP_5_EXON_ALT_DEFAULT,
                                  min_count=fci.Constants.MIN_COUNT_DEFAULT,
                                  to_filter_out_subsets=True):
    """
    (1) Collapse isoforms and merge fuzzy junctions if needed.
    (2) Generate read stat file and abundance file
    (3) Based on abundance file, filter collapsed isoforms by min FL count
    """
    log.info('args: {!r}'.format(locals()))
    # Check input and output format
    in_suffix = parse_ds_filename(in_isoforms)[1]
    out_prefix, out_suffix = parse_ds_filename(out_isoforms)
    if in_suffix != out_suffix:
        raise ValueError("Format of input and output isoforms %s, %s must be the same." %
                         (in_isoforms, out_isoforms))
    if in_suffix not in ("fasta", "fastq"):
        raise ValueError("Format of input and output isoforms %s, %s must be FASTA or FASTQ." %
                         (in_isoforms, out_isoforms))

    #(1) Collapse isoforms and merge fuzzy junctions if needed.
    cf = CollapsedFiles(prefix=out_prefix, allow_extra_5exon=allow_extra_5exon)
    cir = CollapseIsoformsRunner(isoform_filename=in_isoforms,
                                 sam_filename=in_sam,
                                 output_prefix=out_prefix,
                                 min_aln_coverage=min_aln_coverage,
                                 min_aln_identity=min_aln_identity,
                                 min_flnc_coverage=min_flnc_coverage,
                                 max_fuzzy_junction=max_fuzzy_junction,
                                 allow_extra_5exon=allow_extra_5exon,
                                 skip_5_exon_alt=skip_5_exon_alt)
    cir.run()

    # (2) Generate read stat file and abundance file
    cr = CountRunner(group_filename=cf.group_fn, pickle_filename=in_pickle,
                     output_read_stat_filename=cf.read_stat_fn,
                     output_abundance_filename=cf.abundance_fn)
    cr.run()

    # (3) Filter collapsed isoforms by min FL count based on abundance file.
    fff = FilteredFiles(prefix=out_prefix, allow_extra_5exon=allow_extra_5exon,
                        min_count=min_count, filter_out_subsets=False)
    filter_by_count(in_group_filename=cf.group_fn, in_abundance_filename=cf.abundance_fn,
                    in_gff_filename=cf.good_gff_fn, in_rep_filename=cf.rep_fn(out_suffix),
                    out_abundance_filename=fff.filtered_abundance_fn,
                    out_gff_filename=fff.filtered_gff_fn,
                    out_rep_filename=fff.filtered_rep_fn(out_suffix),
                    min_count=min_count)

    fft = FilteredFiles(prefix=out_prefix, allow_extra_5exon=allow_extra_5exon,
                        min_count=min_count, filter_out_subsets=True)
    # (4) Remove collapsed isoforms which are a subset of another isoform
    if to_filter_out_subsets is True:
        filter_out_subsets(in_abundance_filename=fff.filtered_abundance_fn,
                           in_gff_filename=fff.filtered_gff_fn,
                           in_rep_filename=fff.filtered_rep_fn(out_suffix),
                           out_abundance_filename=fft.filtered_abundance_fn,
                           out_gff_filename=fft.filtered_gff_fn,
                           out_rep_filename=fft.filtered_rep_fn(out_suffix),
                           max_fuzzy_junction=max_fuzzy_junction)
        fff = fft

    # (5) ln outputs files
    ln_pairs = [(fff.filtered_rep_fn(out_suffix), out_isoforms), # rep isoforms
                (fff.filtered_gff_fn, out_gff), # gff annotation
                (fff.filtered_abundance_fn, out_abundance), # abundance info
                (fff.group_fn, out_group), # groups
                (fff.read_stat_fn, out_read_stat)] # read stat info
    for src, dst in ln_pairs:
        if dst is not None:
            ln(src, dst)

    logging.info("Filter arguments: min_count = %s, filter_out_subsets=%s",
                 min_count, filter_out_subsets)
    logging.info("Collapsed and filtered isoform sequences written to %s",
                 realpath(out_isoforms) if out_isoforms is not None else
                 realpath(fff.filtered_rep_fn(out_suffix)))
    logging.info("Collapsed and filtered isoform annotations written to %s",
                 realpath(out_gff) if out_gff is not None else realpath(fff.filtered_gff_fn))
    logging.info("Collapsed and filtered isoform abundance info written to %s",
                 realpath(out_abundance) if out_abundance is not None else
                 realpath(fff.filtered_abundance_fn))
    logging.info("Collapsed isoform groups written to %s",
                 realpath(out_group) if out_group is not None else realpath(fff.group_fn))
    logging.info("Read status of FL and nFL reads written to %s",
                 realpath(out_read_stat) if out_read_stat is not None else
                 realpath(fff.read_stat_fn))


def args_runner(args):
    """Run given input args"""
    post_mapping_to_genome_runner(
        in_isoforms=args.in_isoforms, in_sam=args.in_sam,
        in_pickle=args.in_pickle, out_isoforms=args.out_isoforms,
        out_gff=args.out_gff, out_abundance=args.out_abundance,
        out_group=args.out_group, out_read_stat=args.out_read_stat,
        min_aln_coverage=args.min_aln_coverage, min_aln_identity=args.min_aln_identity,
        min_flnc_coverage=args.min_flnc_coverage, max_fuzzy_junction=args.max_fuzzy_junction,
        allow_extra_5exon=args.allow_extra_5exon,
        min_count=args.min_count)
    return 0


def resolved_tool_contract_runner(rtc):
    """Run given a resolved tool contract"""
    post_mapping_to_genome_runner(
        in_isoforms=rtc.task.input_files[0], in_sam=rtc.task.input_files[1],
        in_pickle=rtc.task.input_files[2], out_isoforms=rtc.task.output_files[0],
        out_gff=rtc.task.output_files[1], out_abundance=rtc.task.output_files[2],
        out_group=rtc.task.output_files[3], out_read_stat=rtc.task.output_files[4],
        min_aln_coverage=rtc.task.options[cmi.Constants.MIN_ALN_COVERAGE_ID],
        min_aln_identity=rtc.task.options[cmi.Constants.MIN_ALN_IDENTITY_ID],
        max_fuzzy_junction=rtc.task.options[cmi.Constants.MAX_FUZZY_JUNCTION_ID],
        allow_extra_5exon=rtc.task.options[cmi.Constants.ALLOW_EXTRA_5EXON_ID],
        min_count=rtc.task.options[fci.Constants.MIN_COUNT_ID],
        to_filter_out_subsets=fci.Constants.FILTER_OUT_SUBSETS_DEFAULT)
    return 0


def get_contract_parser():
    """Get tool contract parser.
    Input:
        idx 0 - A FASTQ file containing uncollapsed isoforms (hq_polished)
        idx 1 - A SORTED GMAP SAM file containing alignments mapping uncollapsed
                isoforms to reference genomes (produced by map_isoforms_to_genome)
        idx 2 - A Pickle file containing dicts mapping HQ (LQ) sample prefixes to
                ICE cluster output directories(e.g., hq_lq_pre_dict.pickle)
    Output:
        idx 0 - A FASTQ file containing representative sequences of filtered collapsed isoforms
        idx 1 - A GFF file containing collapsed filtered isoforms
        idx 2 - A Abundnace file containing abundance info of collapsed filtered isoforms
        idx 3 - A Group file which associates collapsed isoforms with uncollapsed isoforms
        idx 4 - A ReadStat file containing FL and nFL read status
    """
    p = get_base_contract_parser(Constants, default_level="DEBUG")

    # argument parser
    add_post_mapping_to_genome_io_arguments(p.arg_parser.parser)
    add_post_mapping_to_genome_arguments(p.arg_parser.parser)

    # tool contract parser
    tcp = p.tool_contract_parser
    tcp.add_input_file_type(FileTypes.FASTQ, "hq_isoforms_fq", "FASTQ In",
                            "Input HQ polished isoforms in FASTQ file") # input 0

    tcp.add_input_file_type(FileTypes.SAM, "sorted_gmap_sam", "SAM In",
                            "Sorted GMAP SAM file") # input 1

    tcp.add_input_file_type(FileTypes.PICKLE, "hq_lq_pre_dict", "PICKLE In",
                            "Pickle file containing dicts mapping HQ (LQ) " +
                            "sample prefixes to ICE cluster output directories") # input 2

    tcp.add_output_file_type(FileTypes.FASTQ, "collapsed_filtered_isoforms_fq",
                             name="Collapsed Filtered Isoforms",
                             description="Representative sequences of collapsed filtered isoforms",
                             default_name="output_mapped") # output 0

    tcp.add_output_file_type(FileTypes.GFF, "collapsed_filtered_isoforms_gff",
                             name="Collapsed Filtered Isoforms",
                             description="Collapsed filtered isoforms gff",
                             default_name="output_mapped") # output 1

    tcp.add_output_file_type(FileTypes.TXT, "abundance_txt",
                             name="Isoform Abundance", description="Abundance file",
                             default_name="output_mapped_abundance") # output 2

    tcp.add_output_file_type(FileTypes.TXT, "groups_txt",
                             name="Collapsed Isoform Groups",
                             description="Collapsed isoform groups",
                             default_name="output_mapped_groups") # output 3

    tcp.add_output_file_type(FileTypes.TXT, "read_stat_txt",
                             name="FL nFL Reads Status", description="Read status of FL and nFL reads",
                             default_name="output_mapped_read_stat") # output 4

    # Add tcp options
    add_post_mapping_to_genome_tcp_options(tcp)
    return p


def main(args=sys.argv[1:]):
    """Main"""
    return pbparser_runner(argv=args,
                           parser=get_contract_parser(),
                           args_runner_func=args_runner,
                           contract_runner_func=resolved_tool_contract_runner,
                           alog=log,
                           setup_log_func=setup_log)


if __name__ == "__main__":
    sys.exit(main())
