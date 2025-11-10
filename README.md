Ethoscope
============

[![CI](https://github.com/gilestrolab/ethoscope/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/gilestrolab/ethoscope/actions/workflows/ci.yml)
[![Code Quality](https://github.com/gilestrolab/ethoscope/actions/workflows/quality.yml/badge.svg?branch=dev)](https://github.com/gilestrolab/ethoscope/actions/workflows/quality.yml)
[![codecov](https://codecov.io/gh/gilestrolab/ethoscope/branch/dev/graph/badge.svg)](https://codecov.io/gh/gilestrolab/ethoscope)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![GitHub release](https://img.shields.io/github/v/release/gilestrolab/ethoscope)](https://github.com/gilestrolab/ethoscope/releases)
[![Documentation](https://img.shields.io/badge/docs-lab.gilest.ro-brightgreen)](https://lab.gilest.ro/ethoscope-manual)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

This is the github repository of the software part of the [ethoscope platform](https://lab.gilest.ro/ethoscope).
All technical information regarding ethoscope is compiled in [our documentation](https://lab.gilest.ro/ethoscope-manual).

Organisation of the code
--------------------------

* `src/ethoscope` contains the main python package named `ethoscope`. It is installed on video monitors (devices), but it can be used as a standalone off-line tracking tool.
* `src/node` contains the software stack running on the 'node'. Node is a unique computer that syncs and controls devices.
* `src/updater` contains the update management tools for both ethoscope devices and nodes.
* `prototypes` contains (rather obsolete) developmental trials.
* `scripts` contains system service files and installation scripts.


Branching system
--------------------------

* `main` is **only** used for hosting tested **stable** software.
* `dev` is a fairly stable developmental used in @gilestrolab.

The workflow is to make issue branches from `dev`, test them as much a possible before merging them to `dev`.
Then, we deploy them in `dev`, and update all devices in the @gilestrolab.
If we experience no new critical issues over several weeks, we can merge `dev` to `main`, allowing the rest of the world to upgrade. The last merge from `dev ` to `main` dates to March 2022.

License
---------------

Ethoscope source code is licensed under the **GPL3** (see [license file](LICENSE)).
