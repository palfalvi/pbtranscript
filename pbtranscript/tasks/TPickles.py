#!/usr/bin/env python
"""
Class ChunkTask defines info used for chunk tasks ICE, ice_partial
and ice_polish.

Class ChunkTasksPickle reads and writes ChunkTask objects from/to
input/output pickle files.
"""
from __future__ import print_function
import cPickle
import os.path as op
from pbcore.io import ContigSet
from pbtranscript.ice.IceFiles import IceFiles

def n_reads_in_contigset(contigset_file):
    """Return number of reads in a contigset"""
    cs = ContigSet(contigset_file)
    cs.assertIndexed()
    return int(cs.numRecords)


def n_reads_in_contigsets(contigset_files):
    """Given a list of contigset files, return number of reads in
    these files as a list of ints"""
    return [n_reads_in_contigset(f) for f in contigset_files]


class ChunkTask(object):
    """
    An instance of class represents a chunk task.
    """
    def __init__(self, cluster_bin_index, flnc_file, cluster_out_dir):
        self.cluster_bin_index = cluster_bin_index
        self.flnc_file = flnc_file
        self.cluster_out_dir = cluster_out_dir
        self.n_flnc_reads = 0
        if op.exists(self.flnc_file):
            self.n_flnc_reads = n_reads_in_contigset(self.flnc_file)
            #raise IOError("Could not find flnc_file %s" % self.flnc_file)

    @property
    def consensus_isoforms_file(self):
        """Return output consensus isoform file, cluster_out/output/final.consensus.fasta"""
        return IceFiles(root_dir=self.cluster_out_dir, prog_name="", no_log_f=True).final_consensus_fa

    @property
    def flnc_pickle(self):
        """Return output flnc pickle file, cluster_out/output/final.pickle"""
        return IceFiles(root_dir=self.cluster_out_dir, prog_name="", no_log_f=True).final_pickle_fn

    def __str__(self):
        strs = ["{cls} obj:".format(cls=self.__class__.__name__),
                "  cluster bin index {i}, ".format(i=self.cluster_bin_index),
                "  flnc file {f}, ".format(f=self.flnc_file),
                "  cluster out dir {d},".format(d=self.cluster_out_dir)]
        if hasattr(self, 'n_flnc_reads'):
            strs.append("  number of flnc reads {n}".format(n=self.n_flnc_reads))
        return "\n".join(strs)

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        return self.cluster_bin_index == other.cluster_bin_index and \
               self.flnc_file == other.flnc_file and \
               self.cluster_out_dir == other.cluster_out_dir


class ClusterChunkTask(ChunkTask):
    """
    Each instance of class represents a ChunkTask of ICE clustering.
    """
    def __init__(self, cluster_bin_index, flnc_file, cluster_out_dir):
        super(ClusterChunkTask, self).__init__(cluster_bin_index=cluster_bin_index,
                                               flnc_file=flnc_file,
                                               cluster_out_dir=cluster_out_dir)
    @property
    def nfl_pickle(self):
        """Return output nfl pickle file, cluster_out/output/nfl.all.partial_uc.pickle
        """
        return IceFiles(prog_name="", root_dir=self.cluster_out_dir, no_log_f=True).nfl_all_pickle_fn


class PartialChunkTask(ChunkTask):
    """
    Each instance of class represents an ice_partail chunk task.
    """
    def __init__(self, cluster_bin_index, flnc_file, cluster_out_dir,
                 nfl_file, nfl_index, n_nfl_chunks):
        super(PartialChunkTask, self).__init__(cluster_bin_index=cluster_bin_index,
                                               flnc_file=flnc_file,
                                               cluster_out_dir=cluster_out_dir)
        self.nfl_file = nfl_file
        self.nfl_index = int(nfl_index)
        self.n_nfl_chunks = int(n_nfl_chunks)

    def __str__(self):
        return "\n".join([super(PartialChunkTask, self).__str__(),
                          "  nfl file {i}/{n}: {f}, ".format(i=self.nfl_index,
                                                             n=self.n_nfl_chunks,
                                                             f=self.nfl_file)])

    def __eq__(self, other):
        return super(PartialChunkTask, self).__eq__(other) and \
               self.nfl_index == other.nfl_index and \
               self.n_nfl_chunks == other.n_nfl_chunks and \
               self.nfl_file == other.nfl_file

    @property
    def nfl_pickle(self):
        """Return output nfl pickle of the i-th chunk."""
        return IceFiles(prog_name="", root_dir=self.cluster_out_dir, no_log_f=True).nfl_pickle_i(self.nfl_index)


class PolishChunkTask(ChunkTask):
    """Class represents an ice_poish (quiver|arrow) chunk task."""
    def __init__(self, cluster_bin_index, flnc_file, cluster_out_dir,
                 polish_index, n_polish_chunks):
        """
        ice_polish (quiver|arrow) chunk (index, num_chunks) of a particular bin.
        Parameters:
          polish_index -- index of this chunked task in all ice_polish tasks
          n_polish_chunks  -- total number of ice_polish chunks
        """
        super(PolishChunkTask, self).__init__(cluster_bin_index=cluster_bin_index,
                                              flnc_file=flnc_file,
                                              cluster_out_dir=cluster_out_dir)
        self.polish_index = int(polish_index)
        self.n_polish_chunks = int(n_polish_chunks)

        assert self.polish_index >= 0
        assert self.polish_index < self.n_polish_chunks

    @property
    def nfl_pickle(self):
        """Return output nfl pickle file, cluster_out/output/nfl.all.partial_uc.pickle
        """
        return IceFiles(prog_name="", root_dir=self.cluster_out_dir, no_log_f=True).nfl_all_pickle_fn

    def __str__(self):
        desc = [super(PolishChunkTask, self).__str__(),
                "ice_polish chunk {x}/{n} for cluster bin {y}".
                format(x=self.polish_index, n=self.n_polish_chunks,
                       y=self.cluster_bin_index)]
        return "\n".join(desc)

    def __eq__(self, other):
        return super(PolishChunkTask, self).__eq__(other) and \
               self.polish_index == other.polish_index and \
               self.n_polish_chunks == other.n_polish_chunks


class ChunkTasksPickle(object):
    """Read and write input/output files used in cluster bins in a pickle."""
    def __init__(self, chunk_tasks=None):
        if chunk_tasks is None:
            chunk_tasks = []
        assert isinstance(chunk_tasks, list)
        assert all([isinstance(task, ChunkTask) for task in chunk_tasks])

        self.chunk_tasks = chunk_tasks

    def write(self, out_pickle_file):
        """Write chunk tasks to output pickle."""
        with open(out_pickle_file, 'wb') as f:
            cPickle.dump(self.chunk_tasks, f)

    def sorted_no_redundant_cluster_bins(self):
        """Return a list of unique (cluster_bin_index, cluster_out_dir) tuples
        sorted by cluster_bin_index"""
        return sorted(list(set([(task.cluster_bin_index, task.cluster_out_dir)
                                for task in self.chunk_tasks])),
                      key=lambda x: x[0])

    @staticmethod
    def read(in_pickle_file):
        """Read an object from a pickle file."""
        with open(in_pickle_file, 'rb') as f:
            a = cPickle.load(f)
            return ChunkTasksPickle(a)

    def append(self, chunk_task):
        """Append this chunk_task to self.chunk_tasks."""
        self.chunk_tasks.append(chunk_task)

    def sorted_by_attr(self, attr, reverse=False):
        """Sort chunk_tasks by attribute attr."""
        assert all([hasattr(task, attr) for task in self.chunk_tasks])
        self.chunk_tasks = sorted(self.chunk_tasks,
                                  key=lambda x: getattr(x, attr),
                                  reverse=reverse)

    @property
    def n_flnc_reads_in_bins(self):
        """Return number of flnc reads in each ChunkTask object."""
        return n_reads_in_contigsets([task.flnc_file for task in self.chunk_tasks])

    def sort_and_group_tasks(self, max_nchunks):
        """
        Scatter chunks accorind to # of flnc reads in each chunk and max_nchunks,
        return groups where groups[i] contains indices of tasks in the i-th group.

        First sort and then group chunk_tasks into no greater than {max_nchunks}
        groups so that the total number of flnc reads in each group is roughly
        the same.
        """
        for t in self.chunk_tasks:
            print(t)
        # sort tasks by weight (n of flnc reads in task) reversely
        self.sorted_by_attr(attr='n_flnc_reads', reverse=True)

        # Create groups where each group contains a list of tasks.
        groups = [[] for dummy_i in range(max_nchunks)]

        # Simple grouping, first spread heavy tasks as much as possible,
        # then assign lighter ones
        for i in range(0, min(max_nchunks, self.__len__())):
            groups[i].append(i)
        # Randomly assign lighter bins
        bin_index = min(max_nchunks, self.__len__())
        while bin_index < self.__len__():
            groups[bin_index % max_nchunks].append(bin_index)
            bin_index += 1
        # Remove empty groups
        groups = [g for g in groups if len(g) > 0]
        return groups

    def spawn_pickles(self, out_pickle_fns):
        """Create n pickles each containing exactly one ChunkTask obj in list"""
        if len(out_pickle_fns) != len(self):
            raise ValueError("Num of spawn pickle %s does not match %s ChunkTask objs"
                             % (len(out_pickle_fns), len(self)))
        for task, out_pickle_fn in zip(self.chunk_tasks, out_pickle_fns):
            ChunkTasksPickle([task]).write(out_pickle_fn)

    def spawn_pickles_by_groups(self, groups, out_pickle_fns):
        """self.chunk_tasks are grouped, create len(groups) pickles according to groups,
        where groups[i] contains all chunk task in the i-th group.
        """
        assert isinstance(groups, list)
        assert all([isinstance(g, list) for g in groups])
        all_items = [i for sublist in groups for i in sublist]
        assert len(set(all_items)) == len(all_items)

        if len(out_pickle_fns) != len(groups):
            raise ValueError("Could not create %s spawn pickles from %d groups: %s"
                             % (len(out_pickle_fns), len(groups), groups))

        for group, out_pickle_fn in zip(groups, out_pickle_fns):
            ChunkTasksPickle([self.chunk_tasks[b] for b in group]).write(out_pickle_fn)

    def __str__(self):
        return "{cls} obj containing {n} chunk tasks:\n".\
               format(cls=self.__class__.__name__, n=len(self)) + \
               "\n".join([str(task) for task in self.chunk_tasks]) + "\n"

    def __repr__(self):
        return self.__str__()

    def __len__(self):
        return len(self.chunk_tasks)

    def __getitem__(self, index):
        return self.chunk_tasks[index]

    def __iter__(self):
        return self.chunk_tasks.__iter__()
