#!/usr/bin/env python

"""
Scatter inputs of map_isoforms_to_genome.

map_isoforms_to_genome takes two inputs:
    idx-0 HQ isoforms FASTQ
    idx-1 GMAP reference dataset
scatter_map_isoforms_to_genome chunks HQ isoforms and copies GMAP
reference dataset to chunk.json.
"""

import logging
import sys
import os
import os.path as op

from pbcommand.pb_io.common import load_pipeline_chunks_from_json
from pbcommand.pb_io import write_pipeline_chunks
from pbcommand.cli import pbparser_runner
from pbcommand.utils import setup_log
from pbcommand.models import get_scatter_pbparser, FileTypes, PipelineChunk

import pbcoretools.chunking.chunk_utils as CU
from pbcoretools.chunking.gather import get_datum_from_chunks_by_chunk_key

log = logging.getLogger(__name__)


class Constants(object):
    """Constants used in pbtranscript.tasks.scatter_map_isoforms_to_genome"""
    TOOL_ID = "pbtranscript.tasks.scatter_map_isoforms_to_genome"
    DEFAULT_NCHUNKS = 24
    VERSION = "0.1.0"
    DRIVER_EXE = "python -m %s --resolved-tool-contract " % TOOL_ID
    PARSER_DESC = __doc__
    CHUNK_KEYS = ('$chunk.fastq_id', '$chunk.gmap_ref_id')


def get_contract_parser():
    """
    input:
      idx 0: fastq_id
      idx 1: gmap_ref_id
    output:
      idx 0: chunk json
    """
    p = get_scatter_pbparser(Constants.TOOL_ID, Constants.VERSION,
                             "Scatter Map Isoforms Chunks",
                             __doc__, Constants.DRIVER_EXE,
                             chunk_keys=Constants.CHUNK_KEYS,
                             is_distributed=True)

    p.add_input_file_type(FileTypes.FASTQ, "fastq_in",
                          "FASTQ In", "HQ isoforms FASTQ file") # input idx 0
    p.add_input_file_type(FileTypes.DS_GMAP_REF, "gmap_referenceset", "GmapReferenceSet In",
                          "Gmap reference set file") # input 1
    p.add_output_file_type(FileTypes.CHUNK, "cjson_out",
                           "Chunk JSON Map Isoforms Tasks",
                           "Chunked JSON Map Isoforms Tasks",
                           "map_isoforms_to_genome.chunked")
    # max nchunks for this specific task
    p.add_int("pbsmrtpipe.task_options.dev_scatter_max_nchunks", "max_nchunks",
              Constants.DEFAULT_NCHUNKS,
              "Max NChunks", "Maximum number of Chunks")
    return p


def run_main(fastq_file, gmap_ref_file, output_json_file, max_nchunks):
    """
    Parameters:
      fastq_file -- HQ isoforms in FASTQ
      gmap_ref_file -- GMAP reference set xml
      output_json -- chunk.json
    """
    # Check size of fastq_file before scattering, so that a meaningful
    # error message can be displayed instead of 'float division by zero'
    if os.stat(fastq_file).st_size == 0:
        raise IOError("Fastq file %s is empty, exiting." % fastq_file)

    # Chunk FASTQ
    output_fastq_json = output_json_file + ".fastq.json"
    output_dir = op.dirname(output_json_file)
    CU.write_fastq_chunks_to_file(output_fastq_json, fastq_file, max_nchunks,
                                  output_dir, "scattered-fastq", "fastq")

    # get fastq_ids from output_fastq_json
    fastq_chunks = load_pipeline_chunks_from_json(output_fastq_json)
    fastq_files = get_datum_from_chunks_by_chunk_key(fastq_chunks, "$chunk.fastq_id")
    log.debug("Chunked FASTQ files are %s.", (', '.join(fastq_files)))

    # Writing chunk.json
    chunks = []
    for i, fastq_file in enumerate(fastq_files):
        chunk_id = "_".join(["map_isoforms_to_genome_chunk", str(i)])
        d = {Constants.CHUNK_KEYS[0]: fastq_file,
             Constants.CHUNK_KEYS[1]: gmap_ref_file}
        c = PipelineChunk(chunk_id, **d)
        chunks.append(c)

    log.info("Writing chunk.json to %s", output_json_file)
    write_pipeline_chunks(chunks, output_json_file,
                          "created by %s" % Constants.TOOL_ID)
    return 0


def args_run(args):
    """Args runner."""
    raise NotImplementedError()


def rtc_runner(rtc):
    """Resolved tool contract runner."""
    return run_main(fastq_file=rtc.task.input_files[0],
                    gmap_ref_file=rtc.task.input_files[1],
                    output_json_file=rtc.task.output_files[0],
                    max_nchunks=rtc.task.max_nchunks)


def main():
    """Main"""
    mp = get_contract_parser()
    return pbparser_runner(sys.argv[1:],
                           mp,
                           args_run,
                           rtc_runner,
                           log,
                           setup_log)


if __name__ == '__main__':
    sys.exit(main())
