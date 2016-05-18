#!/usr/bin/env python
###########################################################################
# Copyright (c) 2011-2014, Pacific Biosciences of California, Inc.
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted (subject to the limitations in the
# disclaimer below) provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright
#  notice, this list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above
#  copyright notice, this list of conditions and the following
#  disclaimer in the documentation and/or other materials provided
#  with the distribution.
#
#  * Neither the name of Pacific Biosciences nor the names of its
#  contributors may be used to endorse or promote products derived
#  from this software without specific prior written permission.
#
# NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE
# GRANTED BY THIS LICENSE. THIS SOFTWARE IS PROVIDED BY PACIFIC
# BIOSCIENCES AND ITS CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL PACIFIC BIOSCIENCES OR ITS
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
###########################################################################
"""
Given an input_fasta file of non-full-length (partial) reads and
(unpolished) consensus isoforms sequences in ref_fasta, align reads to
consensus isoforms using BLASR, and then build up a mapping between
consensus isoforms and reads (i.e., assign reads to isoforms).
Finally, save
    {isoform_id: [read_ids],
     nohit: set(no_hit_read_ids)}
to an output pickle file.
"""

import os
import os.path as op
import time
import logging
from cPickle import dump
import json

from pbcommand.models import FileTypes
from pbcore.io import ContigSet

from pbtranscript.ClusterOptions import IceOptions
from pbtranscript.Utils import realpath, touch, real_upath, execute
from pbtranscript.PBTranscriptOptions import add_fofn_arguments, \
        add_tmp_dir_argument, add_use_blasr_argument
from pbtranscript.io.ContigSetReaderWrapper import ContigSetReaderWrapper
from pbtranscript.ice_daligner import DalignerRunner
from pbtranscript.ice.ProbModel import ProbFromModel, ProbFromQV, ProbFromFastq
from pbtranscript.ice.IceUtils import blasr_against_ref, \
        daligner_against_ref, ice_fa2fq
from pbtranscript.ice.__init__ import ICE_PARTIAL_PY


def build_uc_from_partial_daligner(input_fasta, ref_fasta, out_pickle,
                                   ccs_fofn=None,
                                   done_filename=None,
                                   use_finer_qv=False,
                                   cpus=24,
                                   no_qv_or_aln_checking=True,
                                   tmp_dir=None):
    """
    Given an input_fasta file of non-full-length (partial) reads and
    (unpolished) consensus isoforms sequences in ref_fasta, align reads to
    consensus isoforms using BLASR, and then build up a mapping between
    consensus isoforms and reads (i.e., assign reads to isoforms).
    Finally, save
        {isoform_id: [read_ids],
         nohit: set(no_hit_read_ids)}
    to an output pickle file.

    ccs_fofn --- If None, assume no quality value is available,
    otherwise, use QV from ccs_fofn.

    tmp_dir - where to save intermediate files such as dazz files.
              if None, writer dazz files to the same directory as query/target.
    """
    input_fasta = realpath(input_fasta)
    ref_fasta = realpath(ref_fasta)
    out_pickle = realpath(out_pickle)
    output_dir = op.dirname(out_pickle)

    ice_opts = IceOptions()
    ice_opts.detect_cDNA_size(ref_fasta)

    # ice_partial is already being called through qsub, so run everything local!
    runner = DalignerRunner(query_filename=input_fasta,
                            target_filename=ref_fasta,
                            is_FL=False, same_strand_only=False,
                            query_converted=False, target_converted=True,
                            dazz_dir=tmp_dir, script_dir=op.join(output_dir, "script"),
                            use_sge=False, sge_opts=None, cpus=cpus)
    runner.run(min_match_len=300, output_dir=output_dir, sensitive_mode=ice_opts.sensitive_mode)

    if no_qv_or_aln_checking:
        # not using QVs or alignment checking!
        # this probqv is just a DUMMY to pass to daligner_against_ref, which won't be used
        logging.info("Not using QV for partial_uc. Loading dummy QV.")
        probqv = ProbFromModel(.01, .07, .06)
    else:
        if ccs_fofn is None:
            logging.info("Loading probability from model (0.01,0.07,0.06)")
            probqv = ProbFromModel(.01, .07, .06)
        else:
            start_t = time.time()
            if use_finer_qv:
                probqv = ProbFromQV(input_fofn=ccs_fofn, fasta_filename=input_fasta)
                logging.info("Loading QVs from %s + %s took %s secs",
                             ccs_fofn, input_fasta, time.time()-start_t)
            else:
                input_fastq = input_fasta[:input_fasta.rfind('.')] + '.fastq'
                logging.info("Converting %s + %s --> %s",
                             input_fasta, ccs_fofn, input_fastq)
                ice_fa2fq(input_fasta, ccs_fofn, input_fastq)
                probqv = ProbFromFastq(input_fastq)
                logging.info("Loading QVs from %s took %s secs",
                             input_fastq, time.time()-start_t)

    logging.info("Calling dalign_against_ref ...")

    partial_uc = {}  # Maps each isoform (cluster) id to a list of reads
    # which can map to the isoform
    seen = set()  # reads seen
    logging.info("Building uc from DALIGNER hits.")

    for la4ice_filename in runner.la4ice_filenames:
        start_t = time.time()
        hitItems = daligner_against_ref(query_dazz_handler=runner.query_dazz_handler,
                                        target_dazz_handler=runner.target_dazz_handler,
                                        la4ice_filename=la4ice_filename,
                                        is_FL=False,
                                        sID_starts_with_c=True,
                                        qver_get_func=probqv.get_smoothed,
                                        qvmean_get_func=probqv.get_mean,
                                        ece_penalty=1,
                                        ece_min_len=20,
                                        same_strand_only=False,
                                        no_qv_or_aln_checking=no_qv_or_aln_checking)
        for h in hitItems:
            if h.ece_arr is not None:
                if h.cID not in partial_uc:
                    partial_uc[h.cID] = set()
                partial_uc[h.cID].add(h.qID)
                seen.add(h.qID)
        logging.info("processing %s took %s sec",
                     la4ice_filename, str(time.time()-start_t))

    for k in partial_uc:
        partial_uc[k] = list(partial_uc[k])

    allhits = set(r.name.split()[0] for r in ContigSetReaderWrapper(input_fasta))

    logging.info("Counting reads with no hit.")
    nohit = allhits.difference(seen)

    logging.info("Dumping uc to a pickle: %s.", out_pickle)
    with open(out_pickle, 'w') as f:
        if out_pickle.endswith(".pickle"):
            dump({'partial_uc': partial_uc, 'nohit': nohit}, f)
        elif out_pickle.endswith(".json"):
            f.write(json.dumps({'partial_uc': partial_uc, 'nohit': nohit}))
        else:
            raise IOError("Unrecognized extension: %s" % out_pickle)

    done_filename = realpath(done_filename) if done_filename is not None \
        else out_pickle + '.DONE'
    logging.debug("Creating %s.", done_filename)
    touch(done_filename)

    # remove all the .las and .las.out filenames
    runner.clean_run()


def _get_fasta_path(file_name):
    if file_name.endswith(".contigset.xml"):
        ds = ContigSet(file_name)
        fasta_files = ds.toExternalFiles()
        assert len(fasta_files) == 1
        return fasta_files[0]
    return file_name


def build_uc_from_partial(input_fasta, ref_fasta, out_pickle,
                          ccs_fofn=None,
                          done_filename=None, blasr_nproc=12, tmp_dir=None):
    """
    Given an input_fasta file of non-full-length (partial) reads and
    (unpolished) consensus isoforms sequences in ref_fasta, align reads to
    consensus isoforms using BLASR, and then build up a mapping between
    consensus isoforms and reads (i.e., assign reads to isoforms).
    Finally, save
        {isoform_id: [read_ids],
         nohit: set(no_hit_read_ids)}
    to an output pickle file.

    ccs_fofn --- If None, assume no quality value is available,
    otherwise, use QV from ccs_fofn.
    blasr_nproc --- equivalent to blasr -nproc, number of CPUs to use
    """
    input_fasta = _get_fasta_path(realpath(input_fasta))
    m5_file = os.path.basename(input_fasta) + ".blasr"
    if tmp_dir is not None:
        m5_file = op.join(tmp_dir, m5_file)

    out_pickle = realpath(out_pickle)

    cmd = "blasr {i} ".format(i=real_upath(input_fasta)) + \
          "{r} --bestn 5 ".format(r=real_upath(_get_fasta_path(ref_fasta))) + \
          "--nproc {n} -m 5 ".format(n=blasr_nproc) + \
          "--maxScore -1000 --minPctIdentity 85 " + \
          "--out {o} ".format(o=real_upath(m5_file)) + \
          "1>/dev/null 2>/dev/null"

    execute(cmd)

    if ccs_fofn is None:
        logging.info("Loading probability from model")
        probqv = ProbFromModel(.01, .07, .06)
    else:
        # FIXME this will not work with current CCS bam output, which lacks
        # QV pulse features required - this is handled via a workaround in
        # pbtranscript.tasks.ice_partial
        logging.info("Loading probability from QV in %s", ccs_fofn)
        probqv = ProbFromQV(input_fofn=ccs_fofn, fasta_filename=input_fasta)

    logging.info("Calling blasr_against_ref ...")
    hitItems = blasr_against_ref(output_filename=m5_file,
                                 is_FL=False,
                                 sID_starts_with_c=True,
                                 qver_get_func=probqv.get_smoothed,
                                 qvmean_get_func=probqv.get_mean,
                                 ece_penalty=1,
                                 ece_min_len=10,
                                 same_strand_only=False)

    partial_uc = {}  # Maps each isoform (cluster) id to a list of reads
    # which can map to the isoform
    seen = set()  # reads seen
    logging.info("Building uc from BLASR hits.")
    for h in hitItems:
        if h.ece_arr is not None:
            if h.cID not in partial_uc:
                partial_uc[h.cID] = set()
            partial_uc[h.cID].add(h.qID)
            seen.add(h.qID)

    for k in partial_uc:
        partial_uc[k] = list(partial_uc[k])

    allhits = set(r.name.split()[0] for r in ContigSetReaderWrapper(input_fasta))

    logging.info("Counting reads with no hit.")
    nohit = allhits.difference(seen)

    logging.info("Dumping uc to a pickle: %s.", out_pickle)
    with open(out_pickle, 'w') as f:
        if out_pickle.endswith(".pickle"):
            dump({'partial_uc': partial_uc, 'nohit': nohit}, f)
        elif out_pickle.endswith(".json"):
            f.write(json.dumps({'partial_uc': partial_uc, 'nohit': nohit}))
        else:
            raise IOError("Unrecognized extension: %s" % out_pickle)

    os.remove(m5_file)

    done_filename = realpath(done_filename) if done_filename is not None \
        else out_pickle + '.DONE'
    logging.debug("Creating %s.", done_filename)
    touch(done_filename)


class IcePartialOne(object):

    """Assign nfl reads of a given fasta to isoforms."""

    desc = "Assign non-full-length reads in the given input fasta to " + \
           "unpolished consensus isoforms."
    prog = "%s one " % ICE_PARTIAL_PY

    def __init__(self, input_fasta, ref_fasta, out_pickle,
                 ccs_fofn=None,
                 done_filename=None, blasr_nproc=12,
                 use_blasr=False, tmp_dir=None):
        self.input_fasta = input_fasta
        self.ref_fasta = ref_fasta
        self.out_pickle = out_pickle
        self.ccs_fofn = ccs_fofn
        self.done_filename = done_filename
        self.blasr_nproc = blasr_nproc
        self.tmp_dir = tmp_dir
        self.use_blasr = use_blasr # True: use blasr, False, use daligner

    def cmd_str(self):
        """Return a cmd string (ice_partial.py one)."""
        return self._cmd_str(input_fasta=self.input_fasta,
                             ref_fasta=self.ref_fasta,
                             out_pickle=self.out_pickle,
                             ccs_fofn=self.ccs_fofn,
                             done_filename=self.done_filename,
                             blasr_nproc=self.blasr_nproc,
                             use_blasr=self.use_blasr,
                             tmp_dir=self.tmp_dir)

    def _cmd_str(self, input_fasta, ref_fasta, out_pickle,
                 ccs_fofn=None,
                 done_filename=None, blasr_nproc=12,
                 use_blasr=False, tmp_dir=None):
        """Return a cmd string (ice_partil.py one)"""
        cmd = self.prog + \
              "{f} ".format(f=input_fasta) + \
              "{r} ".format(r=ref_fasta) + \
              "{o} ".format(o=out_pickle)
        if ccs_fofn is not None:
            cmd += "--ccs_fofn {c} ".format(c=ccs_fofn)
        if done_filename is not None:
            cmd += "--done {d} ".format(d=done_filename)
        if blasr_nproc is not None:
            cmd += "--blasr_nproc {b} ".format(b=blasr_nproc)
        if use_blasr is True:
            cmd += "--use_blasr "
        if tmp_dir is not None:
            cmd += "--tmp_dir {t} ".format(t=tmp_dir)
        return cmd

    def run(self):
        """Run"""
        logging.info("Building uc from non-full-length reads using DALIGNER.")
        if not self.use_blasr:
            build_uc_from_partial_daligner(input_fasta=self.input_fasta,
                                           ref_fasta=self.ref_fasta,
                                           out_pickle=self.out_pickle,
                                           ccs_fofn=self.ccs_fofn,
                                           cpus=self.blasr_nproc,
                                           no_qv_or_aln_checking=True,
                                           tmp_dir=self.tmp_dir)
        else:
            # replaced by dagliner above
            build_uc_from_partial(input_fasta=self.input_fasta,
                                  ref_fasta=self.ref_fasta,
                                  out_pickle=self.out_pickle,
                                  ccs_fofn=self.ccs_fofn,
                                  blasr_nproc=self.blasr_nproc,
                                  tmp_dir=self.tmp_dir)
        return 0


def add_ice_partial_one_arguments(parser):
    """Add arguments for assigning nfl reads of a given input fasta
    to unpolished isoforms."""
    parser.add_input_file_type(FileTypes.DS_CONTIG, "input_fasta",
                               name="ContigSet",
                               description="ContigSet of non-full-length reads")
    parser.add_input_file_type(FileTypes.DS_CONTIG, "ref_fasta",
                               name="Reference ContigSet",
                               description="Reference fasta file, most likely " +
                               "ref_consensus.fasta from ICE output")
    arg_parser = add_fofn_arguments(parser.arg_parser.parser,
                                    ccs_fofn=True,
                                    tool_contract_parser=parser.tool_contract_parser)
    parser.add_output_file_type(FileTypes.PICKLE, "out_pickle",
                                name="JSON pickle",
                                description="Output pickle file",
                                default_name="ice_partial_one")
    arg_parser.add_argument("--done", dest="done_filename", type=str,
                            help="An empty file generated to indicate that " +
                            "out_pickle is done.")
    arg_parser = add_use_blasr_argument(arg_parser)
    arg_parser = add_tmp_dir_argument(arg_parser)

# ToDo: comment OUT BLASR-related arguments; using DALIGNER
    arg_parser.add_argument("--blasr_nproc", dest="blasr_nproc",
                            type=int, default=12,
                            help="blasr --nproc, number of CPUs [default: 12]")
    return parser
