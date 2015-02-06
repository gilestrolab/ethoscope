This is maily a package stub at the moment, but qute some **WIP**.

Building package:
==================

Requierements:

* `R` statistical software
* `LaTeX` (to build the PDF documentation)

E.g. `#pacman -S r texlive-most`

Then, in order to build the package:

```
make clean
make 
```

In the end, the PDF documentation should pop up in a new window.

Quick start
==================
Assuming you have a data file named `result.db` in your path:

```
$ R
R> library(risonno)
# load ROIs 1,3 and 5 from the result file
R> loadROIsFromFile("result.db", rois=c(1,3,5))
```

