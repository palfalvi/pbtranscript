#!/usr/bin/env python

"""
Calls 'ice_partial.py one'.
"""
from __future__ import print_function

import logging
import sys

from pbcore.io import ConsensusReadSet
from pbcommand.cli import pbparser_runner
from pbcommand.utils import setup_log

from pbtranscript.ice.IcePartial import *
from pbtranscript.PBTranscriptOptions import (BaseConstants,
                                              get_base_contract_parser, get_argument_parser, add_cluster_arguments)

log = logging.getLogger(__name__)

class Constants(BaseConstants):
    TOOL_ID = "pbtranscript.tasks.ice_partial"
    DRIVER_EXE = "python -m pbtranscript.tasks.ice_partial --resolved-tool-contract"
    PARSER_DESC = __doc__


def get_contract_parser():
    p = get_base_contract_parser(Constants, default_level="INFO")
    add_ice_partial_one_arguments(p)
    return p


def args_runner(args):
    return IcePartialOne(
        input_fasta=args.input_fasta,
        ref_fasta=args.ref_fasta,
        ccs_fofn=None,  # args.ccs_fofn,
        blasr_nproc=args.blasr_nproc,
        tmp_dir=args.tmp_dir).run()


def resolved_tool_contract_runner(rtc):
    ccs_set = rtc.task.input_files[2]
    # FIXME we have to ignore the new CCS output for now because it doesn't
    # contain the necessary QV fields; however, since the old behavior appears
    # to be to use this always (independent of --use_finer_qv), it will still
    # accommodate the older CCS files we use for testing
    log.info("Looking for QVs in CCS input...")
    with ConsensusReadSet(ccs_set) as ds:
        for bam in ds.resourceReaders():
            qvs = bam.pulseFeaturesAvailable()
            if qvs != set(['SubstitutionQV', 'InsertionQV', 'DeletionQV']):
                log.warn(
                    "Missing QV fields from %s, will use default probabilities"
                    % bam.filename)
                ccs_set = None
                break
    tmp_dir = rtc.task.tmpdir_resources[0].path \
            if len(rtc.task.tmpdir_resources) > 0 else None
    print('my tmp_dir is ')
    print(tmp_dir)
    return IcePartialOne(
        input_fasta=rtc.task.input_files[0],
        ref_fasta=rtc.task.input_files[1],
        out_pickle=rtc.task.output_files[0],
        ccs_fofn=ccs_set,
        blasr_nproc=rtc.task.nproc,
        tmp_dir=tmp_dir).run()


def main(argv=sys.argv[1:]):
    mp = get_contract_parser()
    return pbparser_runner(
        argv=argv,
        parser=mp,
        args_runner_func=args_runner,
        contract_runner_func=resolved_tool_contract_runner,
        alog=log,
        setup_log_func=setup_log)


if __name__ == "__main__":
    sys.exit(main())
