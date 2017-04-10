#!/bin/bash -xe
rm -rf prebuild deployment build
mkdir build

# some bamboo artifacts: better than 0 artifact
PBBAM=`/bin/ls -t tarballs/pbbam*-x86_64.tgz|head -1`
BLASR=`/bin/ls -t tarballs/blasr-*tgz|head -1`
BLASR_LIBCPP=`/bin/ls -t tarballs/blasr_libcpp*tgz|head -1`
PBDAGCON=`/bin/ls -t tarballs/pbdagcon-*tgz|head -1`

# download + extract from nexus
curl -s -L http://ossnexus/repository/maven-snapshots/pacbio/sat/htslib/htslib-1.1-SNAPSHOT.tgz | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/hmmer-3.1b2.tgz           | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/libressl-2.2.5.tgz        | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/zlib-1.2.8.tgz            | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/gmap-2016-11-07.tgz       | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/ncurses-6.0.tgz           | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/samtools-1.3.1.tgz        | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/pitchfork/gcc-4.9.2/readline-6.3.tgz          | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/gcc-4.9.2/DAZZ_DB-SNAPSHOT.tgz                | tar zvxf - -C build
curl -s -L http://ossnexus/repository/unsupported/gcc-4.9.2/DALIGNER-SNAPSHOT.tgz               | tar zvxf - -C build

# extract from artifacts
tar zxf $PBBAM        --strip-components 1 -C build
tar zxf $BLASR        -C build
tar zxf $BLASR_LIBCPP -C build
tar zxf $PBDAGCON     -C build
grep deployment -r build|grep -v ^Binary|awk -F : '{print $1}'|sort -u \
|xargs sed -i -e "s@/var/lib/bamboo/bamboo-agent-home/xml-data/build-dir/DEP-PFK-JOB1/pitchfork/deployment@$PWD/build@g"

# preload software
type module >& /dev/null || . /mnt/software/Modules/current/init/bash
module load git/2.8.3
module load gcc/4.9.2
module load ccache/3.2.3
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
NX3PBASEURL=http://nexus/repository/unsupported/pitchfork/gcc-4.9.2
$PIP install --user \
  $NX3PBASEURL/pythonpkgs/pysam-0.9.1.4-cp27-cp27mu-linux_x86_64.whl \
  $NX3PBASEURL/pythonpkgs/xmlbuilder-1.0-cp27-none-any.whl \
  $NX3PBASEURL/pythonpkgs/avro-1.7.7-cp27-none-any.whl \
  iso8601 \
  $NX3PBASEURL/pythonpkgs/tabulate-0.7.5-cp27-none-any.whl \
  coverage \
  git+ssh://git@bitbucket.nanofluidics.com:7999/sat/pbcore.git \
  git+ssh://git@bitbucket.nanofluidics.com:7999/sat/pbcoretools.git \
  git+ssh://git@bitbucket.nanofluidics.com:7999/sl/pbcommand.git
$PIP install --user -r repos/pbtranscript/REQUIREMENTS.txt
$PIP install --user -e repos/pbtranscript
