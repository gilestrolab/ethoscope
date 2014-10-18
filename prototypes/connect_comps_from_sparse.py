__author__ = 'quentin'


comps = [{1,2},{5,4},{2,5},{6,7}, {6,9}, {11,44}]



repeat = True
out_sets = comps
while repeat:
    comps = out_sets
    out_sets = []
    repeat=False
    for s in comps:
        connected = False
        for i,o in enumerate(out_sets):
            if o & s:
                out_sets[i] = s | out_sets[i]
                connected = True
                repeat=True
        if not connected:
            out_sets.append(s)

print comps == [set([1, 2, 4, 5]), set([9, 6, 7]), set([11, 44])]







