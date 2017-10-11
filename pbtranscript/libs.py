#!/usr/bin/env python
# pylint: disable=no-name-in-module, import-error

from pysam import array_to_qualitystring, Samfile
from pysam import index as pysam_index

try:
    from pysam.libcalignmentfile import AlignmentFile
    from pysam.libcalignedsegment import AlignedSegment
    from pysam.libcfaidx import Fastafile
except ImportError:
    from pysam.calignmentfile import AlignmentFile
    from pysam.calignedsegment import AlignedSegment
    from pysam.cfaidx import Fastafile


