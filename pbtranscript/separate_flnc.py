#!/usr/bin/env python

"""
Split full-length non-chimeric reads, either by length
or by primer.
"""
import logging
import os
import os.path as op
import sys
from cPickle import dump, load
from collections import defaultdict
from pbtranscript.Utils import realpath, mkdir, as_contigset
from pbtranscript.io.ContigSetReaderWrapper import ContigSetReaderWrapper


__author__ = "etseng@pacificbiosciences.com"

__all__ = ["SeparateFLNCRunner",
           "convert_pickle_to_sorted_flnc_files"]


class SeparateFLNCBase(object):
    """
    Base class to separate FLNC reads.
    """
    def __init__(self, flnc_filename, root_dir, out_pickle, output_basename):
        """
        Reads in input flnc file will be separated into multiple categories
        according to separation criterion, and reads in each category will
        be written into
            <root_dir>/<separation_criteria>/<output_basename>.fasta|contigset.xml

        e.g., if reads are separated by primers, then reads will be written to
        <root_dir>/<primer*>/<output_basename>.fasta|contigset.xml

        Parameters:
          flnc_filename - input full length non-chimeric reads in FASTA or CONTIGSET
          root_dir - output root directory
          output_basename - output file basename
        """
        self.flnc_filename = flnc_filename
        self.root_dir = realpath(root_dir)
        mkdir(root_dir)
        self.output_basename = output_basename
        self.create_contigset = True if flnc_filename.endswith(".xml") else False
        self.handles = {} # key --> fasta file handler
        self.out_pickle = out_pickle if out_pickle is not None \
                          else op.join(self.root_dir, "separate_flnc.pickle")

    def __enter__(self):
        # make a sub dir for each separation criteria
        for d in self.out_dirs:
            mkdir(d)

        # open all fasta file handlers
        for index, key in enumerate(self.sorted_keys):
            self.handles[key] = open(self.out_fasta_files[index], 'w')

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close all fasta file handles.
        If create_contigset is True, convert out_fasta_files to out_contigset_files.
        """
        # close fasta file handlers
        for f in self.handles.itervalues():
            f.close()

        if self.create_contigset is True:
            for fasta_fn, xml_fn in zip(self.out_fasta_files, self.out_contigset_files):
                as_contigset(fasta_fn, xml_fn)

        # write out_pickle
        self.write_pickle()

    def __len__(self):
        """Return total number of separation criterion."""
        return len(self.sorted_keys)

    def __str__(self):
        return "{c} separate FLNC reads by: {sc}\nOutput dirs:\n{o}\n" \
                .format(c=self.__class__.__name__,
                        sc=", ".join(self.separation_criterion),
                        o="\n".join(self.out_dirs))

    def __repr__(self):
        return self.__str__()

    @property
    def sorted_keys(self):
        """Return a list of sorted keys each represents a separation criteria."""
        raise NotImplementedError("%s.sorted_keys" % self.__class__.__name__)

    def separation_criteria(self, key):
        """Return separation criteria of key.
        e.g., a primer index or a tuple of (SizeBin, part_num)
        """
        raise NotImplementedError("%s.separation_criteria" % self.__class__.__name__)

    @property
    def separation_criterion(self):
        """Return a list of sorted separation criterion strings."""
        return [self.separation_criteria(key=key) for key in self.sorted_keys]

    @property
    def out_dirs(self):
        """Return a list of output directories.
        e.x., <root_dir>/<separation_criteria_i>/
        """
        return [op.join(self.root_dir, sc) for sc in self.separation_criterion]

    @property
    def out_fasta_files(self):
        """Return a list of output fasta files."""
        return [op.join(d, ("%s.fasta" % self.output_basename))
                for d in self.out_dirs]

    @property
    def out_contigset_files(self):
        """Return a list of output contigset files."""
        return [op.join(d, ("%s.contigset.xml" % self.output_basename))
                for d in self.out_dirs]

    def run(self):
        """Separate reads and write to out_fasta_files."""
        raise NotImplementedError("%s.run" % self.__class__.__name__)

    def write_pickle(self):
        """Write output pickle with {sorted_key: out_contigset|fasta_files}
        """
        d = dict()
        d['sorted_keys'] = self.sorted_keys
        d['key_to_file'] = dict()
        for index, key in enumerate(self.sorted_keys):
            if os.stat(self.out_fasta_files[index]).st_size > 0:
                if self.create_contigset is False:
                    d['key_to_file'][key] = self.out_fasta_files[index]
                else:
                    d['key_to_file'][key] = self.out_contigset_files[index]
        with open(self.out_pickle, 'wb') as writer:
            dump(d, writer)

    @staticmethod
    def convert_pickle_to_sorted_flnc_files(in_pickle):
        """Read from in_pickle and convert to sorted flnc files.
        Return a list of sorted flnc files.
        """
        a = load(open(in_pickle, 'rb'))
        if 'sorted_keys' not in a.keys() or 'key_to_file' not in a.keys():
            raise ValueError("%s is not a valid SeparateFLNCBase pickle."
                             % in_pickle)
        return [a['key_to_file'][key] for key in a['sorted_keys']]


class SeparateFLNCByPrimer(SeparateFLNCBase):
    """
    Separate flnc fasta by primer and save separated flnc reads to
    <root_dir>/primer<id>/isoseq_flnc.fasta|contigset.xml

    This is useful for targeted sequencing.

    Note that each flnc read name must contain 'primer=<id>' string.

    ex: make <root_dir>/primer0/isoseq_flnc.fasta|contigset.xml
    """
    def __init__(self, flnc_filename, root_dir, out_pickle=None,
                 output_basename="isoseq_flnc"):
        super(SeparateFLNCByPrimer, self).__init__(flnc_filename=flnc_filename,
                                                   root_dir=root_dir,
                                                   out_pickle=out_pickle,
                                                   output_basename=output_basename)

        self.primer_ids = self.get_primer_ids()

    def _get_primer_id(self, r):
        """Given a read, return its primer id as an int."""
        for x in r.name.split(';'):
            if x.startswith('primer='):
                return int(x.split('=')[1])

        raise ValueError("Unable to find primer information " +
                         "from sequence ID for {n} in {f}! Abort!"
                         .format(n=r.name, f=self.flnc_filename))

    def get_primer_ids(self):
        """Return primer ids seen in input FLNC file."""
        primer_ids = set()
        for r in ContigSetReaderWrapper(self.flnc_filename):
            primer_ids.add(self._get_primer_id(r))

        primer_ids = sorted(list(primer_ids))
        return primer_ids

    @property
    def sorted_keys(self):
        """Return a list of sorted primer ids as keys."""
        return self.primer_ids

    def separation_criteria(self, key):
        """Key is a primer id, return separation criteria of the primer."""
        return "primer{key}".format(key=key)

    def run(self):
        """Run"""
        # separate reads and write
        for r in ContigSetReaderWrapper(self.flnc_filename):
            p = self._get_primer_id(r)
            self.handles[p].write(">{0}\n{1}\n".format(r.name, r.sequence[:]))

        assert all([os.stat(x).st_size > 0 for x in self.out_dirs])


class SizeBin(object):
    """
    SizeBin(lb, ub) -> [lb kb, ub kb)
    """
    def __init__(self, lb, ub):
        assert isinstance(lb, int) and isinstance(ub, int)
        self.lb = min(lb, ub)
        self.ub = max(lb, ub)

    def contains(self, input_value):
        """If input_value in [lb, ub). Note that lb and ub are in kb."""
        if isinstance(input_value, int):
            return input_value/1000 >= self.lb and input_value/1000 < self.ub
        elif isinstance(input_value, SizeBin):
            return self.lb <= input_value.lb and self.ub >= input_value.ub

    def __str__(self):
        return "{lb}to{ub}kb".format(lb=self.lb, ub=self.ub)

    def __repr__(self):
        return "%s %s" % (self.__class__.__name__, self.__str__())

    def __lt__(self, other):
        if max(self.lb, other.lb) < min(self.ub, other.ub):
            raise ValueError("Could not compare size bin %s and %s)" %
                             (self.__str__(), str(other)))
        return self.ub <= other.lb

    def __eq__(self, other):
        return self.lb == other.lb and self.ub == other.ub


class SizeBins(object):
    """
    Convert a list of ints or a list of SizeBins to a `sorted` list of SizeBins
    e.x. SizeBins([0, 1, 3, 4]) -> [ SizeBin(0, 1), SizeBin(1, 3), SizeBin(3, 4), SizeBin(4, 5)]
    """
    def __init__(self, b_list):
        b_list = list(b_list[:])
        self._bins = None
        if all([isinstance(b, int) for b in b_list]):
            b_list = sorted(set(b_list))
            b_list.append(b_list[-1]+1)
            self._bins = [SizeBin(b_list[i], b_list[i+1]) for i in range(0, len(b_list)-1)]
        elif all([isinstance(b, SizeBin) for b in b_list]):
            self._bins = sorted(b_list)
        else:
            raise ValueError("%s could not take %s as input." %
                             (self.__class__.__name__, str(b_list)))

    def toList(self):
        """Return a list of SizeBin objects."""
        assert isinstance(self._bins, list)
        assert all([isinstance(b, SizeBin) for b in self._bins])
        return self._bins

    def __len__(self):
        return len(self._bins)

    def __str__(self):
        return "SizeBins: [%s]" % (", ".join([str(self._bins[i])
                                              for i in range(0, self.__len__())]))
    def __repr__(self):
        return self.__str__()

    def __iter__(self):
        return iter(self._bins)

    def __getitem__(self, index):
        return self._bins[index]

    def __setitem__(self, index, value):
        self._bins[index] = value
        self._bins = sorted(self._bins)
        return self

    def __delitem__(self, index):
        self._bins.__delitem__(index)
        return self

    def which_bin_contains(self, input_value):
        """which bin does input input_value belong to?"""
        assert isinstance(input_value, int) or isinstance(input_value, SizeBin)

        for b in self._bins:
            if b.contains(input_value):
                return b
        raise ValueError("Could not assign input value %s to %s" %
                         (input_value, self.__str__()))


class SeparateFLNCBySize(SeparateFLNCBase):
    """
    Separate flnc fasta into different size bins
    ex: make <root_dir>/0to2k/isoseq_flnc.fasta ... etc ...

    """
    def __init__(self, flnc_filename, root_dir, out_pickle=None,
                 output_basename="isoseq_flnc", bin_size_kb=1,
                 bin_manual=None, max_base_limit_MB=600):
        """
        Parameters:
          bin_size_kb - size bins are "0to1K", "1to2K", ..., "{n}to{n+1}K"
          bin_manual - manually sepcificied size bin
          max_base_limit_MB - maximum number of bases in Mb in each bin.

          If <bin_manual> (ex: (0, 2, 4, 12)) is given, <bin_size_kb> is ignored.

          If max_base_limit_MB is not None, it caps the per-partition # of bases (in Mb)
          So could have 0to1k_part1, 0to2k_part2...etc...
        """
        super(SeparateFLNCBySize, self).__init__(flnc_filename=flnc_filename,
                                                 root_dir=root_dir,
                                                 out_pickle=out_pickle,
                                                 output_basename=output_basename)
        # a dictionary mapping a SizeBin to number of parts in the SizeBin
        # {SizeBin(lb, ub): num_parts in SizeBin(lb, ub)}
        self.size_bins_parts = self.get_size_bins_parts(bin_size_kb=bin_size_kb,
                                                        bin_manual=bin_manual,
                                                        max_base_limit_MB=max_base_limit_MB)

    def get_size_bins_parts(self, bin_size_kb, bin_manual, max_base_limit_MB):
        """
        return a dict {SizeBin: number of parts in this SizeBin}
        """
        # first check min - max size range
        min_size = sys.maxsize + 1
        max_size = 0
        base_in_each_size = defaultdict(lambda: 0) # SizeBin --> number of bases
        for r in ContigSetReaderWrapper(self.flnc_filename):
            seqlen = len(r.sequence)
            min_size = min(min_size, seqlen)
            max_size = max(max_size, seqlen)
            b = SizeBin(seqlen/1000, seqlen/1000+1)
            base_in_each_size[b] += len(r.sequence)

        min_size_kb = min_size/1000
        max_size_kb = max_size/1000 + (1 if max_size%1000 != 0 else 0)

        logging.info("Min read length: %s, %s KB, max read length: %s, %s KB",
                     str(min_size), str(min_size_kb), str(max_size), str(max_size_kb))

        size_bins = None
        if bin_manual is not None and len(bin_manual) > 0:
            if bin_manual[0] > min_size_kb:
                bin_manual.insert(0, min_size_kb)
                logging.warning("bin_manual has been reset to %s kb!", bin_manual)
            if bin_manual[-1] < max_size_kb:
                bin_manual.append(max_size_kb)
                logging.warning("bin_manual has been reset to %s kb!", bin_manual)
            size_bins = SizeBins(bin_manual)
        else:
            size_bins = SizeBins(range(min_size_kb, max_size_kb+1, bin_size_kb))

        logging.info("Read size bins are: %s", str(size_bins))
        size_bins_bases = dict({b:0 for b in size_bins}) # SizeBin -> total n of bases in it
        size_bins_parts = dict({b:0 for b in size_bins}) # SizeBin -> total n of partitions in it
        if max_base_limit_MB is not None:
            for _b, num_bases in base_in_each_size.iteritems():
                b = size_bins.which_bin_contains(_b)
                size_bins_bases[b] += num_bases

            for b, num_bases in size_bins_bases.iteritems():
                size_bins_parts[b] = int((size_bins_bases[b]*1.0 / 10**6) / max_base_limit_MB) + \
                        (1 if (num_bases*1. / 10**6) % max_base_limit_MB > 0 else 0)

        return size_bins_parts

    @property
    def size_bins(self):
        """Return a list of sorted SizeBin objects.
        Note that some size_bins may not contain any reads and thus not in sorted_keys
        """
        return SizeBins(self.size_bins_parts.keys())

    @property
    def sorted_keys(self):
        """Return a list of sorted tuples, where each tuple is (SizeBin, partnum), as keys.
        Note that every item in the tuple must contain at least one read.
        """
        ret = []
        for b in self.size_bins:
            for p in range(0, self.size_bins_parts[b]):
                ret.append((b, p))
        return ret

    def separation_criteria(self, key):
        """key is a tuple (SizeBin, part), return a string "<SizeBin>_part<p>"
        e.g.. "0to1kb_part0"
        """
        assert len(key) == 2
        b, p = key[0], key[1]
        assert isinstance(b, SizeBin) and isinstance(p, int)
        return "{b}_part{p}".format(b=b, p=p)

    def run(self):
        """Run"""
        read_counter_in_each_bin = dict({b:0 for b in self.size_bins})

        for r in ContigSetReaderWrapper(self.flnc_filename):
            b = self.size_bins.which_bin_contains(len(r.sequence))
            p = read_counter_in_each_bin[b] % self.size_bins_parts[b]
            read_counter_in_each_bin[b] += 1
            self.handles[(b, p)].write(">{0}\n{1}\n".format(r.name, r.sequence[:]))


class SeparateFLNCRunner(object):
    """Runner to either bin by primer, by manual or by size kb."""
    def __init__(self, flnc_fa, root_dir, out_pickle,
                 bin_size_kb, bin_by_primer, bin_manual, max_base_limit_MB):
        self.flnc_fa = flnc_fa
        self.root_dir = root_dir
        self.out_pickle = out_pickle
        self.bin_size_kb = bin_size_kb
        self.bin_by_primer = bool(bin_by_primer)
        self.bin_manual = bin_manual
        self.max_base_limit_MB = int(max_base_limit_MB)

    def run(self):
        """Run"""
        if self.bin_by_primer is True:
            logging.warning("Separate FLNC reads by primers, overwrite bin_manual and bin_size_kb.")
            with SeparateFLNCByPrimer(flnc_filename=self.flnc_fa,
                                      root_dir=self.root_dir,
                                      out_pickle=self.out_pickle) as obj:
                obj.run()
        else:
            bin_manual = None
            if self.bin_manual is not None:
                tmp = "".join([x for x in str(self.bin_manual) if x.isdigit() or x == ','])
                if len(tmp) > 0:
                    logging.info("Converting bin_manual %s to a list of integers.", tmp)
                    bin_manual = sorted([int(x) for x in tmp.split(',')])
                    logging.info("converted bin_manual=%s", bin_manual)
            with SeparateFLNCBySize(flnc_filename=self.flnc_fa, root_dir=self.root_dir,
                                    bin_size_kb=self.bin_size_kb,
                                    bin_manual=bin_manual,
                                    max_base_limit_MB=self.max_base_limit_MB,
                                    out_pickle=self.out_pickle) as obj:
                obj.run()
        return 0


def convert_pickle_to_sorted_flnc_files(in_pickle):
    return SeparateFLNCBase.convert_pickle_to_sorted_flnc_files(in_pickle)
