#!/usr/bin/env python

"""Streaming IO support for ReadStat files."""

import os.path as op
from pbcore.io import ReaderBase, WriterBase
from pbcore.io._utils import splitFileContents


__all__ = ["MapStatus",
           "ReadStatRecord",
           "ReadStatReader",
           "ReadStatWriter"]


def get_len_from_read_name(seqid):
    """Return length from read name"""
    # <movie>/<zmw>/<start>_<end>_CCS
    try:
        if seqid.endswith('_CCS'):
            #raise ValueError("CCS read name must be <movie>/<zmw>/<start>_<end>_CCS! Abort!")
            s, e, dummy_junk = seqid.split('/')[2].split('_')
        else:
            s, e = seqid.split('/')[2].split('_')
        return abs(int(s)-int(e))
    except (IndexError, ValueError):
        raise ValueError("Could not get read length from read name %s" % seqid)


class MapStatus(object):
    """Read mapping status"""
    UNMAPPED = "unmapped"
    UNIQUELY_MAPPED = "unique"
    AMBIGUOUSLY_MAPPED = "ambiguous"


class ReadStatRecord(object):
    """A ReadStatRecord contains status of a read, including
    read name, read length, is it FLNC, status, and pbid.
    while pbid is id of collapsed isoform that the read is associated with;
    and status can be one of unmapped|uniquely mapped|ambiguously mapped

    e.g.,
    {name}\t{len}\t{is_fl}\t{stat}\t{pbid}
    """
    STATUS = [MapStatus.UNMAPPED, MapStatus.UNIQUELY_MAPPED, MapStatus.AMBIGUOUSLY_MAPPED]

    def __init__(self, name, is_fl, stat, pbid):
        self.name = name
        self.length = get_len_from_read_name(name)
        if str(is_fl) == "True" or str(is_fl) == "Y":
            self.is_fl = True
        elif str(is_fl) == "False" or str(is_fl) == "N":
            self.is_fl = False
        if stat not in ReadStatRecord.STATUS:
            raise ValueError("ReadStatRecord status %s must be in %s" %
                             (stat, ReadStatRecord.STATUS))
        self.stat = stat
        self.pbid = None if str(pbid) in ('None', 'NA') else pbid

        if self.is_unmapped and self.pbid is not None:
            raise ValueError("pbid of unmapped ReadStatRecord %s must be None." % str(self))
        if self.is_fl and self.is_ambiguously_mapped:
            raise ValueError("FL read %s must not be ambiguously mapped." % str(self.name))

    def __str__(self):
        return "\t".join([str(x) for x in [self.name, self.length,
                                           'Y' if self.is_fl is True else 'N',
                                           self.stat,
                                           'NA' if self.pbid is None else self.pbid]])

    def __repr__(self):
        return "<ReadStatIO %s>" % self.__str__()

    def __eq__(self, other):
        return (self.name == other.name and self.length == other.length and
                self.is_fl == other.is_fl and self.stat == other.stat and
                self.pbid == other.pbid)

    @classmethod
    def fromString(cls, line):
        """Construct and return a ReadStatRecord object given a string."""
        fields = line.strip().split('\t')
        if len(fields) != 5:
            raise ValueError("Could not recognize %s as a valid ReadStatRecord." % line)
        if int(fields[1]) != get_len_from_read_name(fields[0]):
            raise ValueError("Read length %s != computed from read name %s" % (fields[1], fields[0]))
        return ReadStatRecord(name=fields[0], is_fl=fields[2], stat=fields[3], pbid=fields[4])

    @classmethod
    def header(cls):
        """Return header string"""
        return "\t".join(["id", "length", "is_fl", "stat", "pbid"])

    @property
    def is_uniquely_mapped(self):
        """Returns True if this record is uniquely mapped to exactly one isoforms."""
        return self.stat == MapStatus.UNIQUELY_MAPPED

    @property
    def is_ambiguously_mapped(self):
        """Returns True if this record is ambiguously mapped to multiple isoforms."""
        return self.stat == MapStatus.AMBIGUOUSLY_MAPPED

    @property
    def is_unmapped(self):
        """Returns True if this record is not mapped to any isoforms."""
        return self.stat == MapStatus.UNMAPPED


class ReadStatReader(ReaderBase):

    """
    Streaming reader for a Read Status file.

    Example:

    .. doctest::
        >>> from pbtranscript.io import ReadStatusReader
        >>> filename = "../../../tests/data/test_ReadStatus.txt"
        >>> for record in ReadStatusReader(filename):
        ...     print record
        readid\t1000\tTrue\tunmapped\tNone

    """
    def __iter__(self):
        try:
            lines = splitFileContents(self.file, "\n")
            for line in lines:
                line = line.strip()
                if len(line) > 0 and line[0] != "#" and line != ReadStatRecord.header():
                    yield ReadStatRecord.fromString(line)
        except AssertionError:
            raise ValueError("Invalid ReadStat file %s." % self.file.name)


class ReadStatWriter(WriterBase):

    """
    Write ReadStat to a file.
    """

    def __init__(self, f, mode='w'):
        """
        Prepare for output to the file
        """
        if mode != "w" and mode != "a":
            raise ValueError("Invalid file open mode %s" % mode)

        self.file = open(op.abspath(op.expanduser(f)), mode)

        if hasattr(self.file, "name"):
            self.filename = self.file.name
        else:
            self.filename = "(anonymous)"
        if mode == "w":
            self.file.write("{0}\n".format(ReadStatRecord.header()))

    def writeRecord(self, record):
        """Write a ReadStatRecrod."""
        if not isinstance(record, ReadStatRecord):
            raise ValueError("record type %s is not ReadStatRecord." % type(record))
        else:
            self.file.write("{0}\n".format(str(record)))
