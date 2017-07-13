#Test pbtranscript cluster, bam input.

  $ . $TESTDIR/setup.sh

  $ D=$SIVDATDIR/bam
  $ NFL=$D/isoseq_nfl.fasta
  $ FLNC=$D/isoseq_flnc.fasta
  $ BAS=$D/bam.fofn
  $ CCS=$D/ccsbam.fofn

  $ OFA=$OUTDIR/cluster_bam_out.fasta
  $ OD=$OUTDIR/test_cluster_bam

  $ rm -rf $OFA $OD && mkdir -p $OD
  $ pbtranscript cluster $FLNC $OFA -d $OD --bas_fofn $BAS --ccs_fofn $CCS 
  $ ls $OFA > /dev/null && echo $?
  0
  $ ls $OD/output/final.consensus.fasta.sensitive.config > /dev/null && echo $?
  0

# Test pbtranscript cluster, bam input, using finer qvs.
  $ rm -rf $OFA $OD && mkdir -p $OD
  $ pbtranscript cluster $FLNC $OFA -d $OD --bas_fofn $BAS --ccs_fofn $CCS  --use_finer_qv
  $ ls $OFA > /dev/null && echo $?
  0
  $ ls $OD/output/final.consensus.fasta.sensitive.config > /dev/null && echo $?
  0

# Test pbtranscript cluster, bam input, no finer qvs, no quiver.
  $ rm -rf $OFA $OD && mkdir -p $OD
  $ pbtranscript cluster $FLNC $OFA -d $OD --bas_fofn $BAS --ccs_fofn $CCS  --quiver --nfl_fa $NFL
  $ ls $OFA > /dev/null && echo $?
  0
  $ ls $OD/output/final.consensus.fasta.sensitive.config > /dev/null && echo $?
  0

# Test pbtranscript cluster, bam input, using finer qvs, quiver.
  $ rm -rf $OFA $OD && mkdir -p $OD
  $ pbtranscript cluster $FLNC $OFA -d $OD --bas_fofn $BAS --ccs_fofn $CCS  --use_finer_qv --quiver --nfl_fa $NFL
  $ ls $OFA > /dev/null && echo $?
  0
  $ ls $OD/output/final.consensus.fasta.sensitive.config > /dev/null && echo $?
  0
