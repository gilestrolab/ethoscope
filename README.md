Ethoscope
============

Organisation of the code
--------------------------

* `src` contains the main python package named `ethoscope`. It is installed on video monitors (devices), but it can be used as a standalone off line tracking tool.
* `node-src` contains the software stack running on the 'node'. Node is a unique computer that syncs and controls devices.
* `prototypes` contains (often unsuccessful) developmental trials.
* `scripts` contains a toolbox of scripts mainly to install the software on target devices.



Branching system
--------------------------

* `master` is **only** used for hosting tested **stable** software.
* `dev` is a fairly stable developmental used in @gilestrolab.

The workflow is to make issue branches from `dev`, test them as much a possible before merging them to `dev`.
Then, we deploy them in `dev`, and update all devices in the @gilestrolab.
If we experience no new critical issues over several weeks, we can merge `dev` to `master`, allowing the rest of the world to upgrade.

More doc to come

In order to analyse the large amount of generated behavioural data, we are developing, [rethomics](https://github.com/gilestrolab/rethomics), a comprehensive `R` package.

Documentation
---------------

The documentation of the API lives on our [github page](http://gilestrolab.github.io/ethoscope/).

License
---------------

Ethoscope source code is licensed under the **GPL3** (see [license file](LICENSE)).
