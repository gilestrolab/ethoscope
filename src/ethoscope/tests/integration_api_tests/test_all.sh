for i in $(ls *.py |grep -v "^_")
do
echo "-----------------------------------"
echo Testing $i ... &&
python2 $i &&
echo "Success!"
done
