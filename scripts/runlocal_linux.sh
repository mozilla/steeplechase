#!/bin/bash

#set -x

print_help() {
  echo "The expected default repository layout is:"
  echo " |"
  echo " +- steeplechase"
  echo " |"
  echo " +- mozilla-central"
  echo " |"
  echo " +- simplesignaling"
  echo " |"
  echo " +- Negatus"
  echo
  echo "You can use these parameters or environment variables for over write:"
  echo " -e | STEEPLECHASE_HOME"
  echo " -m | MOZILLA_CENTRAL"
  echo " -n | NEGATUS_HOME"
  echo " -s | SIMPLESIG_HOME"
  echo
}

while getopts "e:h?m:n:s:" opt; do
  case "$opt" in
  e) STEEPLECHASE_HOME=$OPTARG
     ;;
  h|\?)
     print_help
     exit 0
     ;;
  m) MOZILLA_CENTRAL=$OPTARG
    ;;
  n) NEGATUS_HOME=$OPTARG
    ;;
  s) SIMPLESIG_HOME=$OPTARG
    ;;
  esac
done

if [ -z ${STEEPLECHASE_HOME} ]; then
  STEEPLECHASE_HOME=`pwd`
  if [ ! -e ${STEEPLECHASE_HOME}/setup.py ]; then
    STEEPLECHASE_HOME=${STEEPLECHASE_HOME}/..
    if [ ! -e ${STEEPLECHASE_HOME}/setup.py ]; then
      print_help
      echo "Failed to locate steeplechase home directory"
      exit 1
    fi
  fi
fi

if [ -z ${MOZILLA_CENTRAL} ]; then
  MOZILLA_CENTRAL=${STEEPLECHASE_HOME}/../mozilla-central
  if [ ! -e ${MOZILLA_CENTRAL}/mach ]; then
    print_help
    echo "Please specify the location of mozilla-central"
    exit 2
  fi
fi

MOZILLA_OBJ=${MOZILLA_CENTRAL}/obj*/
if [ ! -e ${MOZILLA_OBJ}/dist ]; then
  echo "Failed to locate firefox build dir at ${MOZILLA_OBJ}"
  exit 3
fi

MOZILLA_DIST=${MOZILLA_OBJ}/dist
if [ ! -e ${MOZILLA_DIST}/bin/firefox ]; then
  echo "Failed to locate firefox binary in ${MOZILLA_DIST}"
  exit 3
fi

if [ -z ${SIMPLESIG_HOME} ]; then
  SIMPLESIG_HOME=${STEEPLECHASE_HOME}/../simplesignalling
  if [ ! -e ${SIMPLESIG_HOME}/server.js ]; then
    print_help
    echo "Failed to locate simplesignaling home directory, please provide it via SIMPLESIG_HOME env var"
    exit 4
  fi
fi

if [ -z ${NEGATUS_HOME} ]; then
  NEGATUS_HOME=${STEEPLECHASE_HOME}/../Negatus
  if [ ! -e ${NEGATUS_HOME}/agent ]; then
    print_help
    echo "Failed to locate Negatus home directory, please provide it via NEGATUS_HOME env var"
    exit 5
  fi
fi

rm -rf /tmp/tests
mkdir -p /tmp/tests/steeplechase-Client1/app/
cp -rs ${MOZILLA_DIST}/bin/* /tmp/tests/steeplechase-Client1/app/
mkdir -p /tmp/tests/steeplechase-Client2/app/
cp -rs ${MOZILLA_DIST}/bin/* /tmp/tests/steeplechase-Client2/app/

cd ${SIMPLESIG_HOME}
node server.js &
SIMPLESIG_PID=$!

${NEGATUS_HOME}/agent &
NEGATUS_PID1=$!

${NEGATUS_HOME}/agent -p 20703 --heartbeat 20702 &
NEGATUS_PID2=$!

python ${STEEPLECHASE_HOME}/steeplechase/runsteeplechase.py \
  --binary ${MOZILLA_DIST}/bin/firefox \
  --specialpowers-path ${MOZILLA_DIST}/xpi-stage/specialpowers \
  --prefs-file ${MOZILLA_CENTRAL}/testing/profiles/prefs_general.js \
  --html-manifest ${MOZILLA_OBJ}/_tests/steeplechase/steeplechase.ini \
  --signalling-server http://127.0.0.1:8080/ \
  --host1 127.0.0.1:20701 \
  --host2 127.0.0.1:20703 \
  --noSetup

kill ${SIMPLESIG_PID}
kill ${NEGATUS_PID1}
kill ${NEGATUS_PID2}
