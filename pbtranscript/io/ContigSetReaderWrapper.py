#!/usr/bin/env python

"""
class ContigSetReaderWrapper wraps ContigSet as reader
to read from FASTA, FASTQ, or xml files.

Note that: ContigSetReaderWrapper respects filters in
contigset xml files.

ContigSetReaderWrapper is provided to avoid the overhead
of using ContigSet when input is a FASTA or FASTQ file.
See difference between:
      [r for r in ContigSet("*.fasta")]
and
      [r for r in ContigSetWrapper("*.fasta")]
"""

import logging
import itertools
from pbcore.io import (FastaReader, FastqReader, ContigSet,
                       FastaRecord, FastqRecord,
                       FastaWriter, FastqWriter)
from pbcore.io.FastaIO import IndexedFastaRecord

__author__ = 'yli@pacificbiosciences.com'

log = logging.getLogger(__name__)

__all__ = ["ContigSetReaderWrapper"]


class ContigSetReaderWrapper(object):

    """
    Wraps readers for input FASTA, FASTQ, ContigSet xml,

    <input>.fasta|fastq|xml accepted.

    e.g.:
        [r for r in ContigSetReaderWrapper(input_fn)]
    """
    FILE_TYPE = {"FA": "FASTA", "FASTA": "FASTA",
                 "FQ": "FASTQ", "FASTQ": "FASTQ",
                 "XML": "CONTIGSET"}
    def __init__(self, *input_filenames):
        """
        *input_filenames - input FASTA/FASTQ/ContigSet files
        """
        self.readers = self._open_files(*input_filenames)
        self.reader_index = 0
        self.it = self.readers[self.reader_index].__iter__()

    @classmethod
    def get_file_type(cls, input_filename):
        """Return file type: FASTA, FASTQ, CONTIGSET"""
        if not input_filename.rfind('.') >= 0:
            raise IOError("Could not recoginize file type of %s" % input_filename)
        else:
            suffix = input_filename[input_filename.rfind('.') + 1:].upper()
            return ContigSetReaderWrapper.FILE_TYPE[suffix]

    def _open_files(self, *input_filenames):
        """Open file handers and return."""
        readers = []
        for fn in input_filenames:
            if ContigSetReaderWrapper.get_file_type(fn) == "FASTA":
                readers.append(FastaReader(fn))
            elif ContigSetReaderWrapper.get_file_type(fn) == "FASTQ":
                readers.append(FastqReader(fn))
            elif ContigSetReaderWrapper.get_file_type(fn) == "CONTIGSET":
                readers.append(ContigSet(fn))
            else:
                raise IOError("Could not read %s as FASTA/FASTQ/CONTIGSET file." % fn)
        return readers

    def __iter__(self):
        iters = [reader.__iter__() for reader in self.readers]
        return itertools.chain(*iters)

    def __len__(self):
        errMsg = "%s.__len__ not defined." % self.__class__.__name__
        raise NotImplementedError(errMsg)

    def __delitem__(self, key):
        errMsg = "%s.__delitem__ not defined." % self.__class__.__name__
        raise NotImplementedError(errMsg)

    def __setitem__(self, key, value):
        errMsg = "%s.__setitem__ not defined." % self.__class__.__name__
        raise NotImplementedError(errMsg)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        """Close all readers."""
        for reader in self.readers:
            reader.close()

    def next(self):
        """Return the next FastaRecord or FastqRecord."""
        try:
            return next(self.it)
        except StopIteration:
            self.reader_index += 1
            if self.reader_index < len(self.readers):
                self.it = self.readers[self.reader_index].__iter__()
            else:
                raise StopIteration

    def consolidate(self, out_prefix):
        """Consolidate ContigSet to FASTA/FASTQ file, return path to output file."""
        try:
            r0 = next(self)
        except StopIteration:
            raise ValueError("No records to consolidate")
        if isinstance(r0, FastaRecord) or isinstance(r0, IndexedFastaRecord):
            out_fn = out_prefix + ".fasta"
            with FastaWriter(out_fn) as writer:
                writer.writeRecord(r0.name, r0.sequence[:])
                while True:
                    try:
                        r = next(self)
                    except StopIteration:
                        break
                    if not (isinstance(r, FastaRecord) or isinstance(r, IndexedFastaRecord)):
                        raise ValueError("Not able to consolidate records of mixed types.")
                    writer.writeRecord(r.name, r.sequence)
            return out_fn
        elif isinstance(r0, FastqRecord):
            out_fn = out_prefix + ".fastq"
            with FastqWriter(out_fn) as writer:
                writer.writeRecord(r0)
                while True:
                    try:
                        r = next(self)
                    except StopIteration:
                        break
                    if not isinstance(r, FastqRecord):
                        raise ValueError("Not able to consolidate records of mixed types.")
                    writer.writeRecord(r)
            return out_fn
        else:
            raise ValueError("Files must only contain FASTA/FASTQ records.")

    @staticmethod
    def name_to_len_dict(args):
        """Return dict {read_name: read_length}."""
        with ContigSetReaderWrapper(args) as reader:
            return dict({r.name.split()[0]: len(r.sequence[:]) for r in reader})

    @staticmethod
    def check_ids_unique(input_filename):
        """
        Confirm that a FASTA/FASTQ file has all unique IDs
        (used probably by collapse or fusion finding script)

        Parameters:
          input_filename - an input FASTA/FASTQ or contigset dataset xml
        """
        reader = ContigSetReaderWrapper(input_filename)
        seen = set()
        for r in reader:
            if r.name in seen:
                raise ValueError("Duplicate id {0} detected. Abort!".format(r.name))
            seen.add(r.name)
