Using schedulers to define when modules will perform their tasks.
=================================================================


When plannig experiment with ethoscope modules, you will often want to decide **when** to run module.
Schedulers allow you to specify this in a flexible maner.
Importantly, this only controls optional hardware modules, not tracking. TRacking is only stopped when clicking on the "stop" button.

Default
--------------
When no value is entered, the default is to start the module immediatly and stop it when the tracking is stopped.


General time range format
-----------------------------
When doing something else than default, you will need to enter text in the scheduler box.
A simple time range has the following structure:
```
DATE1 > DATE2
```
Where `DATE1` and `DATE2` are two dates formated as `YYYY-MM-DD hh:mm:ss`.
So, for instance, a valid time range could be `2016-04-01 21:00:00 > 2016-04-02 09:00:00`, which is 12h overnight.

Special cases
--------------
Simply entering one date:

```
DATE1
```
means "start at this date, and stop when tracking stops".

If the date is preceded by `>`:

```
 > DATE2
```
it means "start now and stop at `DATE2`"

Advances uses
------------------

Sometimes, you will want to specify several valid time intervals when to apply your module.
For instance, overnight interaction for two consecutive night (but nothing during the day).

You can set sevral time range by separating them with a `,`. FOr inctance:
```
DATE1 > DATE2, DATE3 > DATE4
```

This means "apply the module between date 1 and date 2 and between date 3 and date 4 exclusively".
This implies that the **date ranges do not overlap**.

This way, you can chain as many interval as you want.

