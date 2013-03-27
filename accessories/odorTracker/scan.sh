#!/bin/bash

PYT='python2'
PVGROOT="`pwd`/../../"
OTROOT="`pwd`/"
MOVIE_FILETYPE="*.AVI*"

ACTIONS=$(zenity --height=300 --list --checklist --title "What do you want to do." --text "Specify actions." --column "" --column "Choices" True "Draw the Mask" True "Write Coordinates" True "Draw Graphs" True "Write Position Summary" False "Vertical")

MAKEMASK=0
COORDS=0
GRAPHS=0


if [[ $ACTIONS =~ .*Mask.* ]]
then
  MAKEMASK=1
fi

if [[ $ACTIONS =~ .*Coordinates.* ]]
then
  COORDS=1
fi

if [[ $ACTIONS =~ .*Graphs.* ]]
then
  GRAPHS=1
fi

if [[ $ACTIONS =~ .*Position.* ]]
then
  POSITION=1
fi

if [[ $ACTIONS =~ .*Vertical.* ]]
then
  VERTICAL="--vertical"
fi


SRC=$(zenity  --file-selection --title="Select Directory that contains the files you want to process" --directory --filename=.)

if [ -z $SRC ]; then

    echo Aborted
   
else

    echo Processing
    
    cd $SRC

    #MAKE MASK
    if [ $MAKEMASK = 1 ]; then
        PVG_MM=$PVGROOT"pvg_standalone.py -t2 --showmask -i"

        for file in `find ${SRC} -name "$MOVIE_FILETYPE" -type f`
        do
            echo 'Now calculating coordinates for ' ${file}
            $PYT ${PVG_MM} ${file}
        done
    fi

    #CALCULATE COORDINATES
    if [ $COORDS = 1 ]; then
        PVG_S=$PVGROOT"pvg_standalone.py -t2 --trackonly -i"

        for file in `find ${SRC} -name "$MOVIE_FILETYPE" -type f`
        do
            echo 'Now calculating coordinates for ' ${file}
            $PYT ${PVG_S} ${file}
        done
    fi


    #DRAW GRAPHS
    if [ $GRAPHS = 1 ]; then
        PVG_OT=$OTROOT"odorTracker.py $VERTICAL --distribution --path --steps -i"
        FILETYPE_COORD="*.txt"

        for file in `find ${SRC} -name "$FILETYPE_COORD" -type f`
        do
            echo 'Now processing figures for' ${file}
            $PYT ${PVG_OT} ${file}
        done
    fi

    #WRITE POSITIONS
    if [ $POSITION = 1 ]; then
        PVG_OT=$OTROOT"odorTracker.py $VERTICAL --ratio -i"
        FILETYPE_COORD="*.txt"

        for file in `find ${SRC} -name "$FILETYPE_COORD" -type f`
        do
            echo 'Now processing figures for' ${file}
            $PYT ${PVG_OT} ${file}
        done
    fi


fi
