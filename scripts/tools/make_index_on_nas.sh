#!/bin/bash
ORIGIN=/ethoscope_data/results
NASMNT=/mnt/nas/auto_generated_data/ethoscope_results/
INDEXFILE=$NASMNT/index.txt

#generate a list of the files to be synced
rsync -arv $ORIGIN/* $NASMNT --dry-run | grep "\.db" > /tmp/synced_files.txt

#generate a temporary addition to the index file
echo "" > /tmp/tmp_index.txt

while read fl; do
    echo -e '"'$fl'",' `du -k $ORIGIN/$fl | cut -f1` >> /tmp/tmp_index.txt
	#echo -e `du -b $ORIGIN/$fl` >> /tmp/tmp_index.txt
done </tmp/synced_files.txt

#make a backup of the index file
cp $INDEXFILE $INDEXFILE.backup

cat /tmp/tmp_index.txt >> $INDEXFILE

rm /tmp/tmp_index.txt
rm /tmp/synced_files.txt