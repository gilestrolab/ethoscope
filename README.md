Ethoscope
============

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
