#!/bin/bash

#Writes a random value to a text file.  Same text file is configured in configuration.yaml as a power sensor
while true
do
    rand=$(( ( RANDOM % 9000 )  + 1000 ))
    echo $rand > sensor-data.txt
    sleep 15
done
