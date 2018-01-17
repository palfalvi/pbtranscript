#!/usr/bin/env python
"""
Class ChainConfig, read and write Chain config file.
"""
from __future__ import print_function

import os.path as op
from collections import namedtuple
from pbtranscript.Utils import realpath

__author__ = "etseng@pacificbiosciences.com, yli@pacificbiosciences.com"


__all__ = ["SampleFiles", "ChainConfig"]


SampleFiles = namedtuple('SampleFiles', ['name', 'path', 'group_fn', 'gff_fn', 'abundance_fn'])


class ChainConfig(object):

    """Chain Config.

        Read a ChainConfig object from an input file
            config_obj = ChainConfig.from_file("input_chain.config")

        Write a ChainConfig object to an output file
        ChainConfig.write("output_chain.config")
    """

    def __init__(self, sample_names, sample_paths, group_fn, gff_fn, abundance_fn):
        self.sample_names = sample_names
        self.sample_paths = sample_paths
        self.group_fn = group_fn  # str
        self.gff_fn = gff_fn  # str
        self.abundance_fn = abundance_fn  # str
        self._sanity_check()

    def _sanity_check(self):
        if not len(self.sample_names) == len(self.sample_paths):
            raise ValueError(
                "sample_names %s must match sample_paths %s", (self.sample_names, self.sample_paths))
        if not all((isinstance(x, str) and len(x) > 0)
                   for x in (self.group_fn, self.gff_fn, self.abundance_fn)):
            raise ValueError("File names must be strings: %s %s %s",
                             self.group_fn, self.gff_fn, self.abundance_fn)

    @property
    def samples(self):
        """return a list of SampleFiles object"""
        ret = []
        for sample_name, sample_dir in zip(self.sample_names, self.sample_paths):
            def g(d, base_fn):
                """Convert file basename to abs file path"""
                return op.join(realpath(d), base_fn)
            s = SampleFiles(name=sample_name, path=sample_dir, gff_fn=g(sample_dir, self.gff_fn),
                            group_fn=g(sample_dir, self.group_fn),
                            abundance_fn=g(sample_dir, self.abundance_fn))
            ret.append(s)
        return ret

    @classmethod
    def from_file(cls, cfg_fn):
        """read from a config file with
        SAMPLE=<name>;<path>

        GROUP_FILENAME=
        GFF_FILENAME=
        COUNT_FILENAME=
        """
        sample_names, sample_paths = [], []
        group_fn = gff_fn = abundance_fn = None
        for line in [line.strip() for line in open(realpath(cfg_fn), 'r')]:
            # read and process
            if line.startswith('SAMPLE='):
                name, path = line.strip()[7:].split(';')
                sample_names.append(name)
                sample_paths.append(realpath(path))
            elif line.startswith('GROUP_FILENAME='):
                group_fn = line.strip()[len('GROUP_FILENAME='):]
            elif line.startswith('GFF_FILENAME='):
                gff_fn = line.strip()[len('GFF_FILENAME='):]
            elif line.startswith('COUNT_FILENAME='):
                abundance_fn = line.strip()[len('COUNT_FILENAME='):]
        try:
            return ChainConfig(sample_names=sample_names, sample_paths=sample_paths,
                               group_fn=group_fn, gff_fn=gff_fn, abundance_fn=abundance_fn)
        except ValueError as e:
            raise ValueError("%s is an invalid ChainConfig file: %s" % (realpath(cfg_fn), str(e)))

    def __str__(self):
        ret1 = ['SAMPLE=%s;%s' % (sample_name, sample_dir)
                for sample_name, sample_dir in zip(self.sample_names, self.sample_paths)]
        ret2 = ['GROUP_FILENAME=%s' % self.group_fn,
                'GFF_FILENAME=%s' % self.gff_fn,
                'COUNT_FILENAME=%s' % self.abundance_fn]
        return '\n'.join(ret1 + [''] + ret2)

    def write(self, o_cfg_fn=None):
        """Write cfg to output file. If o_cfg_fn is None, print to stdout."""
        if o_cfg_fn is not None:
            with open(o_cfg_fn, 'w') as writer:
                writer.write(self.__str__())
        else:
            print(self.__str__())


