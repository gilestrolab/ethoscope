[![Documentation Status](https://readthedocs.org/projects/ethoscope/badge/?version=latest)](http://ethoscope.readthedocs.org/en/latest/?badge=latest)
[![Documentation Status](https://readthedocs.org/projects/ethoscope/badge/?version=dev)](http://ethoscope.readthedocs.org/en/dev/?badge=dev)
Ethoscope
============

This is the github repository of the software part of the [ethoscope platform](http://gilestrolab.github.io/ethoscope/).
All technical information regarding ethoscope is compiled in [our documentation](https://qgeissmann.gitbooks.io/ethoscope-manual/content/).

Organisation of the code
--------------------------

* `src` contains the main python package named `ethoscope`. It is installed on video monitors (devices), but it can be used as a standalone off-line tracking tool.
* `node-src` contains the software stack running on the 'node'. Node is a unique computer that syncs and controls devices.
* `prototypes` contains (often unsuccessful) developmental trials.
* `scripts` contains a toolbox of scripts. For instance to install the software on target device or to convert aquiered videos to a handy format.


Branching system
--------------------------

* `master` is **only** used for hosting tested **stable** software.
* `dev` is a fairly stable developmental used in @gilestrolab.

The workflow is to make issue branches from `dev`, test them as much a possible before merging them to `dev`.
Then, we deploy them in `dev`, and update all devices in the @gilestrolab.
If we experience no new critical issues over several weeks, we can merge `dev` to `master`, allowing the rest of the world to upgrade.

License
---------------

Ethoscope source code is licensed under the **GPL3** (see [license file](LICENSE)).
