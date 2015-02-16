__author__ = 'quentin'


import unittest
import os
import shutil
import numpy as np
import tempfile
from pysolovideo.tracking.roi_builders import ROI
from pysolovideo.utils.io import ResultWriter, SQLiteResultWriter


from pysolovideo.tracking.trackers import DataPoint, BoolVariableBase, IntVariableBase, DistanceIntVarBase


class DummyBoolVariable(BoolVariableBase):
    header_name="dummy_bool"

class DummyIntVariable(IntVariableBase):
    functional_type = "dum_type"
    header_name="dummy_int"

class DummyDistVariable(DistanceIntVarBase):
    header_name="dummy_dist_int"

class XVar(DistanceIntVarBase):
    header_name="x"

class YVar(DistanceIntVarBase):
    header_name="y"

class RandomResultGenerator(object):
    def make_one_point(self):
        out = DataPoint([
                DummyBoolVariable(True),
                DummyIntVariable(1),
                DummyDistVariable(3),
                XVar(9),
                YVar(2),
                ])
        return out


class TestMySQL(unittest.TestCase):

    def _test_dbwriter(self, rw):
        """
        This test hardcode ROIs and generate random results for a set of arbitrary variables.
        The goal is to be able to test and benchmark result write independently of any tracking

        :return:
        """
        # building five rois
        coordinates = np.array([(0,0), (100,0), (100,100), (0,100)])
        rois = [ROI(coordinates +i*100) for i in range(1,6)]
        rpg = RandomResultGenerator()


        for t in range(1, 10000):
            for r in rois:
                data = rpg.make_one_point()
                rw.write(t*100, r, data)
            rw.flush()
        rw.close()



    def test_sqlite(self):
        a = tempfile.mkdtemp(prefix="psv_results_")
        try:
            rw = SQLiteResultWriter(a)
            self._test_dbwriter(rw)

            self.assertEqual(1, 1)
        finally:
            shutil.rmtree(a)

    def test_mysql(self):

        rw = ResultWriter("psv_db")
        self._test_dbwriter(rw)
        self.assertEqual(1, 1)
