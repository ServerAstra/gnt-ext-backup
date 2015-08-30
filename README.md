gnt-ext-backup
===============

Python ganeti external (read over SSH) backup script

Requires:
---------
Python 2.6+

Standard python modules:
* subprocess
* datetime
* jsone
* argparse

Additional python module:
* py-yaml

Setup:
------
To run out of the box just clone the repo, then:
```console
# python -m gnt_ext_backup -h
```
Or you can chmod it to 700
```console
# gnt_ext_backup.py -h
```
Any additional hacks can be applied before init of class

Check `help(gnt_ext_backup.gnt_ext_backup)` for more info

Todo:
-------------
* Add VM custom config from gnt-list data as a yaml file accompanying the main one