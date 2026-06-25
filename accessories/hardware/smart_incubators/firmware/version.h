// version.h
// FW_VERSION is the human-set semantic version. FW_BUILD is an integer auto-incremented by
// build.sh on every build (do NOT edit it by hand). FW_BUILD_DATE is the compile timestamp
// and changes on every rebuild even if you bypass build.sh. All three are reported by the
// REST API so a flash is self-evident in /telemetry.
#pragma once

#define FW_VERSION     "3.2.0-wifi"
#define FW_BUILD       6
#define FW_BUILD_DATE  __DATE__ " " __TIME__
