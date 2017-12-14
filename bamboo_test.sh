#!/bin/bash -xe

type module >& /dev/null || . /mnt/software/Modules/current/init/bash
module load git
module load gcc
module load ccache
module load htslib
module load hdf5-tools

cat > pbtranscript_dummy.xml << EOF
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="nosetests" tests="2" errors="0" failures="0" skip="0">
  <testcase classname="dummy.system" name="pwd" time="0.00">
    <system-out><![CDATA[`pwd`]]></system-out>
  </testcase>
  <testcase classname="dummy.system" name="hostname" time="0.00">
    <system-out><![CDATA[`hostname`]]></system-out>
  </testcase>
</testsuite>
EOF
if [ -e pitchfork/deployment/setup-env.sh ]; then
  module load graphviz
  source pitchfork/deployment/setup-env.sh
else
  export PATH=$PWD/build/bin:/mnt/software/a/anaconda2/4.2.0/bin:$PATH
  export PYTHONUSERBASE=$PWD/build
  export LD_LIBRARY_PATH=$PWD/build/lib:/mnt/software/a/anaconda2/4.2.0/lib:$LD_LIBRARY_PATH
fi
export PYTHONWARNINGS="ignore"
# for debug purpose
blasr --version
nosetests --verbose --with-xunit --xunit-file=pbtranscript_nose.xml \
    repos/pbtranscript/tests/unit/*.py

chmod +w -R repos/pbtranscript/tests
