#!/usr/bin/env python

"""
Compute read status of FL and nFL reads, and make abundance file.
"""
import sys
import logging

from pbcommand.cli.core import pbparser_runner
from pbcommand.models import FileTypes
from pbcommand.utils import setup_log

from pbtranscript.PBTranscriptOptions import get_base_contract_parser
from pbtranscript.counting import CountRunner


log = logging.getLogger(__name__)


class Constants(object):
    """Constants used in tool contract."""
    TOOL_ID = "pbtranscript.tasks.make_abundance"
    DRIVER_EXE = "python -m %s --resolved-tool-contract " % TOOL_ID
    PARSER_DESC = __doc__


def add_make_abundance_io_arguments(arg_parser):
    """Add io arguments to parser."""
    helpstr = "Input group file which associates collapsed isoforms with reads."
    arg_parser.add_argument("group_filename", type=str, help=helpstr)

    helpstr = "Input pickle file (e.g., hq_lq_pre_dict.pickle) which maps HQ " + \
              "(LQ) isoforms' sample prefixes to cluster output directories."
    arg_parser.add_argument("pickle_filename", type=str, help=helpstr)

    helpstr = "Output read status file."
    arg_parser.add_argument("output_read_stat_filename", type=str, help=helpstr)

    helpstr = "Output abundance file."
    arg_parser.add_argument("output_abundance_filename", type=str, help=helpstr)
    return arg_parser


def args_runner(args):
    """Run given input args, e.g.,
    make_abundance.py group.txt hq_lq_pre_dict.pickle out.read_stat.txt out.abundance.txt
    """
    c = CountRunner(group_filename=args.group_filename,
                    pickle_filename=args.pickle_filename,
                    output_read_stat_filename=args.output_read_stat_filename,
                    output_abundance_filename=args.output_abundance_filename)
    c.run()
    return 0


def resolved_tool_contract_runner(rtc):
    """Run given a resolved tool contract"""
    raise NotImplementedError() # Merged to post_mapping_to_genome
#    c = CountRunner(group_filename=rtc.task.input_files[0],
#                    pickle_filename=rtc.task.input_files[1],
#                    output_read_stat_filename=rtc.task.output_files[0],
#                    output_abundance_filename=rtc.task.output_files[1])
#    c.run()
#    return 0


def get_contract_parser():
    """Get tool contract parser.
    Input:
        idx 0 - group file
        idx 1 - pickle file
    Output:
        idx 0 - read stat file
        idx 1 - abundance file
    """
    p = get_base_contract_parser(Constants, default_level="DEBUG")

    # argument parser
    add_make_abundance_io_arguments(p.arg_parser.parser)

    # tool contract parser
    tcp = p.tool_contract_parser
    tcp.add_input_file_type(FileTypes.TXT, "group_txt", "TXT In",
                            "Group file associating isoforms with reads") # input 0
    tcp.add_input_file_type(FileTypes.PICKLE, "hq_lq_pre_dict", "PICKLE In",
                            "Pickle file containing dicts mapping HQ (LQ) " +
                            "sample prefixes to ICE cluster output directories") # input 1
    tcp.add_output_file_type(FileTypes.TXT, "read_stat_txt",
                             name="TXT file", description="Read status of FL and nFL reads",
                             default_name="output_mapped_read_stat")
    tcp.add_output_file_type(FileTypes.TXT, "abundance_txt",
                             name="TXT file", description="Abundance file",
                             default_name="output_mapped_abundance")
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
