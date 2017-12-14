#!/bin/bash
set -vex
rm -rf prebuild deployment build
mkdir build

# some bamboo artifacts: better than 0 artifact
PBBAM=tarballs/pbbam.tgz
BLASR=tarballs/blasr.tgz
BLASR_LIBCPP=tarballs/blasr_libcpp.tgz
PBDAGCON=`/bin/ls -t tarballs/pbdagcon-*tgz|head -1`
NX3PBASEURL=http://nexus/repository/unsupported/pitchfork/gcc-6.4.0

# download + extract from nexus
#curl -sL http://nexus/repository/maven-snapshots/pacbio/sat/htslib/htslib-1.1-SNAPSHOT.tgz | tar zvxf - -C build
curl -sL $NX3PBASEURL/hmmer-3.1b2.tgz           | tar zvxf - -C build
curl -sL $NX3PBASEURL/zlib-1.2.8.tgz            | tar zvxf - -C build
curl -sL $NX3PBASEURL/libbzip2-1.0.6.tgz        | tar zvxf - -C build
curl -sL $NX3PBASEURL/gmap-2016-11-07.tgz       | tar zvxf - -C build
curl -sL $NX3PBASEURL/ncurses-6.0.tgz           | tar zvxf - -C build
curl -sL $NX3PBASEURL/samtools-1.6.tgz        | tar zvxf - -C build
curl -sL http://nexus/repository/unsupported/gcc-6.4.0/DAZZ_DB-SNAPSHOT.tgz                | tar zvxf - -C build
curl -sL http://nexus/repository/unsupported/gcc-6.4.0/DALIGNER-SNAPSHOT.tgz               | tar zvxf - -C build

# extract from artifacts
tar zxf $PBBAM        -C build
tar zxf $BLASR        -C build
tar zxf $BLASR_LIBCPP -C build
tar zxf $PBDAGCON     -C build

# preload software
type module >& /dev/null || . /mnt/software/Modules/current/init/bash
module load git
module load gcc
module load ccache
module load htslib
CXX="$CXX -static-libstdc++"
GXX="$CXX"
export CXX GXX
CCACHE_BASEDIR=$PWD
CCACHE_DIR=/mnt/secondary/Share/tmp/bamboo.mobs.ccachedir
export CCACHE_BASEDIR CCACHE_DIR

echo "## Use PYTHONUSERBASE in lieu of virtualenv"
export PATH=$PWD/build/bin:/mnt/software/a/anaconda2/4.2.0/bin:$PATH
export PYTHONUSERBASE=$PWD/build
# pip 9 create some problem with egg style install so don't upgrade pip
PIP="pip --cache-dir=$PWD/.pip --disable-pip-version-check"

echo "## Install pip modules"
ConsensusCore_VERSION=`curl -sL http://bitbucket:7990/projects/SAT/repos/consensuscore/raw/setup.py?at=refs%2Fheads%2Fdevelop|grep 'version='|sed -e 's/^.*="//;s/",//'`
ConsensusCore2_VERSION=`curl -sL http://bitbucket:7990/projects/SAT/repos/unanimity/raw/CMakeLists.txt?at=refs%2Fheads%2Fdevelop|grep 'project.*UNANIMITY.*VERSION'|sed -e 's/project(UNANIMITY VERSION //;s/ LANGUAGES CXX C)//'`
GenomicConsensus_VERSION=`curl -sL http://bitbucket.nanofluidics.com:7990/projects/SAT/repos/genomicconsensus/raw/GenomicConsensus/__init__.py?at=refs%2Fheads%2Fdevelop|grep __VERSION__|sed -e 's/.*__VERSION__ = "//;s/".*$//'`
$PIP install --user \
  $NX3PBASEURL/pythonpkgs/pysam-0.13-cp27-cp27mu-linux_x86_64.whl \
  $NX3PBASEURL/pythonpkgs/xmlbuilder-1.0-cp27-none-any.whl \
  $NX3PBASEURL/pythonpkgs/avro-1.7.7-cp27-none-any.whl \
  $NX3PBASEURL/pythonpkgs/iso8601-0.1.12-py2.py3-none-any.whl \
  $NX3PBASEURL/pythonpkgs/tabulate-0.7.5-cp27-none-any.whl \
  http://nexus/repository/unsupported/distfiles/coverage-4.4.1.tar.gz
$PIP install --user \
  git+ssh://git@bitbucket.nanofluidics.com:7999/sat/pbcore.git \
  git+ssh://git@bitbucket.nanofluidics.com:7999/sl/pbcommand.git
$PIP install --user \
  git+ssh://git@bitbucket.nanofluidics.com:7999/sat/pbcoretools.git \
  http://nexus/repository/unsupported/gcc-6.4.0/pythonpkgs/ConsensusCore-${ConsensusCore_VERSION}-cp27-cp27mu-linux_x86_64.whl \
  http://nexus/repository/unsupported/gcc-6.4.0/pythonpkgs/ConsensusCore2-${ConsensusCore2_VERSION}-cp27-cp27mu-linux_x86_64.whl \
  http://nexus/repository/unsupported/gcc-6.4.0/pythonpkgs/GenomicConsensus-${GenomicConsensus_VERSION}-cp27-cp27mu-linux_x86_64.whl
$PIP install --user -r repos/pbtranscript/REQUIREMENTS.txt
$PIP install --user -e repos/pbtranscript
